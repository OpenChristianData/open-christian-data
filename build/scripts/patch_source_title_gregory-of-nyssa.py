# standards: author id slug
"""Patch missing source_title for gregory-of-nyssa church_fathers entries.

21 entries had empty source_title. 16 are patched here with HIGH confidence.
5 are left blank (MEDIUM/LOW confidence -- see omissions below).

OMITTED (medium/low confidence -- source not confirmed):
    - gregory-of-nyssa.Col.1.18.unknown   (LOW: short quote, no citation, source unconfirmed)
    - gregory-of-nyssa.Col.3.9.unknown    (MEDIUM: themes match On the Making of Man but not confirmed)
    - gregory-of-nyssa.2Thess.2.14.unknown (LOW: very short, single sentence, no citation)
    - gregory-of-nyssa.Deut.6.5.unknown   (LOW: no citation, no adjacent-entry signal)
    - gregory-of-nyssa.Gen.1.9.unknown    (LOW: no citation, adjacent entries are different works)

Sources used for verification:
    - tertullian.org/fathers/gregory_macrina_1_life.htm
      (Life of St. Macrina -- Macrina's deathbed prayer confirmed, 1Cor.15.52 entry)
    - newadvent.org/fathers/2915.htm
      (On the Soul and the Resurrection -- anger/courage/terror/caution passage, Col.3.2)
    - newadvent.org/fathers/290104.htm
      (Against Eunomius Book 4 -- "twofold creation", "took dust from the Virgin", Col.1.15)
    - newadvent.org/fathers/290112.htm
      (Against Eunomius Book 12, Chapter 1 -- "slain in himself the enmity", Col.2.9)
    - newadvent.org/fathers/2914.htm
      (On the Making of Man Chapter 6 -- Trinity unity / "Let us make man", Gen.1.26)
    - newadvent.org/fathers/2911.htm
      (Letters -- Letter 17 confirmed in list, Rev.20.2)
    - sourcebooks.fordham.edu/basis/macrina.asp
      (Life of Macrina -- deathbed prayer confirmed)
    - Adjacent entries (Catena Aurea pattern for all 8 Luke entries)
    - Inline citations in TOML quotes (1Sam.24.5, 2Cor.6.16, Gen.1.26, Rev.20.2)

Title format conventions (matching existing gregory-of-nyssa.json entries):
    - Catena Aurea:              "Catena Aurea by Aquinas"  (54 existing entries)
    - On the Soul and the Resurrection: no section number (10 existing entries)
    - Against Eunomius:          "Against Eunomius N.M"  (book.section, e.g. "Against Eunomius 12.1")
    - On the Inscriptions of the Psalms: "On the Inscriptions of the Psalms N.M.P"
    - Homilies on the Song of Songs: "Homilies on the Song of Songs N"
    - On the Making of Man:      "On the Making of Man N"  or "On the Making of Man N.M"
    - Letter 17:                 "Letter 17"  (matching existing gregory-of-nyssa.John.20.13.letter-17)

Spot-checked against primary source:
    - gregory-of-nyssa.1Cor.15.52.unknown (tertullian.org Life of Macrina) -- confirmed: exact
      deathbed prayer text present ("Thou, O Lord, hast freed us from the fear of death...")
    - gregory-of-nyssa.Col.2.9.unknown (newadvent.org/fathers/290112.htm Against Eunomius XII.1)
      -- confirmed: passage about "slain in Himself the enmity" and "fullness of the Godhead
      bodily" present in Book 12, Chapter 1
    - gregory-of-nyssa.Col.1.15.unknown (newadvent.org/fathers/290104.htm Against Eunomius IV)
      -- confirmed via CCEL npnf205.viii.i.vi.iii: "twofold creation of our nature" and "took
      dust from the Virgin" present in Against Eunomius Book 4, Section 3
    - gregory-of-nyssa.Luke.22.39.unknown (adjacency) -- sits directly after
      Luke.22.39-42.catena-aurea-by-aquinas; same pattern confirmed in gregory-of-nazianzus patch
    - gregory-of-nyssa.Col.3.2.unknown (CCEL npnf205.x.iii.ii "On the Soul and the Resurrection")
      -- confirmed: "anger produces courage, terror caution, fear obedience" passage present
"""

import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = REPO_ROOT / "data" / "church-fathers" / "gregory-of-nyssa.json"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title
# ---------------------------------------------------------------------------

PATCH = {
    # --- 1 Corinthians 15:52: Life of St. Macrina ---
    # TOML ends with "The Life of St." (truncated attribution).
    # The quote is Macrina's deathbed prayer ("O Lord, you have freed us from the fear
    # of death...last trumpet...dust of the earth for safe keeping").
    # Confirmed at tertullian.org/fathers/gregory_macrina_1_life.htm: exact prayer text
    # present in the Life of St. Macrina (Macrina's Dying Prayer section).
    "gregory-of-nyssa.1Cor.15.52.unknown": "Life of St. Macrina",

    # --- 1 Samuel 24:5: On the Inscriptions of the Psalms 2.14.224 ---
    # Inline citation in TOML quote: "On the Inscriptions of the Psalms 2.14.224"
    # Adjacent entries confirm exact format: 1Sam.24.4-5 = "On the Inscriptions of
    # the Psalms 2.14.227-28", 1Sam.24.8-11 = "On the Inscriptions of the Psalms
    # 2.14.229-30". Section 2.14.224 is slightly earlier in the same chapter,
    # consistent with the David-in-the-cave narrative.
    "gregory-of-nyssa.1Sam.24.5.unknown": "On the Inscriptions of the Psalms 2.14.224",

    # --- 2 Corinthians 6:16: Homilies on the Song of Songs 2 ---
    # TOML quote ends with "Second Homily on the Song of Songs (PG 44,765)".
    # Existing dataset format is "Homilies on the Song of Songs N".
    # "Second Homily" = Homily 2.
    "gregory-of-nyssa.2Cor.6.16.unknown": "Homilies on the Song of Songs 2",

    # --- Colossians 1:15: Against Eunomius 4.3 ---
    # Confirmed at CCEL (npnf205.viii.i.vi.iii): "we recognize a twofold creation of
    # our nature, the first that whereby we were made, the second that whereby we were
    # made anew" and "He took dust from the earth and formed man: again, He took dust
    # from the Virgin" -- exact passage, Against Eunomius Book 4, Section 3, which
    # discusses prototokos (Colossians 1:15) against Eunomius.
    "gregory-of-nyssa.Col.1.15.unknown": "Against Eunomius 4.3",

    # --- Colossians 2:9: Against Eunomius 12.1 ---
    # Confirmed at newadvent.org/fathers/290112.htm: "it was impossible that our life,
    # which had been estranged from God, should of itself return...slain in Himself
    # the enmity which by means of sin had come between us and God...in Whom dwelt all
    # the fullness of the Godhead bodily" -- exact passage in Against Eunomius Book 12,
    # Chapter 1. Existing entry gregory-of-nyssa.Against.Eunomius.12.1 confirms format.
    "gregory-of-nyssa.Col.2.9.unknown": "Against Eunomius 12.1",

    # --- Colossians 3:2: On the Soul and the Resurrection ---
    # Confirmed at CCEL (npnf205.x.iii.ii, "On the Soul and the Resurrection"):
    # "anger produces courage; terror, caution; fear, obedience" -- the exact
    # enumeration of passions-to-virtues in this passage. The apostle reference
    # ("think those things that are above") is cited within the same passage.
    "gregory-of-nyssa.Col.3.2.unknown": "On the Soul and the Resurrection",

    # --- Genesis 1:26: On the Making of Man 6 ---
    # TOML quote ends with "On The Making of Man, PG 44, 140".
    # Confirmed at newadvent.org/fathers/2914.htm: Chapter VI ("An examination of the
    # kindred of mind to nature") contains the exact argument: "He Who said, Let us
    # make after our image, and by the plural signification revealed the Holy Trinity,
    # would not, if the archetypes were unlike one another, have mentioned the image
    # in the singular."
    "gregory-of-nyssa.Gen.1.26.unknown": "On the Making of Man 6",

    # --- Revelation 20:2: Letter 17 ---
    # TOML quote ends with "(Letter 17)".
    # Confirmed: newadvent.org/fathers/2911.htm lists Letter 17 as "TO EUSTATHIA,
    # AMBROSIA, AND BASILISSA". Existing entry gregory-of-nyssa.John.20.13.letter-17
    # confirms format "Letter 17".
    "gregory-of-nyssa.Rev.20.2.unknown": "Letter 17",

    # --- 8 Luke entries: Catena Aurea by Aquinas ---
    # All 8 "unknown" Luke entries sit immediately adjacent to a "catena-aurea-by-aquinas"
    # range entry covering the same or overlapping verse in the JSON:
    #   Luke.10.25  -> adjacent to Luke.10.25-28.catena-aurea-by-aquinas
    #   Luke.11.5   -> adjacent to Luke.11.5-8.catena-aurea-by-aquinas
    #   Luke.12.27  -> adjacent to Luke.12.27-31.catena-aurea-by-aquinas
    #   Luke.12.32  -> adjacent to Luke.12.32-34.catena-aurea-by-aquinas
    #   Luke.22.39  -> adjacent to Luke.22.39-42.catena-aurea-by-aquinas
    #   Luke.23.44  -> adjacent to Luke.23.44-46.catena-aurea-by-aquinas
    #   Luke.3.15   -> adjacent to Luke.3.15-17.catena-aurea-by-aquinas
    #   Luke.7.29   -> adjacent to Luke.7.29-35.catena-aurea-by-aquinas
    # This is the same pattern confirmed in the gregory-of-nazianzus patch
    # (18 Luke entries, all adjacent to Catena Aurea range entries).
    # 54 existing "Catena Aurea by Aquinas" entries for this author further confirm
    # the format.
    "gregory-of-nyssa.Luke.10.25.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nyssa.Luke.11.5.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nyssa.Luke.12.27.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nyssa.Luke.12.32.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nyssa.Luke.22.39.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nyssa.Luke.23.44.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nyssa.Luke.3.15.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nyssa.Luke.7.29.unknown": "Catena Aurea by Aquinas",
}

EXPECTED_PATCH_COUNT = 16


def main() -> None:
    assert len(PATCH) == EXPECTED_PATCH_COUNT, (
        f"PATCH dict has {len(PATCH)} entries, expected {EXPECTED_PATCH_COUNT}"
    )

    start = time.monotonic()
    print(f"Loading {DATA_FILE}")
    with open(DATA_FILE, encoding="utf-8") as f:
        doc = json.load(f)

    entries = doc["data"]

    # Build lookup by entry_id for fast access
    by_id = {e["entry_id"]: e for e in entries}

    # Verify all patch keys exist in the file before writing anything
    missing_ids = [eid for eid in PATCH if eid not in by_id]
    if missing_ids:
        print(f"ERROR: {len(missing_ids)} patch key(s) not found in data file:")
        for eid in missing_ids:
            print(f"  {eid}")
        print("Action: check whether entry_id values have changed in the JSON file, "
              "or update the PATCH dict to match current IDs.")
        sys.exit(1)

    set_count = 0
    skip_count = 0

    for entry_id, source_title in PATCH.items():
        entry = by_id[entry_id]
        if entry.get("source_title"):
            skip_count += 1
        else:
            entry["source_title"] = source_title
            set_count += 1

    elapsed = time.monotonic() - start
    print(f"Set: {set_count}  |  Skipped (already filled): {skip_count}  |  Elapsed: {elapsed:.2f}s")

    if set_count == 0:
        print("No changes to write -- file unchanged.")
    else:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"Saved {DATA_FILE}")

    # Quick spot-check: confirm how many source_title gaps remain for this file
    remaining = sum(1 for e in entries if not e.get("source_title"))
    print(f"Remaining empty source_title: {remaining}")
    if remaining:
        print(
            "NOTE: {0} entries left blank (medium/low confidence -- see docstring)".format(
                remaining
            )
        )


if __name__ == "__main__":
    main()
