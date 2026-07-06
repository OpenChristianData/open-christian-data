"""Follow-up patch for 2 gregory-of-nazianzus entries confirmed after the initial session.

These two entries were left blank in patch_gregory_nazianzus_source_titles.py because
their TOML files were missing and sources weren't located in the initial pass.
Both were confirmed via further web research:

  Col.1.15 -- Oration 30 (Fourth Theological Oration, On the Son), section 20
    newadvent.org Oration 30 section XX: "And the Image as of one substance with Him,
    and because He is of the Father, and not the Father of Him. For this is of the
    Nature of an Image, to be the reproduction of its Archetype... in this case it is
    the living reproduction of the Living One, and is more exactly like than was Seth
    to Adam." -- matches the Col.1.15 quote exactly (different translation, same passage).

  Jer.1.8 -- Oration 2 (In Defence of His Flight to Pontus), section 114
    earlychristiancommentary.com (scripindex id 02004013) confirms section 114:
    "some readily complied with the call, others deprecated the gift... Aaron was eager,
    but Moses resisted, Isaiah readily submitted, but Jeremiah was afraid of his youth."
    Adjacent entry Jer.1.6 is also Oration 2:114 -- both verses are part of the same
    Jeremiah call narrative Gregory addresses in that section.

Still omitted (confirmed unverifiable with available sources):
  - gregory-of-nazianzus.Jonah.1.1.unknown-2  (Oration 2, section unconfirmed)
  - gregory-of-nazianzus.Jonah.1.3.unknown    (Oration 2, section unconfirmed)
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
    # Col 1:15 -- Fourth Theological Oration (Oration 30), section 20
    # Gregory discusses Christ's title "Image" in Oration 30.20, explaining he is of one
    # substance with the Father, that the nature of an image is to copy the original,
    # and that this is a living image -- more exactly like than Seth was to Adam.
    # Same section as Acts.17.28 (Oration 30.20 covers multiple divine titles of the Son).
    "gregory-of-nazianzus.Col.1.15.unknown": "ON THE SON, THEOLOGICAL ORATION 4(30).20",
    # Jer 1:8 -- Oration 2 (In Defence of His Flight to Pontus), section 114
    # Gregory surveys prophets who accepted or resisted God's call, noting "some readily
    # complied... others deprecated the gift" -- Aaron eager, Moses resisting, Isaiah
    # readily submitting, Jeremiah afraid of his youth. Adjacent Jer.1.6 is also 2:114.
    "gregory-of-nazianzus.Jer.1.8.unknown": "IN DEFENSE OF HIS FLIGHT TO PONTUS, ORATION 2:114",
}

EXPECTED_PATCH_COUNT = 2


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

    # Confirm how many source_title gaps remain for this file
    remaining = sum(1 for e in entries if not e.get("source_title"))
    print(f"Remaining empty source_title: {remaining}")
    if remaining:
        print("NOTE: {0} entries left blank (section unconfirmable -- see docstring)".format(remaining))


if __name__ == "__main__":
    main()
