import ctypes
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from seed_agent.media_import import sqlite_io
from seed_agent.media_import.store import MediaStore


class Native:
    def __init__(self):
        self.sequence = 1
        self.drops = 0
        self.rows = []
        self.read_error = False

    def sequence_mark(self):
        return self.sequence

    def dropped_count(self):
        return self.drops

    def drain(self, buffer, maximum):
        if self.read_error:
            raise RuntimeError('private detail')
        rows, self.rows = self.rows[:maximum], self.rows[maximum:]
        for index, row in enumerate(rows):
            buffer[index] = row
        return len(rows)

    def add(self, *, tid=None, errno=2, target=1, flags=1, code=14):
        self.rows.append(sqlite_io._Record(
            self.sequence, 1, tid or threading.get_native_id(), code, errno, 123, 1,
            target, flags,
        ))
        self.sequence += 1


def error():
    exc = sqlite3.OperationalError('private SQL/path')
    exc.sqlite_errorcode = 14
    return exc


@pytest.fixture
def capture(tmp_path, monkeypatch):
    native = Native()
    instance = sqlite_io._Capture(native, tmp_path / 'state.db')
    output = []
    monkeypatch.setattr(sqlite_io, '_emit', output.append)
    return instance, native, output


def test_same_session_thread_window_family_and_known_target(capture):
    instance, native, output = capture
    native.add(errno=13)  # Old row must not explain this failure.
    token = instance.begin(instance.path)
    native.add()
    # Generic SQLite wrapper contains no native OS evidence.
    native.add(errno=-1, target=0, flags=0)
    instance.failure(token, 'connect', error())
    assert output[-1]['os_errno'] == 2
    assert output[-1]['correlation'] == 'matched'
    assert output[-1]['session'] == instance.session
    assert 'private' not in str(output)
    assert instance.begin(Path('/other.db')) is None


@pytest.mark.parametrize('extra', [
    {'errno': 13}, {'target': 0}, {'flags': 3}, {'code': 10},
])
def test_ambiguous_native_rows_are_uncorrelated(capture, extra):
    instance, native, output = capture
    token = instance.begin(instance.path)
    native.add()
    native.add(**extra)
    instance.failure(token, 'body', error())
    assert output[-1]['correlation'] == 'uncorrelated'
    assert output[-1]['os_errno'] is None


@pytest.mark.parametrize('damage', ['drops', 'read', 'evict'])
def test_incomplete_windows_are_uncorrelated(capture, damage):
    instance, native, output = capture
    token = instance.begin(instance.path)
    native.add()
    if damage == 'drops':
        native.drops = 1
    elif damage == 'read':
        native.read_error = True
    else:
        instance.evicted_through = token[0]
    instance.failure(token, 'body', error())
    assert output[-1]['correlation'] == 'uncorrelated'
    assert output[-1]['os_errno'] is None


def test_single_consumer_retains_other_thread_rows(capture):
    instance, native, output = capture
    token = instance.begin(instance.path)
    native.add(tid=threading.get_native_id() + 1)
    native.add()
    instance.failure(token, 'body', error())
    assert len(instance.events) == 2 and len(output[-1]['events']) == 1
    assert output[-1]['os_errno'] == 2


def test_cache_is_bounded_and_evictions_explicit(capture):
    instance, native, output = capture
    for _ in range(5):
        token = instance.begin(instance.path)
        for _ in range(64):
            native.add()
        instance.failure(token, 'body', error())
    assert len(instance.events) == 256
    assert output[-1]['cache_evictions'] == 64
    assert output[-1]['events_truncated'] is True


def test_diagnostic_failures_preserve_business_commit_rollback_and_exception(tmp_path, monkeypatch):
    store = MediaStore(tmp_path / 'state.db')

    def broken(*args):
        raise RuntimeError('diagnostic helper failed')

    monkeypatch.setattr(sqlite_io, '_controller', SimpleNamespace(begin=broken, failure=broken))
    with store._connect() as conn:
        conn.execute('CREATE TABLE fixture (value INTEGER)')
        conn.execute('INSERT INTO fixture VALUES(1)')
    original = error()
    with pytest.raises(sqlite3.OperationalError) as caught, store._connect() as conn:
        conn.execute('INSERT INTO fixture VALUES(2)')
        raise original
    assert caught.value is original
    with store._connect() as conn:
        assert conn.execute('SELECT * FROM fixture').fetchall() == [(1,)]


def test_store_reports_connect_and_body_without_new_connections(tmp_path, monkeypatch):
    store = MediaStore(tmp_path / 'state.db')
    observations = []
    monkeypatch.setattr(sqlite_io, 'begin', lambda path: 'token')
    monkeypatch.setattr(sqlite_io, 'failure', lambda token, phase, exc:
                        observations.append((token, phase, exc)))
    original = error()
    with pytest.raises(sqlite3.Error), store._connect():
        raise original
    assert observations == [('token', 'body', original)]

    def fail_connect(*args, **kwargs):
        raise original

    monkeypatch.setattr(sqlite3, 'connect', fail_connect)
    with pytest.raises(sqlite3.Error), store._connect():
        pass
    assert observations[-1] == ('token', 'connect', original)


@pytest.mark.parametrize('case', ['owner', 'platform', 'threads', 'library'])
def test_startup_safe_disabled_and_no_business_connection(monkeypatch, tmp_path, case):
    monkeypatch.setattr(sqlite_io, '_attempted', False)
    monkeypatch.setattr(sqlite_io, '_controller', None)
    monkeypatch.setattr(sqlite_io.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(sqlite_io.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(sqlite_io.threading, 'active_count', lambda: 1)
    observations = []
    monkeypatch.setattr(sqlite_io, '_emit', observations.append)
    if case == 'platform':
        monkeypatch.setattr(sqlite_io.platform, 'system', lambda: 'Darwin')
    if case == 'threads':
        monkeypatch.setattr(sqlite_io.threading, 'active_count', lambda: 2)
    monkeypatch.setattr(sqlite_io, '_load', lambda path: (_ for _ in ()).throw(OSError('private')))
    sqlite_io.startup(tmp_path / 'state.db', exclusive_worker_owner=case != 'owner')
    assert sqlite_io._controller is None
    assert len(observations) == 1
    assert observations[0]['state'] == 'disabled'
    assert observations[0]['reason'] in {'owner', 'startup', 'unavailable'}
    assert 'private' not in str(observations)


def test_ctypes_record_abi_size():
    assert ctypes.sizeof(sqlite_io._Record) == 48


@pytest.mark.parametrize('case', ['abi', 'record', 'atomics', 'path', 'provider', 'source',
                                 'registration', 'success'])
def test_loader_validation_and_registration_pins(monkeypatch, tmp_path, case):
    from unittest.mock import Mock

    source = ctypes.create_string_buffer(b'expected-source')
    version = ctypes.create_string_buffer(sqlite3.sqlite_version.encode())
    source_function = ctypes.CFUNCTYPE(ctypes.c_void_p)(lambda: ctypes.addressof(source))
    version_function = ctypes.CFUNCTYPE(ctypes.c_void_p)(lambda: ctypes.addressof(version))
    registrations = []

    def register(option, callback, context):
        assert len(sqlite_io._PINS) == 3  # Already pinned before a successful config call.
        registrations.append(option)
        return 1 if case == 'registration' else 0

    config_function = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                      ctypes.c_void_p)(register)
    native = SimpleNamespace(
        expected_source_id=Mock(return_value=b'wrong' if case == 'source' else b'expected-source'),
        configure_db_path=Mock(return_value=1 if case == 'path' else 0),
        drain=Mock(), record_size=Mock(return_value=1 if case == 'record' else 48),
        sequence_mark=Mock(), dropped_count=Mock(),
        same_provider=Mock(return_value=0 if case == 'provider' else 1),
        capture_abi=Mock(return_value=0 if case == 'abi' else 1),
        lock_free=Mock(return_value=0 if case == 'atomics' else 1),
        capture=ctypes.CFUNCTYPE(None) (lambda: None),
    )
    provider = SimpleNamespace(sqlite3_config=config_function,
                               sqlite3_sourceid=source_function,
                               sqlite3_libversion=version_function,
                               sqlite3_libversion_number=Mock(return_value=3046001))
    libraries = iter([native, provider])
    monkeypatch.setattr(ctypes, 'CDLL', lambda path: next(libraries))
    monkeypatch.setattr(sqlite_io, '_PINS', [])
    if case == 'success':
        result = sqlite_io._load(tmp_path / 'state.db')
        assert result.native is native
        assert registrations == [16]
    else:
        with pytest.raises(ValueError):
            sqlite_io._load(tmp_path / 'state.db')
        assert registrations == ([16] if case == 'registration' else [])
    if case in {'registration', 'success'}:
        assert sqlite_io._PINS[:2] == [native, provider]
    else:
        assert not sqlite_io._PINS


@pytest.mark.parametrize('helper', ['begin', 'failure'])
@pytest.mark.parametrize('failure_case,expected,calls', [
    ('commit', 'commit', ['commit', 'rollback', 'close']),
    ('rollback', 'rollback', ['rollback', 'close']),
    ('close', 'close', ['commit', 'close']),
    ('all_cleanup', 'close', ['rollback', 'close']),
])
def test_diagnostic_failure_preserves_real_cleanup_error_priority(
    tmp_path, monkeypatch, helper, failure_case, expected, calls,
):
    store = MediaStore(tmp_path / 'state.db')
    errors = {name: error() for name in ('body', 'commit', 'rollback', 'close')}
    observed = []

    def action(name):
        observed.append(name)
        if (name == failure_case or name in {'rollback', 'close'}
                and failure_case == 'all_cleanup'):
            raise errors[name]

    connection = SimpleNamespace(execute=lambda _: None,
                                 commit=lambda: action('commit'),
                                 rollback=lambda: action('rollback'),
                                 close=lambda: action('close'))
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: connection)

    def broken(*args):
        raise RuntimeError('diagnostic helper error')

    controller = SimpleNamespace(begin=lambda _: 'token', failure=lambda *args: None)
    setattr(controller, helper, broken)
    monkeypatch.setattr(sqlite_io, '_controller', controller)
    with pytest.raises(sqlite3.Error) as caught, store._connect():
        if failure_case in {'rollback', 'all_cleanup'}:
            raise errors['body']
    assert caught.value is errors[expected]
    assert observed == calls


def test_cleanup_has_its_own_sequence_window(tmp_path, monkeypatch):
    store = MediaStore(tmp_path / 'state.db')
    counter = iter(range(100))
    observations = []
    monkeypatch.setattr(sqlite_io, 'begin', lambda _: next(counter))
    monkeypatch.setattr(sqlite_io, 'failure', lambda token, phase, exc:
                        observations.append((token, phase)))

    def broken():
        raise error()

    connection = SimpleNamespace(execute=lambda _: None, rollback=broken, close=broken)
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: connection)
    with pytest.raises(sqlite3.Error), store._connect():
        raise error()
    assert [phase for _, phase in observations] == ['body', 'rollback', 'close']
    assert len({token for token, _ in observations}) == 3
