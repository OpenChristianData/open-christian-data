# standards: author id slug
"""
Patch source_title for Lactantius's 9 blank entries (all 9 resolved here).

All 9 entries are HIGH confidence -- verified against primary source text at
wikisource.org (Wikisource Ante-Nicene Fathers Vol. VII Epitome chapters) and
worthychristianbooks.com (ANF Book VI and VII full chapter text).

Sources verified:
  - Epitome of the Divine Institutes: Wikisource individual chapter pages
  - Divine Institutes Book VI chapters XVIII, XIX, XXV: worthychristianbooks.com
  - Divine Institutes Book VII chapter XXVII: worthychristianbooks.com

Spot-checked against primary source:
  - lucius-caecilius-firmianus-lactantius.1Cor.1.21.unknown
      (Wikisource Ante-Nicene Fathers/Volume_VII/.../Epitome/.../Chap._XL)
      Confirmed: "Since, therefore, human wisdom has no existence (Socrates says
      in the writings of Plato), let us follow that which is divine" appears
      verbatim in Chap. XL Of the Foolishness of the Philosophers.

  - lucius-caecilius-firmianus-lactantius.Rev.19.12.unknown
      (Wikisource Ante-Nicene Fathers/Volume_VII/.../Epitome/.../Chap._XLII)
      Confirmed: "His name is known to none, except to Himself and the Father,
      as John teaches in the Revelation" appears verbatim in Chap. XLII Of
      Religious Wisdom: the Name of Christ Known to None, Except Himself and
      His Father.

  - lucius-caecilius-firmianus-lactantius.John.14.6.unknown
      (Wikisource Ante-Nicene Fathers/Volume_VII/.../Epitome/.../Chap._XLIX)
      Confirmed: "This is wisdom, and this is the mystery of the Supreme God.
      God willed that He should be acknowledged and worshipped through Him"
      appears verbatim in Chap. XLIX That God is One Only.
      Also confirmed in the same chapter: "Nor let the Jews, or philosophers,
      flatter themselves respecting the Supreme God. He who has not acknowledged
      the Son has been unable to acknowledge the Father" (assigns 1John.4.15).

  - lucius-caecilius-firmianus-lactantius.Heb.10.30.unknown
      (worthychristianbooks.com ANF Lactantius Divine Institutes Book VI cont.)
      Confirmed: "he must also diligently take care, lest by any fault of his
      he should at any time make an enemy" appears verbatim in Chap. XVIII
      Of Some Commands of God, and of Patience.

  - lucius-caecilius-firmianus-lactantius.Rom.12.14.unknown
      Same chapter XVIII confirmation: "He must not receive a gift from a poor
      man" and "If any one reviles, he must answer him with a blessing" both
      confirmed verbatim in Chap. XVIII.

  - lucius-caecilius-firmianus-lactantius.Col.3.5.unknown
      (worthychristianbooks.com ANF Lactantius Divine Institutes Book VI cont.)
      Confirmed: "God has appointed fixed limits to all of these; and if they
      pass these limits and begin to be too great, they must necessarily pervert
      their nature" appears verbatim in Chap. XIX Of the Affections and Their
      Use; And of the Three Furies.

  - lucius-caecilius-firmianus-lactantius.1Cor.4.4.unknown
      (worthychristianbooks.com ANF Lactantius Divine Institutes Book VI cont.)
      Confirmed: "But that he may obtain the favour of God, and be free from
      every stain, let him always implore the mercy of God" appears verbatim
      in Chap. XXV Of Sacrifice, and of an Offering Worthy of God, and of the
      Form of Praising God.

  - lucius-caecilius-firmianus-lactantius.Rev.21.7.unknown
      (worthychristianbooks.com ANF Lactantius Divine Institutes Book VII cont.)
      Confirmed: "Let those who are hungry come, that being fed with heavenly
      food, they may lay aside their lasting hunger; let those who are athirst
      come, that they may with full mouth draw forth the water of salvation from
      an ever-flowing fountain" appears verbatim in Chap. XXVII An Encouragement
      and Confirmation of the Pious.

Run twice to verify idempotency.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "lucius-caecilius-firmianus-lactantius.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # ---- Epitome of the Divine Institutes, Chapter XL ----
    # "human wisdom has no existence (Socrates says in the writings of Plato),
    # let us follow that which is divine" -- confirmed verbatim in Chap. XL.
    "lucius-caecilius-firmianus-lactantius.1Cor.1.21.unknown":
        "Epitome of the Divine Institutes 40",

    # ---- The Divine Institutes Book 6, Chapter XXV ----
    # "obtain the favour of God, and be free from every stain, let him always
    # implore the mercy of God" -- confirmed verbatim in Chap. XXV.
    "lucius-caecilius-firmianus-lactantius.1Cor.4.4.unknown":
        "The Divine Institutes Book 6, Chapter XXV",

    # ---- Epitome of the Divine Institutes, Chapter XLIX ----
    # "Nor let the Jews, or philosophers, flatter themselves respecting the
    # Supreme God. He who has not acknowledged the Son has been unable to
    # acknowledge the Father" -- confirmed verbatim in Chap. XLIX.
    "lucius-caecilius-firmianus-lactantius.1John.4.15.unknown":
        "Epitome of the Divine Institutes 49",

    # ---- The Divine Institutes Book 6, Chapter XIX ----
    # "God has appointed fixed limits to all of these; and if they pass these
    # limits and begin to be too great, they must necessarily pervert their
    # nature" -- confirmed verbatim in Chap. XIX.
    "lucius-caecilius-firmianus-lactantius.Col.3.5.unknown":
        "The Divine Institutes Book 6, Chapter XIX",

    # ---- The Divine Institutes Book 6, Chapter XVIII ----
    # "he must also diligently take care, lest by any fault of his he should
    # at any time make an enemy" -- confirmed verbatim in Chap. XVIII.
    "lucius-caecilius-firmianus-lactantius.Heb.10.30.unknown":
        "The Divine Institutes Book 6, Chapter XVIII",

    # ---- Epitome of the Divine Institutes, Chapter XLIX ----
    # "This is wisdom, and this is the mystery of the Supreme God. God willed
    # that He should be acknowledged and worshipped through Him" -- confirmed
    # verbatim in Chap. XLIX (same chapter as 1John.4.15).
    "lucius-caecilius-firmianus-lactantius.John.14.6.unknown":
        "Epitome of the Divine Institutes 49",

    # ---- Epitome of the Divine Institutes, Chapter XLII ----
    # "His name is known to none, except to Himself and the Father, as John
    # teaches in the Revelation" -- confirmed verbatim in Chap. XLII.
    "lucius-caecilius-firmianus-lactantius.Rev.19.12.unknown":
        "Epitome of the Divine Institutes 42",

    # ---- The Divine Institutes Book 7, Chapter XXVII ----
    # "Let those who are hungry come, that being fed with heavenly food, they
    # may lay aside their lasting hunger; let those who are athirst come, that
    # they may with full mouth draw forth the water of salvation from an
    # ever-flowing fountain" -- confirmed verbatim in Chap. XXVII.
    "lucius-caecilius-firmianus-lactantius.Rev.21.7.unknown":
        "The Divine Institutes Book 7, Chapter XXVII",

    # ---- The Divine Institutes Book 6, Chapter XVIII ----
    # "He must not receive a gift from a poor man" and "If any one reviles, he
    # must answer him with a blessing" -- both confirmed verbatim in Chap. XVIII
    # (same chapter as Heb.10.30).
    "lucius-caecilius-firmianus-lactantius.Rom.12.14.unknown":
        "The Divine Institutes Book 6, Chapter XVIII",
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
             "data/church-fathers/lucius-caecilius-firmianus-lactantius.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 9, f"Expected 9 patch entries, got {len(PATCH)}"
    main()
