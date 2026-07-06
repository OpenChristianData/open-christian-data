# standards: author id slug
"""Patch missing source_title for rabanus-maurus church_fathers entries.

SESSION 1 (commit fa172ff): 12 of 20 missing entries patched with HIGH confidence.
SESSION 2 (this script):    8 remaining entries confirmed blank after exhaustive
                            primary-source research. 0 new entries added.

--- Original 20 missing entries broke into three groups ---

  GROUP A: 13 x Matthew single-verse TOML files (e.g. Matthew 4_22.toml)
  GROUP B:  6 x Acts single-verse TOML files
  GROUP C:  1 x Jonah single-verse TOML (Jonah 2_1.toml)

--- GROUP A: Matthew entries (patched in Session 1) ---

Every Matthew entry in rabanus-maurus.json is attributed to the Catena Aurea
by Aquinas, sourced from historicalchristian.faith. For the 13 missing
entries, each is a single-verse TOML file with no source metadata, sitting
adjacent to verse-range TOMLs (e.g. Matthew 4_3-4.toml, Matthew 4_18-22.toml)
that *do* carry source_title='Catena Aurea by Aquinas'.

Spot-checks on historicalchristian.faith confirmed the identical quote text
appears on that site attributed explicitly to "Catena Aurea by Aquinas" for
every Matthew entry verified. The single-verse TOMLs are data propagation
gaps -- the same quote was imported from the site without the source metadata.

  HIGH confidence (12 entries, all patched): Matt.4.4, Matt.4.22, Matt.5.19,
  Matt.9.35, Matt.10.4, Matt.11.24, Matt.14.12, Matt.15.31, Matt.19.22,
  Matt.20.19, Matt.26.35, Matt.26.38.

  EXCEPTION -- Matt.24.35.unknown (MEDIUM, left blank):
    The historicalchristian.faith page for Matt 24:35 shows TWO distinct
    Rabanus entries:
      - First:  "The heaven which shall pass away is not the starry heaven
                which of old was destroyed by the deluge." (no source label)
      - Second: "...not the starry but the atmospheric heaven..." (Catena Aurea)
    Our entry matches the FIRST, which has no source attribution on the site.
    The text also differs from the curated Matt.24.32-35 Catena Aurea entry.
    Verified directly at https://historicalchristian.faith/matthew/24/35
    (Session 2). MEDIUM confidence -- left blank.

--- GROUP B/C: Acts and Jonah entries (7 entries, all left blank) ---

Thorough research in Session 2 confirms no source can be assigned with HIGH
confidence for any of these 7 entries. Key findings:

1. KNOWN WORKS: Rabanus Maurus (d. 856) has NO known commentary on Acts or
   Jonah. Per Wikipedia (confirmed): his biblical commentaries cover Genesis
   to Judges, Ruth, Kings, Chronicles, Judith, Esther, Canticles, Proverbs,
   Wisdom, Sirach, Jeremiah, Lamentations, Ezekiel, Maccabees, Matthew, and
   the Pauline Epistles (incl. Hebrews). His other works include De Universo
   (encyclopedic), homilies, De institutione clericorum, De laudibus sanctae
   crucis, and minor works. No Acts or Jonah commentary appears anywhere.

2. SOURCE SITE: historicalchristian.faith shows ALL 7 entries without any
   "Source:" label (confirmed for Acts 2:1 and Jonah 2:1 by direct inspection;
   Acts 12:19 also confirmed). The site does provide source labels for other
   authors on the same pages (e.g. Bede: "Commentary on Acts"; Oecumenius:
   "Commentary on Acts").

3. CANDIDATE WORKS INVESTIGATED:
   - Catena Aurea by Aquinas: covers only the four Gospels, not Acts or Jonah.
   - ACCS (Ancient Christian Commentary on Scripture): cutoff c. AD 750;
     Rabanus Maurus (776-856) is excluded from that series.
   - CCEL, tertullian.org, roger-pearse.com: no Acts or Jonah works by Rabanus.
   - De Universo / homilies: plausible candidates for brief allegorical glosses
     but not accessible for primary-source verification.
   - No English translation of any Rabanus work on Acts or Jonah is known to
     exist (as of April 2026).

4. QUOTE STYLE: All 7 quotes are brief (12-34 words), allegorical or
   typological glosses, consistent with a homily or encyclopedic work, but
   their brevity means multiple works are plausible and no work-level title
   can be assigned with HIGH confidence.

   MEDIUM confidence -- all 7 left blank per curation rules.

--- Spot-checked against primary source (Session 2) ---

  - rabanus-maurus.Matt.24.35.unknown
    URL: https://historicalchristian.faith/matthew/24/35
    Two distinct Rabanus entries on page. Only the SECOND is labelled "Catena
    Aurea by Aquinas"; our entry matches the FIRST, which has no source label.
    Text differs from the curated Matt.24.32-35 Catena Aurea entry.
    CONFIRMED: no source attributable. Left blank.

  - rabanus-maurus.Acts.2.1.unknown
    URL: https://historicalchristian.faith/acts/2/1
    Rabanus entry present ("The Law was given on Mount Sinai...") with NO
    "Source:" label. Other authors on same page DO have source labels.
    CONFIRMED: no source attributable at this page. Left blank.

  - rabanus-maurus.Jonah.2.1.unknown
    URL: https://historicalchristian.faith/jonah/2/1
    Rabanus entry present ("The fish which swallowed Jonah...") with NO
    "Source:" label. Haimo of Auxerre immediately follows -- also no label.
    CONFIRMED: no source attributable at this page. Left blank.

  - rabanus-maurus.Acts.12.19.unknown
    URL: https://historicalchristian.faith/acts/12/19
    Rabanus entry present ("That the release of Peter should harm no one...")
    with NO "Source:" label.
    CONFIRMED: no source attributable at this page. Left blank.

All 4 spot-checks confirmed: source cannot be assigned. 4/3 required checks
completed (3 minimum per task spec; 4 performed).
"""

import json
import subprocess
from pathlib import Path

# Project root is two levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "rabanus-maurus.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title
#
# Session 1 (commit fa172ff) applied 12 HIGH-confidence Matthew patches.
# Session 2 research confirmed the remaining 8 entries must stay blank --
# no source title can be assigned at HIGH confidence. See docstring above.
#
# PATCH is empty: this script is now documentation-only. Running it is
# idempotent -- it will confirm all existing source_title values are intact
# and print a final blank count.
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {}

# Entries confirmed blank after research (not patched):
# rabanus-maurus.Matt.24.35.unknown  -- MEDIUM: no source attribution on site
# rabanus-maurus.Acts.12.19.unknown  -- MEDIUM: no Acts commentary by Rabanus
# rabanus-maurus.Acts.14.7.unknown   -- MEDIUM: no Acts commentary by Rabanus
# rabanus-maurus.Acts.2.1.unknown    -- MEDIUM: no Acts commentary by Rabanus
# rabanus-maurus.Acts.2.30.unknown   -- MEDIUM: no Acts commentary by Rabanus
# rabanus-maurus.Acts.5.5.unknown    -- MEDIUM: no Acts commentary by Rabanus
# rabanus-maurus.Acts.8.4.unknown    -- MEDIUM: no Acts commentary by Rabanus
# rabanus-maurus.Jonah.2.1.unknown   -- MEDIUM: no Jonah commentary by Rabanus


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
    print(f"  (8 entries intentionally left blank -- MEDIUM confidence only)")
    print(f"  See docstring for full research findings from Session 2.")

    print(f"\nNo file write needed (PATCH is empty).")
    print("Done.")

    # Run validator to confirm data file is still valid
    print("\nRunning validate.py ...")
    try:
        subprocess.run(
            ["py", "-3", str(VALIDATE_SCRIPT),
             "data/church-fathers/rabanus-maurus.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 0, f"Expected 0 patch entries, got {len(PATCH)}"
    main()
