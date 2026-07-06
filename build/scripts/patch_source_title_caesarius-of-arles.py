# standards: author id slug
"""Patch missing source_title for caesarius-of-arles church_fathers entries.

5 of 12 missing entries are patched here with HIGH confidence.
7 entries are left blank -- MEDIUM or LOW confidence only.

--- Background ---

All 12 missing entries are from TOML files in
raw/Commentaries-Database/Caesarius of Arles/. None have source_url or
source_title in the upstream HistoricalChristianFaith/Commentaries-Database
repository. The source_title must be determined from the quote text itself,
adjacent entries in the same TOML file, and comparison to neighbouring entries
in caesarius-of-arles.json.

--- Sermon 124 (1 Kings entries, sections 1-5) ---

Five entries covering 1 Kings 17:6, 17:9, 17:12, 17:22 and 18:44 all have
the sermon section reference embedded as trailing text at the end of the quote,
in the form: - "Sermon 124.X"

This is consistent with the ACCS (Ancient Christian Commentary on Scripture)
citation style used throughout this database -- the Commentaries-Database
compilers append the source citation as trailing text to the quote.

The five quotes form a sequential, self-consistent narrative series:
  - 124.1 (1Kgs 17:6): Elijah's flight; ravens = Gentiles typology
  - 124.2 (1Kgs 17:9): Elijah sent to widow at Zarephath; church typology
  - 124.3 (1Kgs 17:12): widow gathering two sticks; cross typology
  - 124.4 (1Kgs 17:22): widow's son revived; baptism typology
  - 124.5 (1Kgs 18:44): cloud rising from sea; sevenfold Spirit typology

Each section refers forward/backward to adjacent sections ("As we mentioned...",
"as we said..."), confirming they are sequential divisions of a single sermon.
Caesarius's Sermon 124 is published in FC 47 (Fathers of the Church, vol. 47:
Saint Caesarius of Arles: Sermons, vol. II, sermons 81-186, translated by
Mary Magdeleine Mueller, CUA Press, 1964).

--- Entries left blank (MEDIUM/LOW confidence) ---

Rev.5.2.unknown -- Adjacent entries (Rev.5.1, Rev.5.6, Rev.5.11-13) all have
  "Exposition ... Homily 4", so this is almost certainly Homily 4. But no
  source_title is present in the upstream TOML and the primary source text
  (FC 130) was not verifiable online. MEDIUM.

Rev.5.3.unknown -- Same situation as Rev.5.2.unknown. MEDIUM.

Gen.25.23.unknown -- The Genesis 25_23.toml has three blocks. Blocks 2 and 3
  are labelled Sermon 86.2 and 86.3 respectively. Block 1 (the unknown) covers
  the same Esau/Jacob theme and is in the first position, suggesting Sermon
  86.1. But Sermon 86.1 has no other entries in the file to cross-reference,
  and primary source verification failed. MEDIUM.

Jonah.3.6.unknown -- Adjacent entry Jonah.3.4 = Sermon 133:3. This is likely
  another section of Sermon 133, but the section number cannot be determined
  without primary source access. MEDIUM.

Jonah.3.7.unknown -- Same as Jonah.3.6.unknown. MEDIUM.

Col.4.2.unknown -- No identifying information in the TOML or adjacent entries.
  The quote references "Be assiduous in prayer, being wakeful" (Col 4:2) in a
  context of spiritual warfare / prayer as the Christian's weapon. Could come
  from many of Caesarius's 238 sermons. LOW.

2Thess.1.8.unknown -- Quote is: "by a flame of fire / This refers to what was
  said about those assembled at Armageddon." The Armageddon reference
  (Rev 16:16) is inconsistent with a 2 Thessalonians commentary context and
  suggests this may be a misattributed fragment from the Exposition on the
  Apocalypse (Homily 12-13 covers Rev 16). Cannot determine which work or
  section with confidence. LOW / potentially misattributed.

--- Confidence ratings ---

HIGH (5 entries): Self-identifying section labels embedded in quote text,
  confirmed by sequential internal cross-references.

MEDIUM/LOW (7 entries, skipped): No source_title in upstream TOML;
  primary source text not accessible online for verification.

--- Spot-checked against primary source ---

  - caesarius-of-arles.1Kgs.17.6.unknown
    Self-identifying label "Sermon 124.1" in quote text (upstream TOML).
    Content verified internally: section 1 opens with "Blessed Elijah typified
    our Lord and Savior" -- consistent with sermon introduction on Elijah
    typology. FC 47 (CUA Press, 1964) not accessible online; primary URL lookup
    failed after two attempts. Confident based on label + narrative position.
    Status: confirmed by internal evidence / URL lookup failed.

  - caesarius-of-arles.1Kgs.17.22.unknown
    Self-identifying label "Sermon 124.4" in quote text.
    Content begins "As we mentioned, that widow prefigured the church" --
    explicitly back-references sections 2 and 3 (widow typology). Position in
    narrative (after son dies, before Elijah on Carmel) aligns with 1Kgs 17:22.
    FC 47 not accessible online.
    Status: confirmed by internal cross-reference / URL lookup failed.

  - caesarius-of-arles.1Kgs.18.44.unknown
    Self-identifying label "Sermon 124.5" in quote text.
    Content covers 1 Kgs 18:44 (cloud like a man's foot) and closes with
    Elijah destroying pagan priests -- last section of the Elijah sermon. Label
    + final-position narrative placement consistent with section 5.
    FC 47 not accessible online.
    Status: confirmed by internal evidence / URL lookup failed.

Note: fewer than 3 PRIMARY SOURCE (URL-verified) spot-checks achieved.
All 5 patched entries rely on self-identifying labels in quote text.
Flagged for review: if FC 47 text becomes accessible, verify sections 1-5
of Sermon 124 begin with the opening words in each entry's quote.

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "caesarius-of-arles.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# All from Sermon 124 on Elijah (1 Kings chapters 17-18).
# Source: FC 47, Saint Caesarius of Arles: Sermons, vol. II (81-186),
#         translated by Mary Magdeleine Mueller, CUA Press, 1964.
# Section references embedded as trailing text in upstream TOML quote fields.
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # 1 Kings entries -- Sermon 124, sections 1-5
    # Ravens/Elijah/Gentiles typology (1 Kgs 17:6)
    "caesarius-of-arles.1Kgs.17.6.unknown": "Sermon 124.1",
    # Elijah sent to widow at Zarephath (1 Kgs 17:9)
    "caesarius-of-arles.1Kgs.17.9.unknown": "Sermon 124.2",
    # Widow gathering two sticks / cross typology (1 Kgs 17:12)
    "caesarius-of-arles.1Kgs.17.12.unknown": "Sermon 124.3",
    # Widow's son revived / Trinity and baptism typology (1 Kgs 17:22)
    "caesarius-of-arles.1Kgs.17.22.unknown": "Sermon 124.4",
    # Cloud like a man's foot / sevenfold Spirit (1 Kgs 18:44)
    "caesarius-of-arles.1Kgs.18.44.unknown": "Sermon 124.5",
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
    print(f"  (7 entries intentionally left blank -- MEDIUM or LOW confidence)")
    print(f"    Rev.5.2.unknown, Rev.5.3.unknown -- MEDIUM (Homily 4 likely but unverified)")
    print(f"    Gen.25.23.unknown -- MEDIUM (Sermon 86.1 likely but unverified)")
    print(f"    Jonah.3.6.unknown, Jonah.3.7.unknown -- MEDIUM (Sermon 133 section unknown)")
    print(f"    Col.4.2.unknown -- LOW (no identifying information)")
    print(f"    2Thess.1.8.unknown -- LOW (possibly misattributed; Armageddon ref)")

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
             "data/church-fathers/caesarius-of-arles.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 5, f"Expected 5 patch entries, got {len(PATCH)}"
    main()
