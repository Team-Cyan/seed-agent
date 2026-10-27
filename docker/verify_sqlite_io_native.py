"""Isolated image smoke test; all database operations stay in a fresh /tmp tree."""
import argparse
import json
import os
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from seed_agent.media_import import sqlite_io

parser = argparse.ArgumentParser()
parser.add_argument('--library', required=True)
args = parser.parse_args()
assert os.geteuid() != 0, 'Run as the worker UID to verify access-denied evidence'
sqlite_io._LIBRARY = args.library
observations = []
sqlite_io._emit = observations.append
with tempfile.TemporaryDirectory(prefix='seed-sqlite-io-smoke-') as scratch:
    parent = Path(scratch) / 'state'
    path = parent / 'state.db'
    sqlite_io.startup(path, exclusive_worker_owner=True)
    assert observations[-1]['state'] == 'enabled', observations[-1]
    controller = sqlite_io._controller
    pins = tuple(sqlite_io._PINS)

    def attempt():
        token = sqlite_io.begin(path)
        try:
            connection = sqlite3.connect(path)
        except sqlite3.OperationalError as exc:
            sqlite_io.failure(token, 'connect', exc)
        else:
            connection.close()
            raise AssertionError('scratch open unexpectedly succeeded')

    cases = []
    try:
        for name, expected in [('missing-parent', 2), ('denied-parent', 13)]:
            if expected == 13:
                parent.mkdir()
                parent.chmod(0)
            attempt()
            row = observations[-1]
            assert row['correlation'] == 'matched' and row['os_errno'] == expected, row
            assert all(event['target_kind'] == 1 for event in row['events']
                       if event['os_errno'] > 0)
            cases.append({'case': name, 'os_errno': expected, 'matched': True})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: attempt(), range(400)))
        failures = [row for row in observations if row['event'] == 'sqlite_io_failure']
        assert len(failures) == 402
        matched = [row for row in failures[2:] if row['correlation'] == 'matched']
        assert matched and all(row['os_errno'] == 13 for row in matched)
        assert all(row['os_errno'] is None for row in failures[2:]
                   if row['correlation'] != 'matched')
        assert len(controller.events) <= 256
        assert tuple(sqlite_io._PINS) == pins
        assert str(path) not in json.dumps(observations)
        assert 'private' not in json.dumps(observations)
        summary = {'architecture': __import__('platform').machine(), 'uid': os.geteuid(),
                   'sqlite_version': sqlite3.sqlite_version, 'abi': 1, 'cases': cases,
                   'concurrent_attempts': 400, 'matched': len(matched),
                   'wrong_errno_associations': 0, 'native_drops': controller.native.dropped_count(),
                   'cache_evictions': controller.evictions, 'cache_bound': 256,
                   'strong_refs_retained': True, 'raw_paths_or_sql_emitted': False}
    finally:
        if parent.exists():
            parent.chmod(0o700)
print(json.dumps(summary))
# Deliberately leave the native callback pinned until process termination.
