# standards: author id slug
"""Patch missing source_title for fabian-of-rome church_fathers entries.

All 16 missing entries are patched here with HIGH confidence.
0 entries left blank.

--- Background ---

Fabian of Rome (pope 236-250 AD) is represented in the Commentaries Database
by 17 entries (one TOML file per verse reference). Only one entry had a
source_title set already (Eph.6.10, from Epistle 3 Part V "To Bishop Hilary, V").
The remaining 16 TOML files carried no source_url or source_title metadata --
just bare quotes.

Fabian's extant works are three spurious decretals/epistles in ANF08 (Schaff,
Ante-Nicene Fathers Vol. 8), all available at CCEL:

  Epistle 1: "To All the Ministers of the Church Catholic"
    URL: https://ccel.org/ccel/schaff/anf08.viii.viii.i.html
    (no subsections)

  Epistle 2: "To All the Bishops of the East"
    Part I: "That new chrism should be made every year..."
    Part II: "Of the right of bishops not to be accused or hurt by detraction"
    URL: https://ccel.org/ccel/schaff/anf08.viii.viii.ii.iii.html

  Epistle 3: "To Bishop Hilary"
    Parts I-V
    (Part V already curated as source_title for Eph.6.10)

--- Evidence for source_title assignment ---

The full XML of ANF08 was fetched from CCEL and every scripture reference was
located in its containing section div. Assignments were confirmed by:
1. Extracting the osisRef for each verse from the XML
2. Matching to the div3/div4 section ID
3. Cross-checking the surrounding plain-text against the TOML quote

All 16 entries map to exactly one epistle with no ambiguity except
1Cor.5.11 (see note below).

Note on 1Cor.5.11: This verse appears in BOTH Epistle 1 AND Epistle 2 Part II.
The TOML quote for fabian-of-rome.1Cor.5.11.unknown combines text from both
occurrences (first sentence = Epistle 1; second sentence = Epistle 2 Part II).
Assigned to Epistle 1 because the quote's opening words match Epistle 1
("In like manner keep yourselves separate from all those...").

Title format matches the existing curated entry:
  "Decretals, Epistles of Pope Fabian, To Bishop Hilary, V"

For Epistle 1 (no numbered subsections):
  "Decretals, Epistles of Pope Fabian, To All the Ministers of the Church Catholic"

For Epistle 2 Part II (section II of Epistle 2):
  "Decretals, Epistles of Pope Fabian, To All the Bishops of the East, II"

--- Confidence ratings ---

HIGH (16 entries): All assignments verified against primary source XML from CCEL
  (https://ccel.org/ccel/schaff/anf08.xml). Scripture references were located by
  osisRef in the XML and confirmed against the surrounding text.

MEDIUM / LOW: None -- all 16 entries patched.

--- Spot-checked against primary source ---

  - fabian-of-rome.1Pet.5.8.unknown
    URL: https://ccel.org/ccel/schaff/anf08.viii.viii.i.html
    Confirmed: "Furthermore, we desire you to know this, that in our times, as
    our sins embarrassed us, and that ancient enemy who always goeth about like
    a roaring lion, seeking whom he may devour" appears in Epistle 1
    (viii.viii.i) as the lead-in to footnote citing 1 Pet. v. 8.
    HIGH. confirmed

  - fabian-of-rome.Rom.13.2.unknown
    URL: https://ccel.org/ccel/schaff/anf08.viii.viii.ii.iii.html
    Confirmed: "For his other actings, however, he is rather to be borne with
    by his flock and those put under him, than accused or made the subject of
    public detraction; because when any offence is committed in these matters
    by those put under them, His ordinance is withstood who set them before him,
    as the apostle says, 'Whosoever resisteth the power, resisteth the ordinance
    of God.'" appears in Epistle 2 Part II (viii.viii.ii.iii), footnote citing
    Rom. xiii. 2.
    HIGH. confirmed

  - fabian-of-rome.1Cor.5.11.unknown
    URL: https://ccel.org/ccel/schaff/anf08.viii.viii.i.html
    Confirmed: "In like manner keep yourselves separate from all those of whom
    the apostle makes mention when he says, 'with such persons, no, not to eat'"
    is the Epistle 1 occurrence. The TOML quote's second sentence ("Those also
    are to be dealt with in like manner...") is from Epistle 2 Part II, but the
    opening words match Epistle 1 unambiguously.
    HIGH. confirmed (assigned to Epistle 1 as primary)

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "fabian-of-rome.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # --- Epistle 1: To All the Ministers of the Church Catholic ---
    # URL: https://ccel.org/ccel/schaff/anf08.viii.viii.i.html
    "fabian-of-rome.Rom.15.4.unknown": "Decretals, Epistles of Pope Fabian, To All the Ministers of the Church Catholic",
    "fabian-of-rome.1Cor.15.58.unknown": "Decretals, Epistles of Pope Fabian, To All the Ministers of the Church Catholic",
    "fabian-of-rome.1Cor.16.13.unknown": "Decretals, Epistles of Pope Fabian, To All the Ministers of the Church Catholic",
    "fabian-of-rome.1Pet.5.8.unknown": "Decretals, Epistles of Pope Fabian, To All the Ministers of the Church Catholic",
    "fabian-of-rome.1Tim.2.4.unknown": "Decretals, Epistles of Pope Fabian, To All the Ministers of the Church Catholic",
    "fabian-of-rome.1Cor.5.11.unknown": "Decretals, Epistles of Pope Fabian, To All the Ministers of the Church Catholic",
    "fabian-of-rome.Rom.1.32.unknown": "Decretals, Epistles of Pope Fabian, To All the Ministers of the Church Catholic",
    "fabian-of-rome.1Cor.15.33.unknown": "Decretals, Epistles of Pope Fabian, To All the Ministers of the Church Catholic",
    # --- Epistle 2 Part II: To All the Bishops of the East, II ---
    # URL: https://ccel.org/ccel/schaff/anf08.viii.viii.ii.iii.html
    "fabian-of-rome.Acts.4.32.unknown": "Decretals, Epistles of Pope Fabian, To All the Bishops of the East, II",
    "fabian-of-rome.Mark.12.31.unknown": "Decretals, Epistles of Pope Fabian, To All the Bishops of the East, II",
    "fabian-of-rome.Rom.13.10.unknown": "Decretals, Epistles of Pope Fabian, To All the Bishops of the East, II",
    "fabian-of-rome.John.13.35.unknown": "Decretals, Epistles of Pope Fabian, To All the Bishops of the East, II",
    "fabian-of-rome.1Cor.6.7.unknown": "Decretals, Epistles of Pope Fabian, To All the Bishops of the East, II",
    "fabian-of-rome.Luke.6.30.unknown": "Decretals, Epistles of Pope Fabian, To All the Bishops of the East, II",
    "fabian-of-rome.Gal.5.21.unknown": "Decretals, Epistles of Pope Fabian, To All the Bishops of the East, II",
    "fabian-of-rome.Rom.13.2.unknown": "Decretals, Epistles of Pope Fabian, To All the Bishops of the East, II",
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
             "data/church-fathers/fabian-of-rome.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 16, f"Expected 16 patch entries, got {len(PATCH)}"
    main()
