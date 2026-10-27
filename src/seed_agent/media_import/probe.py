"""Offline bounded media inspection shared by inventory and the standalone CLI."""

import json
import math
import os
import re
import selectors
import stat
import subprocess
import time
from fractions import Fraction
from pathlib import Path


class ProbeError(ValueError):
    """A fixed, non-sensitive inspection failure; never a guessed zero duration."""


def _ffprobe(path: Path, *, timeout=20, max_output=1_000_000, pass_fd=None):
    args = [
        "ffprobe",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-show_entries",
        "format=duration,format_name:stream=codec_type,codec_name,width,height,avg_frame_rate,channels:"
        "stream_tags=language:stream_disposition=forced,hearing_impaired,attached_pic",
        "-of",
        "json",
        str(path),
    ]
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=() if pass_fd is None else (pass_fd,),
        )
    except OSError:
        raise ProbeError("ffprobe_unavailable") from None
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProbeError("probe_timeout")
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffers[key.data].extend(chunk)
                    bound = max_output if key.data == "stdout" else 65536
                    if len(buffers[key.data]) > bound:
                        raise ProbeError("probe_output_limit")
            try:
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise ProbeError("probe_timeout") from None
        if code:
            raise ProbeError("probe_failed")
        return bytes(buffers["stdout"])
    finally:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait()
        process.stdout.close()
        process.stderr.close()


def parse_probe(raw):
    try:
        data = json.loads(raw)
        raw_duration = data["format"]["duration"]
        if type(raw_duration) not in {int, float, str}:
            raise ProbeError("probe_invalid_duration")
        duration = float(raw_duration)
        streams = data["streams"]
    except ValueError, TypeError, KeyError:
        raise ProbeError("probe_invalid_result") from None
    if not math.isfinite(duration) or not 0 < duration <= 604800:
        raise ProbeError("probe_invalid_duration")
    if (
        not isinstance(streams, list)
        or len(streams) > 256
        or not all(isinstance(s, dict) for s in streams)
    ):
        raise ProbeError("probe_invalid_streams")
    if any(not isinstance(s.get("disposition", {}), dict) for s in streams):
        raise ProbeError("probe_invalid_streams")
    videos = [
        s
        for s in streams
        if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
    ]
    if not videos:
        raise ProbeError("probe_no_video")
    fps = None
    try:
        number = float(Fraction(videos[0].get("avg_frame_rate", "0/1")))
        if math.isfinite(number) and 0 < number < 1000:
            fps = number
    except ValueError, TypeError, ZeroDivisionError:
        pass
    container = data["format"].get("format_name")
    if not isinstance(container, str) or not re.fullmatch(r"[A-Za-z0-9_,]{1,128}", container):
        container = None
    return {
        "duration": duration,
        "fps": fps,
        "container": container,
        "streams": streams,
        "duration_provenance": "ffprobe_local_file",
    }


def probe(path: Path) -> dict:
    path = Path(path).absolute()
    fd = None

    def identity(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

    try:
        initial = path.lstat()
        if not stat.S_ISREG(initial.st_mode):
            raise ProbeError("probe_regular_file_required")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or identity(initial) != identity(before):
            raise ProbeError("probe_source_changed")
        value = parse_probe(_ffprobe(Path(f"/dev/fd/{fd}"), pass_fd=fd))
        after = os.fstat(fd)
        current = path.lstat()
        if identity(before) != identity(after) or identity(before) != identity(current):
            raise ProbeError("probe_source_changed")
        return value
    except ProbeError:
        raise
    except OSError:
        raise ProbeError("probe_file_unavailable") from None
    finally:
        if fd is not None:
            os.close(fd)


def duration_text(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    whole, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d}.{milliseconds:03d}"


def describe(path):
    value = probe(path)
    return {
        "status": "ok",
        "duration_seconds": value["duration"],
        "duration_hms": duration_text(value["duration"]),
        "container": value["container"],
        "fps": value["fps"],
        "streams": value["streams"],
        "duration_provenance": value["duration_provenance"],
        "edition_proven": False,
    }
