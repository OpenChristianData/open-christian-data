# Hugging Face publishing

OCD publishes to Hugging Face as JSONL (auto-converts to Parquet for the viewer). Multi-dataset repos use the `configs` YAML block in README.md — no loading script needed. The published dataset license identifier is `cc0-1.0`; source-repository code, schemas, and tooling are CC BY-NC 4.0. Files >10MB are handled automatically by `huggingface_hub`. Free tier sufficient.

Each JSONL record inlines 7 meta fields (`_source_id`, `_source_title`, `_author`, `_contributors`, `_schema_type`, `_license`, `_source_url`) so records are self-describing without the parent JSON envelope. Schema-specific fields follow unchanged from the source.

## Account and infrastructure

- Username: `OpenChristianData`
- Org: `OpenChristianDataOrg`
- Dataset repo: `OpenChristianDataOrg/open-christian-data`
- Live URL: https://huggingface.co/datasets/OpenChristianDataOrg/open-christian-data
- Auth: `HF_TOKEN` Windows User environment variable (Write-scoped token)
- Upload script: `build/scripts/upload_huggingface.py` (dry-run by default, `--live` to push)
- Authoritative whole-corpus export script: `build/scripts/export_huggingface.py` (writes to
  `exports/huggingface/`)
- Dataset card source: `docs/HUGGINGFACE_DATASET_CARD.md`; the exporter copies it to
  `exports/huggingface/README.md`.
- Public writing guidance: `docs/HUGGINGFACE_STYLE_GUIDE.md` defines the dataset-card voice,
  required sections, release-note structure, version presentation, and publication checklist.
- Count source: `build/tools/count_dataset_records.py`; it generates the author/work catalogue,
  public count table, and metadata audit surface.
- Token and file-size source: `build/tools/export_stats.py`, run against `exports/huggingface/`.
  It produces the card's per-configuration Records/Tokens/File-size table (`--json` for machine
  output). Tokens use tiktoken `o200k_base` over schema-defined text fields only, excluding JSON
  structure and the inlined `_`-prefixed metadata. `--check-parity` asserts its record counts match
  `count_dataset_records.py`, so this tool does not become a second count set. Regenerate the table
  after any export change rather than hand-editing the card.
- First published: 2026-04-12 (baseline now designated `v0.1.0`; 11 configs, 247,649 records; final Hub revision `238d35aa009e8a1154902b82e05b8073624ccbc0`)

## Public file map

The Hugging Face dataset repository contains the rendered `README.md` plus 12
data files:

- `data/bible_text.jsonl`
- `data/catechism_qa.jsonl`
- `data/church_fathers.jsonl`
- `data/commentary.jsonl`
- `data/devotional.jsonl`
- `data/doctrinal_document.jsonl`
- `data/hymn_collection.jsonl`
- `data/prayer.jsonl`
- `data/reference_entry.jsonl`
- `data/sermon.jsonl`
- `data/structured_text.jsonl`
- `data/topical_reference.jsonl`

The corresponding public GitHub documentation is:

- `README.md` — project front door;
- `docs/HUGGINGFACE_DATASET_CARD.md` — canonical Hugging Face card;
- `docs/releases/v0.2.0.md` — full release notes;
- `docs/SOURCES.md` — source and acknowledgment ledger;
- `docs/LICENSING.md` and `THIRD_PARTY_NOTICES.md` — rights policy and notices;
- `data/hymns/hymnary-pd/README.md` and `docs/sources/ccel-permission.md` — requested source-specific credit;
- `docs/HUGGINGFACE_STYLE_GUIDE.md` — public writing and release-note guidance; and
- the two allowlisted research notes linked by the style guide and source ledger.

The upload-ready local equivalents are `exports/huggingface/README.md` and the
12 sibling JSONL files. The canonical card and upload-ready README must remain
byte-for-byte identical.

## Release versioning and notes

- `main` is the latest published dataset state.
- Semantic release tags identify stable consumer revisions. The chosen `v0.1.0` target is
  `238d35aa009e8a1154902b82e05b8073624ccbc0`. The corrected `v0.2.0` target remains pending
  until the repaired payload and final card have been uploaded and independently verified.
  The earlier `19f46f3a83913f5fd9734bf758d763d57380d5f3` revision still contains the five removed
  ESV-derived records and must not be tagged as the corrected release. Creating either tag is a
  separate, explicitly authorized Hub mutation.
- Record the final card-inclusive revision as the tag target and retain the earlier all-data-upload
  revision separately as payload-integrity evidence.
- Full release notes live under `docs/releases/`. The Hugging Face card carries a concise,
  consumer-facing `Release history` section centered on authors, works, compatibility, and the
  immutable Hub revisions.
- A release tag does not replace verification: run the exporter and count reconciliation first,
  upload only with explicit authorization, verify the remote payload, and do not create or move a
  tag until the final intended card and data state is known.

`build/tools/export_hf_dataset.py` is the newer `original`/`modernised` record exporter used by the
NSH-style publish-projection path. It is not the authoritative whole-corpus HuggingFace export path.
Do not maintain two public count sets silently: README and dataset-card counts must come from
`build/tools/count_dataset_records.py`.

`build/tools/verify_publish_provenance.py --release-root ...` expects the manifest-based S6/NSH
release layout (`manifests/slim.json`). It does not verify the legacy whole-corpus
`exports/huggingface/*.jsonl` layout. For the live export, require a clean exporter exit, zero load
and write errors, and count parity against `build/tools/count_dataset_records.py`.

## Verifying dataset state (no auth)

`https://huggingface.co/api/datasets/<org>/<name>` returns JSON with `lastModified` (ISO timestamp) and `sha` (latest commit). The public dataset page shows "Updated X ago" but that's rendered by JS and invisible to WebFetch/curl-without-JS. Use the API endpoint for programmatic verification:

```bash
curl -s "https://huggingface.co/api/datasets/OpenChristianDataOrg/open-christian-data" | \
  py -3 -c "import json,sys; d=json.load(sys.stdin); print('lastModified:', d.get('lastModified'), '| sha:', d.get('sha',''))"
```
