# standards: author id slug
"""
Patch source_title for pope-anterus (all 9 entries, all HIGH confidence).

--- Background ---

Pope Anterus (bishop of Rome, Nov 235 - Jan 236 AD) has one surviving text in the
patristic record: a single epistle in ANF Volume VIII, "The Decretals". This epistle
is a Pseudo-Isidorian forgery (ninth century) addressed to bishops in the provinces
of Boetica and Toletana on the subject of the transfer of bishops between sees.

Primary source: Ante-Nicene Fathers, Vol. 8 -- The Decretals, Epistle of Pope Anterus
  https://www.tertullian.org/fathers2/ANF-08/anf08-128.htm
  Also available at:
  https://www.wisdomlib.org/christianity/book/ante-nicene-fathers/d/doc1574099.html

The epistle is a single continuous letter with NO internal section numbers.
All 9 entries in pope-anterus.json are confirmed as quotes from this single epistle.

--- Title format ---

Title format follows the identical convention already established for the adjacent
pope in this collection: Fabian of Rome. See:
  build/scripts/patch_source_title_fabian-of-rome.py

Fabian (multiple epistles) uses: "Decretals, Epistles of Pope Fabian, [epistle name]"
Anterus (single epistle, no sub-title needed) uses: "Decretals, Epistle of Pope Anterus"

The ANF08 TOC labels the Anterus text "Pope Anterus: The Epistle." (singular).
The full heading on tertullian.org/wisdomlib reads: "The Epistle of Pope Anterus"
with subtitle: "On the translation of bishops and of episcopal seats."

--- Confidence ratings ---

All 9 entries: HIGH
  Verified by fetching the complete epistle text from tertullian.org ANF-08/anf08-128.htm
  and confirming each TOML quote appears verbatim (or as a recognized partial excerpt)
  in the body of the epistle. There is only one surviving Anterus text, so no
  alternative work is possible for any of these entries.

--- Spot-checked against primary source ---

  - pope-anterus.2Tim.3.8.unknown (https://www.tertullian.org/fathers2/ANF-08/anf08-128.htm)
    Quote: "Not lawful, and what is not lawful is lawful. Even as Jannes and Mambres"
    In full text: "What is lawful is with them not lawful, and what is not lawful is
    lawful. Even as Jannes and Mambres resisted the truth..." -- confirmed. TOML quote
    is a truncated excerpt from mid-sentence; text identity confirmed.

  - pope-anterus.2Thess.3.4.unknown (https://www.tertullian.org/fathers2/ANF-08/anf08-128.htm)
    Quote: "Confidence in the Lord touching you, brethren, that ye both do and will do
    the things which we command you."
    In full text: "And we have confidence in the Lord touching you, brethren, that ye
    both do and will do the things which we command you." -- confirmed (TOML omits
    opening "And we have").

  - pope-anterus.Eph.4.29.unknown (https://www.tertullian.org/fathers2/ANF-08/anf08-128.htm)
    Quote: "And be ye kind one to another, tender-hearted, forgiving one another, even
    as God in Christ hath forgiven you."
    In full text: "And be ye kind one to another, tender-hearted, forgiving one another,
    even as God in Christ hath forgiven you." -- confirmed verbatim.
    Note: The anchor_ref "Ephesians 4:29" appears to be a pre-existing tagging error
    (the quoted text is Eph 4:32) -- this is a data quality issue in the source DB,
    not a source_title issue. Left as-is; source_title assignment is correct.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "pope-anterus.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# All 9 entries are from the single "Epistle of Pope Anterus" in ANF08 Decretals.
# Verified against: https://www.tertullian.org/fathers2/ANF-08/anf08-128.htm
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    "pope-anterus.1Cor.15.32.unknown": "Decretals, Epistle of Pope Anterus",
    "pope-anterus.2Thess.2.15.unknown": "Decretals, Epistle of Pope Anterus",
    "pope-anterus.2Thess.3.1.unknown": "Decretals, Epistle of Pope Anterus",
    "pope-anterus.2Thess.3.4.unknown": "Decretals, Epistle of Pope Anterus",
    "pope-anterus.2Tim.3.5.unknown": "Decretals, Epistle of Pope Anterus",
    "pope-anterus.2Tim.3.8.unknown": "Decretals, Epistle of Pope Anterus",
    "pope-anterus.Eph.4.29.unknown": "Decretals, Epistle of Pope Anterus",
    "pope-anterus.Eph.5.1.unknown": "Decretals, Epistle of Pope Anterus",
    "pope-anterus.John.8.44.unknown": "Decretals, Epistle of Pope Anterus",
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
             "data/church-fathers/pope-anterus.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 9, f"Expected 9 patch entries, got {len(PATCH)}"
    main()
