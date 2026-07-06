"""
Upgrade patch: replace work-level 'Commentary on Psalms' source_titles for
Hilary of Poitiers psalm entries with section-specific NPNF references.

Context:
The original patch (patch_source_title_hilary_of_poitiers.py) assigned
'Commentary on Psalms' to all 16 psalm entries because section numbers were
not known at the time. A subsequent evaluation identified this as an
inconsistency: adjacent set entries in the same file use section-specific
format ('HOMILY ON PSALM 1:11', 'HOMILY ON PSALM 54:6' etc.).

This script upgrades those 16 entries to section-specific titles confirmed
via NewAdvent NPNF translation (newadvent.org/fathers/3303xxx.htm):

  Psalm 1:  https://www.newadvent.org/fathers/3303001.htm
  Psalm 53 (=MT 54): https://www.newadvent.org/fathers/3303053.htm
  Psalm 131: https://www.newadvent.org/fathers/3303131.htm

Verification method: for each missing entry, the opening words of the TOML
quote were matched against the NewAdvent text section-by-section to confirm
the section number. The section numbering matches the existing set entries
(e.g. 'HOMILY ON PSALM 54:6' is confirmed as NewAdvent section 6, matching
quote "Hear my prayer, O God, give ear to the words of my mouth").

Psalm 54 convention: the existing set entries use MT numbering ('54:X') not
LXX+MT hybrid ('53(54):X'), so this script follows the same convention.

Note: Ps.54.2.unknown is assigned 'HOMILY ON PSALM 54:6', the same section
as the existing set entry Ps.54.1-2.homily-on-psalm-546. Both are correct --
they are different quote excerpts from the same commentary section, attached
to different verse anchors in the upstream TOML database.

Run with:  py -3 build/patch_upgrade_hilary_psalms_sections.py
Then:      py -3 build/validate.py data/church-fathers/hilary-of-poitiers.json
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = REPO_ROOT / "data" / "church-fathers" / "hilary-of-poitiers.json"

# Only upgrade entries whose source_title is currently 'Commentary on Psalms'.
# Keyed by entry_id, value is the section-specific title to assign.
UPGRADES = {
    # --- Homily on Psalm 1 (6 entries) ---
    # Confirmed via newadvent.org/fathers/3303001.htm
    "hilary-of-poitiers.Ps.1.2.unknown-3": "HOMILY ON PSALM 1:3",   # Sec 3: "Now the words which stand at the beginning of the Psalm are quite unsuited to the Person..."
    "hilary-of-poitiers.Ps.1.1.unknown":   "HOMILY ON PSALM 1:6",   # Sec 6: "The Prophet recites five kinds of caution as continually present in the mind of the happy man..."
    "hilary-of-poitiers.Ps.1.2.unknown":   "HOMILY ON PSALM 1:7",   # Sec 7: "There is no doubt then that, as this instance proves, the undutiful (or ungodly)..."
    "hilary-of-poitiers.Ps.1.2.unknown-2": "HOMILY ON PSALM 1:12",  # Sec 12: "But then sometimes the will needs supplementing; and the mere desire for perfect happiness..."
    "hilary-of-poitiers.Ps.1.5.unknown":   "HOMILY ON PSALM 1:20",  # Sec 20: "And the Prophet, seeing that the change of their solid substance into dust..."
    "hilary-of-poitiers.Ps.1.6.unknown":   "HOMILY ON PSALM 1:23",  # Sec 23: "It is precisely the scheme and system thus laid down in the Gospel that the Prophet has followed..."

    # --- Homily on Psalm 54 (7 entries, MT numbering to match existing set entries) ---
    # Confirmed via newadvent.org/fathers/3303053.htm (NewAdvent uses LXX Psalm 53)
    "hilary-of-poitiers.Ps.54.1.unknown":  "HOMILY ON PSALM 54:1",  # Sec 1: "The doctrines of the Gospel were well known to holy and blessed David..."
    "hilary-of-poitiers.Ps.54.2.unknown":  "HOMILY ON PSALM 54:6",  # Sec 6: "Next there follows: Hear my prayer, O God, give ear unto the words of my mouth..."
    "hilary-of-poitiers.Ps.54.3.unknown":  "HOMILY ON PSALM 54:7",  # Sec 7: "He has next added the reason why He prays for His words to be heard: For strangers are risen..."
    "hilary-of-poitiers.Ps.54.4.unknown":  "HOMILY ON PSALM 54:9",  # Sec 9: "The introduction of a pause marks a change of person. He no longer speaks but is addressed."
    "hilary-of-poitiers.Ps.54.5.unknown":  "HOMILY ON PSALM 54:11", # Sec 11: "After this there is a return to the Person of God: Destroy them by Your truth..."
    "hilary-of-poitiers.Ps.54.6.unknown":  "HOMILY ON PSALM 54:13", # Sec 13: "For next there follows: I will sacrifice unto You freely..."
    "hilary-of-poitiers.Ps.54.7.unknown":  "HOMILY ON PSALM 54:14", # Sec 14: "Then He gives thanks to God the Father: I will give thanks unto Your name, O Lord..."

    # --- Homily on Psalm 131 (3 entries) ---
    # Confirmed via newadvent.org/fathers/3303131.htm
    "hilary-of-poitiers.Ps.131.1.unknown": "HOMILY ON PSALM 131:1", # Sec 1: "This Psalm, a short one, which demands an analytical rather than a homiletical treatment..."
    "hilary-of-poitiers.Ps.131.2.unknown": "HOMILY ON PSALM 131:5", # Sec 5: "Then he goes on: Like a weaned child upon his mother's breast..."
    "hilary-of-poitiers.Ps.131.3.unknown": "HOMILY ON PSALM 131:6", # Sec 6: "But he does not demand this living bread from heaven for himself alone..."
}

EXPECTED_UPGRADE_SIZE = 16
EXPECTED_PREVIOUS_VALUE = "Commentary on Psalms"


def main():
    assert len(UPGRADES) == EXPECTED_UPGRADE_SIZE, (
        f"UPGRADES size mismatch: expected {EXPECTED_UPGRADE_SIZE}, got {len(UPGRADES)}"
    )

    with open(DATA_FILE, encoding='utf-8') as f:
        data = json.load(f)

    entries = data['data']
    total = len(entries)
    index = {e['entry_id']: e for e in entries}

    # Verify all upgrade keys exist in data
    missing_ids = [eid for eid in UPGRADES if eid not in index]
    if missing_ids:
        print(f"ERROR: {len(missing_ids)} entry_ids not found in data:")
        for eid in missing_ids:
            print(f"  {eid}")
        raise SystemExit(1)

    upgraded = 0
    skipped_already_specific = 0
    skipped_wrong_value = 0

    for entry_id, new_title in UPGRADES.items():
        entry = index[entry_id]
        current = entry.get('source_title', '')
        if current == new_title:
            # Already at the target value -- idempotent skip
            upgraded += 1  # count as applied for idempotency reporting
            skipped_already_specific += 1
        elif current == EXPECTED_PREVIOUS_VALUE:
            entry['source_title'] = new_title
            upgraded += 1
        else:
            # Unexpected value -- log but don't overwrite
            print(f"  SKIP (unexpected value): {entry_id} -> '{current}'")
            skipped_wrong_value += 1

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Done. Total entries: {total}")
    print(f"  Upgraded:                 {upgraded - skipped_already_specific}")
    print(f"  Already specific (skip):  {skipped_already_specific}")
    print(f"  Unexpected value (skip):  {skipped_wrong_value}")


if __name__ == '__main__':
    main()
