# standards: author id slug
"""Patch missing source_title for cyril-of-jerusalem church_fathers entries.

16 of 20 missing entries are patched here with HIGH confidence.
4 entries are left blank -- MEDIUM confidence only (source not located in
NewAdvent's Catechetical Lectures).

--- Background ---

All 20 missing entries are "unknown" stubs with empty source_url, verse_ref,
and in some cases no source_title.

Two categories of entries were identified:

CATEGORY A -- embedded citation in quote text (5 + 1 + 1 entries):
  Five entries (1Cor.15.55, Job.40.23, Job.41.13, Luke.10.19, Ps.74.14)
  share the same long passage about Jesus's baptism and the dragon in the
  Jordan. All five end with: - "Catechetical Lectures 3, Chapter 11."
  The Dan.3.27 entry ends with: - "Catechetical Lectures 2.16"
  The 1Kgs.1.39 entry ends with: - "Mystagogical Lectures 3.6"

  These embedded citations were normalised to the format already used in
  the file: "Catechetical Lecture 3:11", "Catechetical Lecture 2:16",
  "Mystagogical Lectures 3.6".

CATEGORY B -- no embedded citation; identified by cross-referencing quote
  content against NewAdvent's full-text Catechetical Lectures:

  - 2Thess.2.4: "he is the man of the race of David, who shall build up the
    Temple which was erected by Solomon" -> Lecture 15:15 (confirmed)
  - Acts.5.3: "Peter was not with Ananias and Sapphira...but he was present
    by the Spirit" -> Lecture 16:17 (confirmed)
  - Col.1.16: "in him were created all things...thrones, or dominations, or
    principalities, or powers...he is before all creatures" -> Lecture 11:24
  - Col.1.20: "making peace through the blood of the cross...He laid it down
    when he willed, and he took it up again when he willed" -> Lecture 13:33
  - Col.2.15: "Let us not be ashamed to confess the Crucified. Let the cross,
    as our seal, be boldly made with our fingers upon our brow" -> Lec 13:36
  - Col.2.8: "pious doctrines, and virtuous practice...philosophy and vain
    deceit" -> Lecture 4:2
  - Col.3.20: "Children, obey your parents in all things, for this is well
    pleasing to the Lord...He who loves father or mother is not worthy of me
    ...but He added, more than Me" -> Lecture 7:15
  - Isa.63.16: "God is so named not as begetting them of Himself, but as
    caring for them and shielding them...of Christ alone He is the Father by
    nature, not by adoption: and the Father of men in time, but of Christ
    before all time" -> Lecture 7:10
  - Mark.15.23: "myrrh is in taste like gall, and very bitter" gall given
    to Jesus -> Lecture 13:29

MEDIUM -- left blank (4 entries):

  Acts.2.17.unknown, Acts.2.36.unknown, Acts.2.38.unknown, Jas.2.24.unknown
  These entries are not found in Cyril of Jerusalem's Catechetical Lectures
  on NewAdvent. The Acts.2.17 entry has a lemma-commentary format
  ("upon all flesh: This suggests...sons and your daughters shall prophesy:
  Implying...and your elders: in my view...") inconsistent with Cyril of
  Jerusalem's homily style -- possibly misattributed or from a catena.
  Acts.2.36, Acts.2.38 and Jas.2.24 are single-sentence snippets with no
  identifiable section in any known NewAdvent lecture. Per curation rules,
  only HIGH entries are patched.

--- Confidence ratings ---

HIGH (16 entries):
  Cat. 3:11  -- 5 entries: 1Cor.15.55, Job.40.23, Job.41.13, Luke.10.19, Ps.74.14
               Embedded citations confirmed; format normalised to match file.
  Cat. 2:16  -- 1 entry:  Dan.3.27. Embedded citation confirmed.
  Myst. 3.6  -- 1 entry:  1Kgs.1.39. Embedded citation confirmed.
  Cat. 15:15 -- 1 entry:  2Thess.2.4. Verified newadvent.org/fathers/310115.htm sec.15.
  Cat. 16:17 -- 1 entry:  Acts.5.3. Verified newadvent.org/fathers/310116.htm sec.17.
  Cat. 11:24 -- 1 entry:  Col.1.16. Verified newadvent.org/fathers/310111.htm sec.24.
  Cat. 13:33 -- 1 entry:  Col.1.20. Verified newadvent.org/fathers/310113.htm sec.33.
  Cat. 13:36 -- 1 entry:  Col.2.15. Verified newadvent.org/fathers/310113.htm sec.36.
  Cat. 4:2   -- 1 entry:  Col.2.8.  Verified newadvent.org/fathers/310104.htm sec.2.
  Cat. 7:15  -- 1 entry:  Col.3.20. Verified newadvent.org/fathers/310107.htm sec.15.
  Cat. 7:10  -- 1 entry:  Isa.63.16.Verified newadvent.org/fathers/310107.htm sec.10.
  Cat. 13:29 -- 1 entry:  Mark.15.23.Verified newadvent.org/fathers/310113.htm sec.29.

MEDIUM (4 entries, skipped):
  Acts.2.17.unknown, Acts.2.36.unknown, Acts.2.38.unknown, Jas.2.24.unknown
  Not located in any Catechetical Lecture at NewAdvent after exhaustive search.

--- Spot-checked against primary source ---

  - cyril-of-jerusalem.2Thess.2.4.unknown
    (https://www.newadvent.org/fathers/310115.htm sec.15)
    Confirmed: "he will make great account of the Temple, that he may more
    completely beguile them; making it supposed that he is the man of the race
    of David, who shall build up the Temple which was erected by Solomon."
    HIGH.

  - cyril-of-jerusalem.Col.2.15.unknown
    (https://www.newadvent.org/fathers/310113.htm sec.36)
    Confirmed: "Let us not then be ashamed to confess the Crucified. Be the
    Cross our seal made with boldness by our fingers on our brow, and on
    everything; over the bread we eat, and the cups we drink; in our comings
    in, and goings out."
    HIGH.

  - cyril-of-jerusalem.Col.1.16.unknown
    (https://www.newadvent.org/fathers/310111.htm sec.24)
    Confirmed: "Christ then is the Only-begotten Son of God, and Maker of the
    world...in Him were all things created that are in the heavens, and that
    are upon the earth, things visible and invisible, whether thrones, or
    dominions, or principalities, or powers...Even if you speak of the worlds,
    of these also Jesus Christ is the Maker by the Father's bidding."
    HIGH.

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "cyril-of-jerusalem.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # --- CATEGORY A: embedded citation in quote text ---

    # Five entries share the same Baptism / Jordan dragon passage,
    # all ending with: - "Catechetical Lectures 3, Chapter 11."
    "cyril-of-jerusalem.1Cor.15.55.unknown": "Catechetical Lecture 3:11",
    "cyril-of-jerusalem.Job.40.23.unknown":   "Catechetical Lecture 3:11",
    "cyril-of-jerusalem.Job.41.13.unknown":   "Catechetical Lecture 3:11",
    "cyril-of-jerusalem.Luke.10.19.unknown":  "Catechetical Lecture 3:11",
    "cyril-of-jerusalem.Ps.74.14.unknown":    "Catechetical Lecture 3:11",

    # Dan.3.27: quote ends with - "Catechetical Lectures 2.16"
    "cyril-of-jerusalem.Dan.3.27.unknown": "Catechetical Lecture 2:16",

    # 1Kgs.1.39: quote ends with - "Mystagogical Lectures 3.6"
    "cyril-of-jerusalem.1Kgs.1.39.unknown": "Mystagogical Lectures 3.6",

    # --- CATEGORY B: identified by cross-reference to NewAdvent full text ---

    # 2Thess 2:4 -- Antichrist in the Temple (Lecture 15, section 15)
    # https://www.newadvent.org/fathers/310115.htm
    "cyril-of-jerusalem.2Thess.2.4.unknown": "Catechetical Lecture 15:15",

    # Acts 5:3 -- Ananias and Sapphira, Peter present by the Spirit (Lecture 16, section 17)
    # https://www.newadvent.org/fathers/310116.htm
    "cyril-of-jerusalem.Acts.5.3.unknown": "Catechetical Lecture 16:17",

    # Col 1:16 -- Christ Maker of all, thrones/principalities (Lecture 11, section 24)
    # https://www.newadvent.org/fathers/310111.htm
    "cyril-of-jerusalem.Col.1.16.unknown": "Catechetical Lecture 11:24",

    # Col 1:20 -- peace through blood of cross, lay down life at will (Lecture 13, section 33)
    # https://www.newadvent.org/fathers/310113.htm
    "cyril-of-jerusalem.Col.1.20.unknown": "Catechetical Lecture 13:33",

    # Col 2:15 -- confess the Crucified, cross as seal on forehead (Lecture 13, section 36)
    # https://www.newadvent.org/fathers/310113.htm
    "cyril-of-jerusalem.Col.2.15.unknown": "Catechetical Lecture 13:36",

    # Col 2:8 -- pious doctrines + virtuous practice, beware philosophy (Lecture 4, section 2)
    # https://www.newadvent.org/fathers/310104.htm
    "cyril-of-jerusalem.Col.2.8.unknown": "Catechetical Lecture 4:2",

    # Col 3:20 -- honour earthly fathers, obey parents, love me more (Lecture 7, section 15)
    # https://www.newadvent.org/fathers/310107.htm
    "cyril-of-jerusalem.Col.3.20.unknown": "Catechetical Lecture 7:15",

    # Isa 63:16 -- God as Father of men in improper sense vs Father of Christ by nature
    # (Lecture 7, section 10) https://www.newadvent.org/fathers/310107.htm
    "cyril-of-jerusalem.Isa.63.16.unknown": "Catechetical Lecture 7:10",

    # Mark 15:23 -- myrrh like gall, bitter; gall offered to Jesus (Lecture 13, section 29)
    # https://www.newadvent.org/fathers/310113.htm
    "cyril-of-jerusalem.Mark.15.23.unknown": "Catechetical Lecture 13:29",
}


def main() -> None:
    print(f"Loading {DATA_FILE}")
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["data"]
    blank_before = sum(1 for e in entries if not e.get("source_title"))
    print(f"Blank source_title entries before patch: {blank_before}")

    set_count = 0
    skipped_already_set = 0
    skipped_not_in_data = []

    # Build lookup by entry_id
    entry_map = {e["entry_id"]: e for e in entries}

    for entry_id, title in PATCH.items():
        if entry_id not in entry_map:
            skipped_not_in_data.append(entry_id)
            continue
        entry = entry_map[entry_id]
        if entry.get("source_title"):
            skipped_already_set += 1  # idempotent skip
        else:
            entry["source_title"] = title
            set_count += 1

    blank_after = sum(1 for e in entries if not e.get("source_title"))

    print(f"Set:                    {set_count}")
    print(f"Skipped (already set):  {skipped_already_set}")
    if skipped_not_in_data:
        print(f"WARNING: entry_ids not found in data ({len(skipped_not_in_data)}):")
        for eid in skipped_not_in_data:
            print(f"  {eid}")
    print(f"Blank source_title entries after patch: {blank_after}")
    print(f"  (4 entries intentionally left blank -- MEDIUM confidence only)")
    print(f"  Acts.2.17.unknown, Acts.2.36.unknown, Acts.2.38.unknown, Jas.2.24.unknown")

    print(f"\nWriting {DATA_FILE}")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Done.")

    # Run validator
    print("\nRunning validate.py ...")
    try:
        subprocess.run(
            ["py", "-3", str(VALIDATE_SCRIPT),
             "data/church-fathers/cyril-of-jerusalem.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 16, f"Expected 16 patch entries, got {len(PATCH)}"
    main()
