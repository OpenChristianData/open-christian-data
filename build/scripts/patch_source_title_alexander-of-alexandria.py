# standards: author id slug
"""Patch missing source_title for alexander-of-alexandria church_fathers entries.

12 of 13 missing entries are patched here with HIGH confidence.
1 entry left blank (LOW confidence -- truncated fragment, ambiguous section).

--- Background ---

Alexander of Alexandria (bishop c.312-328 AD) is represented by 33 entries,
all from his "Epistles on the Arian Heresy" (ANF06), available at NewAdvent:
  https://www.newadvent.org/fathers/0622.htm

The work contains 6 epistles. The two used in this dataset are:
  Epistle 1: "To Alexander, Bishop of the City of Constantinople" (14 sections)
  Epistle 2: "Epistle Catholic" (6 sections)

13 TOML files had no source_url or source_title. No source_url was present in any
of the 13 missing-title files. The full ANF06 text was fetched from NewAdvent and
each quote was located in its section by searching for the key phrase.

--- Evidence for source_title assignment ---

Full page text was fetched from https://www.newadvent.org/fathers/0622.htm and
each quote was matched to its section by scanning the plain-text paragraph content.
All 12 patched entries matched exactly one section with no ambiguity. See
section-by-section breakdown below.

Title format matches the existing curated entries in the same file:
  - Epistle 1 sections: "Epistles on the Arian Heresy, I.N"
    (matching existing "Epistles on the Arian Heresy, I.9" and "I.12")
  - Epistle 2 (Catholic) sections: "Epistles on the Arian Heresy, Epistle Catholic N"
    (matching existing "Epistle Catholic 3" and "Epistle Catholic 4")
  - Exception: Ep.1 Sec.8 (Rom.8.32) uses "Epistles on the Arian Heresy 1:8"
    to match the existing TOML-sourced entry for the same section in the file.

--- Section assignments (all verified against NewAdvent primary source) ---

Epistle 1 (To Alexander, Bishop of the City of Constantinople):
  Sec. 5 -- 1Cor.2.9: "For if the knowledge of many other things..."
  Sec. 6 -- Col.1.16: "But by Him also were all things created..."
  Sec. 7 -- 2Cor.6.14: "E can the truth itself and God the Word receive?
              ...And the apostle says, on this place, What communion hath light
              with darkness?" (full Sec.7 passage matched)
  Sec. 8 -- Rom.8.32: "Paul has declared, who thus speaks of God: Who spared
              not His own Son..." (Sec.8 opens with this exact phrase)
  Sec.11 -- 1John.5.1: "As in a certain place the Lord Himself testified,
              saying, Every one that loveth Him that begat..." (Sec.11, final sentence)
  Sec.13 -- Gal.1.8: "To these Arius and Achilles opposing themselves..."
  Sec.13 -- 1Tim.6.3: "And also, If any man teach otherwise, and consent not..."
  Sec.13 -- 2Tim.3.4: "They go about the cities, attempting nothing else..."
              (all three are consecutive citations within Sec.13)

Epistle 2 (Epistle Catholic):
  Sec. 3 -- Heb.11.10: "Who hath induced them to say, that for our sakes He was made..."
  Sec. 3 -- Heb.13.8: "For even though one saying may refer to the Father Himself..."
  Sec. 5 -- 2Tim.2.17: "although we grieve at the destruction of these men..."
  Sec. 5 -- Luke.21.8: "concerning these very men, warnings are not wanting to us..."

--- Left blank (LOW confidence) ---

  Heb.1.3 (entry_id: alexander-of-alexandria.Heb.1.3.unknown):
    Quote is a truncated fragment: 'Person.".\nand, "From the womb, before the
    morning have I begotten Thee?"' The opening word "Person." is the tail of
    Heb.1:3 which appears in Epistle 1 Sec.12 ("the express image of His Father's
    person"), but the "From the womb" citation (Ps.110:3) appears only in Sec.8 of
    Epistle 1 and Sec.3 of the Epistle Catholic -- not Sec.12. The fragment is too
    short and ambiguous to assign with confidence.

--- Confidence ratings ---

HIGH (12 entries): All assignments verified against the ANF06 primary source text
  at https://www.newadvent.org/fathers/0622.htm -- the key phrase from each TOML
  quote was found exactly once in the identified section.

LOW (1 entry, left blank): Heb.1.3 -- truncated fragment spanning two potential
  source sections.

--- Spot-checked against primary source ---

  - alexander-of-alexandria.1Cor.2.9.unknown (Ep.1 Sec.5)
    URL: https://www.newadvent.org/fathers/0622.htm
    Confirmed: Section 5 text reads "For if the knowledge of many other things that
    are incomparably inferior to this, are hidden from human comprehension, such as in
    the apostle Paul, Eye has not seen, nor ear heard, neither have entered into the
    heart of man, the things which God has prepared for them that love Him." -- exact
    match to TOML quote. HIGH. confirmed

  - alexander-of-alexandria.2Cor.6.14.unknown (Ep.1 Sec.7)
    URL: https://www.newadvent.org/fathers/0622.htm
    Confirmed: Section 7 text reads "What increase can the truth itself and God the
    Word receive? In what respect can the life and the true light be made better? And
    if this be so, how much more unnatural is it that wisdom should ever be capable of
    folly; that the power of God should be con-joined with infirmity; that reason
    should be obscured by unreason; or that darkness should be mixed up with the true
    light? And the apostle says, on this place, What communion has light with
    darkness? And what concord has Christ with Belial?" -- the TOML quote opens with
    "E can the truth itself and God the Word receive?" (truncated "What" -> "E" is
    a data artefact) and continues with the same passage. HIGH. confirmed

  - alexander-of-alexandria.2Tim.2.17.unknown (Ep. Catholic Sec.5)
    URL: https://www.newadvent.org/fathers/0622.htm
    Confirmed: Epistle Catholic Section 5 text reads "And indeed, although we grieve
    at the destruction of these men, especially that after having once learned the
    doctrine of the Church, they have now gone back; yet we do not wonder at it; for
    this very thing Hymenaeus and Philetus suffered, 2 Timothy 2:17" -- exact match
    to TOML quote. HIGH. confirmed

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "alexander-of-alexandria.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # --- Epistle 1 (To Alexander, Bishop of the City of Constantinople) ---
    # URL: https://www.newadvent.org/fathers/0622.htm
    # Section 5: on the incomprehensible generation of the Son (cites 1 Cor 2:9)
    "alexander-of-alexandria.1Cor.2.9.unknown": "Epistles on the Arian Heresy, I.5",
    # Section 6: on Christ as maker of all things (cites Col 1:16-17)
    "alexander-of-alexandria.Col.1.16.unknown": "Epistles on the Arian Heresy, I.6",
    # Section 7: on the immutability of the Son (cites 2 Cor 6:14)
    "alexander-of-alexandria.2Cor.6.14.unknown": "Epistles on the Arian Heresy, I.7",
    # Section 8: on the natural Sonship of Christ (cites Rom 8:32)
    # Uses colon notation to match the existing Sec.8 entry for this epistle
    "alexander-of-alexandria.Rom.8.32.unknown": "Epistles on the Arian Heresy 1:8",
    # Section 11: on begetting vs adoption; rebuts two-unbegottens charge (cites John 5:1)
    "alexander-of-alexandria.1John.5.1.unknown": "Epistles on the Arian Heresy, I.11",
    # Section 13: concluding condemnation of Arius and Achilles (cites Gal 1:8, 1 Tim 6:3, 2 Tim 3:4)
    "alexander-of-alexandria.Gal.1.8.unknown": "Epistles on the Arian Heresy, I.13",
    "alexander-of-alexandria.1Tim.6.3.unknown": "Epistles on the Arian Heresy, I.13",
    "alexander-of-alexandria.2Tim.3.4.unknown": "Epistles on the Arian Heresy, I.13",
    # --- Epistle 2 (Epistle Catholic) ---
    # URL: https://www.newadvent.org/fathers/0622.htm
    # Section 3: refutation of Arian propositions; rhetorical questions (cites Heb 11:10, Heb 13:8)
    "alexander-of-alexandria.Heb.11.10.unknown": "Epistles on the Arian Heresy, Epistle Catholic 3",
    "alexander-of-alexandria.Heb.13.8.unknown": "Epistles on the Arian Heresy, Epistle Catholic 3",
    # Section 5: on the excommunication of heretics (cites 2 Tim 2:17, Luke 21:8)
    "alexander-of-alexandria.2Tim.2.17.unknown": "Epistles on the Arian Heresy, Epistle Catholic 5",
    "alexander-of-alexandria.Luke.21.8.unknown": "Epistles on the Arian Heresy, Epistle Catholic 5",
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
             "data/church-fathers/alexander-of-alexandria.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 12, f"Expected 12 patch entries, got {len(PATCH)}"
    main()
