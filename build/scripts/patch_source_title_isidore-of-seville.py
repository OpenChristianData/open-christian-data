# standards: author id slug
"""Patch missing source_title for isidore-of-seville church_fathers entries.

0 of 12 missing entries are patched here.
All 12 are left blank -- none reached HIGH confidence.

--- Background ---

35 entries total; 12 have blank source_title.
The 12 fall into three groups:

--- Group A: 9 Luke entries (MISATTRIBUTION -- do not patch) ---

All 9 Luke entries are attributed in the source TOML database to
"Isidore of Seville" but are actually from ISIDORE OF PELUSIUM,
quoted in Thomas Aquinas's Catena Aurea.

Entries:
  isidore-of-seville.Luke.6.1.unknown
  isidore-of-seville.Luke.6.43.unknown
  isidore-of-seville.Luke.7.24.unknown
  isidore-of-seville.Luke.8.1.unknown
  isidore-of-seville.Luke.9.10.unknown
  isidore-of-seville.Luke.10.3.unknown
  isidore-of-seville.Luke.12.41.unknown
  isidore-of-seville.Luke.18.31.unknown
  isidore-of-seville.Luke.24.25.unknown

Evidence:
  Each was verified via Playwright against Catena Aurea on historicalchristian.faith.
  The heading label in the Catena Aurea for every one of these quotes reads
  "ISIDORE OF PELEUSIUM" (not Isidore of Seville). Examples:

    Luke 6:1  -- Catena Aurea Luke Ch.6: "ISIDORE OF PELEUSIUM. (Isidore. l.i. Ep.110.)"
    Luke 6:43 -- Catena Aurea Luke Ch.6: "ISIDORE OF PELEUSIUM. (lib. iv. ep. 81.)"
    Luke 7:24 -- Catena Aurea Luke Ch.7: "ISIDORE OF PELEUSIUM. (lib. l. Ep. 33.)"
    Luke 8:1  -- Catena Aurea Luke Ch.8: "ISIDORE OF PELEUSIUM. (lib. iii. ep. 206.)"
    Luke 9:10 -- Catena Aurea Luke Ch.9: "ISIDORE OF PELEUSIUM. (l.I. ep. 233.)"
    Luke 10:3 -- Catena Aurea Luke Ch.10: "ISIDORE OF PELEUSIUM. (l.i. ep. 438.)"
    Luke 12:41 -- Catena Aurea Luke Ch.12: "ISIDORE OF PELEUSIUM. (l.3. Ep. 170.)"
    Luke 18:31 -- Catena Aurea Luke Ch.18: "ISIDORE OF PELEUSIUM. (l.ii. Ep. 212.)"
    Luke 24:25 -- Catena Aurea Luke Ch.24: "ISIDORE OF PELEUSIUM. (lib. iii. Ep. 98.)"

  This is a systematic misattribution in the upstream
  HistoricalChristianFaith/Commentaries-Database. The TOML files for these
  Luke passages are in the "Isidore of Seville" directory but the quotes
  belong to Isidore of Pelusium. Flagged for upstream correction.

  Confidence: N/A (wrong author -- cannot assign source_title for Isidore of Seville)

--- Group B: Acts 5:9 (MEDIUM confidence -- not patched) ---

  isidore-of-seville.Acts.5.9.unknown

  Quote: "The punishment by death from the wisest Peter against those who
  erred is not out of madness but out of teaching of prescient..."

  historicalchristian.faith labels this "Isidore of Seville on Acts 5:9"
  but gives no work title. The upstream TOML has no source_url or
  source_title. No matching passage found in Isidore's known digitised
  works (Etymologiae, Sententiae, De ecclesiasticis officiis) via primary
  source check. Single-signal inference only.

  Confidence: MEDIUM -- left blank per curation rules.

--- Group C: Exodus 9:9 (MEDIUM confidence -- not patched) ---

  isidore-of-seville.Exod.9.9.unknown

  Quote ends with "Questions on the Old Testament, Exodus" embedded in
  the quote text itself -- a data artefact where the source citation was
  not separated from the quote content in the upstream database.

  The work name is almost certainly "Questions on the Old Testament" (the
  same work as the other 9 Exodus entries). However:

    1. The other Exodus entries carry section-specific titles (e.g.
       "Questions on the Old Testament, Ex 14:1-2") -- not just "Exodus".
    2. The question number for Exod 9:9 cannot be determined from the
       embedded text alone, and no primary-source URL is available to
       verify the exact section.

  Without confirming the question/section number from a scan of Isidore's
  Quaestiones in Vetus Testamentum, assigning "Questions on the Old
  Testament, Exodus" (without section ref) would be less specific than
  existing entries, and assigning "Questions on the Old Testament, Ex 9:9"
  would be an unverified inference.

  Confidence: MEDIUM -- left blank per curation rules.

--- Mark 16:5 (MEDIUM confidence -- not patched) ---

  isidore-of-seville.Mark.16.5.unknown

  Quote: "Why a 'young man'? The resurrection of the dead, as the apostle
  declares, will be 'unto the fullness of the measure of the stature of
  Christ,' that is, in the season of youth..."

  historicalchristian.faith labels this "Isidore of Seville on Mark 16:5"
  but gives no work title. The quote is not in the Catena Aurea on Mark
  (verified: no Isidore attribution appears in Mark 16 Catena Aurea).
  The passage's content (allegorical reading of resurrection age) is
  consistent with Isidore's Allegoriae quaedam Scripturae Sacrae or
  Quaestiones, but no primary-source URL or work title is in the upstream
  TOML. Single-signal inference only.

  Confidence: MEDIUM -- left blank per curation rules.

--- Spot-checked against primary source ---

  - isidore-of-seville.Luke.6.1.unknown
    URL: https://historicalchristian.faith/by_father.php?file=Thomas%2520Aquinas
         %2FCatena%2520Aurea%2FCommentary%2520on%2520Luke%2FChapter%25206.html
    Result: CONFIRMED misattribution. Quote text matches exactly but heading
    reads "ISIDORE OF PELEUSIUM" not Isidore of Seville.

  - isidore-of-seville.Luke.9.10.unknown
    URL: https://historicalchristian.faith/by_father.php?file=Thomas%2520Aquinas
         %2FCatena%2520Aurea%2FCommentary%2520on%2520Luke%2FChapter%25209.html
    Result: CONFIRMED misattribution. "ISIDORE OF PELEUSIUM. (l.I. ep. 233.)"

  - isidore-of-seville.Luke.24.25.unknown
    URL: https://historicalchristian.faith/by_father.php?file=Thomas%2520Aquinas
         %2FCatena%2520Aurea%2FCommentary%2520on%2520Luke%2FChapter%252024.html
    Result: CONFIRMED misattribution. "ISIDORE OF PELEUSIUM. (lib. iii. Ep. 98.)"

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "isidore-of-seville.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# All 12 missing entries are excluded:
#   - 9 Luke entries: wrong author (Isidore of Pelusium, not Seville)
#   - Acts 5:9, Mark 16:5, Exod 9:9: MEDIUM confidence only
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {}


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
    print("  (12 entries intentionally left blank -- see docstring for reasons)")
    print("  NOTE: 9 Luke entries are likely misattributed to Isidore of Seville;")
    print("  primary author is Isidore of Pelusium (verified via Catena Aurea).")

    # No writes needed -- patch is empty
    print("\nNo changes written (PATCH dict is empty).")

    # Run validator to confirm clean state
    print("\nRunning validate.py ...")
    try:
        subprocess.run(
            ["py", "-3", str(VALIDATE_SCRIPT),
             "data/church-fathers/isidore-of-seville.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 0, f"Expected 0 patch entries, got {len(PATCH)}"
    main()
