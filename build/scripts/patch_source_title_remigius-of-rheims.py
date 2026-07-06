# standards: author id slug
"""Patch missing source_title for remigius-of-rheims church_fathers entries.

9 of 10 missing entries are patched here with HIGH confidence.
1 entry (Acts.3.26) is left blank -- LOW confidence, no primary source found.

--- Background ---

196 total entries; 186 have source_title='Catena Aurea by Aquinas'.
10 entries have an empty source_title and carry the '.unknown' suffix in their
entry_id. These came from standalone TOML files under
raw/Commentaries-Database/Remigius of Rheims/ that had no source_title field.

Each of the 9 patched entries (Matthew + Mark) has a corresponding RANGE TOML
file covering the same verse(s) in the same chapter -- e.g.
  Matthew 3_3.toml  <-->  Matthew 3_1-3.toml  (source_title='Catena Aurea by Aquinas')
  Mark 5_20.toml    <-->  Mark 5_1-20.toml    (source_title='Catena Aurea by Aquinas')

All range TOMLs carry source_url pointing to historicalchristian.faith (Catena
Aurea by Aquinas). The standalone TOMLs are stripped-down duplicates of the same
passage with attribution removed -- a data propagation gap in the upstream
Commentaries-Database.

The Acts.3.26 entry has NO adjacent range TOML, no source_url, and no matching
primary source. Aquinas's Catena Aurea covers only the four Gospels, not Acts.
No commentary on Acts by Remigius of Rheims or Remigius of Auxerre is known.
Acts.3.26 is left blank.

--- Evidence for source_title assignment ---

Triage: data propagation gap for all 9 Matthew/Mark entries.

For each entry, the evidence chain is:
  1. A RANGE TOML for the same chapter+verse carries source_title='Catena Aurea
     by Aquinas' and a source_url pointing to the relevant chapter page.
  2. The range TOML and standalone TOML contain identical or condensed versions
     of the same quote text (the standalone files omit attribution markup and
     collapse whitespace).
  3. Seven of nine entries were directly verified against the primary source at
     historicalchristianfaith.github.io/Writings-Database -- the Remigius quote
     text matches the TOML verbatim within that chapter's HTML.
  4. The remaining two (Matt.15.11, Matt.15.31) could not be verified via the
     GitHub Pages source because Chapter 15 is absent from that repository.
     However both have adjacent range TOMLs (Matthew 15_7-11.toml and
     Matthew 15_29-31.toml) that explicitly cite the same Chapter 15 URL and
     source_title, with word-for-word matching quote text.

--- Confidence ratings ---

HIGH (9 entries): all Matthew + Mark entries.
  - Adjacent range TOML corroboration (all 9)
  - Direct primary-source text match (7 of 9)
  - Competing signal: none. No alternate source_url, no different author hint.

LOW / unresolvable (1 entry): Acts.3.26 -- left blank.
  - Short quote (30 words), single-signal inference only
  - No adjacent range TOML exists
  - Catena Aurea does not cover Acts
  - No Acts commentary by Remigius confirmed in scholarship

--- Spot-checked against primary source ---

  - remigius-of-rheims.Matt.3.3.unknown
    URL: https://historicalchristianfaith.github.io/Writings-Database/Thomas%20Aquinas/Catena%20Aurea/Commentary%20on%20Matthew/Chapter%203.html
    Confirmed: REMIGIUS block found: "In these words (ver. 1.) we have not only
    time, place, and person, respecting St. John, but also his office and
    employment. First the time, generally; In those days." -- exact match.

  - remigius-of-rheims.Matt.8.13.unknown
    URL: https://historicalchristianfaith.github.io/Writings-Database/Thomas%20Aquinas/Catena%20Aurea/Commentary%20on%20Matthew/Chapter%208.html
    Confirmed: REMIGIUS text found at position 36913: "...gnashing of teeth to
    those who should dwell in the colder regions, as Hyrcania and Seythia."
    -- exact match (minor OCR variant 'Seythia' for 'Scythia').

  - remigius-of-rheims.Mark.5.20.unknown
    URL: https://historicalchristianfaith.github.io/Writings-Database/Thomas%20Aquinas/Catena%20Aurea/Commentary%20on%20Mark/Chapter%205.html
    Confirmed: REMIGIUS block found with explicit cross-reference
    "(v. Aur. Cat. in Matt p. 327)" -- exact match including the page reference
    that appears as the opening phrase in the standalone TOML.

Additional spot-checks (not listed above):
  - Matt.13.9: "These ears to hear, are ears of the mind" -- confirmed in Ch 13.
  - Matt.16.28: "fulfilled in the three disciples" with "(vid. Bed. in Luc.
    9:27.)" -- confirmed in Ch 16.
  - Matt.17.9: "Let the shadow of the Law be past" -- confirmed in Ch 17.
  - Matt.24.41: "three orders in the Church" -- confirmed in Ch 24.

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "remigius-of-rheims.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# All 9 patched entries: "Catena Aurea by Aquinas"
# 1 entry (Acts.3.26) deliberately omitted -- LOW confidence, left blank
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # Matthew entries -- all verified against adjacent range TOMLs + primary source
    "remigius-of-rheims.Matt.3.3.unknown": "Catena Aurea by Aquinas",
    "remigius-of-rheims.Matt.8.13.unknown": "Catena Aurea by Aquinas",
    "remigius-of-rheims.Matt.13.9.unknown": "Catena Aurea by Aquinas",
    "remigius-of-rheims.Matt.15.11.unknown": "Catena Aurea by Aquinas",
    "remigius-of-rheims.Matt.15.31.unknown": "Catena Aurea by Aquinas",
    "remigius-of-rheims.Matt.16.28.unknown": "Catena Aurea by Aquinas",
    "remigius-of-rheims.Matt.17.9.unknown": "Catena Aurea by Aquinas",
    "remigius-of-rheims.Matt.24.41.unknown": "Catena Aurea by Aquinas",
    # Mark entry -- verified against adjacent range TOML + primary source
    "remigius-of-rheims.Mark.5.20.unknown": "Catena Aurea by Aquinas",
    # Acts.3.26 deliberately excluded -- see docstring
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
             "data/church-fathers/remigius-of-rheims.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 9, f"Expected 9 patch entries, got {len(PATCH)}"
    main()
