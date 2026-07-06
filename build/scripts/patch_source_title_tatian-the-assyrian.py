# standards: author id slug
"""
Patch source_title for tatian-the-assyrian (8 of 9 blank entries resolved).

Tatian the Assyrian has one surviving prose work: "Address of Tatian to the
Greeks" (also known as "Oratio ad Graecos").  All 8 patched entries are from
this single work.  Chapter assignments verified against the NewAdvent primary
source text at newadvent.org/fathers/0202.htm, which marks inline Scripture
cross-references directly in the body of each chapter.

Title format convention (matched to existing entries in this file):
  "Address of Tatian to the Greeks, Chapter <ROMAN>"

One entry left blank:
  tatian-the-assyrian.Mark.9.48.unknown
    Quote: "With which he careth for. / us, to appear"
    This extremely short, fragmentary quote does not appear anywhere in the
    NewAdvent text of "Address of Tatian to the Greeks".  No other surviving
    Tatian prose work covers Mark 9:48.  The quote is too short (<10 words,
    clearly truncated) to verify against any primary source.  Confidence: LOW.
    Left blank rather than assign a best-guess.

Spot-checked against primary source (newadvent.org/fathers/0202.htm):
  - tatian-the-assyrian.1Pet.2.17.unknown (Chapter 4) -- confirmed:
    "Does my master command me to act as a bondsman and to serve, I acknowledge
    the serfdom. Man is to be honoured as a fellow-man" appears in Chapter 4
    body text, in the paragraph beginning "For what reason, men of Greece..."
  - tatian-the-assyrian.Eph.6.13.unknown (Chapter 16) -- confirmed:
    "Being armed with the breastplate of the celestial Spirit" appears in
    Chapter 16, in the paragraph "But now this they can by no means effect..."
  - tatian-the-assyrian.Rom.1.28.unknown (Chapter 40) -- confirmed:
    "But what the learned among the Greeks have said concerning our polity and
    the history of our laws" appears verbatim in Chapter 40 body text.

Run twice to verify idempotency.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "tatian-the-assyrian.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# All verified against newadvent.org/fathers/0202.htm
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # ---- Chapter IV ----
    # NewAdvent Chapter 4 ("The Christians Worship God Alone") contains the
    # inline Scripture cross-reference markers [John 4:24] and [Romans 1:20]
    # within a single block of text about God being a Spirit.  The 1Cor.15.44
    # TOML quote ("Not pervading matter, but the Maker of material spirits...
    # The sun and moon were made for us...") is part of that same Chapter 4
    # block.  The 1Pet.2.17 TOML quote ("Does my master command me to act as a
    # bondsman...") opens Chapter 4.  The Rom.1.20 TOML quote ("apprehend His
    # invisible power by His works") is also in Chapter 4 marked [Romans 1:20].
    "tatian-the-assyrian.1Cor.15.44.unknown": "Address of Tatian to the Greeks, Chapter IV",
    "tatian-the-assyrian.1Pet.2.17.unknown": "Address of Tatian to the Greeks, Chapter IV",
    "tatian-the-assyrian.Rom.1.20.unknown": "Address of Tatian to the Greeks, Chapter IV",

    # ---- Chapter XV ----
    # NewAdvent Chapter 15 ("Necessity of a Union with the Holy Spirit") contains
    # "And only by those whom the Spirit of God dwells in and fortifies are the
    # bodies of the demons easily seen, not at all by others -- I mean those who
    # possess only soul."  This matches the 1Cor.2.14 TOML quote verbatim.
    "tatian-the-assyrian.1Cor.2.14.unknown": "Address of Tatian to the Greeks, Chapter XV",

    # ---- Chapter XVI ----
    # NewAdvent Chapter 16 ("Vain Display of Power by the Demons") contains
    # "Being armed with the breastplate of the celestial Spirit" -- the Eph 6:13
    # TOML quote opens with that same imagery about the lower matter and war
    # against matter, ending at the breastplate.
    "tatian-the-assyrian.Eph.6.13.unknown": "Address of Tatian to the Greeks, Chapter XVI",

    # ---- Chapter XXV ----
    # NewAdvent Chapter 25 ("Boastings and Quarrels of the Philosophers") contains
    # "What injury do we inflict upon you, O Greeks? Why do you hate those who
    # follow the word of God, as if they were the vilest of mankind? It is not we
    # who eat human flesh" -- matching the 1Cor.10.16 TOML quote.
    "tatian-the-assyrian.1Cor.10.16.unknown": "Address of Tatian to the Greeks, Chapter XXV",

    # ---- Chapter XXVII ----
    # NewAdvent Chapter 27 ("The Christians are Hated Unjustly") contains
    # "though some one says that the Cretans are liars" -- matching Titus 1:12
    # TOML quote verbatim.
    "tatian-the-assyrian.Titus.1.12.unknown": "Address of Tatian to the Greeks, Chapter XXVII",

    # ---- Chapter XL ----
    # NewAdvent Chapter 40 ("Moses More Ancient and Credible Than the Heathen
    # Heroes") contains "But what the learned among the Greeks have said
    # concerning our polity and the history of our laws" -- matching the Rom.1.28
    # TOML quote verbatim.  The same chapter ends "These things, O Greeks, I
    # Tatian, a disciple of the barbarian philosophy" (the Rom.1.28 quote
    # continues with this Tatian self-identification).
    "tatian-the-assyrian.Rom.1.28.unknown": "Address of Tatian to the Greeks, Chapter XL",
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
             "data/church-fathers/tatian-the-assyrian.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 8, f"Expected 8 patch entries, got {len(PATCH)}"
    main()
