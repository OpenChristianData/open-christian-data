"""Patch missing author and original_publication_year fields in source JSON files.

One-shot patch script — run once, idempotent on re-run (skips already-filled fields).

Sources consulted:
  - Nicene and Post-Nicene Fathers (NPNF) series introductions (same editions used in dataset)
  - Philip Schaff, ed., NPNF Series 1 & 2 introductions and chronologies
  - Standard patristic reference: Quasten, Patrology vols 1-3
  - BCP attribution: official Church of England and ECUSA publication records
"""

import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

# Maps relative path (from DATA) -> {field: value}
# Dates are original composition years, not translation years.
# Blank-over-unverifiable rule: omit entries where authorship or date is genuinely uncertain.
PATCHES: dict[str, dict] = {
    # --- doctrinal-documents: missing authors ---
    "doctrinal-documents/apostles-creed.json": {
        "author": "Unknown",
    },
    "doctrinal-documents/athanasian-creed.json": {
        "author": "Unknown",
    },
    # Matthew 16:16 — attributed speech of Peter
    "doctrinal-documents/confession-of-peter.json": {
        "author": "Peter the Apostle",
    },
    # Drafted by John Calvin and submitted to the Synod of Paris (La Rochelle, 1559)
    "doctrinal-documents/french-confession-of-faith.json": {
        "author": "Synod of Paris",
    },
    # Adopted at the Savoy Assembly of Congregational churches, 1658
    "doctrinal-documents/savoy-declaration.json": {
        "author": "Savoy Assembly",
    },
    # Traditional Waldensian confession; authorship corporate
    "doctrinal-documents/waldensian-confession.json": {
        "author": "Waldensian Church",
    },
    # --- doctrinal-documents: missing year ---
    # Tertullian, De Praescriptione Haereticorum, c. 200 AD
    "doctrinal-documents/tertullians-rule-of-faith.json": {
        "original_publication_year": 200,
    },
    # --- prayers: missing authors ---
    "prayers/bcp-1662/collects.json": {
        "author": "Church of England",
    },
    # American 1928 revision of the Book of Common Prayer
    "prayers/bcp-1928/collects.json": {
        "author": "Protestant Episcopal Church",
    },
    # Didache (Teaching of the Twelve Apostles), c. 100 AD; authorship unknown
    "prayers/didache/prayers.json": {
        "author": "Unknown",
        "original_publication_year": 100,
    },
    # --- structured-text: missing original_publication_year ---
    # Athanasius -- dates from NPNF Series 2, vol. 4 introduction (Philip Schaff, 1891)
    "structured-text/athanasius-against-the-arians.json": {
        "original_publication_year": 339,
    },
    "structured-text/athanasius-against-the-heathen.json": {
        "original_publication_year": 318,
    },
    "structured-text/athanasius-apology-to-the-emperor.json": {
        "original_publication_year": 357,
    },
    "structured-text/athanasius-arian-history.json": {
        "original_publication_year": 357,
    },
    "structured-text/athanasius-circular-to-bishops-of-egypt-and-libya.json": {
        "original_publication_year": 339,
    },
    "structured-text/athanasius-defence-against-the-arians.json": {
        "original_publication_year": 349,
    },
    "structured-text/athanasius-defence-of-dionysius.json": {
        "original_publication_year": 350,
    },
    "structured-text/athanasius-defence-of-his-flight.json": {
        "original_publication_year": 357,
    },
    "structured-text/athanasius-defence-of-the-nicene-definition.json": {
        "original_publication_year": 351,
    },
    "structured-text/athanasius-deposition-of-arius.json": {
        "original_publication_year": 320,
    },
    "structured-text/athanasius-encyclical-letter.json": {
        "original_publication_year": 339,
    },
    # Festal Letters: first extant letter c. 329 AD
    "structured-text/athanasius-letters-and-chronicles.json": {
        "original_publication_year": 329,
    },
    "structured-text/athanasius-life-of-antony.json": {
        "original_publication_year": 356,
    },
    "structured-text/athanasius-on-ariminum-and-seleucia.json": {
        "original_publication_year": 359,
    },
    # athanasius-on-luke-10-22: date too uncertain -- left blank
    "structured-text/athanasius-on-the-incarnation.json": {
        "original_publication_year": 318,
    },
    # Expositio Fidei, c. 328
    "structured-text/athanasius-statement-of-faith.json": {
        "original_publication_year": 328,
    },
    "structured-text/athanasius-synodal-letter-to-africa.json": {
        "original_publication_year": 369,
    },
    # Tomus ad Antiochenos, 362 AD
    "structured-text/athanasius-synodal-letter-to-antioch.json": {
        "original_publication_year": 362,
    },
    # Augustine -- dates from NPNF Series 1 introductions
    "structured-text/augustine-care-for-dead.json": {
        "original_publication_year": 421,
    },
    "structured-text/augustine-faith-things-not-seen.json": {
        "original_publication_year": 400,
    },
    # Letters begin c. 386 AD (first extant)
    "structured-text/augustine-letters-part-1.json": {
        "original_publication_year": 386,
    },
    "structured-text/augustine-on-continence.json": {
        "original_publication_year": 395,
    },
    "structured-text/augustine-on-patience.json": {
        "original_publication_year": 418,
    },
    # De Symbolo ad Catechumenos, c. 393 AD
    "structured-text/augustine-on-the-creed.json": {
        "original_publication_year": 393,
    },
    # augustine-sermons-selected-lessons: modern editorial compilation -- left blank
    # Chrysostom individual homilies: composition dates unattested in NPNF -- left blank
    # Eusebius -- dates from NPNF Series 2, vol. 1 introduction
    # Historia Ecclesiastica final edition c. 313 AD
    "structured-text/eusebius-ecclesiastical-history.json": {
        "original_publication_year": 313,
    },
    # Letter to his diocese on the Nicene Creed, written 325 AD
    "structured-text/eusebius-letter-on-nicene-creed.json": {
        "original_publication_year": 325,
    },
    # Vita Constantini, begun c. 337 AD after Constantine's death
    "structured-text/eusebius-life-of-constantine.json": {
        "original_publication_year": 337,
    },
    # Gregory of Nyssa -- dates from NPNF Series 2, vol. 5 introduction
    # Contra Eunomium, first delivered c. 380 AD
    "structured-text/gregory-of-nyssa-against-eunomius.json": {
        "original_publication_year": 380,
    },
    # Answer to Eunomius' Second Book, c. 381
    "structured-text/gregory-of-nyssa-answer-to-eunomius-second-book.json": {
        "original_publication_year": 381,
    },
    # Delivered at Council of Constantinople, 381 AD
    "structured-text/gregory-of-nyssa-funeral-oration-on-meletius.json": {
        "original_publication_year": 381,
    },
    # Oratio Catechetica Magna, c. 383
    "structured-text/gregory-of-nyssa-great-catechism.json": {
        "original_publication_year": 383,
    },
    # Letters: first extant c. 371 AD
    "structured-text/gregory-of-nyssa-letters.json": {
        "original_publication_year": 371,
    },
    # Ad Ablabium (On Not Three Gods), c. 375
    "structured-text/gregory-of-nyssa-not-three-gods.json": {
        "original_publication_year": 375,
    },
    # gregory-of-nyssa-on-infants-early-deaths: date disputed -- left blank
    # gregory-of-nyssa-on-pilgrimages: date uncertain -- left blank
    # In Diem Luminum / On the Baptism of Christ, c. 383
    "structured-text/gregory-of-nyssa-on-the-baptism-of-christ.json": {
        "original_publication_year": 383,
    },
    # De Fide, c. 375
    "structured-text/gregory-of-nyssa-on-the-faith.json": {
        "original_publication_year": 375,
    },
    # Against Macedonius (On the Holy Spirit), c. 374
    "structured-text/gregory-of-nyssa-on-the-holy-spirit.json": {
        "original_publication_year": 374,
    },
    # On the Holy Trinity, c. 375
    "structured-text/gregory-of-nyssa-on-the-holy-trinity.json": {
        "original_publication_year": 375,
    },
    # De Hominis Opificio, c. 379
    "structured-text/gregory-of-nyssa-on-the-making-of-man.json": {
        "original_publication_year": 379,
    },
    # De Anima et Resurrectione (Macrinia), c. 380
    "structured-text/gregory-of-nyssa-on-the-soul-and-resurrection.json": {
        "original_publication_year": 380,
    },
    # De Virginitate, c. 371 -- first major work
    "structured-text/gregory-of-nyssa-on-virginity.json": {
        "original_publication_year": 371,
    },
    # john-owen-sermons: posthumous editorial compilation -- left blank
    # edwards-select-sermons: modern editorial compilation -- left blank
    # Socrates Scholasticus, Historia Ecclesiastica, c. 440 AD
    "structured-text/socrates-ecclesiastical-history.json": {
        "original_publication_year": 440,
    },
    # Sozomen, Historia Ecclesiastica, c. 440 AD
    "structured-text/sozomen-ecclesiastical-history.json": {
        "original_publication_year": 440,
    },
    # Theodoret, Historia Ecclesiastica, c. 449 AD
    "structured-text/theodoret-ecclesiastical-history.json": {
        "original_publication_year": 449,
    },
}


def patch_file(rel_path: str, fields: dict) -> str:
    path = DATA / rel_path
    if not path.exists():
        return f"MISSING: {rel_path}"

    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = raw.get("meta")
    if not isinstance(meta, dict):
        return f"NO META: {rel_path}"

    changed = []
    for field, value in fields.items():
        current = meta.get(field)
        if current is not None and current != "" and current != []:
            # Already filled -- skip (idempotent)
            continue
        meta[field] = value
        changed.append(field)

    if not changed:
        return f"skip (already set): {rel_path}"

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return f"patched {changed}: {rel_path}"


def main() -> None:
    patched = skipped = errors = 0
    for rel, fields in sorted(PATCHES.items()):
        result = patch_file(rel, fields)
        print(result)
        if result.startswith("patched"):
            patched += 1
        elif result.startswith("skip"):
            skipped += 1
        else:
            errors += 1
    print(f"\nDone: {patched} patched, {skipped} already set, {errors} errors")


if __name__ == "__main__":
    main()
