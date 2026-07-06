# standards: author id slug
"""Patch missing source_title for leo-the-great church_fathers entries.

2 of 10 missing entries are patched here with HIGH confidence.
8 entries are left blank -- MEDIUM or LOW confidence only.

--- Background ---

161 entries total; 10 have blank source_title.
None of the 10 blank-entry TOML files in the upstream
HistoricalChristianFaith/Commentaries-Database have source_url or
source_title. Attribution required quote-level text matching against
primary source texts.

Primary sources consulted:
  - NewAdvent.org (NPNF translation of Leo's sermons and letters)
  - HistoricalChristianFaith/Writings-Database GitHub (same NPNF translation)
  - Letter 129 verified at: https://www.newadvent.org/fathers/3604129.htm
  - Sermon 95 verified at: https://www.newadvent.org/fathers/360395.htm
    (also: https://raw.githubusercontent.com/HistoricalChristianFaith/
     Writings-Database/master/Leo%20the%20Great/Sermons/
     Sermon%2095%20A%20Homily%20on%20the%20Beatitudes%2C%20St%20Matt%205%201-9.html)


--- HIGH confidence patches (2 entries) ---

Acts.3.6.unknown -> Sermon 95.3
  Quote: "What more sublime than this humility? what richer than this poverty?"
  Sermon 95, Section III ("Scriptural Examples of Humility") contains this
  exact phrase verbatim in both NewAdvent and the GitHub source:
    "What more sublime than this humility? what richer than this poverty?
     He has not stores of money, but he has gifts of nature. He whom his
     mother had brought forth lame from the womb, is made whole by Peter
     with a word..." (Acts 3:6).
  Confidence: HIGH -- exact phrase match in primary source.

2Thess.3.2.unknown -> Letters 129.1
  Quote: "For the crafty Tempter, the Devil, delights greatly in wounding
    the hearts of men as when he can poison their unwary minds with errors
    that are opposed to Gospel Truth..."
  Letter 129 (to Proterius, Bishop of Alexandria), Section I begins:
    "...because 'all men have not faith' [2 Thess 3:2] and the crafty
    Tempter never delights so much in wounding the hearts of men as when
    he can poison their unwary minds with errors that are opposed to
    Gospel Truth..."
  The entry explicitly anchors to 2 Thess 3:2, which Letter 129 cites
  directly in this passage. Minor translation variant ('delights greatly'
  vs 'never delights so much') but otherwise phrase-identical.
  Confidence: HIGH -- phrase match plus explicit verse citation in primary
  source confirming this passage is Leo's commentary on 2 Thess 3:2.


--- MEDIUM/LOW entries left blank (8 entries) ---

Acts.3.7.unknown
  Quote: "The one whom he encouraged by word he strengthed by his right
    hand, because the discourse of a teacher is less efficacious in the
    hearts of his hearers if it is not also recommended by the example
    of his own action."
  This quote discusses Acts 3:7 (Peter lifting the lame man). The phrase
  "discourse of a teacher is less efficacious" does not appear in any of
  the 48 Leo sermons or 165 Leo letters in the GitHub corpus (NPNF
  translation). The phrasing uses a modern translation style (distinct
  from NPNF) -- likely from the FC (Fathers of the Church, CUA Press)
  series. Unable to verify primary source without access to FC vol 93.
  Confidence: LOW -- not found in any available primary source.

Acts.3.14.unknown
  Quote: "And so Pilate, willing to content the people, released Barabbas
    to them, and delivered Jesus, when he had scourged him, to be crucified."
  This is nearly verbatim Mark 15:15 (the phrase "willing to content the
  people" follows the NT text closely). Leo's Passion sermon 59 covers
  Pilate and Barabbas (Sections II and III) but uses entirely different
  phrasing. The exact phrase "willing to content the people" was searched
  across all 48 Leo sermons in the GitHub corpus: not found. Leo may be
  quoting scripture directly in a sermon not covered by NPNF. No FC or
  ACCS source accessible for verification.
  Confidence: LOW -- not found in any available primary source.

Acts.3.23.unknown
  Quote: "Peter teaches briefly but clearly by the testimony of the
    prophets and the law that the Lord is to be listened to by the nations,
    and that he will surely condemn the unbelieving, but he will grant an
    eternal blessing to the faithful."
  Not found in any Leo sermon or letter in the GitHub corpus (all 48
  sermons + 165 letters searched). Modern translation style.
  Confidence: LOW -- not found in any available primary source.

Acts.3.24.unknown
  Quote: "Although the patriarchs and saints of earlier times prophesied
    many things about Christ by their words and deeds, who wrote properly
    speaking the time of the prophets had its beginning from Samuel, under
    whom the period of the kings began in Israel, and i lasted up to the
    deliverance from the Babylonian captivity."
  Not found in any Leo sermon or letter in the GitHub corpus. Modern
  translation style. Note: the text contains a likely typo ('and i lasted'
  for 'and it lasted') suggesting OCR or transcription error.
  Confidence: LOW -- not found in any available primary source.

Col.1.13.unknown
  Quote: "'Snatched from the powers of darkness' at such a great 'price,'
    and by so great a 'mystery,' and loosed from the chains of the ancient
    captivity, make sure, dearly beloved, that the devil does not destroy
    the integrity of your souls with any stratagem..."
  The opening words ("Snatched from the powers of darkness") match Col
  1:13, and the rhetorical style (warning about devil's wiles, baptismal
  reference) is characteristic of Leo's Nativity or baptismal sermons.
  Sermon 24 contains related baptismal content but this exact passage was
  not found there or in any other Leo text in the GitHub corpus. Modern
  translation style.
  Confidence: LOW -- not found in any available primary source.

Col.1.15.unknown
  Quote: "Let those then 'who were born not from blood, nor from the will
    of the flesh, but from God' offer concord to God as peaceloving
    children. Let all the adopted members join together into that 'firstborn'
    of new 'creation'..."
  The phrase "peaceloving children" returns no results in any web or
  corpus search. The phrase "adopted members" also returns no hits.
  Modern translation style. Not found in any available Leo text.
  Confidence: LOW -- not found in any available primary source.

Col.2.9.unknown
  Quote: "Embracing then, dearly beloved, the sole pledge of the Christian
    hope, let us not be torn from our faithful bonding to the body of
    Christ, in whom, as the apostle says, 'dwells the fullness of divinity
    in bodily manner, and you have been filled out in him.' Since the
    substance of God is incorporeal, how does it dwell in bodily manner in
    Christ unless the flesh of our race has been made the flesh of the
    divinity?..."
  The phrase "sole pledge of the Christian hope" returns no results in
  any web or corpus search. Modern translation style. Not found in any
  available Leo text.
  Confidence: LOW -- not found in any available primary source.

Col.2.15.unknown
  Quote: "As renowned victor over the devil and most powerful conqueror of
    hostile spirits, in an admirable spectacle, he carried the trophy of
    his 'victory.' On the shoulders of his unconquered endurance, he bore
    the sign of salvation to be worshiped in every kingdom."
  Sermon 59, Section IV ("Christ Bearing His Own Cross is an Eternal Lesson
  to the Church") contains a passage with the same content and structure:
    "...He, the glorious vanquisher of the Devil, and the strong defeater
    of the powers that were against Him, was carrying in noble sort the
    trophy of His triumph, and on the shoulders of His unconquered patience
    bore into all realms the adorable sign of salvation..."
  Both passages close with the same scripture quotation (Matt 10:38). The
  conceptual match is strong but the phrasing differs entirely -- a
  different translation of the same Latin. Without access to the FC
  translation of Sermon 59, cannot confirm this is Section IV vs a
  different Leo sermon. MEDIUM confidence is insufficient for patching.
  Confidence: MEDIUM -- strong conceptual match but cannot verify exact
  section via accessible primary source text.


--- Spot-checked against primary source ---

  - leo-the-great.Acts.3.6.unknown
    URL: https://www.newadvent.org/fathers/360395.htm
    Also: https://raw.githubusercontent.com/HistoricalChristianFaith/
           Writings-Database/master/Leo%20the%20Great/Sermons/
           Sermon%2095%20A%20Homily%20on%20the%20Beatitudes%2C
           %20St%20Matt%205%201-9.html
    Confirmed: Sermon 95 Section III contains verbatim:
      "What more sublime than this humility? what richer than this poverty?"
      in the context of Peter healing the lame man (Acts 3:6).
    Status: CONFIRMED

  - leo-the-great.2Thess.3.2.unknown
    URL: https://www.newadvent.org/fathers/3604129.htm
    Also: https://raw.githubusercontent.com/HistoricalChristianFaith/
           Writings-Database/master/Leo%20the%20Great/Letters/
           Letter%20129%20To%20Proterius%2C%20Bishop%20of%20Alexandria.html
    Confirmed: Letter 129, Section I ("He Commends His Persistent Loyalty
      to the Faith") explicitly cites 2 Thess 3:2 and contains the phrase
      "crafty Tempter never delights so much in wounding the hearts of men
      as when he can poison their unwary minds with errors that are opposed
      to Gospel Truth". Translation variant: 'delights greatly' (entry) vs
      'never delights so much' (NPNF) -- both primary source texts confirm
      the passage.
    Status: CONFIRMED

  - leo-the-great.Col.2.15.unknown (MEDIUM -- not patched)
    URL: https://raw.githubusercontent.com/HistoricalChristianFaith/
           Writings-Database/master/Leo%20the%20Great/Sermons/
           Sermon%2059%20(on%20the%20Passion%2C%208%3A%20on%20Wednesday
           %20in%20Holy%20Week).html
    Checked: Sermon 59, Section IV ("Christ Bearing His Own Cross") contains
      the same conceptual content (trophy, sign of salvation, cross-bearing),
      but in a different translation. Cannot confirm without the FC text.
    Status: MEDIUM -- not patched per curation rules.

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "leo-the-great.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
#
# 2 entries patched:
#   Acts.3.6  -- Sermon 95, Section III (exact phrase match, NewAdvent + GitHub)
#   2Thess.3.2 -- Letter 129, Section I (phrase match + explicit 2Thess 3:2
#                 citation in the primary source text)
#
# 8 entries left blank (not found in any accessible Leo text):
#   Acts.3.7, Acts.3.14, Acts.3.23, Acts.3.24 -- not in NPNF corpus
#   Col.1.13, Col.1.15, Col.2.9 -- not in NPNF corpus
#   Col.2.15 -- MEDIUM only (Sermon 59.4 match, different translation)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # Sermon 95, Section III -- "Scriptural Examples of Humility"
    # Peter heals lame man: "What more sublime than this humility?" (Acts 3:6)
    "leo-the-great.Acts.3.6.unknown": "Sermon 95.3",
    # Letter 129, Section I -- to Proterius of Alexandria
    # Commentary on 2 Thess 3:2 ("all men have not faith")
    "leo-the-great.2Thess.3.2.unknown": "Letters 129.1",
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
    print("  (8 entries intentionally left blank -- MEDIUM or LOW confidence)")
    print("  Acts.3.7, Acts.3.14, Acts.3.23, Acts.3.24 -- not found in NPNF corpus")
    print("  Col.1.13, Col.1.15, Col.2.9 -- not found in NPNF corpus")
    print("  Col.2.15 -- MEDIUM (Sermon 59.4 likely but different translation, unverified)")

    if set_count > 0:
        print(f"\nWriting {DATA_FILE}")
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("Done.")
    else:
        print("\nNo changes to write (all entries already set or patch is empty).")

    # Run validator
    print("\nRunning validate.py ...")
    try:
        subprocess.run(
            ["py", "-3", str(VALIDATE_SCRIPT),
             "data/church-fathers/leo-the-great.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 2, f"Expected 2 patch entries, got {len(PATCH)}"
    main()
