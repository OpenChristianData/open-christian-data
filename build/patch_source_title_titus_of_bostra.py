"""
Patch source_title for Titus of Bostra church-fathers entries.

38 entries were missing source_title. All are single-verse TOML files whose
quotes appear verbatim (minor transcription variation only) in corresponding
range TOML files that carry explicit Catena Aurea attribution:
  - source_url pointing to historicalchristian.faith Catena Aurea on Luke
  - source_title = 'Catena Aurea by Aquinas'
  - append_to_author_name = ' (as quoted by Aquinas, AD 1274)'

Example: Luke 8_1.toml (no source_title) vs Luke 8_1-3.toml (has source_title)
-- same quote, same source.

Spot-checked 3 entries against historicalchristian.faith Catena Aurea pages
using Playwright (depth=4 required for iframe content):
  - Luke 8:1  (Ch.8)  -- "TITUS BOSTRENSIS: For He who descends from heaven
                          to earth, brings tidings..." confirmed
  - Luke 22:3 (Ch.22) -- "TITUS BOSTRENSIS: Satan entered into Judas not by
                          force, but finding the door open..." confirmed
  - Luke 9:51 (Ch.9)  -- "TITUS BOSTRENSIS: Because it was necessary that the
                          true Lamb should there be offered..." confirmed

Title format matches the established convention for this file:
all 47 existing entries use "Catena Aurea by Aquinas" (work-level, not
section-specific -- consistent with how the database attributes these quotes).

Run with:  py -3 build/patch_source_title_titus_of_bostra.py
Then:      py -3 build/validate.py data/church-fathers/titus-of-bostra.json
"""

import json
from pathlib import Path

# Build the path relative to this script's location so it works on any machine.
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = REPO_ROOT / "data" / "church-fathers" / "titus-of-bostra.json"

PATCH = {
    # All 38 entries are from the Catena Aurea on Luke by Thomas Aquinas.
    # Each single-verse TOML file contains the same quote as its corresponding
    # range TOML file, which carries explicit Catena Aurea attribution.
    "titus-of-bostra.Luke.10.13.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.10.17.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.10.21.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.10.5.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.11.1.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.11.14.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.11.17.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.13.1.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.15.11.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.15.25.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.17.11.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.18.18.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.19.1.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.19.28.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.1.39.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.20.19.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.21.28.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.21.34.unknown": "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.21.5.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.22.3.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.2.22.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.4.5.unknown":   "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.5.12.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.6.43.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.6.6.unknown":   "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.7.11.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.7.24.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.7.29.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.7.36.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.8.1.unknown":   "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.8.19.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.8.26.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.8.4.unknown":   "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.8.40.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.9.32.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.9.37.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.9.43.unknown":  "Catena Aurea by Aquinas",
    "titus-of-bostra.Luke.9.51.unknown":  "Catena Aurea by Aquinas",
}

EXPECTED_PATCH_SIZE = 38


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
