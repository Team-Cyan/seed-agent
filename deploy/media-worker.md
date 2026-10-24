# Media worker deployment contract

This template implements delivery plan `2026-10-24.r2`. It is an example, not a
production deployment receipt. Use the same immutable image reference/digest for
both roles. Configure `deployment.source_id` explicitly in the one shared config
directory. Seed/Web writes that directory; media mounts the directory read-only
so atomic replacement remains visible. Keep desired policy in YAML, not separate
role-specific business environment overrides.

`docker-compose.example.yml` gives each role separate CPU/memory/PID limits and
five failure restarts. Docker health state alone does not restart a container;
a failed process must exit for the restart policy to apply. The media worker's
read-only health response reports the last lifecycle error, and cannot establish
whether the container restart budget is exhausted. Inspect container runtime
state for that evidence. The media role has no Web port, downloader secrets,
Docker socket or dependency on the seed process.

Initialize the independent media state explicitly with `media-state-init` before
starting the media worker. The shared default media database is
`/app/.media-import/state.db`; seed/Web may enqueue commands there. The worker
never mounts the seed database. Align configured paths and individual secret-file
mounts; remove credentials for disabled providers. The four listed files are only
examples for the four enabled Phase 1 providers, not a requirement to enable them.
Do not bind a whole downloader-containing secrets directory into the worker.

Set the host `MEDIA_PARENT_DIR` to one existing common parent containing all source
and library paths, and configure container paths under `/media`. The default
production layout uses `/media/Media` as source and `/media/Library/{Movie,TV,Animation}`
as outputs. Do not add nested source/target bind mounts, including a source RO
overlay: Linux hardlinks can fail with `EXDEV` across separate mounts even on the
same underlying filesystem. The common parent must also be on one compatible
filesystem; this layout alone does not prove hardlink capability. There is no copy
fallback or publisher service. The RW common parent provides no kernel-level
source read-only guarantee; application rules preserve source bytes, names and
permissions. Verify marker/root identity, real mounts and a controlled hardlink
probe before production acceptance. Do not use source deletion as a probe.

State is a separate RW bind; config and individual media credential files are RO.
Avoid placing state inside source/library. Existing root identity/readiness and
receipt controls remain mandatory. Test fixture success cannot prove deployed
mount behavior, full-library completion, provider coverage or Plex playback.
