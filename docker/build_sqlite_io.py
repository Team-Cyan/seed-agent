"""Build an optional native capture shim; never link another SQLite provider."""
import _sqlite3
import ctypes
import subprocess
import sys
from pathlib import Path

provider = ctypes.CDLL(_sqlite3.__file__)
provider.sqlite3_sourceid.restype = ctypes.c_char_p
source_id = provider.sqlite3_sourceid().decode('ascii')
assert 0 < len(source_id) <= 128 and '"' not in source_id
output = Path(sys.argv[1])
output.parent.mkdir(parents=True, exist_ok=True)
subprocess.run([
    'cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared', '-Wl,-z,now',
    '-DEXPECTED_SQLITE_SOURCE_ID="' + source_id + '"',
    str(Path(__file__).with_name('sqlite_io_native.c')), '-o', str(output),
], check=True)
