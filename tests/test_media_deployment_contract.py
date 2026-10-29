"""Static examples prove declared isolation, never real mount/image acceptance."""

import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_media_role_has_one_common_parent_no_source_overlay():
    services = yaml.safe_load((ROOT / "deploy/docker-compose.example.yml").read_text())["services"]
    seed, media = services["seed-agent"], services["media-worker"]
    assert seed["image"] == media["image"] and "immutable" in media["image"]
    assert media["environment"]["SEED_AGENT_ROLE"] == "media"
    assert media["environment"]["SEED_AGENT_MODE"] == "media-worker"
    assert media["environment"]["SEED_AGENT_WEB_ENABLED"] == "false"
    assert "ports" not in media and "depends_on" not in media
    assert media["read_only"] is True
    assert media["restart"] == seed["restart"] == "on-failure:5"
    assert all(
        role.get(key) for role in [seed, media] for key in ["cpus", "mem_limit", "pids_limit"]
    )
    mounts = media["volumes"]
    media_mounts = [m for m in mounts if ":/media" in m]
    assert len(media_mounts) == 1 and media_mounts[0].endswith(":/media:rw")
    assert "../config:/app/config:ro" in mounts
    assert "../.media-import:/app/.media-import:rw" in mounts
    assert all(".seed-agent" not in m and "docker.sock" not in m for m in mounts)
    secret_mounts = [m for m in mounts if "/secrets" in m]
    assert len(secret_mounts) == 4
    assert all(m.endswith(".json:ro") and m.count(".json") == 2 for m in secret_mounts)
    assert all("downloader" not in m and "qbittorrent" not in m for m in secret_mounts)
    assert media["healthcheck"]["test"] == [
        "CMD",
        "/app/docker/entrypoint.sh",
        "healthcheck",
        "--role",
        "media",
        "--config",
        "/app/config/config.yaml",
    ]


def test_unraid_template_declares_bounded_role_and_common_parent_mount():
    root = ET.parse(ROOT / "deploy/unraid/media-worker.xml").getroot()
    assert root.findtext("Privileged") == "false"
    assert root.find("WebUI") is None
    extra = root.findtext("ExtraParams")
    for argument in [
        "--restart=on-failure:5",
        "--cpus=1.0",
        "--memory=1g",
        "--pids-limit=128",
        "--read-only",
        "healthcheck --role media",
    ]:
        assert argument in extra
    configs = {c.attrib["Target"]: c for c in root.findall("Config")}
    assert configs["SEED_AGENT_MODE"].text == "media-worker"
    assert configs["SEED_AGENT_WEB_ENABLED"].text == "false"
    mounts = {k: c.attrib["Mode"] for k, c in configs.items() if c.attrib["Type"] == "Path"}
    assert mounts["/media"] == "rw"
    assert not any(k.startswith("/media/") for k in mounts)
    assert mounts["/workspace/runtime/config"] == "ro"
    assert mounts["/workspace/runtime/.media-import"] == "rw"
    assert all(
        mode == "ro" and path.endswith(".json")
        for path, mode in mounts.items()
        if "secrets" in path
    )
    assert not any("docker.sock" in path or "/.seed-agent" in path for path in mounts)


def test_deployment_guidance_does_not_promise_kernel_source_ro_or_hardlink_proof():
    text = (ROOT / "deploy/media-worker.md").read_text()
    for required in ["EXDEV", "kernel-level", "no copy", "atomic replacement", "restart budget"]:
        assert required in text
