# Spurgeon MTP Missing Sermons — Primary Source Research

**Date:** 2026-04-13  
**Status:** COMPLETE — 3 sermons added (708, 1698, 3032). 13 entries classified as intentional gaps. Total: 3,550 entries in `data/sermons/spurgeon-mtp.json`. See `data/sermons/MANIFEST.md` for full gap documentation.

**Context:** The Kingdom Collective (thekingdomcollective.com/spurgeon/) hosts 3,547 of the 3,563 MTP sermon numbers. The following 16 numbers returned HTTP 404 and have no cached HTML. These are confirmed site gaps (verified manually), not parser errors.

**Missing sermon numbers:**  
8, 40, 42, 62, 67, 82, 142, 155, 269, 270, 298, 332, 390, 708, 1698, 3032

---

## Goal

For each missing sermon number, find:
1. The **sermon title** as published in the original MTP volume
2. The **primary scripture reference** (book, chapter, verse)
3. The **original publication year** (MTP volumes ran 1855–1917)
4. A **primary source URL** where the full text can be found (SpurgeonGems PDF, archive.org, etc.)

---

## Research Prompt

Use this prompt in a new agent or the workspace session with web search access:

---

```
You are researching 16 missing sermons from C. H. Spurgeon's Metropolitan Tabernacle Pulpit (MTP) series. These sermon numbers are absent from The Kingdom Collective's online collection (thekingdomcollective.com/spurgeon/), which is the source used by the Open Christian Data project.

Your task: for each sermon number below, find the sermon title, primary scripture reference, and a URL where the full text is available online in a readable form (not paywalled, not scanned image-only).

Missing sermon numbers:
8, 40, 42, 62, 67, 82, 142, 155, 269, 270, 298, 332, 390, 708, 1698, 3032

PRIMARY SOURCES TO CHECK (in priority order):

1. **SpurgeonGems PDFs** — spurgeongems.org/spurgeon-sermons/  
   Each MTP volume is a downloadable PDF. Volumes are numbered 1–63; sermon numbers map to volumes roughly as: Vol 1 = sermons 1-100, Vol 2 = 101-200, etc. (not exact — some volumes have gaps or reorderings). Find the volume PDF, locate the sermon by number, and note the title and reference.

2. **archive.org MTP scans** — search archive.org for "Metropolitan Tabernacle Pulpit" + the volume number. Original Victorian editions are fully scanned.

3. **The Spurgeon Center** — spurgeon.org — has a searchable index of MTP sermons including titles and references.

4. **Logos/Faithlife free preview** — some MTP volumes are previewed at faithlife.com.

For each sermon number, report:
- Sermon number
- Title
- Scripture reference (raw text as Spurgeon cited it)
- Volume number (which MTP volume it appears in)
- Source where you found it (URL or "SpurgeonGems Vol N PDF")
- Whether full text is available online (yes/no/partial)

If a sermon number genuinely does not appear in any MTP index you can find, note that — it may be a numbering anomaly in the original publication.

Format as a markdown table.
```

---

## What to do with results

If full text is available for some missing sermons:
1. Download the source (PDF page or HTML)
2. Cache in `raw/spurgeon_sermons/missing/` (not in the `html/` folder — different format)
3. Write a small manual-entry script or add to `spurgeon_mtp.py` as a supplementary loader
4. Re-run parse + validate

If only metadata (title + reference) is available but not full text:
- Add stub entries to `data/sermons/spurgeon-mtp.json` with `content_blocks: []` and `completeness: "stub"` in provenance notes
- Or leave as-is and document the gap in `data/sermons/MANIFEST.md`

---

## Notes

- The MTP ran 1855–1917. Spurgeon died in 1892; volumes 38–63 are posthumous re-publications of earlier sermons or transcribed addresses.
- Sermon numbers in the Kingdom Collective collection do not always correspond 1:1 with MTP volume/number — Benry Yip's digitisation used sermon IDs assigned by SpurgeonGems/Emmett O'Donnell.
- The 404 pattern (mostly low numbers: 8, 40, 42, 62, 67, 82) suggests these may be sermons O'Donnell did not transcribe rather than volumes Spurgeon never preached — they almost certainly exist in the original MTP volumes.
