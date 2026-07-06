"""
Patch source_title for Tertullian's 22 blank entries (20 resolved here).

Confidence tiers (per entry in PATCH dict below):
  HIGH -- explicit attribution clue in quote text (inline citation bracket), adjacent
          block with a matching primary-source-verified source_title, or confirmed
          against newadvent.org by direct fetch.

Only HIGH-confidence entries are included.  2 entries remain blank:

  tertullian.Gen.1.28.unknown  -- Quote contains TWO inline citations from different
    works: "[On the Resurrection of the Flesh 45]" and "[On Exortation to Chastity 6]".
    Multi-source block; no single source_title can be assigned reliably.

  tertullian.Jonah.3.9.unknown -- No inline citation.  Content (METANOIA / divine
    repentance as "change of mind") is consistent with Against Marcion Book II ch.24,
    but chapter 24 onward is truncated on newadvent.org and could not be fetched during
    this session.  Downgraded to MEDIUM; left blank.

Spot-checked against primary source:
  - tertullian.Gen.1.1.unknown (newadvent.org/fathers/0313.htm ch.19+26) --
    confirmed: "arche / beginning / order of works" is Against Hermogenes 19;
    firmament/heaven arrangement discussion is Against Hermogenes 26
  - tertullian.Gen.1.6.unknown (newadvent.org/fathers/0321.htm ch.3) --
    confirmed: "waters...suspension of the celestial firmament" / "baptism gives life"
  - tertullian.Gen.2.17.unknown (newadvent.org/fathers/03122.htm ch.4) --
    confirmed: "most benignant act of His thus to point out the issues of transgression"
  - tertullian.Mark.1.18.unknown (newadvent.org/fathers/0302.htm ch.12) --
    confirmed: "Do you hesitate about arts, and trades...for the sake of children and
    parents?" / James and John / Matthew at tollbooth
  - tertullian.Matt.6.12.unknown (newadvent.org/fathers/0322.htm ch.7) --
    confirmed: "addressing His clemency" / debt parable / forgive seventy-seven times
  - tertullian.Col.1.6.unknown -- near-verbatim duplicate of tertullian.Col.1.5
    .against-marcion-book-v (already source_title=Against Marcion Book V), with
    additional preamble; same passage, same work.

Run twice to verify idempotency.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "tertullian.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # ---- Against Hermogenes ----
    # Inline citation "[Against Hermogenes 19]" and "[Against Hermagenes 26]"
    # Confirmed: ch.19 discusses Gen 1:1 / "arche" meaning;
    # ch.26 discusses creation narrative method (newadvent.org/fathers/0313.htm)
    "tertullian.Gen.1.1.unknown": "Against Hermogenes",

    # Inline citation "[Against Hermagenes 29]"
    "tertullian.Gen.1.9.unknown": "Against Hermogenes",

    # Inline citation "[Against Hermagenes 29]"
    "tertullian.Gen.1.10.unknown": "Against Hermogenes",

    # Inline citation "[Against Hermagenes 22]"
    "tertullian.Gen.1.12.unknown": "Against Hermogenes",

    # Inline citation "[Against Hermagenes 22]"
    "tertullian.Gen.1.20.unknown": "Against Hermogenes",

    # Inline citation "[Against Hermagenes 12]"
    "tertullian.Gen.1.22.unknown": "Against Hermogenes",

    # Inline citation "[Against Hermogenes 3]"
    "tertullian.Gen.2.15.unknown": "Against Hermogenes",

    # ---- On Baptism ----
    # Inline citation "[On Baptism 3]"
    # Confirmed: ch.3 discusses waters / firmament / baptism gives life
    # (newadvent.org/fathers/0321.htm)
    "tertullian.Gen.1.6.unknown": "On Baptism",

    # ---- Against Marcion Book V ----
    # Inline citation "[Against Marcion 5.6]"
    "tertullian.Gen.1.13.unknown": "Against Marcion Book V",

    # Near-verbatim duplicate of tertullian.Col.1.5.against-marcion-book-v
    # (same passage with extra preamble); same work confirmed
    "tertullian.Col.1.6.unknown": "Against Marcion Book V",

    # ---- Against Praxeas ----
    # Inline citation "[Against Praxeas 12]"
    "tertullian.Gen.1.27.unknown": "Against Praxeas",

    # ---- Against Marcion Book II ----
    # Inline citation "[Against Marcion 2.4]"
    # Confirmed: ch.4 contains "most benignant act of His thus to point out the issues
    # of transgression" (newadvent.org/fathers/03122.htm)
    "tertullian.Gen.2.17.unknown": "Against Marcion Book II",

    # Inline citation "[Against Marcion 2.11]"
    "tertullian.Gen.3.16.unknown": "Against Marcion Book II",

    # Inline citation "[Agaist Marcion 2.11]" (typo in source; same reference)
    "tertullian.Gen.3.17.unknown": "Against Marcion Book II",

    # ---- A Treatise on the Soul ----
    # Inline citation "[Treatise on the Soul 43]"
    "tertullian.Gen.2.21.unknown": "A Treatise on the Soul",

    # ---- On Exhortation to Chastity ----
    # Inline citation "[Exortation to Chastity 5]"
    "tertullian.Gen.2.24.unknown": "On Exhortation to Chastity",

    # ---- On the Apparel of Women Book I ----
    # Inline citation "[On the Apparel of Women 1.3]" at the end of the quote
    "tertullian.Ezra.6.7.unknown": "On the Apparel of Women Book I",

    # ---- On Prayer ----
    # Citation "(Prayer Chapter 17)" at the end of the quote
    "tertullian.Jonah.2.2.unknown": "On Prayer",

    # Surrounded by "On Prayer" entries (Matt.6.11, Matt.6.13, Matt.6.14, Matt.6.16);
    # content discusses "forgive us our trespasses" / debt parable / seventy-seven times.
    # Confirmed: ch.7 of On Prayer matches (newadvent.org/fathers/0322.htm)
    "tertullian.Matt.6.12.unknown": "On Prayer",

    # ---- On Idolatry ----
    # Confirmed: On Idolatry ch.12 contains "Do you hesitate about arts, and trades...
    # for the sake of children and parents?" / James and John / Matthew at tollbooth
    # (newadvent.org/fathers/0302.htm ch.12)
    "tertullian.Mark.1.18.unknown": "On Idolatry",
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

    # Build lookup
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
             "data/church-fathers/tertullian.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 20, f"Expected 20 patch entries, got {len(PATCH)}"
    main()
