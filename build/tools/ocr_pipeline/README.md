# NSH OCR pipeline — orientation runbook

Operational guide for the tools in this directory. For project *state* (what's built, what's next)
read `docs/NSH_PROJECT_STATE.md` (the anchor doc) first — this file is the *how it works on disk*
companion to it. Written 2026-06-17 from the friction points an actual OCR run hit; keep it current
when those mechanics change.

## What this directory is

The Schaff-Herzog (NSH) OCR-to-publication pipeline, stage by stage:

- **S1 — OCR.** Per-engine runners live in `build/parsers/s1_*_runner.py` (tesseract, kraken,
  kraken-greek, surya are live inference; ABBYY is *imported* — it parses FineReader JSON that
  Internet Archive ships, not live OCR). Each writes one sidecar JSON per page.
- **S2 — render.** `render_s2.py` turns S1 sidecars into `rendering-v1` page renderings.
- **WCT + reconcile + correct.** `build_wct.py`, `reconcile_s3.py`, and the corrector
  (`build/lib/gold_free_corrector/`) consume S2. Front/back matter does NOT go here — only body.

The orchestrator that runs S1+S2 across volumes is `run_ocr_pipeline.py`. The disk-truth coverage
report is `ocr_inventory.py`.

## Store layout (read this before interpreting any sidecar count)

S1 sidecars: `reports/s1-sidecars/<lineage>/vol_NN/pages/` (gitignored — large). Two filename shapes
live side by side and mean different things:

| File | What it is | In the body manifest? |
|---|---|---|
| `page_NNNN.json` | a **body** page (an encyclopedia article page) | yes — these are the `ocr_input` set |
| `leaf_NNNN.json` | a **front/back-matter** leaf (title page, preface, contents, editor list, errata) | no — these are orphans relative to the body manifest |

This distinction is the single biggest source of "why is this count weird". The runners only OCR
**body** leaves (`nsh_leaf_model.ocr_input()` returns body-only), so `leaf_*.json` files come from a
*separate* front/back OCR pass. As of 2026-06-17 only **vol_01** has any (`leaf_*.json`, one-off pass
2026-06-16); the other 12 volumes have front/back *images* but no front/back OCR. See
`prompts/2026-06-17-1345-nsh-frontback-matter-ocr.md` for the planned front/back OCR work.

Manifests/state per (lineage, volume): `manifest.json` (the page set), `manifest.state.json`
(emitted-page tracker). The source manifests (which leaf is body/front/back/plate) live at
`raw/internet-archive/schaff-herzog-pages/vol_NN.manifest.json` and are read ONLY through the
`build/lib/nsh_leaf_model.py` accessor (`body_pages`, `front_matter`, `back_matter`, `ocr_input`,
`derive_kind`, `image_state`) — never `manifest["pages"]` directly (a TEST-08 grep gate enforces this).

## The reuse model — why a re-run may or may not redo work

S1 will **not** re-OCR a page whose sidecar passes `_sidecar_is_done()` (in each `s1_*_runner.py`).
"Done" means the sidecar exists AND: no `failure_class`, schema `sidecar-page-v1`, matching
`rendering_id`, matching `source_payload_sha256` (the image's hash — the immutable reuse key),
matching `canonical_leaf_id` (or sha-only when the leaf can't be resolved), AND
`runner_cache_version == S1_SIDECAR_CACHE_VERSION`. The runner prints a pre-run line per
(engine, volume): `N leaves | R reused | T to OCR` — if you see `0 to OCR` on a complete volume,
reuse is holding; if you see all pages `to OCR` on a volume that's already done, something below
invalidated the cache.

**The `runner_cache_version` landmine.** The field was added 2026-06-09 (`e6a08a98`) but existing
sidecars were never backfilled, so every pre-2026-06-09 sidecar reads `runner_cache_version: None`
and fails the gate — a naive full re-run would re-OCR thousands of pages whose text is byte-identical
to a fresh run. The value has only ever been `"s1-sidecar-currentness-v1"` (never bumped), so a
missing field means "written before the field existed", not "incompatible". Fix without re-OCR:
`stamp_s1_cache_version.py` stamps the current version onto legacy sidecars that pass every *other*
currentness check (it refuses any sidecar with a failure or a sha/leaf mismatch — those genuinely
need re-OCR). Dry-run by default; `--apply` to write. Run it before a full re-run if `ocr_inventory`
or a probe shows large `to OCR` counts on volumes that should be complete.

To force a clean re-OCR of a volume: delete its `manifest.state.json` (the runner then treats all
pages as unemitted) — documented in `run_ocr_pipeline.process_volume`.

## Reading `ocr_inventory.py status` (the coverage SSOT)

`py -3 build/tools/ocr_pipeline/ocr_inventory.py status` rebuilds from disk each call (never stale).
Per row: `present/expected extra=E missing=M [failed=F] [s2_lag=L]`.

- `expected` = body leaf count; `missing` = body leaves with no good sidecar (real OCR gaps).
- `extra` = sidecars whose leaf number is **outside** the body range = **front/back-matter leaves**
  (the footer legend says this too). `extra` is a coarse hint, not a classifier: it tells you
  non-body sidecars exist, not which leaves, their filenames, or whether they're blank. To actually
  see them, glob `leaf_*.json` in the pages dir and classify with `nsh_leaf_model` (`front_matter` /
  `back_matter` / `image_state`). The `extra` count can also differ between engines for the same dir
  depending on whether that engine's run recorded the non-body leaves — don't treat it as ground
  truth for front/back coverage.

## S2 render guard and `--allow-stale-manifest`

`render_s2` refuses to render when `count_sidecars(pages_dir)` (which counts **all** `*.json`,
including `leaf_*.json` orphans) exceeds the manifest's page count: `manifest has N pages but M
sidecars on disk`. This is why vol_01's S2 fails — 500 body + 37 front/back `leaf_*.json` = 537 > 500.
The orphan front/back sidecars are not body data and shouldn't be rendered into the body S2 set;
`--allow-stale-manifest` makes the guard warn-and-render the manifest's pages instead of failing.
The clean fix is to stop storing front/back `leaf_*.json` in the body `pages/` dir at all (see the
front/back OCR prompt above).

## Running the pipeline

```
# Body OCR, two fast CPU engines, all 13 volumes:
py -3 build/tools/ocr_pipeline/run_ocr_pipeline.py --volumes 1 2 3 4 5 6 7 8 9 10 11 12 13 \
    --engines tesseract kraken --throttle background-8
```

- `--throttle background-8` = 8 threads, below-normal priority (machine stays usable). `minimal-4` (idle
  priority) collapses CPU-engine throughput to minutes/page — only use it for GPU-bound Surya.
  (`full-speed` = no limit, the default.)
- `--engines geometry` = surya+tesseract+abbyy only (the WCT geometry lanes), skips Kraken.
- `--dry-run` only checks paths + ABBYY presence; it does **not** preview OCR-vs-skip. Use a
  small real `--volumes`/`--pages` run and read the `reused | to OCR` line for that.
- The run tees to `reports/_logs/ocr-pipeline/ocr-pipeline-<ts>.log` and requests the OS stay awake. That request
  blocks *idle* sleep only — it does NOT survive Modern Standby triggered by lid-close or running
  on battery, so a multi-day run can die overnight if the machine sleeps (see gotchas below).

**Confirm completion from the log, not just the exit code.** The runner exits 0 on success / 1 on
failures. An earlier teardown bug that forced exit 120 (a `_Tee`/atexit `I/O operation on closed
file` at shutdown) is fixed — the Tee now guards writes/flushes on a closed log. Still confirm a run
actually finished via the `OCR pipeline complete` line plus the `reports/_logs/ocr-pipeline/ocr-pipeline-<ts>.failures.json`
report (written only on failure): a killed or slept run leaves neither. Per-page failures are
non-fatal (logged, run continues — REL-08); a volume's S2 failing does not stop other volumes.

## Unattended / remote-launch runs

For runs that must survive the launching terminal closing (overnight, multi-day kraken), use the
Scheduled Task apparatus instead of running `run_ocr_pipeline.py` directly.

**Full lifecycle — three scripts, one for each phase:**

| Phase | Command | What it does |
|---|---|---|
| Setup | `py -3 build/tools/ocr_pipeline/setup_remote_ocr_task.py` | Disables AC sleep, writes `run_remote_ocr.cmd`, registers + starts `OCD-Remote-OCR` task |
| Harden (battery) | `py -3 build/tools/ocr_pipeline/harden_remote_ocr_task.py` | Re-registers task with battery guards off, disables DC sleep — run after setup if the machine may go on battery mid-run |
| **Teardown** | **`py -3 build/tools/ocr_pipeline/teardown_remote_ocr_task.py`** | Kills any running OCR processes, deletes the task, restores DC standby to 30 min — run this when you stop the run early |

**Teardown is the step most likely to be forgotten.** Without it:
- The task re-fires at 23:59 that night and restarts the run
- DC sleep stays at "never", even after you're done

`stop_ocr.py` only kills processes — it does not delete the task or restore sleep. Always use
`teardown_remote_ocr_task.py` for a full stop.

Log file: `logs/remote-ocr-<timestamp>.log` (timestamped at setup time, not when the task fires).
To check status mid-run: `py -3 build/tools/ocr_pipeline/diag_ocr.py`.

## Known gotchas (2026-06-17)

- **Legacy `runner_cache_version: None`** triggers needless re-OCR — stamp first (above).
- **Long runs can die overnight** — Modern Standby (Connected Standby, S0) suspends/kills the run
  even with the lid open on AC; the keep-awake call blocks only idle sleep, not lid-close/battery.
  For a multi-day job (kraken is ~77s/page, ~3 days for the corpus) keep the machine awake + on AC.
- **vol_01 trips the S2 guard** — 37 orphan front/back `leaf_*.json` in its body dir; use
  `--allow-stale-manifest` or relocate them.
- **Front/back-matter OCR is missing for 12 of 13 volumes** — images exist (P3 pass), OCR doesn't;
  separate task (prompt referenced above), kept out of the body article pipeline by design.
- **kraken vol_04 p433** is a known persistent inference timeout (1 page) — it will re-attempt and
  likely fail again; not a regression.
