# HuggingFace publishing

OCD publishes to HuggingFace as JSONL (auto-converts to Parquet for the viewer). Multi-dataset repos use the `configs` YAML block in README.md — no loading script needed. License identifiers: `cc0-1.0` for data, `mit` for code. Files >10MB auto-handled by Git LFS via `huggingface_hub`. Free tier sufficient.

Each JSONL record inlines 7 meta fields (`_source_id`, `_source_title`, `_author`, `_contributors`, `_schema_type`, `_license`, `_source_url`) so records are self-describing without the parent JSON envelope. Schema-specific fields follow unchanged from the source.

## Account and infrastructure

- Username: `OpenChristianData`
- Org: `OpenChristianDataOrg`
- Dataset repo: `OpenChristianDataOrg/open-christian-data`
- Live URL: https://huggingface.co/datasets/OpenChristianDataOrg/open-christian-data
- Auth: `HF_TOKEN` Windows User environment variable (Write-scoped token)
- Upload script: `build/scripts/upload_huggingface.py` (dry-run by default, `--live` to push)
- Export script: `build/scripts/export_huggingface.py` (writes to `exports/huggingface/`)
- First published: 2026-04-12 (11 configs, 247,647 records)

## Verifying dataset state (no auth)

`https://huggingface.co/api/datasets/<org>/<name>` returns JSON with `lastModified` (ISO timestamp) and `sha` (latest commit). The public dataset page shows "Updated X ago" but that's rendered by JS and invisible to WebFetch/curl-without-JS. Use the API endpoint for programmatic verification:

```bash
curl -s "https://huggingface.co/api/datasets/OpenChristianDataOrg/open-christian-data" | \
  py -3 -c "import json,sys; d=json.load(sys.stdin); print('lastModified:', d.get('lastModified'), '| sha:', d.get('sha',''))"
```
