# standards: author id slug
"""
Patch source_title for Eusebius of Caesarea's 21 blank entries (16 resolved here).

Confidence tiers (per entry in PATCH dict below):
  HIGH -- confirmed against primary source (NewAdvent, tertullian.org, explicit inline
          citation in the quote text), or explicit attribution label inside the quote.

Only HIGH-confidence entries are included.  5 entries remain blank:

  eusebius-of-caesarea.Acts.1.8.unknown -- 16-word quote only; no citation signal;
    adjacent entries span multiple works (Church History, Proof of the Gospel); single
    assignment would be speculation. Downgraded to LOW.

  eusebius-of-caesarea.Col.2.16.unknown -- Typological discussion of Mosaic law as
    shadow. Content matches Proof of the Gospel style but no inline citation and not
    located in checked books (PotG 1, 2, 3, 5). Single-signal inference only;
    downgraded to MEDIUM.

  eusebius-of-caesarea.Luke.12.8.unknown -- About the Only-Begotten bearing witness at
    divine judgment / "he that denies me before men, shall be denied before the Angels of
    God". Checked Theophania Books 3, 4, 5 and Proof of the Gospel Books 3, 4, 10 --
    passage not located. Downgraded to MEDIUM.

  eusebius-of-caesarea.Luke.21.34.unknown -- "Watch you therefore, and pray always, that
    you may be accounted worthy to escape". Checked Theophania Books 3, 4, 5 -- not
    located. Downgraded to MEDIUM.

  eusebius-of-caesarea.Mark.1.16.unknown -- About God choosing lowly fishermen; adjacent
    to Mark.1.17 (Proof of the Gospel). Thematic match in Theophania 5.46, but quote text
    not confirmed in that passage, and no explicit work citation in the quote. Downgraded
    to MEDIUM.

Spot-checked against primary source:
  - eusebius-of-caesarea.Luke.22.7.unknown (tertullian.org/fathers/eusebius_on_easter.htm
    Section 9) -- confirmed: "on the fifth day of the week, was reclining at table with
    his disciples" / "he himself, before he suffered, ate the Pascha...not with the Jews"
  - eusebius-of-caesarea.Luke.24.45.unknown (tertullian.org/fathers/eusebius_theophania_
    05book4.htm Sections 8-9) -- confirmed: "repentance and remission of sins should be
    preached in His name among all nations" + "Ask of me, and I will give thee the heathen
    for thine inheritance" + "ye are the witnesses of these things" -- all three phrases
    from the TOML quote present in Theophania 4.8-9
  - eusebius-of-caesarea.Josh.5.14.unknown -- explicit in-quote citation
    "Proof of the Gospel 5.19"; no external check needed

Run twice to verify idempotency.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "eusebius-of-caesarea.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {

    # ---- Ecclesiastical History ----

    # Explicit inline tag "[quoting Irenaeus, Church History 5.8.15]" -- Eusebius
    # quotes Irenaeus at that precise location in his own Church History.
    "eusebius-of-caesarea.Ezra.6.7.unknown": "Ecclesiastical History 5.8.15",

    # Explicit inline citation "Eccles. Hist., 1, 8:" at start of quote; confirmed:
    # EH 1.8 covers Herod's punishment, his disease, and the slaughter of infants.
    "eusebius-of-caesarea.Matt.2.20.unknown": "Ecclesiastical History 1.8",

    # Confirmed: statue of the woman with an issue of blood at Paneas is described in
    # Ecclesiastical History Book VII, Chapter 18 (NewAdvent.org/fathers/250107.htm).
    "eusebius-of-caesarea.Luke.8.40.unknown": "Ecclesiastical History 7.18",

    # ---- Church History (Book III, Chapter 39) ----

    # Explicit inline tag "(Church History 3.39.13)" at end of quote.
    # Adjacent entry Rev.20.4-6 uses "Church History (Book III), Chapter 39,
    # Sections 12-13" -- same chapter, section 13 specifically.
    "eusebius-of-caesarea.Rev.20.2.unknown": "Church History (Book III), Chapter 39, Section 13",

    # ---- Proof of the Gospel ----

    # Quote ends with explicit citation: - "Proof of the Gospel 5.19"
    "eusebius-of-caesarea.Josh.5.14.unknown": "Proof of the Gospel 5.19",

    # Quote ends with explicit label: "Proof of the Gospel"
    # (no section number given in source; no section appended)
    "eusebius-of-caesarea.Mark.15.24.unknown": "Proof of the Gospel",

    # Quote ends with explicit label: "The Proof of the Gospel"
    # Content (disciples' inability to preach to Romans, Egyptians, Persians, Armenians,
    # Chaldeans, Scythians, Indians) also confirmed in Theophania 5.46, suggesting
    # parallel passages; explicit "Proof of the Gospel" label in source takes precedence.
    "eusebius-of-caesarea.Mark.1.17.unknown": "Proof of the Gospel",

    # ---- On the Pascha ----

    # About whether Christ kept Passover at the same time as the Jews, and that
    # "our Lord on the first day of unleavened bread, that is, on the fifth day of the
    # week, kept the Passover with His disciples."
    # Confirmed: tertullian.org/fathers/eusebius_on_easter.htm Section 9 contains
    # "on the fifth day of the week, was reclining at table with his disciples" and the
    # argument that Christ celebrated Passover before the Jews' Preparation Day.
    "eusebius-of-caesarea.Luke.22.7.unknown": "On the Pascha",

    # ---- Theophania ----

    # About repentance and remission of sins preached to all nations + Ps 2:8 ("Ask of
    # me, and I will give you the heathen") + "you are witnesses of these things...of
    # My death and resurrection."
    # Confirmed: tertullian.org/fathers/eusebius_theophania_05book4.htm Sections 8-9
    # contains all three key phrases from this TOML quote.
    "eusebius-of-caesarea.Luke.24.45.unknown": "Theophania",

    # ---- Concerning the Star ----

    # TOML heading: "CONCERNING THE STAR; SHOWING HOW AND THROUGH WHAT THE MAGI
    # RECOGNIZED THE STAR, AND THAT JOSEPH DID NOT TAKE MARY AS HIS WIFE."
    # Confirmed: tertullian.org/fathers/eusebius_star.htm is exactly this work;
    # opening words match ("I WILL write and inform thee, our dear brother...").
    "eusebius-of-caesarea.Matt.2.2.unknown": "Concerning the Star",

    # ---- Commentary on Psalms ----

    # All six entries are verse-by-verse commentary on Psalm 52 (LXX Ps 51).
    # Source confirmed: tertullian.org has eusebius_commentary_on_psalm_51.htm
    # covering exactly these verses. Section references follow the existing dataset
    # convention: "Commentary on Psalms [psalm]:[verse]".

    # Introductory commentary on the superscription / setting of Psalm 52 (the
    # occasion of Doeg the Idumaean reporting David's visit to Abimelech).
    "eusebius-of-caesarea.Ps.52.1.unknown": "Commentary on Psalms 52:1",

    # Preamble on chronological arrangement of Psalms 51-70 relative to Psalm 50;
    # establishes that Psalm 52 was spoken while Saul was still alive.
    "eusebius-of-caesarea.Ps.52.2.unknown": "Commentary on Psalms 52:2",

    # Short note: "So that the righteous, when they see it, will be afraid and will
    # mock him" -- commentary on the verse about the righteous observing judgment.
    "eusebius-of-caesarea.Ps.52.5.unknown": "Commentary on Psalms 52:5",

    # Commentary on verse 7: Doeg as a bitter root cast out of the tabernacle of God;
    # the "farmer of souls" (God) plucks out those powerful in wickedness.
    "eusebius-of-caesarea.Ps.52.7.unknown": "Commentary on Psalms 52:7",

    # Commentary on verse 8: "But I am like a fruitful olive tree in the house of
    # God" -- David as the olive tree image; discussion of the house of God as the
    # pious way of life rather than a physical building.
    "eusebius-of-caesarea.Ps.52.8.unknown": "Commentary on Psalms 52:8",

    # Commentary on verse 9: David's hope in the mercy of God; the wicked face
    # uprooting; David attributes all goodness to God as its source.
    "eusebius-of-caesarea.Ps.52.9.unknown": "Commentary on Psalms 52:9",
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
             "data/church-fathers/eusebius-of-caesarea.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 16, f"Expected 16 patch entries, got {len(PATCH)}"
    main()
