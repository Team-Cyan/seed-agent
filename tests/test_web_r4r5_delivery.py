"""The real HTTP handler ships the reviewed conditional-state fixes on reload."""

import hashlib
from http.client import HTTPConnection
from pathlib import Path

from test_web_settings import _running_server, _write_minimal_config


def test_static_handler_delivers_current_r4_r5_asset_without_stale_cache(tmp_path):
    config = _write_minimal_config(tmp_path)
    source = Path(__file__).resolve().parents[1] / "src/seed_agent/web/static/app.js"
    with _running_server(config) as host:
        connection = HTTPConnection(host)
        connection.request("GET", "/static/app.js")
        response = connection.getresponse()
        body = response.read()
        connection.close()
    assert response.status == 200
    assert response.getheader("Cache-Control") == "no-cache"
    assert hashlib.sha256(body).digest() == hashlib.sha256(source.read_bytes()).digest()
    assert b"Promise.allSettled" in body and b"clear-filters" in body
