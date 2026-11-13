import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_media_extras import setup_extra as setup_extra
from test_media_extras import setup_variant
from test_web_settings import _request_json, _running_server, _write_minimal_config
from typer.testing import CliRunner

from seed_agent.web.media_actions import reviewed_request_status, variant_candidates


def test_variant_candidates_use_identity_not_filename_or_page(setup_extra):
    engine, source, _, parent = setup_extra
    sid = setup_variant(engine, source, parent)
    before = engine.store.path.read_bytes()
    assert variant_candidates(engine, parent) == [{"source_id": sid, "path": sid}]
    assert engine.store.path.read_bytes() == before
    with engine.store._connect() as conn:
        mapping = json.loads(
            conn.execute(
                "SELECT mapping_json FROM media_import_jobs WHERE source_id=?", (sid,)
            ).fetchone()[0]
        )
        mapping["edition"] = "Different cut"
        conn.execute(
            "UPDATE media_import_jobs SET mapping_json=? WHERE source_id=?",
            (json.dumps(mapping), sid),
        )
    assert variant_candidates(engine, parent) == []
    with pytest.raises(ValueError, match="invalid source"):
        variant_candidates(engine, "bad")


def test_lost_response_request_lookup_is_read_only_and_rejects_ambiguity(setup_extra):
    engine, _, _, _ = setup_extra
    token = "12345678-1234-1234-1234-123456789abc"
    assert reviewed_request_status(engine, token) == []
    with engine.store._connect() as conn:
        conn.execute(
            "INSERT INTO media_commands VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL,?)",
            (
                "command",
                "key",
                "featurette-preview",
                json.dumps({"client_request_id": token}),
                "config",
                "revision",
                engine.store.epoch(),
                "{}",
                "complete",
                1,
                '{"preview_id":7}',
            ),
        )
    before = engine.store.path.read_bytes()
    assert reviewed_request_status(engine, token) == [
        {"id": "command", "status": "complete", "result": {"preview_id": 7}}
    ]
    assert engine.store.path.read_bytes() == before
    with engine.store._connect() as conn:
        conn.execute(
            "INSERT INTO media_commands SELECT 'duplicate',coalesce_key,action,"
            "payload_json,config_source,config_revision,epoch,modes_json,status,created,"
            "claimed,claim_token,result_json FROM media_commands WHERE id='command'"
        )
    with pytest.raises(ValueError, match="multiple commands"):
        reviewed_request_status(engine, token)


@pytest.mark.skipif(not shutil.which("node"), reason="Node is required for UI behavior fixture")
def test_ui_holds_lost_submit_and_recovers_by_read_only_request_lookup():
    source = Path("src/seed_agent/web/static/app.js").read_text()
    functions = source[
        source.index("function mediaElement(") : source.index("async function loadMedia()")
    ]
    harness = r"""
const assert = require('node:assert/strict');
// NAS HTTP origins may lack randomUUID; getRandomValues remains available.
const crypto = {getRandomValues:require('node:crypto').getRandomValues};
class Element {
  constructor(tag) {this.tag = tag; this.children = []; this.events = {}; this.hidden = false;}
  append(...items) {this.children.push(...items);}
  prepend(item) {this.children.unshift(item);}
  setAttribute(key, value) {if (key === 'hidden') this.hidden = true; else this[key] = value;}
  addEventListener(name, fn) {this.events[name] = fn;}
}
const document = {createElement: tag => new Element(tag)};
const setTimeout = resolve => resolve();
let refreshes = 0;
function loadMedia() {refreshes++;}
let posts = 0, queries = [], result = [];
async function apiFetch(path, options) {
  if (options.method === 'POST') {posts++; throw new Error('response lost');}
  queries.push(path);
  return {ok:true, json:async () => result};
}
"""
    checks = r"""
(async () => {
  const section = mediaReviewedAction({id:'source', path:'extra.mkv'}, 'featurette');
  const form = section.children.find(node => node.tag === 'form');
  const buttons = form.children.filter(node => node.tag === 'button');
  const [preview, publish, poll] = buttons;
  form.events.submit({preventDefault(){}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(posts, 1);
  assert.equal(preview.disabled, true);
  assert.equal(poll.hidden, false);
  await poll.events.click();
  assert.equal(preview.disabled, true);
  assert.equal(queries[0].startsWith('/api/media/requests?id='), true);
  result = [{id:'command', status:'complete', result:{preview_id:7,
    projection:{target:'Film/Featurettes/extra.mkv'}}}];
  await poll.events.click();
  assert.equal(posts, 1);
  assert.equal(preview.disabled, false);
  assert.equal(publish.hidden, false);
  assert.equal(poll.hidden, true);
  let completionBody;
  apiFetch = async (path, options) => {
    if (options.method === 'POST') {
      completionBody = JSON.parse(options.body);
      assert.equal(path, '/api/media/completion-confirm');
      return {ok:true, json:async () => ({command_id:'completion'})};
    }
    return {ok:true, json:async () => [{status:'complete',result:{readiness:'operator'}}]};
  };
  const completion = mediaReviewedAction({id:'unidentified',generation:2,
    fingerprint:'exact-fingerprint',path:'unknown.mkv'}, 'completion');
  const completionForm = completion.children.find(node => node.tag === 'form');
  completionForm.children.find(node => node.tag === 'label').children[0].checked = true;
  completionForm.events.submit({preventDefault(){}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(completionBody.source_id, 'unidentified');
  assert.equal(completionBody.generation, 2);
  assert.equal(completionBody.fingerprint, 'exact-fingerprint');
  assert.equal(completionBody.completion_confirmed, true);
  assert.equal(completionBody.execute, true);
  assert.equal('mapping' in completionBody, false);
  assert.equal(refreshes, 1);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run(
        [shutil.which("node")],
        input=harness + functions + checks,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "action",
    [
        "featurette-preview",
        "featurette-publish",
        "variant-preview",
        "variant-switch",
        "completion-confirm",
    ],
)
def test_reviewed_http_actions_preserve_explicit_execution(monkeypatch, tmp_path, action):
    import seed_agent.media_import.commands as commands

    received = []

    def submit(config, kind, body, *, execute):
        received.append((kind, body, execute))
        return {"command_id": "fixture", "status": "queued"}

    monkeypatch.setattr(commands, "submit", submit)
    config = _write_minimal_config(tmp_path)
    with _running_server(config) as host:
        for execute in (False, True):
            result = _request_json(
                host,
                "POST",
                f"/api/media/{action}",
                {"preview_id": 1, "execute": execute},
                expected_status=202,
            )
            assert result["command_id"] == "fixture"
        _request_json(host, "POST", f"/api/media/{action}", {"execute": "yes"}, expected_status=400)
    assert received == [(action, {"preview_id": 1}, False), (action, {"preview_id": 1}, True)]


@pytest.mark.parametrize(
    "action",
    [
        "featurette-preview",
        "featurette-publish",
        "variant-preview",
        "variant-switch",
        "completion-confirm",
    ],
)
def test_reviewed_cli_does_not_execute_implicitly(monkeypatch, tmp_path, action):
    import seed_agent.media_import.commands as commands
    from seed_agent.cli import app

    received = []
    monkeypatch.setattr(
        commands,
        "submit",
        lambda config, kind, body, *, execute: (
            received.append((kind, execute)) or {"command_id": "fixture"}
        ),
    )
    request = tmp_path / "request.json"
    request.write_text('{"preview_id":1}')
    result = CliRunner().invoke(app, [f"media-{action}", "--request", str(request)])
    assert result.exit_code == 0, result.output
    assert received == [(action, False)]
