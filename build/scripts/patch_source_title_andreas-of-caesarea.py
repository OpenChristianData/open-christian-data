# standards: author id slug
"""
Patch source_title for andreas-of-caesarea (8 missing entries).

Andreas of Caesarea has one surviving major work: the Commentary on the
Apocalypse (Commentary on Revelation). All 8 patched entries are from this
single work. Verse-range assignments verified against the primary source:

  Constantinou, Eugenia Scarvelis (trans.). Commentary on the Apocalypse /
  Andrew of Caesarea. Fathers of the Church, vol. 123.
  Catholic University of America Press, 2011.
  archive.org identifier: commentaryonapoc0123andr
  Also available as Fathers of the Church vol. 123 in:
  archive.org/details/the-fathers-of-the-church-a-new-translation-147-volumes

The Commentary is organized verse-by-verse (and occasionally by verse ranges).
Section headings in the translation use the form "1.1", "1.3", "5.2-3", etc.
The existing data convention for source_title is:
  "Commentary on the Apocalypse [chapter:verse]"
  (matching the already-populated entries in this file, e.g.
   "Commentary on the Apocalypse 1:4", "Commentary on the Apocalypse 5:1")

Scripture index pages 265-270 of the translation (PDF pages 283-285)
confirm the verse-to-page mapping for every entry below.

Notable findings:
- "Revelation 1_5.toml" maps to section "1.5b-6" in the Commentary (covers
  verses 5b-6 together). Source_title is "Commentary on the Apocalypse 1:5-6"
  to match the section boundary.
- "Revelation 5_3.toml" maps to section "5.2-3" (combined section). The
  section heading in the translation covers both verses 2 and 3.
- "Revelation 20_9.toml" and "2 Thessalonians 1_8.toml" both contain short
  excerpts of the section "20.9-10". The 2 Thess 1:8 TOML entry exists
  because the commentary cross-references 2 Kgs 1 and 2 Thess 1:8 imagery
  (fire of judgment) -- the quote is from the Rev 20:9-10 section.

Spot-checked against primary source
(Fathers of the Church vol. 123, archive.org/details/the-fathers-of-the-church-a-new-translation-147-volumes):

  - andreas-of-caesarea.Rev.1.1.unknown (Commentary on the Apocalypse 1:1)
    PDF p.70, section 1.1: "An apocalypse is the manifestation of hidden
    mysteries when the intellect is illuminated either through divine dreams
    or according to waking visions from divine enlightenment." Matches TOML
    quote "Revelation is the revealing of hidden mysteries when the intellect
    is enlightened by either divine dreams or by visions from divine
    enlightenment while awake." -- confirmed.

  - andreas-of-caesarea.Rev.5.3.unknown (Commentary on the Apocalypse 5:2-3)
    PDF p.101, section 5.2-3: "By these is meant that neither angels nor
    human beings, those existing in the flesh, nor the saints who had departed
    from the flesh <are able> to grasp the precise knowledge of the divine
    judgments, except the 'Lamb of God,' through his presence releasing the
    obscurity of the things prophesied about him." Matches TOML quote exactly
    -- confirmed.

  - andreas-of-caesarea.Rev.20.9.unknown (Commentary on the Apocalypse 20:9-10)
    PDF p.228, section 20.9-10: "fire comes down from heaven, either a
    visible fire as <happened to> the two commanders of fifty men in the
    presence of Elijah, or the coming of Christ in glory will destroy them
    by the breath of his mouth." Matches TOML quote exactly -- confirmed.

Run twice to verify idempotency.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "andreas-of-caesarea.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# All verified against Fathers of the Church vol. 123 (CUA Press, 2011)
# Scripture index pp.265-270 confirms section boundaries.
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # ---- Commentary on the Apocalypse 1:1 ----
    # PDF p.70, section heading "1.1". Commentary opens: "An apocalypse is
    # the manifestation of hidden mysteries when the intellect is illuminated
    # either through divine dreams or according to waking visions from divine
    # enlightenment." Scripture index: 1.1 -> p.55.
    "andreas-of-caesarea.Rev.1.1.unknown": "Commentary on the Apocalypse 1:1",

    # ---- Commentary on the Apocalypse 1:3 ----
    # PDF p.71, section heading "1.3". Commentary: "He blesses those who read
    # and hear... the time is near, the time of the distribution of prizes,
    # on account of the brevity of the present life in comparison to the
    # future." Scripture index: 1.3 -> p.56.
    "andreas-of-caesarea.Rev.1.3.unknown": "Commentary on the Apocalypse 1:3",

    # ---- Commentary on the Apocalypse 1:5-6 ----
    # PDF pp.73-74, section heading "1.5b-6". Commentary: "The glory belongs
    # to him, it says, who freed us through love from the bondage of death,
    # and washed the stains of sin through the outpouring of his life-giving
    # blood and water." Scripture index: 1.5 -> p.58, 1.6 -> p.58.
    # Section covers both verses 5b and 6 together.
    "andreas-of-caesarea.Rev.1.5.unknown": "Commentary on the Apocalypse 1:5-6",

    # ---- Commentary on the Apocalypse 1:7 ----
    # PDF p.74, section heading "1.7". Commentary: "Either the bodiless
    # powers are implied by the clouds, or those which covered him on Mount
    # Tabor with his holy disciples." Scripture index: 1.7 -> p.59.
    "andreas-of-caesarea.Rev.1.7.unknown": "Commentary on the Apocalypse 1:7",

    # ---- Commentary on the Apocalypse 5:2-3 ----
    # PDF p.101, section heading "5.2-3". The section covers verses 2-3
    # together. Commentary: "By these is meant that neither angels nor human
    # beings...are able to grasp the precise knowledge of the divine
    # judgments, except the Lamb of God." Scripture index: 5.2 -> p.86,
    # 5.3 -> p.86 (same section).
    "andreas-of-caesarea.Rev.5.3.unknown": "Commentary on the Apocalypse 5:2-3",

    # ---- Commentary on the Apocalypse 5:4 ----
    # PDF p.101, section heading "5.4". Commentary: "I was weeping, he says,
    # perhaps since the most spotless order of the angelic substances fell
    # into ignorance." Scripture index: 5.4 -> p.86.
    "andreas-of-caesarea.Rev.5.4.unknown": "Commentary on the Apocalypse 5:4",

    # ---- Commentary on the Apocalypse 20:9-10 (Rev 20:9 TOML) ----
    # PDF p.228, section heading "20.9-10". Short excerpt of the section.
    # Commentary: "fire comes down from heaven, either a visible fire as
    # <happened to> the two commanders of fifty men in the presence of
    # Elijah, or the coming of Christ in glory will destroy them by the
    # breath of his mouth." Scripture index: 20.9-10 -> pp.213-216.
    "andreas-of-caesarea.Rev.20.9.unknown": "Commentary on the Apocalypse 20:9-10",

    # ---- Commentary on the Apocalypse 20:9-10 (2 Thess 1:8 TOML) ----
    # Same primary section (PDF pp.228-230). The 2 Thess TOML entry exists
    # because the commentary cross-references 2 Kgs 1 fire imagery (which
    # also evokes 2 Thess 1:8 "in flaming fire"). The quote is an expanded
    # version of the same passage. Confirmed: "the fire is either a visible
    # fire as happened to the two commanders of fifty men...or the coming of
    # Christ in glory will destroy them by the breath of his mouth...deliver
    # the devil to the lake of fire together with the Antichrist and the
    # false prophet to be tortured forever and ever" -- matches the full
    # 20.9-10 section text at PDF pp.229-230.
    "andreas-of-caesarea.2Thess.1.8.unknown": "Commentary on the Apocalypse 20:9-10",
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
             "data/church-fathers/andreas-of-caesarea.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 8, f"Expected 8 patch entries, got {len(PATCH)}"
    main()
