"""
Patch source_title for jerome (third pass) -- 2 of 10 remaining blanks resolved.

Confidence tiers (per CODING_DEFAULTS PIPE-12):
  HIGH -- Verified against primary source (primary text fetched and quote
          matched verbatim or near-verbatim).

Spot-checked against primary source:
  - jerome.Acts.5.1.unknown
      Quote: 'The name Ananais means "grace of the Lord."'
      Primary source: Jerome's On Hebrew Names (Liber interpretationis
      hebraicorum nominum), section "On the Acts of the Apostles, A."
      URL: https://raw.githubusercontent.com/HistoricalChristianFaith/
           Writings-Database/master/Jerome/On%20Hebrew%20Names.html
      Verified: "Ananias: Grace of the Lord." appears verbatim in the
      "On the Acts of the Apostles" A-section of that file (position
      ~113309 in raw text). The adjacent entry in the database for
      Acts 4:36 (Barnabas) uses source_title
      'Book on Hebrew Names, On the Acts of the Apostles, B' with the
      same source URL -- same work, same section-letter convention.
      Confidence: HIGH -- verbatim match against the primary text.

  - jerome.Acts.1.2.unknown
      Quote: "instructing the Apostles, whom he had chosen through the
      Holy Spirit: Observe the order (In Matt. 28:19) of these
      injunctions. He bids the Apostles first to teach all nations, then
      to wash them with the sacrament of faith, and after faith and
      baptism then to teach them what things they ought to observe..."
      Primary source: Jerome's Commentary on Matthew, comment on Matt
      28:19-20.
      URL: https://raw.githubusercontent.com/HistoricalChristianFaith/
           Writings-Database/master/Jerome/Commentary%20on%20Matthew.html
      Verified: "He commanded the apostles to first teach all nations,
      then to immerse them in the sacrament of faith, and after faith and
      baptism, to command what should be observed." found at position
      ~555831 in the raw text, under the heading "28:20 (Verse 20)
      Teaching them to observe all things whatsoever I have commanded
      you."  The TOML quote cites "(In Matt. 28:19)" inline, which is
      consistent with commentary on Matthew. This is the only Jerome work
      where he expounds Matt 28:19-20 in commentary form.
      Confidence: HIGH -- near-verbatim match (older English translation
      vs. modern rendering of the same Latin passage).

Upstream bugs filed (see UPSTREAM_BUGS.md):
  - jerome.Mark.1.11.unknown -- Catena Aurea on Mark Ch. 1 attributes
    both dove/Canticles paragraphs to PSEUDO-JEROME, not Jerome. Cannot
    assign source_title to a mis-attributed entry.
  - jerome.Mark.15.32.unknown -- Catena Aurea on Mark Ch. 15 verse 32
    explicitly labels the "foal of Judah" quote as PSEUDO-JEROME.

Unresolved entries (8 remain blank after this pass):
  jerome.1Cor.15.50.unknown   -- no work citation, no primary source found
  jerome.Col.1.22.unknown     -- Jerome has no Colossians commentary; source
                                  unconfirmed across all available works
  jerome.Col.2.3.unknown      -- "Homilies on Mark (x)" inline reference
                                  format unresolved; no primary source found
  jerome.Col.3.5.unknown      -- source work unconfirmed; no Col commentary
  jerome.Mark.1.11.unknown    -- PSEUDO-JEROME per Catena Aurea; upstream bug
  jerome.Mark.1.20.unknown    -- no primary source confirmation; MEDIUM at best
  jerome.Mark.15.32.unknown   -- PSEUDO-JEROME per Catena Aurea; upstream bug
  jerome.Rom.3.30.unknown     -- single short sentence, no work attribution found

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
    # Verbatim match: "Ananias: Grace of the Lord." in the "On the Acts of
    # the Apostles, A." section of On Hebrew Names. Adjacent Barnabas entry
    # (Acts 4:36) uses the same source with "B" suffix -- same convention.
    "jerome.Acts.5.1.unknown": "Book on Hebrew Names, On the Acts of the Apostles, A",

    # Near-verbatim match: Commentary on Matthew 28:19-20 contains "He
    # commanded the apostles to first teach all nations, then to immerse them
    # in the sacrament of faith, and after faith and baptism, to command what
    # should be observed." The TOML quote cites "(In Matt. 28:19)" inline,
    # directly pointing to this work. Title "Commentary on Matthew" matches
    # the dominant source_title (663 existing entries).
    "jerome.Acts.1.2.unknown": "Commentary on Matthew",
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
            ["py", "-3", str(VALIDATE_SCRIPT), "data/church-fathers/jerome.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 2, f"Expected 2 patch entries, got {len(PATCH)}"
    main()
