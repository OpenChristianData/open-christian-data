# Surya OCR Efficiency — Benchmark Results 2026-06-01

Investigation into practical efficiency improvements for Surya on Schaff-Herzog vol 1.
All experiments on `page_0011.jpg` (5034×6959 px, representative body page).
Experiment outputs in `.tmp/surya-bench/` (gitignored). No production data touched.

## Key result

`--surya-max-width 2500` is the recommended setting. It is wired into the pipeline
and available now via `run_ocr_pipeline.py --surya-max-width 2500`.

## Timing

| Config | Wall time | Peak RAM | vs full size |
|---|---|---|---|
| Full size (5034 px) | ~350s | 8034 MB | baseline |
| `--max-width 3000` | 202s | — | 1.7× faster |
| `--max-width 2500` | ~185s | 6233 MB | **~2× faster, −1.8 GB RAM** |
| Batch 2 pages at 2500 px | 349s (2 pages) | — | no gain |
| Reduced env (rec=8, det=2) | 232s | — | 36% slower than 2500 default |

Note: a prior session reported 616s baseline — not reproduced. Measured baseline is ~350s.
The prior figure was almost certainly inflated by concurrent system load.

## Word accuracy at max_width=2500

- Word-sequence similarity vs full size: **96.6%** (1020/1056 exact positional matches)
- Character-level similarity: **96.9%**
- Remaining diffs are mostly positional shifts (same content, different sequence alignment)
- 5 substantive text differences; 3 favour the downsampled output:
  - `Thaddaus,` (full) vs `Thaddæus,` (2500px) — 2500px correct, æ ligature recognised
  - `29-32),` (full) vs `29–32),` (2500px) — 2500px correct, en-dash recognised
  - `Abgareage,` (full) vs `Abgarsage,` (2500px) — 2500px correct, German proper noun
- Plausible reason: PIL high-quality resize gives Surya a cleaner input than JPEG at native resolution

## Confidence scores

| Metric | Full size | max_width=2500 | Delta |
|---|---|---|---|
| Mean | 0.9955 | 0.9958 | +0.0003 (noise) |
| p5 | 0.9780 | 0.9823 | +0.004 (marginal gain) |
| Min | 0.8532 | 0.7908 | −0.06 (one word) |
| Words < 50% | 0 | 0 | 0 |

No quality degradation in confidence distribution. The lower min at 2500px is a single
word; zero words fall below 50% at either resolution.

## Batching

No benefit. Model load at this resolution is cheap relative to inference cost.
Batching 2 pages in one subprocess (349s) vs 2× sequential (341s estimated) — 2% slower.
`batch_size=1` is correct; `batch_size > 1` adds memory pressure for no gain.

## Env tuning

Default dynamic batch sizes (rec=32, det=8 on this CPU) are already optimal.
The code comment previously claimed "CPU defaults: rec=8, det=2" — this was wrong
and has been corrected in `surya_page.py`.

## Leaf/page overlap

| Category | Count |
|---|---|
| Unique leaf (no page_ counterpart): front + back matter | 16 (leaf_0000–0009, 0535–0540) |
| Page-only | 449 |
| Both leaf_NN and page_NN exist | 42 (sequences 10–51) |

Overlapping files are **not duplicates** — mean pixel diff 20.7 (17.3% of pixels differ
by >5). Both should be processed: they produce different OCR output from the same
physical page, adding engine diversity for WCT alignment.

## Full volume 1 projection

| Config | Projection |
|---|---|
| Full size | 543 × ~350s ≈ 52 hours |
| max_width=2500 | 543 × ~185s ≈ 27 hours |

Still a multi-night CPU job. Realistic plan: ~3 overnight segments of ~170 pages each.

## Recommended next command

```
py -3 build/tools/ocr_pipeline/run_ocr_pipeline.py ^
  --volumes 1 --pages 10-20 --throttle test ^
  --force-s1 --surya-max-width 2500
```

Covers ~15–20 Surya page slots at ~185s each (~45–60 min for Surya).
Confirm valid sidecars before committing to full volume.

## Code changes made this session

### `build/tools/ocr_runners/surya_page.py`
- Corrected stale batch-size comment (8/2 → 32/8 with measurement source)
- `_build_page_payload()` now emits `surya_inference_width` and `surya_scale_to_native`
  when downscaling was applied, so the page sidecar is self-describing

### `build/parsers/s1_surya_runner.py`
- Added `max_width: int | None = None` to `normalize_volume()`, `_run_page()`, `_run_page_batch()`
- Threads `--max-width N` into subprocess commands when set
- Logs `surya: max_width=Npx (downscaling active)` at run start
- Records `surya_max_width` in manifest `bundle_extras_carried` when set

### `build/tools/ocr_pipeline/run_ocr_pipeline.py`
- Added `--surya-max-width PX` CLI flag with correct ~2x speedup figure
- Threaded through `process_volume()` → `_run_surya()`

### `tests/test_s1_surya_runner.py`
- 6 new tests: max_width flag in single/batch cmd, None omits flag,
  bundle_extras recorded, bundle_extras empty when None,
  inference_width/scale_to_native in page sidecar

### `.tmp/surya-bench/run_bench.py` (gitignored)
- Benchmark harness: timing, peak RAM (psutil), confidence distribution (mean/min/p5/p10/p25, frac<50%)
- Popen-based with background RAM polling thread

### `.tmp/surya-bench/compare_accuracy.py` (gitignored)
- Word-level text comparison between full-size and downsampled runs

## Test results

2506 collected (up 3 from session start), 2301 passed, 6 skipped, 26 xfailed, 0 failures.
