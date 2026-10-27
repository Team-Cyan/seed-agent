#!/usr/bin/env python3
"""Inspect AVI/MP4/MKV and other local media by content, without state writes.

Usage: uv run python scripts/probe_media.py /path/to/video --json
"""

import sys

from seed_agent.cli import app

if __name__ == "__main__":
    app(["media-probe", *sys.argv[1:]])
