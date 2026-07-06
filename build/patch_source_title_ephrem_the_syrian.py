"""
Patch source_title for Ephrem the Syrian church-fathers entries.

41 entries were missing source_title. They fall into five groups:

1. Commentary on Genesis -- Chapter 1 material (13 entries, Gen 1:1-2:2)
   Source: Ephrem the Syrian, Commentary on Genesis, Section I
   Format: "COMMENTARY ON GENESIS 1.X" where X is the paragraph number
   Verified against: FotC vol. 91 (Mathews/Amar trans.), Scripture index
   and adjacent entries already in the database.

2. Commentary on Genesis -- Chapter 2 material (12 entries, Gen 2:4-2:23)
   Source: Ephrem the Syrian, Commentary on Genesis, Section II
   Format: "COMMENTARY ON GENESIS 2.X"
   Verified against: FotC vol. 91, Section II paragraph structure.
   Gen 2:10 and 2:14 confirmed in section 2.6 (same as adjacent 2:10-14 entry).

3. Commentary on Genesis -- Chapter 3 material (13 entries, Gen 3:1-3:22)
   Source: Ephrem the Syrian, Commentary on Genesis, Section III
   Format: "COMMENTARY ON GENESIS 2.X" (database uses prefix 2 for all Eden/Fall
   content -- Sections II and III are merged under chapter 2 in this dataset,
   consistent with all existing Gen 3 entries using the 2.X prefix).
   Verified against: FotC vol. 91, Section III paragraph structure.

4. Commentary on Genesis -- later chapters (2 entries)
   - Gen 24:47: Adjacent entries at Gen 24:39 and Gen 24:67 both use
     "COMMENTARY ON GENESIS 21:4"; Gen 24:47 falls in the same narrative span.
   - Gen 2:2: Section I paragraph 32, verified by FotC Scripture index entry
     for Gen 2:1-2 at page 96 (section 32).

5. Other works (4 entries)
   - 1 Kings 1:52: Quote text ends with "On the First Book of Kings 1.52" --
     self-citing reference. Normalised to colon format matching existing 1 Kings
     entries ("ON THE FIRST BOOK OF KINGS 1:52").
   - Job 2:11: Quote text ends with "Commentary on Job 2:11" -- self-citing.
   - Mark 7:33: Deaf-mute healing narrative; all 13 other Mark entries in this
     dataset use "COMMENTARY ON TATIAN'S DIATESSARON".
   - Col 2:14: Nativity census meditation ("At the birth of the Son the King was
     enrolling all men..."); adjacent Col 1:20 entry uses the same Diatessaron
     source; nativity census (Luke 2) is covered in the Diatessaron commentary.

Run with:  py -3 build/patch_source_title_ephrem_the_syrian.py
Then:      py -3 build/validate.py data/church-fathers/ephrem-the-syrian.json
"""

import json
from pathlib import Path

# Build the path relative to this script's location so it works on any machine.
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = REPO_ROOT / "data" / "church-fathers" / "ephrem-the-syrian.json"

PATCH = {
    # --- Commentary on Genesis, Section I (Gen 1:1 - Gen 2:2) ---
    # Paragraph numbers verified against FotC vol. 91 Scripture index.
    # "1.X" = Commentary chapter 1, paragraph X.
    "ephrem-the-syrian.Gen.1.1.unknown":  "COMMENTARY ON GENESIS 1.1",
    "ephrem-the-syrian.Gen.1.6.unknown":  "COMMENTARY ON GENESIS 1.17",
    "ephrem-the-syrian.Gen.1.7.unknown":  "COMMENTARY ON GENESIS 1.18",
    "ephrem-the-syrian.Gen.1.8.unknown":  "COMMENTARY ON GENESIS 1.20",
    "ephrem-the-syrian.Gen.1.9.unknown":  "COMMENTARY ON GENESIS 1.21",
    # Gen 1:14 and 1:16 are both within the lights-of-heaven discussion.
    # FotC body text verified: Gen 1:14 reference appears in para 23(1)-(2);
    # Gen 1:16 passage ("Indeed Moses said, God made the two great lights...") opens
    # para 23(3) on p.90. Para 24 (p.91) begins a new argument about creation timing.
    "ephrem-the-syrian.Gen.1.14.unknown": "COMMENTARY ON GENESIS 1.23",
    "ephrem-the-syrian.Gen.1.16.unknown": "COMMENTARY ON GENESIS 1.23",  # corrected from 1.24
    "ephrem-the-syrian.Gen.1.20.unknown": "COMMENTARY ON GENESIS 1.26",
    "ephrem-the-syrian.Gen.1.24.unknown": "COMMENTARY ON GENESIS 1.27",
    "ephrem-the-syrian.Gen.1.26.unknown": "COMMENTARY ON GENESIS 1.28",
    "ephrem-the-syrian.Gen.1.28.unknown": "COMMENTARY ON GENESIS 1.30",
    # Gen 2:2 ("God rested on the seventh day") -- FotC Section I paragraph 32
    "ephrem-the-syrian.Gen.2.2.unknown":  "COMMENTARY ON GENESIS 1.32",

    # --- Commentary on Genesis, Section II (Gen 2:4 - Gen 2:23) ---
    # "2.X" = Commentary chapter 2, paragraph X (Section II in FotC vol. 91).
    # Gen 2:4 = opening of Section II (para 1); verified.
    "ephrem-the-syrian.Gen.2.4.unknown":  "COMMENTARY ON GENESIS 2.1",
    "ephrem-the-syrian.Gen.2.6.unknown":  "COMMENTARY ON GENESIS 2.3",
    "ephrem-the-syrian.Gen.2.9.unknown":  "COMMENTARY ON GENESIS 2.5",
    # Gen 2:10 and 2:14 are both within the river-of-Eden discussion (para 6),
    # consistent with adjacent set entry Gen 2:10-14 -> "COMMENTARY ON GENESIS 2.6".
    "ephrem-the-syrian.Gen.2.10.unknown": "COMMENTARY ON GENESIS 2.6",
    "ephrem-the-syrian.Gen.2.14.unknown": "COMMENTARY ON GENESIS 2.6",
    "ephrem-the-syrian.Gen.2.15.unknown": "COMMENTARY ON GENESIS 2.7",
    "ephrem-the-syrian.Gen.2.17.unknown": "COMMENTARY ON GENESIS 2.8",
    # Gen 2:19 and 2:20 are both in the animal-naming passage (para 9),
    # consistent with adjacent set entry Gen 2:19-20 -> "COMMENTARY ON GENESIS 2.9.3".
    "ephrem-the-syrian.Gen.2.19.unknown": "COMMENTARY ON GENESIS 2.9",
    "ephrem-the-syrian.Gen.2.20.unknown": "COMMENTARY ON GENESIS 2.9",
    "ephrem-the-syrian.Gen.2.22.unknown": "COMMENTARY ON GENESIS 2.12",
    "ephrem-the-syrian.Gen.2.23.unknown": "COMMENTARY ON GENESIS 2.13",

    # --- Commentary on Genesis, Section III (Gen 3:1 - Gen 3:22) ---
    # Database uses "2.X" prefix for all Eden/Fall content -- Section III paragraph
    # numbers continue sequentially from Section II (paras 15 onwards = Gen 3 material).
    # Verified against FotC vol. 91 Scripture index entries for Gen 3.
    "ephrem-the-syrian.Gen.3.1.unknown":  "COMMENTARY ON GENESIS 2.15",
    # Gen 3:5: FotC Scripture index places 3.5 at p.111-112; para 20 (greed discussion).
    "ephrem-the-syrian.Gen.3.5.unknown":  "COMMENTARY ON GENESIS 2.20",
    # Gen 3:6: the large block (~1400 words, full temptation narrative) is para 17,
    # FotC p.108-109; "the woman saw that the tree was good to eat" opens II.17.
    # (Not para 20 -- that is the shorter greed/avarice excerpt already in the database.)
    # Corrected from 2.20 after body-text spot-check.
    "ephrem-the-syrian.Gen.3.6.unknown":  "COMMENTARY ON GENESIS 2.17",
    "ephrem-the-syrian.Gen.3.7.unknown":  "COMMENTARY ON GENESIS 2.22",
    "ephrem-the-syrian.Gen.3.8.unknown":  "COMMENTARY ON GENESIS 2.24",
    "ephrem-the-syrian.Gen.3.9.unknown":  "COMMENTARY ON GENESIS 2.25",
    # Gen 3:10 and 3:12 both within Adam's failure-to-confess section (para 27),
    # consistent with adjacent set entry Gen 3:10-12 -> "COMMENTARY ON GENESIS 2.27.1-2".
    "ephrem-the-syrian.Gen.3.10.unknown": "COMMENTARY ON GENESIS 2.27",
    "ephrem-the-syrian.Gen.3.12.unknown": "COMMENTARY ON GENESIS 2.27",
    # Gen 3:14 within the serpent-cursed section (para 29),
    # consistent with adjacent set entries Gen 3:14 -> "2.29.1" and "2.29.2".
    "ephrem-the-syrian.Gen.3.14.unknown": "COMMENTARY ON GENESIS 2.29",
    # Gen 3:15 within the enmity-between-serpent-and-woman section (para 30),
    # consistent with adjacent set entry Gen 3:16 -> "COMMENTARY ON GENESIS 2.30.1".
    "ephrem-the-syrian.Gen.3.15.unknown": "COMMENTARY ON GENESIS 2.30",
    # Gen 3:17 and 3:19 both within the Adam-cursed / toil section (para 31).
    "ephrem-the-syrian.Gen.3.17.unknown": "COMMENTARY ON GENESIS 2.31",
    "ephrem-the-syrian.Gen.3.19.unknown": "COMMENTARY ON GENESIS 2.31",
    # Gen 3:22 within the Tree-of-Life / irony section (para 34),
    # consistent with adjacent set entries -> "2.34.1-2" and "2.35.1".
    "ephrem-the-syrian.Gen.3.22.unknown": "COMMENTARY ON GENESIS 2.34",

    # --- Commentary on Genesis, later chapters ---
    # Gen 24:47 falls in the servant's visit to Bethuel's household (Gen 24:34-67).
    # Adjacent set entries at Gen 24:39 and Gen 24:67 both use "COMMENTARY ON GENESIS
    # 21:4"; Gen 24:47 sits within the same narrative span.
    "ephrem-the-syrian.Gen.24.47.unknown": "COMMENTARY ON GENESIS 21:4",

    # --- Other works ---
    # 1 Kings 1:52: quote text ends with "On the First Book of Kings 1.52" --
    # self-citing. Colon format matches existing 1 Kings entries in this dataset.
    "ephrem-the-syrian.1Kgs.1.52.unknown": "ON THE FIRST BOOK OF KINGS 1:52",

    # Job 2:11: quote text ends with "Commentary on Job 2:11" -- self-citing.
    "ephrem-the-syrian.Job.2.11.unknown": "COMMENTARY ON JOB 2:11",

    # Mark 7:33: deaf-mute healing; all 13 other set Mark entries in this dataset
    # use "COMMENTARY ON TATIAN'S DIATESSARON".
    "ephrem-the-syrian.Mark.7.33.unknown": "COMMENTARY ON TATIAN'S DIATESSARON",

    # Col 2:14: nativity census meditation ("At the birth of the Son the King was
    # enrolling all men..."); connects Luke 2 census to Col 2:14 debt-cancellation.
    # Adjacent Col 1:20 entry uses "Commentary on Tatian's Diatessaron" (same source).
    "ephrem-the-syrian.Col.2.14.unknown": "COMMENTARY ON TATIAN'S DIATESSARON",
}

EXPECTED_PATCH_SIZE = 41


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
