# standards: author id slug
"""
Patch source_title for callistus-i-of-rome (9 blank entries, all HIGH confidence).

--- Background ---

Pope Callistus I (bishop of Rome, c. 217-222 AD) has two surviving texts in the
patristic record in ANF Volume VIII, "The Decretals" (Pseudo-Isidorian forgeries,
ninth century): a First Epistle to Bishop Benedictus (anf08-120.htm) and a Second
Epistle to All the Bishops of Gaul (anf08-121.htm).

Primary source: Ante-Nicene Fathers, Vol. 8 -- The Decretals, The Second Epistle of
Pope Callistus to All the Bishops of Gaul:
  https://www.tertullian.org/fathers2/ANF-08/anf08-121.htm

All 9 blank entries are from The Second Epistle to All the Bishops of Gaul, which
contains 6 numbered sections (I-VI). The existing source_title entries in this file
already use the format "The Second Epistle to All the Bishops of Gaul [N]" for
section N (e.g. section 6 = "The Second Epistle to All the Bishops of Gaul 6").

Section assignments (confirmed by fetching the full epistle text):
  Section 1 -- Conspiracies against bishops (Rom 1:32)
  Section 2 -- Excommunicated persons and unbelievers (2Cor 6:14)
  Section 3 -- Parish boundaries, episcopal transfer, marriage analogy (Mark 10:44, Rom 7:2)
  Section 5 -- Witness requirements, mercy toward the fallen (Gal 6:1)
  Section 6 -- Restoration of priests after lapse; divine mercy (John 8:11,
               Rom 3:23, Rom 3:3, Rom 6:12)

--- Title format ---

Matches the section-specific convention already established in this file:
  "The Second Epistle to All the Bishops of Gaul [section_number]"

--- Confidence ratings ---

All 9 entries: HIGH
  Verified by fetching the complete epistle text from:
  https://www.tertullian.org/fathers2/ANF-08/anf08-121.htm
  and confirming each TOML quote appears verbatim in the body of the epistle.
  All 9 quotes are from the same single epistle; no alternative work is plausible.

--- Spot-checked against primary source ---

  - callistus-i-of-rome.Rom.1.32.unknown
    (https://www.tertullian.org/fathers2/ANF-08/anf08-121.htm, Section I)
    Quote: "the laws not only of the Church, but of the world, condemn those who are
    guilty of this crime; and not only those indeed who actually conspire, but those
    also who take part with such."
    Confirmed verbatim in Section I (On conspiracies against bishops).

  - callistus-i-of-rome.Rom.7.2.unknown
    (https://www.tertullian.org/fathers2/ANF-08/anf08-121.htm, Section III)
    Quote: "Wherefore the apostle says: The wife is bound by the law so long as her
    husband liveth; but if he be dead, she is loosed from the law of her husband."
    Confirmed verbatim in Section III (On episcopal parish boundaries).

  - callistus-i-of-rome.Gal.6.1.unknown
    (https://www.tertullian.org/fathers2/ANF-08/anf08-121.htm, Section V)
    Quote: "But if any one has fallen in anything, let us not consign him to ruin;
    but let us reprove him with brotherly affection, as the blessed apostle says:
    If a man be overtaken in any fault, ye which are spiritual restore such an one
    in the spirit of meekness; considering thyself, lest thou also be tempted."
    Confirmed verbatim in Section V (On witnesses and mercy).

  - callistus-i-of-rome.2Cor.6.14.unknown
    (https://www.tertullian.org/fathers2/ANF-08/anf08-121.htm, Section II)
    Quote: "Whence the apostle says: What part hath he that believeth with an infidel?
    or what fellowship hath righteousness with unrighteousness?"
    Confirmed verbatim in Section II (On excommunicated persons and unbelievers).

  - callistus-i-of-rome.Mark.10.44.unknown
    (https://www.tertullian.org/fathers2/ANF-08/anf08-121.htm, Section III)
    Quote: "And in another passage He says: And whosoever of you is the greater,
    shall be your servant"
    Confirmed verbatim in Section III.

  - callistus-i-of-rome.John.8.11.unknown
    (https://www.tertullian.org/fathers2/ANF-08/anf08-121.htm, Section VI)
    Quote: "Let him see to it that he sin no more, that the sentence of the Gospel
    may abide in him: Go, and sin no more."
    Confirmed verbatim in Section VI (On restoration of priests after lapse).

Run twice to verify idempotency.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "callistus-i-of-rome.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# All entries are from The Second Epistle to All the Bishops of Gaul (ANF08).
# Verified against: https://www.tertullian.org/fathers2/ANF-08/anf08-121.htm
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # Section 1 -- Conspiracies against bishops
    # "the laws not only of the Church, but of the world, condemn those who are
    # guilty of this crime; and not only those indeed who actually conspire..."
    "callistus-i-of-rome.Rom.1.32.unknown": "The Second Epistle to All the Bishops of Gaul 1",

    # Section 2 -- Excommunicated persons and unbelievers
    # "What part hath he that believeth with an infidel? or what fellowship
    # hath righteousness with unrighteousness?"
    "callistus-i-of-rome.2Cor.6.14.unknown": "The Second Epistle to All the Bishops of Gaul 2",

    # Section 3 -- Parish boundaries and episcopal transfer
    # "And whosoever of you is the greater, shall be your servant"
    "callistus-i-of-rome.Mark.10.44.unknown": "The Second Epistle to All the Bishops of Gaul 3",

    # Section 3 -- Marriage analogy for bishop-church relationship
    # "The wife is bound by the law so long as her husband liveth"
    "callistus-i-of-rome.Rom.7.2.unknown": "The Second Epistle to All the Bishops of Gaul 3",

    # Section 5 -- Mercy toward the fallen; witness requirements
    # "If a man be overtaken in any fault, ye which are spiritual restore
    # such an one in the spirit of meekness"
    "callistus-i-of-rome.Gal.6.1.unknown": "The Second Epistle to All the Bishops of Gaul 5",

    # Section 6 -- Restoration of lapsed priests; divine mercy
    # "Let him see to it that he sin no more...Go, and sin no more."
    "callistus-i-of-rome.John.8.11.unknown": "The Second Epistle to All the Bishops of Gaul 6",

    # Section 6 -- "All have sinned, and come short of the glory of God"
    "callistus-i-of-rome.Rom.3.23.unknown": "The Second Epistle to All the Bishops of Gaul 6",

    # Section 6 -- "glory, honour, and peace, to every man that worketh good"
    # (Rom 2:10 quoted in Section VI; entry tagged as Rom 3:3 in source DB)
    "callistus-i-of-rome.Rom.3.3.unknown": "The Second Epistle to All the Bishops of Gaul 6",

    # Section 6 -- "Being then made free from sin, ye became the servants
    # of righteousness. I speak after the manner of men."
    "callistus-i-of-rome.Rom.6.12.unknown": "The Second Epistle to All the Bishops of Gaul 6",
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
             "data/church-fathers/callistus-i-of-rome.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 9, f"Expected 9 patch entries, got {len(PATCH)}"
    main()
