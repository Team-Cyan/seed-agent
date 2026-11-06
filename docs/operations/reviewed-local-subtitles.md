# Reviewed Local Subtitle Delivery

This is a narrow normal-worker path for a plain SRT already obtained and reviewed
by an operator. It does not solve website challenges, download providers, unpack
archives, infer identity from a title, or guess timing corrections. Normal provider
discovery and the shared choice cap continue independently.

## Stage Immutable Inputs

The controller stages each bounded regular SRT at
`<media-state-directory>/subtitle-inbox/<sha256>.srt`, where the directory is the
parent of the configured media database. The SHA-256 is of the exact submitted
bytes. The worker rejects symlinks, non-regular files, oversized input, digest
changes, archives and unsupported formats. There is no caller-supplied host path.

An explicitly precomputed timing variant also requires its original plain SRT in
that inbox under the original byte digest. Original and transformed files are
preserved. Staging and controller permissions are separate from command submission;
this command is not an upload API or a new filesystem writer.

## Preview And Approve One Source

Submit `media-subtitle-import --request REQUEST.json --config CONFIG.yaml`.
This only queues a preview. The normal media worker reads and validates the staged
object, confirms the imported source and owned video receipt, then records a
`subtitle_local_preview` event and returns `preview_id` plus its exact binding.

The request has exactly these required keys:

- `source_id`, `generation`, `fingerprint`: current imported source fences.
- `payload_sha256`: exact staged input byte digest.
- `language`: explicit reviewed `zh`, `zh-Hans`, `zh-Hant` or `en`; it must satisfy
  an active profile requirement. Country labels or filenames do not grant script
  evidence. Use generic Chinese only if the profile permits it.
- `kind`: `full`, `forced` or `sdh`, matching the active profile.
- `provenance`: an object containing `provider`, `reference`, `original_sha256`
  and `transformation`. Provider is `manual`, `zimuku`, `assrt`, `subdl` or
  `opensubtitlescom`. Reference is a bounded stable identifier, never a URL,
  credential or arbitrary path. These fields are operator provenance, not remote
  provider identity proof.

For unchanged input use `transformation: {"kind": "none"}` and equal original and
input digests. For an already prepared timing variant use:

```json
{
  "kind": "precomputed_time_scale",
  "numerator": 24,
  "denominator": 25,
  "source_fps": 25,
  "evidence_sha256": "<64 lower-case hex characters>"
}
```

The worker verifies the actual source FPS and that all timestamp-line conversions
and unchanged cue text match the staged original using that explicit rational
scale, with nearest-millisecond rounding. It never chooses the scale or produces
a new subtitle. The evidence digest references the operator's reviewed evidence;
it is not an independent assertion that the whole film is synchronized.

After reviewing the preview and source/version/timing evidence, resubmit the same
request with `preview_id` and `compatibility_acknowledged: true`, adding `--execute`.
The subtitle configuration policy must also permit execution. Submission pins
the media configuration, restore epoch and source/plan baseline. The worker
compares the preview binding again, checks source and staged inputs immediately
before publication, and uses the existing common subtitle publisher.

The common publisher preserves source, plan, root, claim, active video receipt and
manual-sidecar protections. Admission counts active managed digests across providers
before publishing; duplicates return `already_present` and the shared cap returns
`limit_reached`. A live job claim cannot be stolen. The event provenance identifies
this as `local` / `operator_source_review`, without invented API IDs or hash matches.
Both submitted byte digest and normalized published byte digest remain in the
preview/import audit. Provider gates, allowances and completed search history are
not cleared by this path.

After an interrupted command, reconcile the durable command, publication intent
and owned artifact receipts. Never blindly replay an uncertain writer. The command
does not delete or overwrite input objects, manual subtitles or older receipts.

## Library Progress

`engine.snapshot()` and `media-status` include library-wide `subtitle_progress`,
independent of source-page pagination. It reports eligible sources, expected
requirements, initialized jobs, due/wait/review states, next eligible times, coverage,
completed discovery jobs and managed external artifact records. `sources_with_any_coverage`
and `fully_covered_sources` have different meanings when multiple language groups
are configured. Active database receipts are not physical/client acceptance.

The existing worker still admits finite fair subtitle turns, including files with
embedded coverage, under normal request pacing and one remote payload attempt per
source per cycle. This addition does not start a bulk crawler or a competing writer.
An empty search, a challenge, a future quota gate, review-required candidates and a
published external file remain distinct states. No aggregate claims global readiness.

`source_progress` is also library-wide: it counts only the latest generation per
configured `(profile, path)`, with `total = imported + pending + review + conflict +
blocked + missing + unknown` and `present = total - missing`. Categories are mutually
exclusive; missing takes precedence, then blocked/conflict/review. `records` and
`historical_generations` retain the excluded generation count. `by_status`,
`by_source_status` and `by_import_status` expose effective and raw persisted states.
Both summaries use a consistent read transaction and declare `physical_readback: false`.
