"""
Patch source_title for Jerome's blank entries (30 total, 17 resolved here).

Confidence tiers (per entry in PATCH dict below):
  HIGH -- explicit attribution clue in quote text (inline citation), adjacent block
          with a verified primary-source URL, or confirmed against newadvent.org /
          tertullian.org by direct fetch.

Only HIGH-confidence entries are included. 13 entries remain blank because they
are short quotes (<20 words), rely on single-signal inference, or could not be
verified against a primary source.

Psalms prefaces confirmed via tertullian.org NPNF2-06 volume:
  jerome.Ps.1.1.unknown   -- Npnf2-06-21.htm: preface to Psalter addressed to Sophronius
  jerome.Ps.1.1.unknown-2 -- Npnf2-06-22.htm: Gallican Psalter preface to Paula & Eustochium

Commentary on Ephesians (jerome.Eph.6.14.unknown) was initially included but removed:
  the catena-only confirmation does not meet the HIGH standard (no primary-source text fetch
  succeeded for Jerome's Commentary on Ephesians at Eph 6:14 during this session).

Unresolved entries (documented):
  jerome.1Cor.15.50.unknown   -- <30 words, no work citation, no URL
  jerome.Acts.1.2.unknown     -- short fragment, no clear work attribution
  jerome.Acts.5.1.unknown     -- single-sentence etymology, no work citation
  jerome.Col.1.22.unknown     -- Jerome has no Col commentary; source work unconfirmed
  jerome.Col.2.3.unknown      -- "Homilies on Mark (x)" inline but exact homily ambiguous
  jerome.Col.3.5.unknown      -- source work unconfirmed (no Col commentary by Jerome)
  jerome.Eph.6.14.unknown     -- likely Commentary on Ephesians (Eph 6:14) but primary
                                  source text not directly accessible; MEDIUM only
  jerome.Jer.1.1.unknown-2    -- single-sentence, single signal
  jerome.Mark.15.32.unknown   -- short, no work citation
  jerome.Mark.1.11.unknown    -- source work unconfirmed via primary fetch
  jerome.Mark.1.20.unknown    -- source work unconfirmed via primary fetch
  jerome.Matt.13.46.unknown   -- primary source fetch unavailable; MEDIUM only
  jerome.Rom.3.30.unknown     -- single sentence, no work citation

Run twice to verify idempotency.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "jerome.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # ---- Prefaces to biblical books (Jerome's Vulgate translation prefaces) ----
    # Prologus Galeatus: "first read my Samuel and Kings" -- confirmed NewAdvent/tertullian.org
    "jerome.1Kgs.1.1.unknown": "Preface to Samuel and Kings",

    # "the third year that you always write...that I might translate the book of Ezra" --
    # confirmed addressed to Domnius and Rogatianus via tertullian.org
    "jerome.Ezra.1.1.unknown": "Preface to Ezra",

    # "The Book of Esther stands corrupted by various translators" -- confirmed tertullian.org
    "jerome.Esth.1.1.unknown": "Preface to Esther",

    # "The Prophet Ezekiel was led captive with Joachin king of Judah to Babylon" --
    # confirmed via tertullian.org (agent: "Prologue to Ezekiel")
    "jerome.Ezek.1.1.unknown": "Preface to Ezekiel",

    # "No one, when he will have seen the Prophets to be written in verses..." --
    # confirmed tertullian.org (jerome_preface_isaiah.htm; adjacent block has that URL);
    # matches existing "PREFACE TO ISAIAH" format already in the file
    "jerome.Isa.1.1.unknown": "PREFACE TO ISAIAH",

    # "The Prophet Jeremiah...for whom this prologue is written" -- confirmed tertullian.org
    "jerome.Jer.1.1.unknown-3": "Preface to Jeremiah",

    # "Having finally finished with the Pentateuch...we set our hand to Jesus son of Nave" --
    # confirmed tertullian.org
    "jerome.Josh.1.1.unknown": "Preface to Joshua",

    # ---- Commentary on Jeremiah (inline citations in TOML quote text) ----
    # Quote ends with "[SIX BOOKS ON JEREMIAH 6.9.3-6]" -- explicit inline citation
    "jerome.Ezra.2.3.unknown": "Commentary on Jeremiah",

    # Quote ends with "[Commentary on Jeremiah, 32:37-41]" -- explicit inline citation
    "jerome.Ezra.2.3.unknown-2": "Commentary on Jeremiah",

    # Verse-by-verse commentary on Jer 1:4-5 ("The great clemency of God is astonishing;
    # with the captivity already neat...") -- confirmed: Jerome's Commentary on Jeremiah
    # covers this passage (agent-verified; existing "Commentary on Jeremiah" in the file)
    "jerome.Jer.1.1.unknown": "Commentary on Jeremiah",

    # ---- Commentary on Matthew ----
    # "Hier. in Matt., 15" at the start of the quote = "Jerome, In Matthaeum, Chapter 15"
    # -- explicit self-identifying inline citation
    "jerome.Mark.7.13.unknown": "Commentary on Matthew",

    # First block in the TOML is labeled "(Prolog. in Comm. in Matt.)" and "(Comm. in Matt.
    # ch. 1.)" -- the missing block is the same text, making this an explicit inline citation
    "jerome.Matt.1.1.unknown": "Commentary on Matthew",

    # Text is near-verbatim duplicate of the adjacent block that carries
    # source_url='historicalchristian.faith/.../Commentary on Matthew.html'
    # and source_title='Commentary on Matthew' -- primary source already verified
    "jerome.Matt.5.9.unknown": "Commentary on Matthew",

    # Same pattern as Matt.5.9: near-verbatim duplicate of adjacent primary-source-verified block
    "jerome.Matt.6.25.unknown": "Commentary on Matthew",

    # ---- Psalms prefaces ----
    # "Eusebius Hieronymus to his Sophronius, health! I know some to think the Psalter to be
    # divided into five books..." -- preface to Jerome's translation of the Psalter from Hebrew.
    # Confirmed: tertullian.org NPNF2-06, Npnf2-06-21.htm (preface to Psalter, Sophronius)
    "jerome.Ps.1.1.unknown": "Preface to the Hebrew Psalter",

    # "Not long ago while located in Rome, I emended the Psalter...Because you see it again,
    # O Paula and Eustochium, corrupted by the error of the scribes..." -- preface to the
    # Gallican Psalter (Jerome's second Psalter revision, based on Origen's LXX Hexapla).
    # Confirmed: tertullian.org NPNF2-06, Npnf2-06-22.htm (Gallican Psalter, Paula & Eustochium)
    "jerome.Ps.1.1.unknown-2": "Preface to the Gallican Psalter",

    # ---- Against Helvidius ----
    # Quote ends with "[Adversus Helvidium]" -- explicit inline citation
    "jerome.Ezra.6.7.unknown": "Against Helvidius",
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
             "data/church-fathers/jerome.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 17, f"Expected 17 patch entries, got {len(PATCH)}"
    main()
