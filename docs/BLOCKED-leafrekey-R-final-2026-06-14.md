# BLOCKED — leaf-rekey R-final (precondition not met: R4b / R6a / R7 not done)

**Date:** 2026-06-14 (autonomous overnight run)
**Step:** R-final (`prompts/2026-06-13-1508-leafrekey-Rfinal-verify-and-require.md`)
**Outcome:** Did NOT run. Precondition unmet — three upstream steps (R4b, R6a, R7) have not
landed. **No verifier extended (none exists to extend), no schema flipped to required, no
enums regenerated, no retention purge run.** `build/` and `schemas/v1/` are unchanged this run.

## Why R-final cannot run now

R-final is the LAST step and has two scope items, both of which require the full upstream
chain to be complete:

1. **R6b — extend `build/tools/ocr_pipeline/verify_leaf_keying.py`** (drop `--primary-only`,
   assert across ALL engines incl ABBYY + the WCT geometry join) and run it green corpus-wide.
2. **R5 — flip `canonical_leaf_id` to required** on the 4 schemas, but **only after R6b is
   green corpus-wide** (the prompt and the design's Codex#3-E/G review make this ordering hard).

Neither is reachable. The chain ordering is
`R3-apply ─► R4a ─► R4b ─► R6a ─► R7 ─► R-final`. The current frontier is between R4a and R4b:

| Step | State (verified this run) | Evidence |
|---|---|---|
| R3-apply | ✅ complete — all 16 work-cells leaf-keyed on disk | commit `4d5e2641`; tracker §2 |
| R4a | ✅ landed in code (S2 gates + line-id reseed + expected-set purge + tests) | commit `8e7c80a9` (tracker §0 row still shows ☐ — **stale**) |
| R4b | ❌ **not done** — WCT / reconciliation / gold join NOT leaf-keyed | commit `9826c226` (blocked); no later WCT commit; `docs/BLOCKED-leafrekey-R4b-2026-06-14.md` |
| R6a | ❌ **not done** — primary-chain verifier never built | commit `78968185` (blocked); `verify_leaf_keying.py` **does not exist** (glob, whole repo); `docs/BLOCKED-leafrekey-R6a-2026-06-14.md` |
| R7 | ❌ **not started** — ABBYY lineages NOT leaf-keyed | no R7 leaf-rekey commit exists; ABBYY/azure sidecars lack `canonical_leaf_id` (disk check below) |
| R-final | this step | — |

Three independent hard blockers, any one of which is sufficient:

- **R6a never built.** R-final's scope item #1 is "extend `verify_leaf_keying.py`." The file
  does not exist anywhere in the repo (glob `**/verify_leaf*.py` returns only the unrelated
  `.tmp_audit/verify_leafrekey_cell.py` helper). There is nothing to extend.
- **R7 never ran.** R6b must assert `canonical_leaf_id` "across ALL engines incl ABBYY." The
  ABBYY stores are still filename-keyed and carry no `canonical_leaf_id` — R6b would fail on
  every ABBYY page. The prompt states explicitly: *"Depends on R7 (ABBYY aligned)."*
- **R4b never landed.** R6b must assert the WCT geometry join (every WCT page's engine spans
  resolve to one `canonical_leaf_id`). WCT / reconciliation / gold are not leaf-keyed.

## Why flipping the schema now would be actively destructive (not just premature)

R5 flips `canonical_leaf_id` from optional to **required** on `sidecar-page-v1`,
`sidecar-manifest-v1`, `rendering-v1`, `word-confusion-table-v1`. On the current data layer
that would make schema-invalid, in one stroke:

- the **entire ABBYY store** (every `ia-abbyy-*` lineage, all volumes — R7 never stamped it),
- the **azure store** (not in the R3-apply primary set; lacks the field),
- the **WCT store** (R4b never leaf-keyed it),
- the **S2 renderings** for any lineage R4a's bounded re-render has not yet covered,

i.e. tens of thousands of pages. This is exactly the Codex#3-E/G hazard the prompt forbids:
*"do NOT flip to required before R6b is green corpus-wide — any un-migrated artifact would
become schema-invalid (R5 is deliberately LAST)."* The schema flip cannot precede the data
migration it enforces.

## Why the retention purge must NOT run

Acceptance includes a `.bak`/quarantine retention purge "now that the full chain is verified."
The full chain is NOT verified. The quarantine dirs under each applied cell's
`run_dir/quarantine/migrate_s1_to_leaf_key/` are gated on the R6a verifier passing (per the
R3-apply notes and `LAST_SESSION_2026-06-14-11-08.md`: "do NOT purge — R6a verifier gates the
retention purge"). They hold recoverable migrated content from the R3-apply bug-2 recovery.
Purging now risks unrecoverable loss. **No purge was run.**

## Verification (primary sources, this run)

1. **Git** — `git log --oneline`: HEAD is `8e7c80a9` (R4a S2). No commit for R4b WCT-rekey,
   R6a verifier, or R7 ABBYY leaf-rekey. The ABBYY commits in history (`4e18cb4f`, `0f3bf310`,
   `e49f9ef2`, etc.) are base-pipeline / JE-oracle work, not the R7 leaf-rekey step.
2. **Filesystem** — `verify_leaf_keying.py` absent (glob, whole repo). The 4 target schemas
   all contain `canonical_leaf_id` as an **optional** field (R0-1 / R4b additions); none flipped.
3. **Disk (untracked ground truth — VER-01)** — `py -3 -c` read of
   `reports/s1-sidecars/ia-abbyy-v1/vol_03/pages/page_0050.json` →
   `'canonical_leaf_id' in sidecar == False`; same for an `azure-ai-vision-v1/vol_03` sample.
   ABBYY/azure stores still use `page_NNNN.json` stems. Inventory
   (`ocr_inventory.py status`) confirms the ABBYY lineages exist at full S1/S2 coverage but
   un-keyed.
4. **Upstream BLOCKED docs** — `docs/BLOCKED-leafrekey-R6a-2026-06-14.md` and
   `-R4b-2026-06-14.md` confirm R6a/R4b never built (those were written before R3-apply
   completed; R3-apply and R4a have since landed, R4b/R6a/R7 have not).

## What unblocks R-final

The remaining upstream chain must land first, in order:

1. **R4b** — WCT / reconciliation / gold join re-keyed on `canonical_leaf_id`; reseed
   `rendering_line_id`; remove hardcoded `page_NNNN` (grep clean).
   Prompt: `prompts/2026-06-13-1505-leafrekey-R4b-wct-recon-rekey.md`.
2. **R6a** — build `verify_leaf_keying.py` (`--primary-only` default), wire to pre-commit, add
   pre-run `vol_NN: N leaves | R reused | K to OCR` logging in runners + orchestrator.
   Prompt: `prompts/2026-06-13-1506-leafrekey-R6a-primary-verifier.md`.
3. **R7** — per ABBYY lineage: content-verified GZ→leaf offset, re-run normalizer to stamp
   `canonical_leaf_id` + regenerate tokens, rekey ABBYY-fed WCT geometry.
   Prompt: `prompts/2026-06-13-1507-leafrekey-R7-abbyy-alignment.md`.
4. **R-final** — only then extend the verifier to full chain (R6b), run it green corpus-wide,
   flip the 4 schemas to required (R5), regen enums, run full suite + `build/validate.py`,
   then the gated retention purge.

Also: update the tracker §0 R4a row to ☑ `8e7c80a9` (it is stale at ☐ — R4a's code + tests
landed but the row was not flipped).

## What was NOT done this run

- No `verify_leaf_keying.py` created or extended; no test added.
- No schema flipped to required; no enums regenerated; no drift check run.
- No full suite / `build/validate.py` run (nothing to validate against — the flip never happened).
- No retention purge (gated on the unreachable verifier).
- No engine invoked; no store touched; `build/` and `schemas/v1/` unchanged.
