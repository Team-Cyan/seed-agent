"""Execute the overview loader and renderer against independent source failures."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("src/seed_agent/web/static/app.js")
KEYS = ["health", "stateSummary", "pools", "ops"]
GOOD = {
    "health": {"status": "ok", "heartbeat_exists": True},
    "stateSummary": {"candidates": {"total": 7, "by_state": {}},
                     "intents": {"total": 3, "by_state": {}}},
    "pools": {"budget_pools": [{"name": "fixture", "max_size_tib": 1}]},
    "ops": {"schedule_backoff": {}, "scheduler_runs": [],
            "tracker_api_events": [], "want_search_runs": []},
}


def run_overview(rounds: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for overview JavaScript behavior tests")
    source = SCRIPT.read_text()
    loader = source[source.index("async function loadOverview()"):
                    source.index("async function loadWants()")]
    renderer = source[source.index("function renderOverviewPanel()"):
                      source.index("function renderSchedulerOperations(")]
    harness = r'''
const state = {overview: {health:null,stateSummary:null,pools:null,ops:null,error:null}};
const uiText = key => key;
const makeNode = () => ({children:[],html:"",classList:{add(){}},
    append(...items){this.children.push(...items)},addEventListener(){},
    set innerHTML(value){this.html=value}});
const document = {createElement: makeNode};
const renderMetricCard = (...args) => ({metric:args,classList:{add(){}}});
const escapeHtml = value => String(value);
const formatHealthStatus = value => value;
const formatStateCounts = value => JSON.stringify(value);
const renderBudgetPoolList = value => "pools:" + value.length;
const renderAttentionList = () => "attention";
const renderSchedulerOperations = ops => ops ? "operations" : "unavailable";
const renderRuntimeProvenance = () => "provenance";
const renderStateChips = () => "states";
let current;
const apiFetch = async path => {
  const key = {"/api/health":"health","/api/state/summary":"stateSummary",
    "/api/pools":"pools","/api/ops":"ops"}[path];
  const setting = current[key] || {};
  if (setting.failure === "throw") throw new Error("SECRET_transport");
  return {ok:!setting.status || setting.status===200,status:setting.status||200,
    json:async()=>{
      if(setting.failure==="json") throw new Error("SECRET_body");
      if(setting.failure==="shape") return [];
      return Object.hasOwn(setting,"body") ? setting.body : GOOD[key];
    }};
};
'''
    harness += "\nconst GOOD=" + json.dumps(GOOD) + ";\n"
    harness += loader + "\n" + renderer
    harness += "\nconst rounds=" + json.dumps(rounds) + ";\n"
    harness += """
(async()=>{
  const outputs=[];
  for(current of rounds){
    await loadOverview();
    outputs.push({overview:state.overview,panel:renderOverviewPanel()});
  }
  console.log(JSON.stringify(outputs));
})().catch(error=>{console.error(error);process.exit(1)});
"""
    completed = subprocess.run([node, "-"], input=harness, text=True, capture_output=True,
                               check=True, timeout=10)
    return json.loads(completed.stdout)


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("failure", ["http", "throw", "json", "shape"])
def test_overview_isolates_each_source_failure_and_clears_old_data(key, failure):
    setting = {"status": 500, "body": {"error": "SECRET_body"}} if failure == "http" else {
        "failure": failure,
    }
    initial, failed, recovered = run_overview([{}, {key: setting}, {}])
    assert initial["overview"][key] == GOOD[key]
    overview = failed["overview"]
    assert overview[key] is None  # Never show the previous successful snapshot as fresh.
    assert len(overview["errors"]) == 1
    assert overview["errors"][0]["label"] == {
        "health": "heartbeat", "stateSummary": "stateDatabase",
        "pools": "budgetPools", "ops": "opsDashboard",
    }[key]
    for other in set(KEYS) - {key}:
        assert overview[other] == GOOD[other]
    assert "SECRET" not in json.dumps(failed)
    assert "unavailable" in json.dumps(failed["panel"])
    assert not recovered["overview"]["errors"]
    assert recovered["overview"][key] == GOOD[key]


@pytest.mark.parametrize("status", ["missing_heartbeat", "stale", "state_database_unavailable"])
def test_overview_preserves_structured_unhealthy_503_body(status):
    body = {"status": status, "heartbeat_exists": False}
    result = run_overview([{"health": {"status": 503, "body": body}}])[0]
    assert result["overview"]["health"] == body
    assert result["overview"]["errors"] == [{"label": "heartbeat", "message": "HTTP 503"}]
    assert status in json.dumps(result["panel"])
    assert "operations" in json.dumps(result["panel"])
    assert "pools:1" in json.dumps(result["panel"])


def test_overview_all_failures_render_unavailable_not_loading_or_zero_success():
    result = run_overview([{key: {"failure": "throw"} for key in KEYS}])[0]
    assert all(result["overview"][key] is None for key in KEYS)
    assert len(result["overview"]["errors"]) == 4
    rendered = json.dumps(result["panel"])
    assert "loading" not in rendered
    assert "operations" not in rendered
    assert "pools:0" not in rendered


def test_overview_all_sources_successful():
    result = run_overview([{}])[0]
    assert not result["overview"]["errors"]
    assert all(result["overview"][key] == GOOD[key] for key in KEYS)
    rendered = json.dumps(result["panel"])
    assert "operations" in rendered and "pools:1" in rendered


@pytest.mark.parametrize("key,body", [
    ("health", {"status": "SECRET_unknown"}),
    ("stateSummary", {"candidates": None, "intents": {}}),
    ("pools", {"budget_pools": [None]}),
    ("ops", {"schedule_backoff": {}, "scheduler_runs": None}),
])
def test_overview_rejects_malformed_success_payload(key, body):
    result = run_overview([{key: {"body": body}}])[0]
    assert result["overview"][key] is None
    assert result["overview"]["errors"][0]["message"] == "overviewInvalidResponse"
    assert "SECRET" not in json.dumps(result)
