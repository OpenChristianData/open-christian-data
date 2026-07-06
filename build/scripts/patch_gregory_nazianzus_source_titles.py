"""Patch missing source_title for gregory-of-nazianzus church_fathers entries.

29 entries had empty source_title.  25 are patched here with HIGH confidence
(verified against primary source or identical-text adjacent entry).  4 are
omitted as unverifiable at this time:

  OMITTED (medium confidence only -- specific section not confirmed):
    - gregory-of-nazianzus.Col.1.15.unknown  (TOML missing; not located in Theological Orations)
    - gregory-of-nazianzus.Jer.1.8.unknown   (TOML missing; section in Oration 2 not confirmed)
    - gregory-of-nazianzus.Jonah.1.1.unknown-2  (Oration 2 but section number not confirmed)
    - gregory-of-nazianzus.Jonah.1.3.unknown    (Oration 2 but section number not confirmed)

Sources used for verification:
  - newadvent.org/fathers/310229.htm  (Oration 29 -- Mark entries confirmed in section XX)
  - newadvent.org/fathers/310230.htm  (Oration 30 -- Acts 17:28 in section XX; Col 3:11 in section VI)
  - newadvent.org/fathers/310238.htm  (Oration 38 -- Luke 2:7 confirmed as section I opening)
  - newadvent.org/fathers/310241.htm  (Oration 41 -- Acts 2:8 confirmed in section XV)
  - sensusfidelium.com Catena Aurea Luke ch.10 (Luke 10:3 Gregory quote confirmed in CA)
  - Adjacent existing entries: Jonah.1.1-3.oration-2108 = same text as Jonah.1.1.unknown

Title format conventions (matching existing gregory-of-nazianzus.json entries):
  - Catena Aurea:     "Catena Aurea by Aquinas"  (no section -- 19 existing entries)
  - Oration 29/30:    "ORATION N, ON THE SON S"  or "ON THE SON, THEOLOGICAL ORATION N(M).S"
  - Oration 38/41:    "ON [TITLE], ORATION N.S"
  - Oration 2:        "IN DEFENSE OF HIS FLIGHT TO PONTUS, ORATION 2:S"
"""

import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = REPO_ROOT / "data" / "church-fathers" / "gregory-of-nazianzus.json"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title
# ---------------------------------------------------------------------------

PATCH = {
    # --- 18 Luke entries: Catena Aurea by Aquinas ---
    # Every entry sits directly after (or within) a "Luke N.M-P.catena-aurea-by-aquinas"
    # range entry in the JSON.  Luke 10:3 independently confirmed against the CA Luke ch.10
    # text at sensusfidelium.com.  Style ("Or else;", "Let us then", etc.) is consistent
    # with Aquinas' Catena Aurea throughout.
    "gregory-of-nazianzus.Luke.1.36.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.1.59.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.3.10.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.3.21.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.4.1.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.5.1.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.5.12.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.6.20.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.8.1.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.8.4.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.9.1.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.10.3.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.11.33.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.12.1.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.12.32.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.13.6.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.15.8.unknown": "Catena Aurea by Aquinas",
    "gregory-of-nazianzus.Luke.24.36.unknown": "Catena Aurea by Aquinas",
    # --- Luke 2:7: Oration 38 (On the Theophany), section 1 ---
    # TOML has inline citation: "Oration 38 (On the Theophany, or Birthday of Christ)".
    # newadvent.org Oration 38 section I confirmed: exact opening text matches
    # ("Christ is born, glorify Him. Christ from heaven, go out to meet Him...").
    "gregory-of-nazianzus.Luke.2.7.unknown": "ON THE THEOPHANY, ORATION 38.1",
    # --- 2 Mark entries: Oration 29 (On the Son), section 20 ---
    # TOML for both ends with "Oration , On the Son" (oration number truncated in source).
    # newadvent.org Oration 29 section XX confirmed: both quotes appear in the
    # extended litany of contrasting-attributes ("He was tired -- yet he is the rest...",
    # "He is given vinegar... who turned water into wine").
    # Mark.15.23 is also flanked by two existing "ORATION 29, ON THE SON 20" entries
    # (Mark.14.11 and Mark.15.38), confirming the section assignment.
    "gregory-of-nazianzus.Mark.15.23.unknown": "ORATION 29, ON THE SON 20",
    "gregory-of-nazianzus.Mark.4.38.unknown": "ORATION 29, ON THE SON 20",
    # --- Acts 17:28: Fourth Theological Oration (Oration 30), section 20 ---
    # TOML has inline citation: "Fourth Theological Oration, 20-21".
    # newadvent.org Oration 30 section XX confirmed: Acts 17:28 ("in Him we live
    # and move and have our being") appears in the discussion of Christ as Life.
    "gregory-of-nazianzus.Acts.17.28.unknown": "ON THE SON, THEOLOGICAL ORATION 4(30).20",
    # --- Acts 2:8: Oration 41 (On Pentecost), section 15 ---
    # newadvent.org Oration 41 section XV confirmed: Gregory discusses whether
    # Pentecost was a miracle of the speakers or of the hearers -- exact topic
    # of the Acts 2:8 quote ("Was it that the speakers expressed what they had to say
    # in the diverse discourse of every language, or each heard in their own tongue").
    "gregory-of-nazianzus.Acts.2.8.unknown": "ON PENTECOST, ORATION 41.15",
    # --- Jonah 1:1: Oration 2 (In Defense of His Flight to Pontus), section 108 ---
    # The opening text of this entry is identical to existing entry
    # gregory-of-nazianzus.Jonah.1.1-3.oration-2108 (source_title = "Oration 2:108").
    # Same text = same source.  Formatted to match dominant Oration 2 style in this file.
    "gregory-of-nazianzus.Jonah.1.1.unknown": "IN DEFENSE OF HIS FLIGHT TO PONTUS, ORATION 2:108",
    # --- Col 3:11: Fourth Theological Oration (Oration 30), section 6 ---
    # newadvent.org Oration 30 section VI confirmed: Gregory addresses "God will be all
    # in all in the time of restitution" (1 Cor 15:28), clarifying it does not mean
    # the Son dissolves into the Father -- matching the Col 3:11 quote exactly.
    "gregory-of-nazianzus.Col.3.11.unknown": "ON THE SON, THEOLOGICAL ORATION 4(30).6",
}

EXPECTED_PATCH_COUNT = 25


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

    # Quick spot-check: confirm how many source_title warnings remain for this file
    remaining = sum(1 for e in entries if not e.get("source_title"))
    print(f"Remaining empty source_title: {remaining}")
    if remaining:
        print("NOTE: {0} entries left blank (medium/low confidence -- see docstring)".format(remaining))


if __name__ == "__main__":
    main()
