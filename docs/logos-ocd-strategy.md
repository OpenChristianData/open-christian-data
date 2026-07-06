# Logos vs OCD — Strategy Document
Created: June 2026
Based on: Full Logos tier inventory extraction + patristic copyright analysis

## What Logos Has That OCD Doesn't

Logos charges for access to its reading/study platform, not just the texts. Most of what's in Gold and Platinum tier OCD already has (ANF/NPNF via CCEL). The genuine gaps are at Diamond and Collector's tier, and in the separately-sold Migne sets.

## Three-Track Strategy

### Track 1: Ingest tertullian.org (do now — no OCR needed)
Roger Pearse's site hosts public domain English translations of ~80 patristic authors NOT in the ANF/NPNF set. These are machine-readable, cleanly formatted, already PD, and freely available.

Key texts not yet in OCD:
- Eusebius — Chronicon, Praeparatio Evangelica, Demonstratio Evangelica, Onomasticon
- Aphrahat — Demonstrations (Syriac, 4th century, no ANF coverage)
- Ephraim the Syrian — prose works
- Cyril of Alexandria — Against Nestorius, Commentary on Luke, Against Julian
- Dionysius the Areopagite — all six works
- Severus of Antioch — letters and sermons
- Jacob of Serug — Syriac homilies
- Multiple Syriac chronicles
- Photius — Bibliotheca (~280 summaries of ancient works)
- Gregory of Nyssa — Life of St. Macrina

Source: https://www.tertullian.org/fathers/

### Track 2: OCR Migne — primary pipeline target

**Migne Patrologia Latina (PL) — 221 volumes**
- Tertullian to Pope Innocent III (AD 200-1216)
- ~150,000 pages, original Latin
- Public domain (Migne 1844-79), no clean free digital edition
- Logos charges $599.99 for their clean edition

**Migne Patrologia Graeca (PG) — 167 volumes**
- Apostolic Fathers through 15th century
- ~112,300 pages, original Greek + Latin apparatus
- Public domain (same era), no clean free digital edition
- Logos charges $529.99 — currently pre-order only, meaning even Logos hasn't solved this

Best AI translation candidates from Migne PG once OCR'd:
1. John of Damascus — Three Treatises on Divine Images (PG 94)
2. Cyril of Alexandria — full homily corpus (PG 68-77)
3. Germanus of Constantinople — On the Divine Liturgy (PG 98)
4. Theodore the Studite — On the Holy Icons (PG 99)
5. Maximus the Confessor — Ambigua, Mystagogy, 200 Chapters (PG 90-91)
6. Chrysostom homilies not in NPNF — PG 47-64

AI translation quality thresholds:
- Greek homilies/letters/treatises: 85-90%
- Greek systematic theology: 75-80%
- Syriac prose: 60-70%
- Syriac/Greek poetry: 40-50%
- Byzantine liturgical texts: 65-75%

### Track 3: Out of scope — copyright, no path in

All of the following won't clear copyright for decades:
- CUA Press "Fathers of the Church" series (1947-present, 142 vols)
- SVS Press "Popular Patristics" (1977-present, 68 vols)
- New City Press Augustine translations (1990s-2020s)
- IVP Academic "Ancient Christian Texts" (2009-2015, 18 vols)
- Newman/Paulist "Ancient Christian Writers" (1946-present)

## Tier Value Assessment for OCD

| Tier | Price | OCD Value |
|---|---|---|
| Gold | $849 | Near zero — OCD already has ANF/NPNF |
| Platinum | $1,499 | Near zero |
| Diamond | $2,999 | Zero — adds 21st-century copyright translations |
| Collector's | $10,999 | Zero — adds PPS + CUA, both copyright |
| Orthodox Gold | $849 | Zero — PPS + CUA, all copyright |
| Migne PL (separate) | $599 | HIGH — primary OCR target |
| Migne PG (separate) | $530 | HIGH — primary OCR target |

OCD should not purchase any Logos tier. OCR Migne instead.

## Eastern Tradition Gap

OCD is strongly Western/Reformed. The Eastern tradition gap is OCD's largest qualitative gap:
- Byzantine theology: Maximus the Confessor, Symeon the New Theologian, Gregory Palamas
- Eastern liturgy: Germanus of Constantinople, John of Damascus
- Syriac: Ephrem, Isaac of Nineveh, Jacob of Serug, Barsanuphius & John

Most have no adequate PD English. Path: OCR Migne PG + AI translate for Greek ones; specialist Syriac pipeline for Syriac ones.

## Files

All Logos inventory files committed to `research/logos-inventory/` (moved from local
Downloads, 2026-06-16):
- `logos-gold-2026.txt`, `logos-platinum-2026.txt`, `logos-diamond-2026.txt`
- `logos-master-inventory.txt` — Collector's Edition full (175KB)
- `logos-popular-patristics-pd-analysis.md` — per-volume PD analysis of PPS 58 vols
- `logos-ocd-patristic-comparison.txt` — cross-tier patristic comparison
- Annotated tier files: `logos-collectors/diamond/gold/platinum-2026-annotated.txt`
- `logos-ocd-usable-items.txt` — 639-line curated PD items list with source URLs

Next step: Full copyright annotation of all tier items.
Continuation prompt: `Open Christian Data/prompts/2026-06-02-1630-logos-copyright-annotation.md`
