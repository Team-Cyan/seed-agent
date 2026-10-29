"""Real Linux direct maintenance callers; no entrypoint/CLI, no production data."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

assert sys.platform == "linux" and os.geteuid() == 0
root = Path(tempfile.mkdtemp(prefix="maintenance-identity-"))
root.chmod(0o755)
os.chown(root, 1000, 100)
env = {**os.environ, "PYTHONPATH": "/workspace/src", "PUID": "1000", "PGID": "100"}
setup = """
from pathlib import Path
import sys
from seed_agent.state import StateStore
from seed_agent.maintenance import verify_sqlite_database
p=Path(sys.argv[1]);StateStore(p);assert verify_sqlite_database(p)['valid'];p.chmod(0o664)
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
        str(root / "source.db"),
    ],
    env=env,
    check=True,
    capture_output=True,
)
code = """
import json,os,sqlite3,sys
from pathlib import Path
from seed_agent.maintenance import (backup_sqlite_database,restore_sqlite_database,
                                    verify_sqlite_database)
from seed_agent.runtime_identity import RuntimeIdentityError
root=Path(sys.argv[1]);kind=sys.argv[2];case=Path(sys.argv[3]);source=root/'source.db'
def snapshot():
 return {str(p.relative_to(root)):(p.stat().st_mode,p.stat().st_mtime_ns,
          p.read_bytes().hex() if p.is_file() else None) for p in [root,*root.rglob('*')]}
before=snapshot();opens=[];real=sqlite3.connect
def connect(*a,**kw):
 opens.append({'uid':os.getresuid(),'gid':os.getresgid()});return real(*a,**kw)
sqlite3.connect=connect
if kind=='positive':
 assert verify_sqlite_database(source)['valid']
 assert verify_sqlite_database(case/'missing.db')['schema_status']=='missing'
 backup=case/'backup'/'state.db';current=case/'restore'/'state.db'
 assert backup_sqlite_database(source,backup)['valid']
 assert restore_sqlite_database(current,backup,execute=False)['status']=='dry_run'
 assert restore_sqlite_database(current,backup,execute=True)['status']=='restored'
 assert verify_sqlite_database(current)['valid']
 assert opens and all(row['uid']==(1000,)*3 and row['gid']==(100,)*3 for row in opens)
else:
 try:
  if kind=='verify-existing':verify_sqlite_database(source)
  elif kind=='verify-missing':verify_sqlite_database(case/'missing.db')
  elif kind=='backup':backup_sqlite_database(source,case/'nested'/'backup.db')
  else:restore_sqlite_database(case/'nested'/'state.db',source,execute=kind=='restore-execute')
 except RuntimeIdentityError:pass
 else:raise AssertionError('identity mismatch not rejected')
 assert not opens,opens
 assert snapshot()==before,'maintenance changed filesystem before rejection'
print(json.dumps({'case':kind,'actual_uid':os.getresuid(),'actual_gid':os.getresgid(),'sql_opens':opens,'zero_effects':kind!='positive'}))
"""
results = []
for kind in ["verify-existing", "verify-missing", "backup", "restore-dry-run", "restore-execute"]:
    case = root / kind
    case.mkdir()
    # Existing output is deliberately nonprivate; reject before overwriting/chmod.
    (case / "existing.db").write_bytes(b"preserve")
    (case / "existing.db").chmod(0o664)
    run = subprocess.run(
        [sys.executable, "-c", code, str(root), kind, str(case)],
        env=env,
        check=True,
        text=True,
        capture_output=True,
        timeout=20,
    )
    results.append(json.loads(run.stdout))
for configured in [True, False]:
    case = root / ("configured" if configured else "env-absent")
    case.mkdir()
    os.chown(case, 1000, 100)
    selected = env.copy()
    if not configured:
        selected.pop("PUID")
        selected.pop("PGID")
    run = subprocess.run(
        [
            "setpriv",
            "--reuid=1000",
            "--regid=100",
            "--clear-groups",
            sys.executable,
            "-c",
            code,
            str(root),
            "positive",
            str(case),
        ],
        env=selected,
        check=True,
        text=True,
        capture_output=True,
        timeout=20,
    )
    result = json.loads(run.stdout)
    result["configured"] = configured
    results.append(result)
print(json.dumps({"status": "passed", "cases": results, "production_access": False}, indent=2))
