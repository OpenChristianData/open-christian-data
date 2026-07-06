# Phantom-page fix — one-shot scripts (archived 2026-06)

These four scripts were written for the 2026-06 NSH "phantom page" incident, in which a
re-fetch re-materialized deleted terminal pages and reverted earlier filename renames on the
gitignored `raw/internet-archive/schaff-herzog-pages/vol_*/page_*.jpg` images.

**Do not re-run any of these.** Each assumes a specific pre-fix disk state that no longer exists.
The phantom-page failure class has since been retired structurally by the leaf-rekey
re-architecture (download→S2 keyed on `canonical_leaf_id` + `source_payload_sha256`, completed
2026-06-17 — see `docs/NSH_PROJECT_STATE.md`). Running them against the current leaf-keyed disk
would corrupt it.

They are kept (not deleted) per REL-05 as an audit trail of the remediation.

| Script | What it did (one-shot, against the pre-fix state) |
|---|---|
| `apply_phantom_file_renames.py` | Renamed mis-named `page_*.jpg` images back to their true page positions |
| `reconcile_manifest_pages.py` | Reconciled a volume manifest's `pages[]` to the on-disk image set |
| `fix_phantom_metadata.py` | Repaired phantom metadata entries left by the re-materialization |
| `delete_dup_terminal_pages.py` | Removed byte-identical duplicate terminal pages produced by the re-fetch |

For the durable history: `docs/NSH_FETCHER_MECHANISM_DIAGNOSIS.md`,
`docs/NSH_CONTENT_POSITION_VERIFICATION.md`, and the leaf-rekey tracker
`docs/BUILD_PLAN_leaf_rekey.md`.
