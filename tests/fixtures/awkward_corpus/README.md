# Awkward mini-corpus fixture

Shared fixture used by A4, C, F, H, and performance-budget gates. The point is to
expose render-cache, dashboard, and budget bugs that unit tests on clean data
miss.

## What lands when

| Phase | File | Purpose |
|---|---|---|
| A1 | `commentary_tiny.json` | One tiny commentary record (first three entries of Clarke 2 John). Resource id rewritten to `fixture-clarke-tiny` so the fixture never collides with the real Clarke record. |
| A1 | `encyclopedia_tiny.json` | One tiny encyclopedia slice (first twenty entries of SH). Resource id rewritten to `fixture-sh-tiny`. |
| A4 | `dead_letter_overflow.json` | Record with >100 deliberately-malformed warnings to exercise sidecar dead-letter spillover. |
| A4 | `many_dismissals.json` | Record with >500 sidecar dismissals to exercise sidecar-load performance. |
| H | `over_long_text.json` | One synthetic over-long text (~10x median entry length) to exercise per-resource memory budget. |

## Why slices, not synthetic data

A4 and onward needs realistic OCR artefacts, Greek/Latin spans, and parser-emitted
shapes. Hand-crafted synthetic JSON drifts from the real schema as it evolves;
sliced real data stays in step.
