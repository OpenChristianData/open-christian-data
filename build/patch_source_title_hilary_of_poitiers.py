"""
Patch source_title for Hilary of Poitiers church-fathers entries.

54 entries were missing source_title. They fall into four groups:

1. Commentary on Matthew (22 entries)
   Source: Hilary of Poitiers, Commentarius in Matthaeum (Commentary on Matthew)
   Confirmed by:
   - Adjacent entries from same verse files link to archive.org commentary
     scans (e.g. John.19.26-27 = "Commentary on Matthew verse 1:4, page 45-46")
   - All 330 set Matthew entries from this file use "Commentary on Matthew"
   - Text style is Hilary's verse-by-verse allegorical exegesis of Matthew

2. On the Trinity -- specific sections (5 entries)
   Source: Hilary of Poitiers, De Trinitate (On the Trinity)
   Confirmed by textual evidence inside the TOML blocks themselves:
   - Matt.3.17.unknown: quote text begins "De Trin. iii. 11:" -- Book 3, Sec. 11
   - Matt.27.50.unknown: quote text begins "De Trin. x. 50:" -- Book 10, Sec. 50
   - John.1.2.unknown: Catena Aurea duplicate block labels it "(ii. de Trin. c. 16)"
     -- adjacent set entry John.1.2.on-the-trinity-book-2-section-16 confirmed
   - John.1.14.unknown: Catena Aurea duplicate labels it "(x. de Trin. c. 21, 22)"
   - John.1.18.unknown: Catena Aurea duplicate labels it "(de Trin. vi. 39)"
     -- adjacent set entry John.1.18.on-the-trinity-book-6-section-39 confirmed

3. On the Trinity -- work identified, section not recoverable (11 entries)
   Source: Hilary of Poitiers, De Trinitate (On the Trinity)
   Confirmed by:
   - All 155 other John entries from this file are from On the Trinity
   - Acts.1.4.on-the-trinity-830 confirms Acts chapter is from On the Trinity
   - Mark.10.17.on-the-trinity-916 and Mark.10.18 confirm Mark chapter is from
     On the Trinity
   - Colossians entries discuss the "image of God" in Trinitarian terms consistent
     with De Trinitate chapters on Colossians 1

4. Commentary on Psalms -- section-specific (16 entries)
   Source: Hilary of Poitiers, Tractatus super Psalmos (Commentary on Psalms)
   Section numbers confirmed via NewAdvent NPNF translation:
   - Psalm 1:  https://www.newadvent.org/fathers/3303001.htm
   - Psalm 54: https://www.newadvent.org/fathers/3303053.htm (LXX Psalm 53)
   - Psalm 131: https://www.newadvent.org/fathers/3303131.htm
   Method: each missing entry's opening words matched against the NewAdvent
   text section-by-section. NPNF section numbering confirmed consistent with
   existing set entries (e.g. section 6 = "Hear my prayer, O God" matches
   the existing 'HOMILY ON PSALM 54:6' entry exactly).
   Psalm 54 uses MT numbering ('54:X') matching the existing set entries.
   NOTE: This patch script was originally committed with work-level
   'Commentary on Psalms' for group 4 entries; section-specific titles were
   applied by patch_upgrade_hilary_psalms_sections.py in a subsequent commit.

Run with:  py -3 build/patch_source_title_hilary_of_poitiers.py
Then:      py -3 build/validate.py data/church-fathers/hilary-of-poitiers.json
"""

import json
from pathlib import Path

# Build the path relative to this script's location so it works on any machine.
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = REPO_ROOT / "data" / "church-fathers" / "hilary-of-poitiers.json"

PATCH = {
    # --- Commentary on Matthew (22 entries) ---
    # All are verse-by-verse exegesis from Hilary's Commentarius in Matthaeum.
    # Confirmed by adjacent archive.org-sourced entries with "Commentary on Matthew" titles.
    "hilary-of-poitiers.Matt.2.23.unknown":   "Commentary on Matthew",
    "hilary-of-poitiers.Matt.3.3.unknown":    "Commentary on Matthew",
    "hilary-of-poitiers.Matt.4.2.unknown":    "Commentary on Matthew",
    "hilary-of-poitiers.Matt.7.23.unknown":   "Commentary on Matthew",
    "hilary-of-poitiers.Matt.8.15.unknown":   "Commentary on Matthew",
    "hilary-of-poitiers.Matt.8.22.unknown":   "Commentary on Matthew",
    "hilary-of-poitiers.Matt.8.34.unknown":   "Commentary on Matthew",
    "hilary-of-poitiers.Matt.9.11.unknown":   "Commentary on Matthew",
    "hilary-of-poitiers.Matt.9.17.unknown":   "Commentary on Matthew",
    "hilary-of-poitiers.Matt.10.31.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.13.58.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.14.19.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.16.19.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.17.13.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.17.19.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.17.25.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.23.16.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.24.14.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.24.47.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.25.2.unknown":   "Commentary on Matthew",
    "hilary-of-poitiers.Matt.25.13.unknown":  "Commentary on Matthew",
    "hilary-of-poitiers.Matt.26.46.unknown":  "Commentary on Matthew",

    # --- On the Trinity -- section confirmed from in-text "De Trin." markers ---
    # Matt.3.17: TOML block starts "De Trin. iii. 11:" -> Book 3, Section 11
    "hilary-of-poitiers.Matt.3.17.unknown":   "On the Trinity, Book 3, Section 11",
    # Matt.27.50: TOML block starts "De Trin. x. 50:" -> Book 10, Section 50
    "hilary-of-poitiers.Matt.27.50.unknown":  "On the Trinity, Book 10, Section 50",
    # John.1.2: Catena Aurea duplicate block labels it "(ii. de Trin. c. 16)"
    "hilary-of-poitiers.John.1.2.unknown":    "On the Trinity, Book 2, Section 16",
    # John.1.14: Catena Aurea duplicate labels it "(x. de Trin. c. 21, 22)"
    "hilary-of-poitiers.John.1.14.unknown":   "On the Trinity, Book 10, Sections 21-22",
    # John.1.18: Catena Aurea duplicate labels it "(de Trin. vi. 39)"
    "hilary-of-poitiers.John.1.18.unknown":   "On the Trinity, Book 6, Section 39",

    # --- On the Trinity -- section not recoverable from TOML alone ---
    # All other John entries in this file (155 of 155) are from On the Trinity.
    "hilary-of-poitiers.John.5.25.unknown":   "On the Trinity",
    "hilary-of-poitiers.John.5.31.unknown":   "On the Trinity",
    "hilary-of-poitiers.John.6.1.unknown":    "On the Trinity",
    "hilary-of-poitiers.John.6.22.unknown":   "On the Trinity",
    "hilary-of-poitiers.John.6.35.unknown":   "On the Trinity",
    "hilary-of-poitiers.John.16.23.unknown":  "On the Trinity",
    # Acts: Acts.1.4 is confirmed "ON THE TRINITY 8.30" in adjacent set entry
    "hilary-of-poitiers.Acts.1.6.unknown":    "On the Trinity",
    "hilary-of-poitiers.Acts.3.26.unknown":   "On the Trinity",
    # Colossians: Trinitarian argument from Col 1:15-16 ("image of God")
    "hilary-of-poitiers.Col.1.15.unknown":    "On the Trinity",
    "hilary-of-poitiers.Col.1.16.unknown":    "On the Trinity",
    # Mark: Mark.10.17 confirmed "ON THE TRINITY 9.16" in adjacent set entry
    "hilary-of-poitiers.Mark.14.39.unknown":  "On the Trinity",

    # --- Homily on Psalm 1 -- section-specific (6 entries) ---
    # Section numbers confirmed via newadvent.org/fathers/3303001.htm (NPNF).
    "hilary-of-poitiers.Ps.1.2.unknown-3":    "HOMILY ON PSALM 1:3",   # Sec 3
    "hilary-of-poitiers.Ps.1.1.unknown":      "HOMILY ON PSALM 1:6",   # Sec 6
    "hilary-of-poitiers.Ps.1.2.unknown":      "HOMILY ON PSALM 1:7",   # Sec 7
    "hilary-of-poitiers.Ps.1.2.unknown-2":    "HOMILY ON PSALM 1:12",  # Sec 12
    "hilary-of-poitiers.Ps.1.5.unknown":      "HOMILY ON PSALM 1:20",  # Sec 20
    "hilary-of-poitiers.Ps.1.6.unknown":      "HOMILY ON PSALM 1:23",  # Sec 23

    # --- Homily on Psalm 54 -- section-specific, MT numbering (7 entries) ---
    # Section numbers confirmed via newadvent.org/fathers/3303053.htm (LXX Ps 53).
    "hilary-of-poitiers.Ps.54.1.unknown":     "HOMILY ON PSALM 54:1",  # Sec 1
    "hilary-of-poitiers.Ps.54.2.unknown":     "HOMILY ON PSALM 54:6",  # Sec 6
    "hilary-of-poitiers.Ps.54.3.unknown":     "HOMILY ON PSALM 54:7",  # Sec 7
    "hilary-of-poitiers.Ps.54.4.unknown":     "HOMILY ON PSALM 54:9",  # Sec 9
    "hilary-of-poitiers.Ps.54.5.unknown":     "HOMILY ON PSALM 54:11", # Sec 11
    "hilary-of-poitiers.Ps.54.6.unknown":     "HOMILY ON PSALM 54:13", # Sec 13
    "hilary-of-poitiers.Ps.54.7.unknown":     "HOMILY ON PSALM 54:14", # Sec 14

    # --- Homily on Psalm 131 -- section-specific (3 entries) ---
    # Section numbers confirmed via newadvent.org/fathers/3303131.htm (NPNF).
    "hilary-of-poitiers.Ps.131.1.unknown":    "HOMILY ON PSALM 131:1", # Sec 1
    "hilary-of-poitiers.Ps.131.2.unknown":    "HOMILY ON PSALM 131:5", # Sec 5
    "hilary-of-poitiers.Ps.131.3.unknown":    "HOMILY ON PSALM 131:6", # Sec 6
}

EXPECTED_PATCH_SIZE = 54


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
