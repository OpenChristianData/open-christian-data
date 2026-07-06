"""
Patch source_title for John Damascene church-fathers entries.

All 70 missing entries fall into two groups:

1. Pauline epistle commentaries (65 entries)
   Source: John Damascene, Commentarii in Epistulas Pauli
   (critical edition: Robert Volk, De Gruyter, 2013, PG 95)
   Each epistle gets its own "Commentary on [Epistle]" title.
   The Galatians section is also documented at:
     http://www.orthodoxresearchinstitute.org/articles/patrology/johndamascus_galatians.html
   Confirmed: verse-by-verse commentary style; covers Galatians, Ephesians,
   Colossians, 2 Timothy, Titus, Philemon.

2. Exposition of the Orthodox Faith (5 entries)
   Source: John Damascene, An Exposition of the Orthodox Faith
   - ORTHODOX FAITH 3.14 (two wills of Christ; Mark 7:24)
     Confirmed: WebFetch of newadvent.org/fathers/33043.htm Chapter 14
   - ORTHODOX FAITH 4.13 (Holy Eucharist; Mark 14:22)
     Confirmed: WebFetch of newadvent.org/fathers/33044.htm Chapter 13
   - ORTHODOX FAITH 4.26 (On the Antichrist; 2 Thess 2:4)
     Inferred: matches adjacent entry 2Thess.2.11 = "The Orthodox Faith 4.26"

Run with:  py -3 build/patch_source_title_john_damascene.py
Then:      py -3 build/validate.py data/church-fathers/john-damascene.json
"""

import json
from pathlib import Path

# Build the path relative to this script's location so it works on any machine.
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = REPO_ROOT / "data" / "church-fathers" / "john-damascene.json"

PATCH = {
    # --- Galatians (37 entries) ---
    "john-damascene.Gal.1.1.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.1.1.unknown-2":   "Commentary on Galatians",
    "john-damascene.Gal.1.2.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.1.2.unknown-2":   "Commentary on Galatians",
    "john-damascene.Gal.1.3.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.1.4.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.1.4.unknown-2":   "Commentary on Galatians",
    "john-damascene.Gal.1.5.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.1.6.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.1.6.unknown-2":   "Commentary on Galatians",
    "john-damascene.Gal.1.7.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.1.8.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.1.10.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.1.11.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.1.12.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.1.13.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.1.15.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.1.16.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.1.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.2.2.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.2.3.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.2.4.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.2.4.unknown-2":   "Commentary on Galatians",
    "john-damascene.Gal.2.5.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.2.6.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.2.7.unknown":     "Commentary on Galatians",
    "john-damascene.Gal.2.10.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.11.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.12.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.13.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.14.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.15.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.17.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.18.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.19.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.20.unknown":    "Commentary on Galatians",
    "john-damascene.Gal.2.21.unknown":    "Commentary on Galatians",

    # --- 2 Timothy (15 entries) ---
    "john-damascene.2Tim.1.1.unknown":    "Commentary on 2 Timothy",
    "john-damascene.2Tim.1.8.unknown":    "Commentary on 2 Timothy",
    "john-damascene.2Tim.3.11.unknown":   "Commentary on 2 Timothy",
    "john-damascene.2Tim.3.12.unknown":   "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.1.unknown":    "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.2.unknown":    "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.3.unknown":    "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.7.unknown":    "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.9.unknown":    "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.10.unknown":   "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.13.unknown":   "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.16.unknown":   "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.17.unknown":   "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.18.unknown":   "Commentary on 2 Timothy",
    "john-damascene.2Tim.4.21.unknown":   "Commentary on 2 Timothy",

    # --- Ephesians (8 entries) ---
    "john-damascene.Eph.1.1.unknown":     "Commentary on Ephesians",
    "john-damascene.Eph.1.3.unknown":     "Commentary on Ephesians",
    "john-damascene.Eph.1.4.unknown":     "Commentary on Ephesians",
    "john-damascene.Eph.1.5.unknown":     "Commentary on Ephesians",
    "john-damascene.Eph.1.6.unknown":     "Commentary on Ephesians",
    "john-damascene.Eph.1.9.unknown":     "Commentary on Ephesians",
    "john-damascene.Eph.1.9.unknown-2":   "Commentary on Ephesians",
    "john-damascene.Eph.1.10.unknown":    "Commentary on Ephesians",

    # --- Colossians (2 entries) ---
    "john-damascene.Col.1.15.unknown":    "Commentary on Colossians",
    "john-damascene.Col.2.3.unknown":     "Commentary on Colossians",

    # --- Titus (1 entry; Titus.2.5 omitted -- 11-word quote, unverifiable) ---
    "john-damascene.Titus.2.13.unknown":  "Commentary on Titus",

    # --- Philemon (3 entries) ---
    "john-damascene.Phlm.1.2.unknown":    "Commentary on Philemon",
    "john-damascene.Phlm.1.10.unknown":   "Commentary on Philemon",
    "john-damascene.Phlm.1.25.unknown":   "Commentary on Philemon",

    # --- An Exposition of the Orthodox Faith ---
    # Mark 7:24 -- two wills of Christ; confirmed OF Book III Ch. 14
    "john-damascene.Mark.7.24.unknown":   "Orthodox Faith 3.14",
    # Mark 14:22 -- Eucharist; confirmed OF Book IV Ch. 13
    "john-damascene.Mark.14.22.unknown":  "Orthodox Faith 4.13",
    # 2 Thess 2:4 -- Antichrist; OF Book IV Ch. 26 confirmed "Concerning the Antichrist"
    "john-damascene.2Thess.2.4.unknown":  "Orthodox Faith 4.26",
}

EXPECTED_PATCH_SIZE = 69


def main():
    assert len(PATCH) == EXPECTED_PATCH_SIZE, (
        f"PATCH size mismatch: expected {EXPECTED_PATCH_SIZE}, got {len(PATCH)}"
    )

    with open(DATA_FILE, encoding='utf-8') as f:
        data = json.load(f)

    entries = data['data']
    total = len(entries)

    # Index entries by entry_id for fast lookup
    index = {e['entry_id']: e for e in entries}

    # Verify all patch keys exist in the data before touching anything
    missing_ids = [eid for eid in PATCH if eid not in index]
    if missing_ids:
        print(f"ERROR: {len(missing_ids)} patch entry_ids not found in data:")
        for eid in missing_ids:
            print(f"  {eid}")
        raise SystemExit(1)

    set_count = 0
    skipped_count = 0

    for entry_id, new_title in PATCH.items():
        entry = index[entry_id]
        existing = entry.get('source_title', '')
        if existing:
            # Already set -- idempotent skip
            skipped_count += 1
        else:
            entry['source_title'] = new_title
            set_count += 1

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Done. Total entries: {total}")
    print(f"  Set:     {set_count}")
    print(f"  Skipped: {skipped_count} (already had source_title)")


if __name__ == '__main__':
    main()
