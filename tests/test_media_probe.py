import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from seed_agent.cli import app
from seed_agent.media_import.probe import ProbeError, _ffprobe, describe, parse_probe, probe


def result(duration="9367.189"):
    return {
        "format": {"duration": duration, "format_name": "matroska,webm"},
        "streams": [{"codec_type": "video", "avg_frame_rate": "25/1", "codec_name": "h264"}],
    }


def fake_ffprobe(tmp_path, monkeypatch, body):
    executable = tmp_path / "ffprobe"
    executable.write_text(f"#!{sys.executable}\n" + body)
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    return executable


def test_content_probe_cli_and_script_share_real_fd_and_write_no_source_or_state(
    tmp_path, monkeypatch
):
    path = tmp_path / "video.unknown"
    path.write_bytes(b"original-video")
    fake_ffprobe(
        tmp_path,
        monkeypatch,
        'import sys\nassert sys.argv[sys.argv.index("-protocol_whitelist")+1]=="file,pipe"\n'
        'assert open(sys.argv[-1],"rb").read()==b"original-video"\n'
        + f"sys.stdout.write({json.dumps(result())!r})\n",
    )
    before = path.stat()
    value = describe(path)
    assert value["duration_seconds"] == 9367.189 and value["duration_hms"] == "02:36:07.189"
    assert value["duration_provenance"] == "ffprobe_local_file" and not value["edition_proven"]
    runner = CliRunner().invoke(app, ["media-probe", str(path), "--json"])
    assert runner.exit_code == 0, runner.output
    assert json.loads(runner.output) == value
    script = subprocess.run(
        [sys.executable, "scripts/probe_media.py", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "02:36:07.189" in script.stdout and "9367.189" in script.stdout
    assert path.read_bytes() == b"original-video" and path.stat().st_mtime_ns == before.st_mtime_ns
    assert not list(tmp_path.rglob("*.db"))


@pytest.mark.parametrize("duration", ["NaN", "Infinity", "-Infinity", "0", "-1", "N/A", None])
def test_invalid_duration_never_becomes_zero(duration):
    with pytest.raises(ProbeError):
        parse_probe(json.dumps(result(duration)))


def test_missing_video_and_attached_picture_only_are_unknown():
    for streams in [
        [],
        [{"codec_type": "audio"}],
        [{"codec_type": "video", "disposition": {"attached_pic": 1}}],
    ]:
        value = result()
        value["streams"] = streams
        with pytest.raises(ProbeError, match="no_video"):
            parse_probe(json.dumps(value))


def test_output_and_timeout_are_enforced_during_streaming(tmp_path, monkeypatch):
    fake_ffprobe(
        tmp_path, monkeypatch, 'import sys\nsys.stdout.write("x"*2000000)\nsys.stdout.flush()\n'
    )
    with pytest.raises(ProbeError, match="output_limit"):
        _ffprobe(Path("/unused"), max_output=10000)
    fake_ffprobe(
        tmp_path, monkeypatch, 'import sys\nsys.stderr.write("secret"*100000)\nsys.stderr.flush()\n'
    )
    with pytest.raises(ProbeError, match="output_limit"):
        _ffprobe(Path("/unused"))
    fake_ffprobe(tmp_path, monkeypatch, "import time\ntime.sleep(5)\n")
    with pytest.raises(ProbeError, match="timeout"):
        _ffprobe(Path("/unused"), timeout=0.05)


def test_probe_failure_is_fixed_unknown_json_not_raw_ffprobe_stderr(tmp_path, monkeypatch):
    path = tmp_path / "bad.avi"
    path.write_bytes(b"bad")
    fake_ffprobe(
        tmp_path, monkeypatch, 'import sys\nsys.stderr.write("private-secret-path")\nsys.exit(7)\n'
    )
    run = CliRunner().invoke(app, ["media-probe", str(path), "--json"])
    assert run.exit_code == 1 and json.loads(run.output) == {
        "status": "unknown",
        "error": "probe_failed",
    }
    assert "private-secret" not in run.output


def test_probe_rejects_replaced_source_and_nonregular_files(tmp_path, monkeypatch):
    from seed_agent.media_import import probe as module

    path = tmp_path / "video.mp4"
    path.write_bytes(b"old")

    def replace_source(*args, **kwargs):
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"new")
        replacement.replace(path)
        return json.dumps(result()).encode()

    monkeypatch.setattr(module, "_ffprobe", replace_source)
    with pytest.raises(ProbeError, match="changed"):
        probe(path)
    link = tmp_path / "link.mkv"
    link.symlink_to(path)
    with pytest.raises(ProbeError, match="regular"):
        probe(link)
