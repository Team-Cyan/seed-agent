"""Exercise Want empty states and the local-only filter reset in JavaScript."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ITEMS = [
    {"title": "Fixture Movie", "source_keys": ["cli"], "media_type": "movie",
     "status": "not_downloaded"},
    {"title": "Fixture Series", "source_keys": ["imdb"], "media_type": "tv",
     "status": "viewed"},
]
ALL = {"source": "all", "media_type": "all", "status": "all"}


def render_wants(language, *, items=None, filters=None, loading=False, error=None,
                 clear=False):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for Want JavaScript behavior tests")
    source = Path("src/seed_agent/web/static/app.js").read_text()
    snippets = [
        source[source.index("const copy ="):
               source.index("const settingsPanelsByLanguage =")],
        source[source.index("function activeCopy()"):
               source.index("function currentSettingsPanels()")],
        source[source.index("function renderWantTable()"):
               source.index("function wantStatusBadgeClass(")],
        source[source.index("async function handleWantAction("):
               source.index("async function refreshWants(")],
    ]
    state = {"language": language, "wants": {
        "items": ITEMS if items is None else items, "filters": filters or ALL,
        "loading": loading, "error": error, "dueCount": 2,
    }}
    harness = "const state = " + json.dumps(state) + ";\n" + r'''
const document = {createElement: () => ({innerHTML: ""})};
const escapeHtml = value => String(value).replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;").replaceAll('"', "&quot;");
const escapeAttribute = escapeHtml;
const renderWantRow = item => `<tr>${escapeHtml(item.title)}</tr>`;
const renderWantCard = item => `<article>${escapeHtml(item.title)}</article>`;
let renders = 0, networkCalls = 0;
const renderSection = () => { renders++; };
const forbiddenNetwork = () => { networkCalls++; throw Error("Unexpected network action"); };
const fetch = forbiddenNetwork, apiFetch = forbiddenNetwork;
const refreshWants = forbiddenNetwork, searchFilteredWants = forbiddenNetwork;
const searchSingleWant = forbiddenNetwork, loadWants = forbiddenNetwork;
'''
    harness += "\n".join(snippets)
    harness += "\nconst clear = " + json.dumps(clear) + ";\n"
    harness += """
(async () => {
  const before = renderWantTable().innerHTML;
  if (clear) await handleWantAction(null, "clear-filters", null);
  console.log(JSON.stringify({before, after: renderWantTable().innerHTML,
    state, renders, networkCalls}));
})().catch(error => {console.error(error); process.exit(1)});
"""
    completed = subprocess.run([node, "-"], input=harness, text=True,
                               capture_output=True, check=True, timeout=10)
    return json.loads(completed.stdout)


@pytest.mark.parametrize("language", ["CN", "EN"])
@pytest.mark.parametrize("filter_key,value", [
    ("source", "missing"), ("media_type", "anime"), ("status", "downloaded"),
])
def test_filtered_empty_clears_all_filters_locally(language, filter_key, value):
    result = render_wants(language, filters={**ALL, filter_key: value}, clear=True)
    before = result["before"]
    label = "清除筛选" if language == "CN" else "Clear filters"
    assert 'data-want-action="clear-filters"' in before
    assert f'aria-label="{label}"' in before
    assert "0 /" in before and ("共 2 项" if language == "CN" else "2 items") in before
    assert ('没有符合当前筛选条件' if language == 'CN' else 'No wants match') in before
    assert 'data-want-action="sync"' not in before
    assert 'data-want-action="config-open"' not in before
    assert result["state"]["wants"]["filters"] == ALL
    assert result["state"]["wants"]["items"] == ITEMS
    assert result["state"]["wants"]["dueCount"] == 2
    assert result["renders"] == 1 and result["networkCalls"] == 0
    assert "Fixture Movie" in result["after"] and "Fixture Series" in result["after"]
    assert "2 /" in result["after"]
    assert 'data-want-action="clear-filters"' not in result["after"]


@pytest.mark.parametrize("language", ["CN", "EN"])
def test_truly_empty_retains_setup_guidance(language):
    rendered = render_wants(language, items=[], filters={**ALL, "status": "viewed"})["before"]
    assert ("暂无想看资源" if language == "CN" else "No wants yet") in rendered
    assert 'data-want-action="sync"' in rendered
    assert 'data-want-action="config-open"' in rendered
    assert 'data-want-action="clear-filters"' not in rendered
    assert "0 /" in rendered and ("共 0 项" if language == "CN" else "0 items") in rendered


@pytest.mark.parametrize("language", ["CN", "EN"])
@pytest.mark.parametrize("mode", ["loading", "error"])
def test_loading_and_error_are_not_presented_as_empty_or_success(language, mode):
    result = render_wants(language, loading=mode == "loading",
                          error="<fixture error>" if mode == "error" else None)
    rendered = result["before"]
    assert 'data-want-action=' not in rendered
    assert 'role="status"' not in rendered
    assert "Fixture Movie" not in rendered
    if mode == "error":
        assert "&lt;fixture error>" in rendered
    else:
        assert ("加载" if language == "CN" else "Loading") in rendered


@pytest.mark.parametrize("language", ["CN", "EN"])
def test_nonempty_filtered_list_reports_visible_and_total(language):
    rendered = render_wants(language, filters={**ALL, "media_type": "movie"})["before"]
    assert "1 /" in rendered and ("共 2 项" if language == "CN" else "2 items") in rendered
    assert "Fixture Movie" in rendered and "Fixture Series" not in rendered
    assert 'data-want-action="clear-filters"' not in rendered
