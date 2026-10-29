"""Real Linux root-process tests; run in an existing cached image, no network.

Mount this repository at /workspace and invoke this script as root using the
Python interpreter. The image must contain seed-agent's existing dependencies,
a prior unpatched installed CLI (baseline), and util-linux setpriv.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

assert sys.platform == "linux" and os.geteuid() == 0
repo = Path("/workspace")
root = Path(tempfile.mkdtemp(prefix="seed-identity-"))
root.chmod(0o755)
os.chown(root, 1000, 100)
wrapper = root / "entrypoint.sh"
wrapper.write_text((repo / "docker/entrypoint.sh").read_text())
wrapper.chmod(0o755)
hook = root / "hook"
hook.mkdir()
(hook / "sitecustomize.py").write_text("""
import json, os, sqlite3
_real=sqlite3.connect
def connect(*a,**kw):
 if os.environ.get('SQL_OPEN_AUDIT'):
  with open(os.environ['SQL_OPEN_AUDIT'],'a') as f:
   rows=(line.split(':',1) for line in open('/proc/self/status'))
   caps={k:v.strip() for k,v in rows if k in ('CapEff','CapAmb','CapBnd')}
   ids={'uid':os.getresuid(),'gid':os.getresgid(),'groups':os.getgroups(),'caps':caps}
   f.write(json.dumps(ids)+'\\n')
 return _real(*a,**kw)
sqlite3.connect=connect
""")
env = {
    **os.environ,
    "PUID": "1000",
    "PGID": "100",
    "HOME": "/tmp/seed-identity-home",
    "PYTHONPATH": f"{hook}:{repo / 'src'}",
    "SEED_AGENT_STARTUP_STATUS": "false",
    "SEED_AGENT_WEB_ENABLED": "false",
}
# Reuse the repository's minimal config contents without importing pytest.
tree = ast.parse((repo / "tests/test_web_settings.py").read_text())
func = next(
    n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_write_minimal_config"
)
text = next(
    n.value
    for n in ast.walk(func)
    if isinstance(n, ast.Constant) and isinstance(n.value, str) and "tracker_sites: []" in n.value
)

setup = """
import json,sys,yaml
from pathlib import Path
from seed_agent.media_import.runtime import build_engine
from seed_agent.state import StateStore
root=Path(sys.argv[1]);config=yaml.safe_load(sys.argv[2]);config.pop('download_client',None)
config['deployment']={'source_id':'identity-linux-test'}
for name in ['source','library']:
 p=root/name;p.mkdir();(p/'.media-volume').write_text('fixture')
config['media_import']={'enabled':True,'profiles':[{'name':'movie','source_root':str(root/'source'),'target_root':str(root/'library'),'marker_value':'fixture','target_marker_value':'fixture','media_type':'movie','min_age_seconds':0}]}
configpath=root/'config.yaml';configpath.write_text(yaml.safe_dump(config))
build_engine(configpath,initialize=True)
StateStore(root/'.seed-agent/state.db')
"""
subprocess.run(
    [
        "setpriv",
        "--reuid=1000",
        "--regid=100",
        "--clear-groups",
        sys.executable,
        "-c",
        setup,
        str(root),
        text,
    ],
    env=env,
    check=True,
    capture_output=True,
)
results = []


def run(
    name, args, changes=None, *, old=False, nonroot=None, expected_sql=None, expected_exit=None
):
    marker = root / (name + ".jsonl")
    selected = {**env, "SQL_OPEN_AUDIT": str(marker), **(changes or {})}
    if old:
        baseline = os.environ.get("IDENTITY_BASELINE_SOURCE", "")
        selected["PYTHONPATH"] = f"{hook}:{baseline}" if baseline else str(hook)
    for key in [k for k, value in selected.items() if value is None]:
        selected.pop(key)
    if nonroot:
        args = ["setpriv", f"--reuid={nonroot}", "--regid=100", "--clear-groups", *args]
    proc = subprocess.run(args, env=selected, text=True, capture_output=True, timeout=20)
    rows = [json.loads(line) for line in marker.read_text().splitlines()] if marker.exists() else []
    if expected_sql is None:
        assert not rows, (name, rows)
    else:
        assert rows and all(
            r["uid"] == [expected_sql] * 3 and r["gid"] == [100 if expected_sql else 0] * 3
            for r in rows
        ), (name, rows, proc.stderr[-1000:])
    if expected_exit is not None:
        assert proc.returncode == expected_exit, (
            name,
            proc.returncode,
            proc.stdout[-1000:],
            proc.stderr[-1000:],
        )
    if expected_sql == 1000 and "healthcheck" in args:
        payload = json.loads(proc.stdout)
        if payload.get("status") == "error" and expected_exit == 1:
            assert payload["error"]
        else:
            assert payload["process_identity"] == {"uid": 1000, "gid": 100}
    results.append(
        {
            "case": name,
            "exit_code": proc.returncode,
            "sqlite_opens": len(rows),
            "actual_open_identities": rows,
        }
    )


for role in ["seed", "media"]:
    args = ["healthcheck", "--role", role, "--config", str(root / "config.yaml")]
    run(f"old-root-bypass-{role}", ["seed-agent", *args], old=True, expected_sql=0)
    run(f"new-root-bypass-{role}", ["seed-agent", *args], expected_exit=2)
    run(
        f"new-forged-marker-{role}",
        ["seed-agent", *args],
        {"SEED_AGENT_PRIVILEGES_DROPPED": "true"},
        expected_exit=2,
    )
    run(
        f"new-wrapper-{role}",
        ["/bin/sh", str(wrapper), *args],
        {"SEED_AGENT_ROLE": role},
        expected_sql=1000,
        expected_exit=0 if role == "seed" else 1,
    )
    run(
        f"new-wrapper-forged-{role}",
        ["/bin/sh", str(wrapper), *args],
        {"SEED_AGENT_ROLE": role, "SEED_AGENT_PRIVILEGES_DROPPED": "true"},
        expected_exit=2,
    )
    run(
        f"new-owner-direct-{role}",
        ["seed-agent", *args],
        nonroot=1000,
        expected_sql=1000,
        expected_exit=0 if role == "seed" else 1,
    )
    run(f"new-wrong-nonroot-{role}", ["seed-agent", *args], nonroot=1001, expected_exit=2)
    run(
        f"new-local-{role}",
        ["seed-agent", *args],
        {"PUID": None, "PGID": None},
        nonroot=1000,
        expected_sql=1000,
        expected_exit=0 if role == "seed" else 1,
    )
    run(
        f"new-runtime-status-root-{role}",
        ["seed-agent", "runtime-status", *args[1:]],
        expected_exit=2,
    )
# Existing seed heartbeat failure and media role restrictions remain unhealthy.
(root / "stale-heartbeat.json").write_text('{"updated_at":"2000-01-01T00:00:00+00:00"}')
run(
    "new-wrapper-seed-stale-heartbeat",
    [
        "/bin/sh",
        str(wrapper),
        "healthcheck",
        "--config",
        str(root / "config.yaml"),
        "--heartbeat-file",
        str(root / "stale-heartbeat.json"),
        "--max-staleness-minutes",
        "90",
    ],
    {"SEED_AGENT_ROLE": "seed"},
    expected_sql=1000,
    expected_exit=1,
)
run(
    "new-wrapper-wrong-role",
    [
        "/bin/sh",
        str(wrapper),
        "healthcheck",
        "--role",
        "seed",
        "--config",
        str(root / "config.yaml"),
    ],
    {"SEED_AGENT_ROLE": "media"},
    expected_exit=2,
)
run(
    "real-saved-root-library-rejected",
    [
        sys.executable,
        "-c",
        """
import os
from pathlib import Path
from seed_agent.media_import.store import MediaStore
from seed_agent.runtime_identity import RuntimeIdentityError
os.setresgid(100,100,100);os.setresuid(1000,1000,0)
try:MediaStore(Path('/tmp/saved-root-must-not-exist/state.db'))
except RuntimeIdentityError:pass
else:raise AssertionError('saved root accepted')
assert not Path('/tmp/saved-root-must-not-exist').exists()
""",
    ],
    expected_exit=0,
)
# Real mismatched library constructors: no directory, file, lock or chmod.
code = """
import os,sys
from pathlib import Path
from seed_agent.state import StateStore
from seed_agent.media_import.store import MediaStore
from seed_agent.runtime_identity import RuntimeIdentityError
r=Path(sys.argv[1]);existing=r/'unchanged';existing.write_bytes(b'unchanged');existing.chmod(0o664)
before=existing.stat()
for Store in [StateStore,MediaStore]:
 for path in [r/'missing'/'deep'/'state.db',existing]:
  try:Store(path,initialize=False)
  except RuntimeIdentityError:pass
  else:raise AssertionError('wrong-identity constructor accepted')
assert not (r/'missing').exists()
assert existing.stat().st_mode==before.st_mode and existing.stat().st_mtime_ns==before.st_mtime_ns
assert not (r/'unchanged.access.lock').exists()
"""
run("real-root-library-no-side-effects", [sys.executable, "-c", code, str(root)], expected_exit=0)
# Wrapper checks prove all capability sets remain empty after existing setpriv.
for item in results:
    if item["case"].startswith("new-wrapper-") and "forged" not in item["case"]:
        assert all(
            set(r["groups"]) <= {100} and all(int(c, 16) == 0 for c in r["caps"].values())
            for r in item["actual_open_identities"]
        )
baseline_env = {**env, "PYTHONPATH": f"{hook}:{os.environ.get('IDENTITY_BASELINE_SOURCE', '')}"}
baseline_version = subprocess.check_output(
    ["seed-agent", "--version"], env=baseline_env, text=True
).strip()
current_version = subprocess.check_output(["seed-agent", "--version"], env=env, text=True).strip()
print(
    json.dumps(
        {
            "identity_defect_reproduced_not_errno_reproduction": True,
            "baseline_version": baseline_version,
            "current_version": current_version,
            "cases": results,
        },
        indent=2,
    )
)
