# standards: author id slug
"""
Patch source_title for pope-urban-i (all 9 entries, all HIGH confidence).

--- Background ---

Pope Urban I (bishop of Rome, c. 222-230 AD) has one surviving text in the
patristic record: a single epistle in ANF Volume VIII, "The Decretals". This
epistle is a Pseudo-Isidorian forgery (ninth century) addressed to all Christians.

Primary source: Ante-Nicene Fathers, Vol. 8 -- The Decretals, Epistle of Pope Urban First
  https://www.tertullian.org/fathers2/ANF-08/anf08-123.htm
  CCEL mirror: https://www.ccel.org/ccel/schaff/anf08.viii.v.html

The epistle full title is: "The Epistle of Pope Urban First to All Christians"
It is a single continuous letter with seven numbered sections (I-VII).
All 9 entries in pope-urban-i.json are confirmed as quotes from this single epistle.

--- Title format ---

Title format follows the identical convention established for the adjacent popes
in this collection. See:
  build/scripts/patch_source_title_pope-anterus.py

Anterus (single epistle) uses: "Decretals, Epistle of Pope Anterus"
Urban I (single epistle)  uses: "Decretals, Epistle of Pope Urban First"

The ANF08 TOC labels this text "The Epistle of Pope Urban First." (singular).

--- Confidence ratings ---

All 9 entries: HIGH
  Verified by fetching the complete epistle text from
  https://www.tertullian.org/fathers2/ANF-08/anf08-123.htm
  and confirming each TOML quote appears verbatim (or as a recognised partial
  excerpt) in the body of the epistle. There is only one surviving Urban I text,
  so no alternative work is possible for any of these entries.

--- Spot-checked against primary source ---

  - pope-urban-i.1Cor.2.14.unknown
    (https://www.tertullian.org/fathers2/ANF-08/anf08-123.htm, section VII)
    Quote: "We receive of the Holy Spirit in order that we may be made spiritual;
    for the natural man receiveth not the things of the Spirit of God."
    Full text confirmed: identical wording in section VII on episcopal hand-imposition.

  - pope-urban-i.1Cor.5.5.unknown
    (https://www.tertullian.org/fathers2/ANF-08/anf08-123.htm, section II-III)
    Quote: "And if any one do so, then, after the sharp vengeance which is due to
    such a crime, and which is justly to be carried out against the sacrilegious,
    let him be condemned to perpetual infamy, and east into prison or consigned to
    life-long exile. For, according to the apostle,"
    Full text confirmed: wording matches section on church property violators.
    Note: "east into prison" is a period typo for "cast into prison" -- in source text.

  - pope-urban-i.Col.3.2.unknown
    (https://www.tertullian.org/fathers2/ANF-08/anf08-123.htm, section VII)
    Quote: ") rather things above, and not things on the earth;"
    Full text confirmed: excerpt ends at mid-sentence; precedes "according to the
    apostle, we may discern rather things above, and not things on the earth." The
    leading ")" is a truncation artifact in the source TOML, not a different work.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "pope-urban-i.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# All 9 entries are from the single "Epistle of Pope Urban First" in ANF08 Decretals.
# Verified against: https://www.tertullian.org/fathers2/ANF-08/anf08-123.htm
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    "pope-urban-i.1Cor.2.14.unknown": "Decretals, Epistle of Pope Urban First",
    "pope-urban-i.1Cor.3.19.unknown": "Decretals, Epistle of Pope Urban First",
    "pope-urban-i.1Cor.5.5.unknown": "Decretals, Epistle of Pope Urban First",
    "pope-urban-i.1Tim.5.6.unknown": "Decretals, Epistle of Pope Urban First",
    "pope-urban-i.1Tim.6.10.unknown": "Decretals, Epistle of Pope Urban First",
    "pope-urban-i.Acts.4.32.unknown": "Decretals, Epistle of Pope Urban First",
    "pope-urban-i.Acts.5.1.unknown": "Decretals, Epistle of Pope Urban First",
    "pope-urban-i.Col.3.2.unknown": "Decretals, Epistle of Pope Urban First",
    "pope-urban-i.John.20.22.unknown": "Decretals, Epistle of Pope Urban First",
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
             "data/church-fathers/pope-urban-i.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 9, f"Expected 9 patch entries, got {len(PATCH)}"
    main()
