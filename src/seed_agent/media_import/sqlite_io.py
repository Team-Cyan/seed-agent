"""Optional, startup-only diagnostics for the explicitly owned worker LOG slot.

No public GET_LOG exists. Only the audited, dedicated CLI worker may opt in.
This module never opens a database or its sidecars and never unloads a callback.
"""

from __future__ import annotations

import ctypes
import json
import logging
import platform
import sqlite3
import threading
import uuid
from collections import deque
from pathlib import Path

_LIBRARY = '/usr/local/lib/seed-agent/sqlite_io_native.so'
# Pin before registration, even if later Python bookkeeping fails. No teardown.
_PINS = []
_controller = None
_attempted = False


class _Record(ctypes.Structure):
    _fields_ = [
        ('sequence', ctypes.c_uint64), ('monotonic_ns', ctypes.c_uint64),
        ('tid', ctypes.c_uint32), ('sqlite_code', ctypes.c_uint32),
        ('os_errno', ctypes.c_int32), ('unix_line', ctypes.c_int32),
        ('syscall_kind', ctypes.c_uint32), ('target_kind', ctypes.c_uint32),
        ('flags', ctypes.c_uint32),
    ]


def _emit(payload):
    try:
        logging.getLogger(__name__).warning('media_sqlite_io %s', json.dumps(payload))
    except Exception:
        pass


class _Capture:
    def __init__(self, native, path):
        self.native, self.path = native, Path(path).absolute()
        self.session = uuid.uuid4().hex
        self.lock = threading.Lock()
        self.events = deque()
        self.evicted_through = 0
        self.evictions = 0
        self.read_failures = 0

    def begin(self, path):
        if Path(path).absolute() != self.path:
            return None
        return (self.native.sequence_mark(), threading.get_native_id(),
                self.native.dropped_count(), self.read_failures)

    def failure(self, token, phase, exc):
        # Capture before consumer/rollback/close can produce any new rows.
        end = self.native.sequence_mark()
        code = getattr(exc, 'sqlite_errorcode', None)
        if token is None or not isinstance(code, int):
            return
        start, tid, initial_drops, initial_read_failures = token
        with self.lock:
            try:
                buffer = (_Record * 64)()
                count = self.native.drain(buffer, 64)
                if not 0 <= count <= 64:
                    raise ValueError('invalid native row count')
                for row in buffer[:count]:
                    event = {name: int(getattr(row, name)) for name, _ in _Record._fields_}
                    if len(self.events) == 256:
                        old = self.events.popleft()
                        self.evicted_through = max(self.evicted_through, old['sequence'])
                        self.evictions += 1
                    self.events.append(event)
            except Exception:
                self.read_failures += 1
            drops = self.native.dropped_count()
            rows = [e for e in self.events if e['tid'] == tid and start <= e['sequence'] < end]
            candidates = [e for e in rows if e['target_kind'] in (1, 2, 3, 4)
                          and e['syscall_kind'] and e['flags'] == 1 and e['os_errno'] > 0
                          and e['sqlite_code'] & 255 == code & 255]
            complete = (drops == initial_drops and self.evicted_through < start
                        and self.read_failures == initial_read_failures)
            errnos = {e['os_errno'] for e in candidates}
            # Generic SQLite wrapper rows carry no OS evidence. A parsed native
            # row for another target, truncation or conflicting errno is ambiguous.
            parsed = [e for e in rows if e['flags'] & 1]
            correlated = (complete and len(errnos) == 1 and len(candidates) == len(parsed)
                          and not any(e['flags'] & 2 for e in rows))
            _emit({'event': 'sqlite_io_failure', 'session': self.session, 'tid': tid,
                   'sequence_start': start, 'sequence_end': end, 'phase': phase,
                   'sqlite_code': code, 'correlation': 'matched' if correlated else 'uncorrelated',
                   'os_errno': next(iter(errnos)) if correlated else None,
                   'events': rows[:16], 'events_truncated': len(rows) > 16,
                   'native_drops': drops, 'cache_evictions': self.evictions,
                   'read_failures': self.read_failures})


def _load(path):
    import _sqlite3

    native = ctypes.CDLL(_LIBRARY)
    native.expected_source_id.restype = ctypes.c_char_p
    native.configure_db_path.argtypes = [ctypes.c_char_p]
    native.drain.argtypes = [ctypes.POINTER(_Record), ctypes.c_size_t]
    native.drain.restype = ctypes.c_size_t
    native.record_size.restype = ctypes.c_size_t
    for name in ('sequence_mark', 'dropped_count'):
        getattr(native, name).restype = ctypes.c_uint64
    native.same_provider.argtypes = [ctypes.c_void_p] * 3
    if native.capture_abi() != 1 or native.record_size() != ctypes.sizeof(_Record):
        raise ValueError('abi')
    if native.lock_free() != 1:
        raise ValueError('atomics')
    if native.configure_db_path(str(Path(path).absolute()).encode()) != 0:
        raise ValueError('path')
    provider = ctypes.CDLL(_sqlite3.__file__)
    provider.sqlite3_sourceid.restype = ctypes.c_char_p
    provider.sqlite3_libversion.restype = ctypes.c_char_p
    functions = [provider.sqlite3_config, provider.sqlite3_sourceid, provider.sqlite3_libversion]
    pointers = [ctypes.cast(function, ctypes.c_void_p) for function in functions]
    if not native.same_provider(*pointers):
        raise ValueError('provider')
    if (provider.sqlite3_sourceid() != native.expected_source_id()
            or provider.sqlite3_libversion().decode('ascii') != sqlite3.sqlite_version
            or provider.sqlite3_libversion_number() < 3042000):
        raise ValueError('source')
    provider.sqlite3_config.argtypes = [ctypes.c_int]
    provider.sqlite3_config.restype = ctypes.c_int
    capture = _Capture(native, path)
    _PINS.extend((native, provider, capture))
    # Final fallible native operation. Never reconfigure, unregister or unload.
    if provider.sqlite3_config(16, ctypes.cast(native.capture, ctypes.c_void_p),
                               ctypes.c_void_p()) != 0:
        raise ValueError('registration')
    return capture


def startup(path, *, exclusive_worker_owner=False):
    """No logger detection is possible: the dedicated entrypoint supplies ownership."""
    global _attempted, _controller
    if _attempted:
        return
    _attempted = True
    try:
        if not exclusive_worker_owner:
            raise ValueError('owner')
        if (platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64')
                or threading.current_thread() is not threading.main_thread()
                or threading.active_count() != 1):
            raise ValueError('startup')
        _controller = _load(path)
    except Exception as exc:
        allowed = {'owner', 'startup', 'abi', 'atomics', 'path', 'provider',
                   'source', 'registration'}
        reason = str(exc) if type(exc) is ValueError and str(exc) in allowed else 'unavailable'
        _emit({'event': 'sqlite_io_startup', 'state': 'disabled', 'reason': reason})
        return
    _emit({'event': 'sqlite_io_startup', 'state': 'enabled', 'session': _controller.session})


def begin(path):
    try:
        return _controller.begin(path) if _controller else None
    except Exception:
        return None


def failure(token, phase, exc):
    try:
        if _controller and token is not None:
            _controller.failure(token, phase, exc)
    except Exception:
        pass
