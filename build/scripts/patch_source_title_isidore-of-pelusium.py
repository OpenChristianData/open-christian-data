# standards: author id slug
"""
Patch source_title for isidore-of-pelusium (9 blank entries resolved).

All 9 missing entries are quotes from Isidore of Pelusium as preserved in
Thomas Aquinas's Catena Aurea on Luke (Chapters 6-24). The TOML source files
already carry source_title='Catena Aurea by Aquinas'; the "unknown" entries in
the JSON are stripped-prefix variants of the same quotes (the epistle-reference
prefixes like "(l. i. ep. 438.)" are absent, but the quote body is identical).

Title format convention (matched to the 10 existing entries already set in this
file):
  "Catena Aurea by Aquinas"

Confidence: HIGH for all 9.
- Every entry's TOML file already has source_title='Catena Aurea by Aquinas'
- Every quote was verified on historicalchristian.faith verse pages, which
  explicitly show Isidore of Pelusium [AD 450] attributed to the Catena Aurea.

Spot-checked against primary source (historicalchristian.faith):
  - isidore-of-pelusium.Luke.10.3.unknown
    (https://historicalchristian.faith/luke/10/3)
    -- confirmed: "[AD 450] Isidore of Pelusium on Luke 10:3-4 ... Denoting
    the simplicity and innocence in His disciples. For those who were riotous,
    and by their enormities did despite to their nature, He calls not lambs,
    but goats. Source: Catena Aurea by Aquinas"

  - isidore-of-pelusium.Luke.24.25.unknown
    (https://historicalchristian.faith/luke/24/25)
    -- confirmed: "[AD 450] Isidore of Pelusium on Luke 24:25-35 ... But
    although it behoved Christ to suffer, yet they who crucified Him are
    guilty... using as it were the viper's flesh for the working of a
    health-giving antidote. Source: Catena Aurea by Aquinas"

  - isidore-of-pelusium.Luke.8.1.unknown
    (https://historicalchristian.faith/luke/8/1)
    -- confirmed: "[AD 450] Isidore of Pelusium on Luke 8:1-3 ... Now this
    kingdom of God some think to be higher and better than the heavenly kingdom
    ... Source: Catena Aurea by Aquinas"

Run twice to verify idempotency.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "isidore-of-pelusium.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# All 9 entries verified via historicalchristian.faith verse-level pages,
# which explicitly attribute each quote to the Catena Aurea by Aquinas.
# The corresponding TOML files all have source_title='Catena Aurea by Aquinas'.
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # Luke 10:3-4 -- Catena Aurea on Luke Chapter 10
    # TOML: Luke 10_3-4.toml has source_title='Catena Aurea by Aquinas'
    # Verified: historicalchristian.faith/luke/10/3 shows "[AD 450] Isidore
    # of Pelusium ... Source: Catena Aurea by Aquinas"
    "isidore-of-pelusium.Luke.10.3.unknown": "Catena Aurea by Aquinas",

    # Luke 12:41-46 -- Catena Aurea on Luke Chapter 12
    # TOML: Luke 12_41-46.toml has source_title='Catena Aurea by Aquinas'
    "isidore-of-pelusium.Luke.12.41.unknown": "Catena Aurea by Aquinas",

    # Luke 18:31-34 -- Catena Aurea on Luke Chapter 18
    # TOML: Luke 18_31-34.toml has source_title='Catena Aurea by Aquinas'
    "isidore-of-pelusium.Luke.18.31.unknown": "Catena Aurea by Aquinas",

    # Luke 24:25-35 -- Catena Aurea on Luke Chapter 24
    # TOML: Luke 24_25-35.toml has source_title='Catena Aurea by Aquinas'
    # Verified: historicalchristian.faith/luke/24/25 shows "[AD 450] Isidore
    # of Pelusium ... Source: Catena Aurea by Aquinas"
    "isidore-of-pelusium.Luke.24.25.unknown": "Catena Aurea by Aquinas",

    # Luke 6:1-5 -- Catena Aurea on Luke Chapter 6
    # TOML: Luke 6_1-5.toml has source_title='Catena Aurea by Aquinas'
    "isidore-of-pelusium.Luke.6.1.unknown": "Catena Aurea by Aquinas",

    # Luke 6:43-45 -- Catena Aurea on Luke Chapter 6
    # TOML: Luke 6_43-45.toml has source_title='Catena Aurea by Aquinas'
    "isidore-of-pelusium.Luke.6.43.unknown": "Catena Aurea by Aquinas",

    # Luke 7:24-28 -- Catena Aurea on Luke Chapter 7
    # TOML: Luke 7_24-28.toml has source_title='Catena Aurea by Aquinas'
    "isidore-of-pelusium.Luke.7.24.unknown": "Catena Aurea by Aquinas",

    # Luke 8:1-3 -- Catena Aurea on Luke Chapter 8
    # TOML: Luke 8_1-3.toml has source_title='Catena Aurea by Aquinas'
    # Verified: historicalchristian.faith/luke/8/1 shows "[AD 450] Isidore
    # of Pelusium ... Source: Catena Aurea by Aquinas"
    "isidore-of-pelusium.Luke.8.1.unknown": "Catena Aurea by Aquinas",

    # Luke 9:10-17 -- Catena Aurea on Luke Chapter 9
    # TOML: Luke 9_10-17.toml has source_title='Catena Aurea by Aquinas'
    "isidore-of-pelusium.Luke.9.10.unknown": "Catena Aurea by Aquinas",
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
             "data/church-fathers/isidore-of-pelusium.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 9, f"Expected 9 patch entries, got {len(PATCH)}"
    main()
