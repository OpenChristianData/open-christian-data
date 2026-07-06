# standards: author id slug
"""Patch missing source_title for nerses-of-lambron church_fathers entries.

0 of 10 entries are patched. All 10 are left blank -- MEDIUM confidence only.

--- Background ---

All 10 entries are commentary on the Book of Revelation (Rev 1:1, 1:4, 1:5,
1:6 x3, 5:1, 5:4, 20:2, 20:8). The TOML files in:
  raw/Commentaries-Database/Nerses of Lambron/
contain NO source_url and NO embedded source attribution. The metadata.toml
only records default_year=1198 and a Wikipedia link.

The historicalchristian.faith website (which renders the database) also shows
NO "Source:" link for any Nerses of Lambron entry -- unlike every other author
in the Revelation chapter whose sources are documented (Bede, Alcuin, Victorinus,
Andreas of Caesarea, Oecumenius, etc.).

--- Candidate work identified ---

The only known English-language Revelation commentary by Nerses of Lambron is:

  "Commentary on the Revelation of Saint John"
  Author: Nerses of Lambron, Saint (1153-1198)
  Translator: Robert W. Thomson
  Publisher: Peeters (Leuven / Dudley, MA), 2007
  Pages: 225
  Series: Hebrew University Armenian studies -- 9
  ISBN-13: 9789042918665
  Open Library: /works/OL5883463W

This is the only work catalogued under Nerses of Lambron relating to Revelation
in Open Library and WorldCat. It covers the full text of Revelation (225 pages),
consistent with commentary spanning Rev 1, 5, and 20.

--- Confidence ratings ---

MEDIUM (all 10 entries): The Thomson 2007 "Commentary on the Revelation of
  Saint John" is the only English-language Revelation commentary by Nerses in
  existence and almost certainly the source text for the HCF database entries.

  However, this is MEDIUM (not HIGH) for two reasons:
  1. Wikipedia itself flags the Revelation commentary attribution as uncertain:
     "Some writers ascribe to him an Armenian version of a commentary of
     Andreas of Caesarea on the Apocalypse." The authorship is disputed.
  2. The HCF database shows no source URL -- an unusual absence that may
     indicate the database contributor was unsure of the source.
  3. The Thomson 2007 book is not digitised on archive.org, CCEL, or Google
     Books (preview unavailable), so quote-level verification was not possible.

  Per curation rules, MEDIUM entries are not committed. These entries are left
  blank until someone with access to Thomson 2007 (Peeters, ISBN 9789042918665)
  can verify that the quote text in the TOML files matches pages in that book.

--- How to verify and complete this patch ---

To elevate all 10 entries to HIGH confidence:
1. Obtain Thomson 2007 (Peeters, ISBN 9789042918665) from a university library.
2. For each entry, check that the opening words of the TOML quote appear on
   a page in the Thomson translation.
3. If confirmed, add the entry_id -> "Commentary on the Revelation of Saint John"
   to the PATCH dict below and update the assert.

--- Spot-checks attempted ---

  Spot-checked against primary source:
    - nerses-of-lambron.Rev.1.1.unknown
      (Open Library OL5883463W -- Thomson 2007, Peeters, ISBN 9789042918665)
      SKIPPED: book not digitised; no preview available on Google Books, CCEL,
      or archive.org. MEDIUM confidence -- left blank.

    - nerses-of-lambron.Rev.1.5.unknown
      (Open Library OL5883463W -- Thomson 2007, same book)
      SKIPPED: same reason as above. MEDIUM confidence -- left blank.

    - nerses-of-lambron.Rev.20.8.unknown
      (Open Library OL5883463W -- Thomson 2007, same book)
      SKIPPED: same reason as above. MEDIUM confidence -- left blank.

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "nerses-of-lambron.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
#
# All 10 entries are MEDIUM confidence -- left blank pending primary source
# verification of Thomson 2007 (Peeters, ISBN 9789042918665).
#
# To add entries once verified: uncomment and add lines like:
#   "nerses-of-lambron.Rev.1.1.unknown": "Commentary on the Revelation of Saint John",
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # No HIGH-confidence entries to patch at this time.
    # See docstring above for candidate work and verification steps.
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
    print("  (all 10 entries left blank -- MEDIUM confidence only)")
    print("  Candidate: 'Commentary on the Revelation of Saint John'")
    print("  (Thomson 2007, Peeters, ISBN 9789042918665)")
    print("  Verify quote text against primary source before committing.")

    # No file changes when PATCH is empty -- skip write and validate
    if not PATCH:
        print("\nNo entries to patch -- skipping file write and validation.")
        return

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
             "data/church-fathers/nerses-of-lambron.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 0, f"Expected 0 patch entries, got {len(PATCH)}"
    main()
