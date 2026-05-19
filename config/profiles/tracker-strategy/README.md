# Tracker Strategy Profile Examples

These files are recommended configuration combinations, not runtime profile
switches. `seed-agent` reads concrete knobs from the main config: discovery
thresholds, M-Team API filters, scoring weights, and downloader budget gates.

Use these examples as copy/merge material when tuning a real config.

## Files

- `balanced.yaml`: conservative default-style behavior.
- `upload-farming.yaml`: prioritizes live demand and upload opportunity.
- `space-saving.yaml`: prioritizes lower storage risk and smaller active pools.

## Workflow

1. Run `seed-agent strategy-report --config <config>`.
2. Compare accepted/rejected buckets by leechers, seed/leecher ratio, size, and score.
3. Copy selected knobs from one of these examples into the real config.
4. Run `seed-agent run-once --config <config>` as a dry-run.
5. Execute only after reviewing accepted candidates and qB runtime gates.
