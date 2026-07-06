"""
Patch source_title for John Chrysostom blank entries (55 entries).

Assignment logic (in priority order):
1. Explicit source clue embedded in quote text (e.g. ends with "Homilies on Genesis")
2. Verse-based inference (Genesis 2-4 = Homilies on Genesis, confirmed by Gen.20.9 + Gen.31.30)
3. Series/adjacent-entry inference (Luke 16 Lazarus = Homilies on Lazarus and the Rich Man)
4. Content-based inference with low confidence (noted per-entry)

Confidence tiers:
  HIGH   -- explicit attribution clue in quote text, or strong adjacent-entry confirmation
  MEDIUM -- verse context + content clearly matches work; no conflicting evidence
  LOW    -- best-guess fallback; noted as unverified

Post-hoc verification notes (2026-04-07):
  - All Genesis 2-4 entries: Homilies on Genesis confirmed via Gen.20.9 and Gen.31.30
    TOML files (both end with explicit "Homilies on Genesis" citation)
  - Dan.3.29: TOML ends with '- "On the Obscurity of Prophecies 2.9"' -- explicit
  - Job.2.10: TOML ends with '- "Commentary on Job 2.10c"' -- explicit
  - Jonah.3.7: TOML ends with "(Concerning Statues Homily III. 9)" -- explicit
  - Luke 16 Lazarus homilies: Homily numbers confirmed by content (numbered openings
    "1. Yesterday...", "1. I was pleased yesterday...", etc.) and existing entries for
    homilies 1, 3, 4, 6 in other book files confirm the series numbering
  - Commentary on Isaiah (Isa.2.1): adjacent entries Isa.1.5, 1.7-8, 2.7-8 all confirmed
    as Commentary on Isaiah -- same exegetical format

Run twice to verify idempotency (TEST-05).
"""

import json
from collections import Counter
from pathlib import Path

INPUT_FILE = Path(__file__).parent.parent.parent / "data" / "church-fathers" / "john-chrysostom.json"
OUTPUT_FILE = INPUT_FILE  # patch in place

# ---------------------------------------------------------------------------
# Confidence tier constants
# ---------------------------------------------------------------------------
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

# ---------------------------------------------------------------------------
# Entry-level overrides: entry_id -> (source_title, confidence)
#
# HIGH   = explicit attribution clue in quote text, or strong adjacent-entry evidence
# MEDIUM = verse context + content clearly matches; plausible but not independently verified
# LOW    = best-guess fallback; requires follow-up verification
# ---------------------------------------------------------------------------
OVERRIDES: dict[str, tuple[str, str]] = {

    # ==========================================================================
    # GENESIS -- Homilies on Genesis
    # All Gen.2-4 entries are from the Homilies on Genesis:
    # - Gen.20.9 TOML ends with "Homilies on Genesis" (explicit citation)
    # - Gen.31.30 TOML ends with "Homilies on Genesis" (explicit citation)
    # - Gen.2-4 entries share the same homily style (direct address "dearly beloved",
    #   commentary on Moses, sequential from prior "yesterday's sermon")
    # ==========================================================================
    "john-chrysostom.Gen.2.4.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.2.5.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.2.7.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.2.9.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.2.15.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.2.16.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.2.19.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.2.20.unknown": ("HOMILIES ON GENESIS", HIGH),

    # Duplicate block -- same homily, second quote block for the same verse
    "john-chrysostom.Gen.2.20.unknown-2": ("HOMILIES ON GENESIS", HIGH),

    "john-chrysostom.Gen.2.21.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.2.23.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.2.25.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.1.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.2.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.4.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.6.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.7.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.8.unknown":  ("HOMILIES ON GENESIS", HIGH),

    # Duplicate block -- two separate commentary blocks on Gen 3:8
    "john-chrysostom.Gen.3.8.unknown-2": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.8.unknown-3": ("HOMILIES ON GENESIS", HIGH),

    "john-chrysostom.Gen.3.9.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.10.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.11.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.13.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.14.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.17.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.20.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.21.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.3.24.unknown": ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.4.1.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.4.2.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.4.3.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.4.4.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.4.5.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.4.6.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.4.7.unknown":  ("HOMILIES ON GENESIS", HIGH),

    # Explicit "Homilies on Genesis" citation at end of TOML quote text
    "john-chrysostom.Gen.20.9.unknown":  ("HOMILIES ON GENESIS", HIGH),
    "john-chrysostom.Gen.31.30.unknown": ("HOMILIES ON GENESIS", HIGH),

    # ==========================================================================
    # DANIEL
    # ==========================================================================

    # TOML quote ends with: - "On the Obscurity of Prophecies 2.9"
    "john-chrysostom.Dan.3.29.unknown": ("ON THE OBSCURITY OF PROPHECIES 2:9", HIGH),

    # TOML quote starts with paraphrase attributed to "Fr. Most" then Chrysostom text:
    # "God also contributed His strength to it. For it was not God's doing only..."
    # Theme: human initiative as prerequisite for divine grace (synergy). The Statues
    # homilies discuss the three young men in homilies 4 and 6 but the specific passage
    # was not found there. Chrysostom's Commentary on Daniel (PG 56.193-246) is a
    # better fit -- covers Daniel 1 in context. Section number unconfirmed (not digitised).
    # LOW confidence pending independent verification.
    "john-chrysostom.Dan.1.16.unknown": ("COMMENTARY ON DANIEL", LOW),

    # ==========================================================================
    # JOB
    # ==========================================================================

    # TOML quote ends with: - "Commentary on Job 2.10c"
    "john-chrysostom.Job.2.10.unknown": ("COMMENTARY ON JOB 2:10C", HIGH),

    # ==========================================================================
    # JONAH
    # ==========================================================================

    # Very short comment on Jonah 1:2 ("excess of their wickedness").
    # All adjacent Jonah 1 entries (1.5, 1.11, 1.12-13, 1.14) are from
    # HOMILIES ON REPENTANCE AND ALMSGIVING 3:8. Same section confirmed for
    # Jonah.1.5.unknown which has source_title already set.
    "john-chrysostom.Jonah.1.2.unknown": ("HOMILIES ON REPENTANCE AND ALMSGIVING 3:8", MEDIUM),

    # TOML quote ends with: (Concerning Statues Homily III. 9)
    "john-chrysostom.Jonah.3.7.unknown": ("HOMILIES CONCERNING THE STATUES 3:9", HIGH),

    # "For the fear was the cause of their safety. The threatening effected the deliverance..."
    # Confirmed via newadvent.org/fathers/190105.htm: exact text appears in Homily 5,
    # section 16 ("For that fear was the cause of its safety. The threatening effected
    # the deliverance from the peril... The sentence threatening death, brought forth life!").
    # "destruction" vs "overthrow" is a translation variant of the same Greek passage.
    "john-chrysostom.Jonah.3.10.unknown": ("HOMILIES CONCERNING THE STATUES 5:16", HIGH),

    # ==========================================================================
    # ISAIAH
    # ==========================================================================

    # "Judea and Jerusalem: Isaiah mentions Judea and Jerusalem..."
    # Format matches Commentary on Isaiah (topic: commentary). Adjacent entries confirm:
    # Isa.1.5 = COMMENTARY ON ISAIAH 1:3, Isa.2.7-8 = COMMENTARY ON ISAIAH 2:7.
    # Isaiah 2:1 falls within the same commentary section.
    "john-chrysostom.Isa.2.1.unknown": ("COMMENTARY ON ISAIAH 2:1", HIGH),

    # "rod of his mouth....: He is not speaking literally... employs in a spiritual sense"
    # Chrysostom explicitly interprets Isaiah 11 spiritually: Commentary on Isaiah covers
    # this chapter and uses the same "not speaking literally" / "spiritual sense" framing
    # (cf. his treatment of 11:6's wolf/lamb passage). Work is partially preserved in
    # Greek and Armenian (Fathers of the Church vol. 142, 2008); not freely digitised.
    # MEDIUM confidence -- Commentary on Isaiah is a strong content match; section unconfirmed.
    "john-chrysostom.Isa.11.4.unknown": ("COMMENTARY ON ISAIAH", MEDIUM),

    # ==========================================================================
    # AMOS
    # ==========================================================================

    # "For this very cause God accuses the Israelites more vehemently..."
    # Short comment on God holding Israel more accountable after receiving honor.
    # Chrysostom wrote a Commentary on Amos (fragmentary; PG 56, "Hermēneia eis ton Amōs").
    # No citation in TOML; Acts homilies were not confirmed as a source. Commentary on Amos
    # is the more natural home for this exegetical note. Section unconfirmed -- not digitised.
    # LOW confidence pending independent verification.
    "john-chrysostom.Amos.3.2.unknown": ("COMMENTARY ON AMOS", LOW),

    # "all the nations who are called by my name..."
    # Discussing Amos 9:12 and the calling of the Gentiles. Amos 9:12 is quoted in Acts 15:17
    # (James at the Jerusalem Council). Confirmed via CCEL text: Chrysostom discusses Amos 9:12
    # in the Recapitulation of Homily 33 on Acts, interpreting James's citation of the verse
    # as fulfillment in the calling of the Gentiles.
    "john-chrysostom.Amos.9.12.unknown": ("HOMILIES ON THE ACTS OF THE APOSTLES 33", HIGH),

    # ==========================================================================
    # LUKE
    # ==========================================================================

    # "CONCERNING DRUNKARDS AND FREQUENTERS OF TAVERNS... ALSO, CONCERNING LAZARUS..."
    # Numbered opening ("1. Yesterday, on the festival of Satan, ye celebrated...")
    # = Homily 1 of the Lazarus series. Existing dataset entries confirm the series:
    # Amos.6.4 = HOMILIES ON LAZARUS AND THE RICH MAN 1 (same homily)
    "john-chrysostom.Luke.16.19.unknown": ("HOMILIES ON LAZARUS AND THE RICH MAN 1", HIGH),

    # "1. I was pleased yesterday to see your right feeling when I entered upon
    #  the subject of Lazarus..." = Homily 2 (reference back to "yesterday's" Homily 1)
    "john-chrysostom.Luke.16.22.unknown": ("HOMILIES ON LAZARUS AND THE RICH MAN 2", HIGH),

    # "1. The parable about Lazarus has benefited us not a little, both rich and poor..."
    # = Homily 3. Existing dataset: Isa.26.12 = HOMILIES ON LAZARUS AND THE RICH MAN 3
    "john-chrysostom.Luke.16.25.unknown": ("HOMILIES ON LAZARUS AND THE RICH MAN 3", HIGH),

    # "CONCERNING THE RICH MAN AND LAZARUS... 1. To-day it is requisite that we should
    #  explain the rest of the parable concerning Lazarus." = Homily 4.
    # Existing dataset: Isa.14.27 = HOMILIES ON LAZARUS AND THE RICH MAN 4
    "john-chrysostom.Luke.16.27.unknown": ("HOMILIES ON LAZARUS AND THE RICH MAN 4", HIGH),

    # "Observe the gracious kindness of the Savior. The innocent associates with the guilty..."
    # Extended commentary on Zacchaeus (Luke 19:1-10). The Catena Aurea on Luke 19 attributes
    # this passage as "PSEUDO-CHRYS." (confirmed via StudyLight's Golden Chain Commentary on
    # Luke 19) -- this is not from a genuine Chrysostom work. The entry is retained in the
    # john-chrysostom dataset as it was found attributed under his name in the source catena.
    # Source_title flags the pseudo-attribution for downstream review.
    "john-chrysostom.Luke.19.1.unknown": ("CATENA (PSEUDO-CHRYSOSTOM)", LOW),

    # ==========================================================================
    # MARK
    # ==========================================================================

    # "He did this so that you might know that the demons would have done the same
    #  thing to human beings..."
    # Confirmed via newadvent.org/fathers/1919.htm (Three Homilies on the Devil, Homily 1,
    # section 6): "For for this reason God let them fall upon the herd of swine, in order
    # that in the case of the bodies of irrational animals you may learn their wickedness,
    # and that they would have done to the possessed the things which they did to the swine."
    # The database quote is a paraphrase/modernization of the same passage.
    "john-chrysostom.Mark.5.13.unknown": ("THREE HOMILIES CONCERNING THE POWER OF DEMONS 1:6", HIGH),

    # "When they went out of the Praetorium, Christ was carrying it: but as they
    #  proceeded Simon took it from him and bore it."
    # Brief harmonization of John 19:17 and Mark 15:21. Adjacent Mark 15.43 entry is
    # THE GOSPEL OF ST MATTHEW, HOMILY 88, which covers the passion narrative.
    # LOW confidence -- needs independent verification.
    "john-chrysostom.Mark.15.21.unknown": ("HOMILIES ON THE GOSPEL OF MATTHEW", LOW),
}

# Expected total entries in PATCH dict -- update if entries are added/removed
_EXPECTED_PATCH_COUNT = 55


def main() -> None:
    assert len(OVERRIDES) == _EXPECTED_PATCH_COUNT, (
        f"OVERRIDES has {len(OVERRIDES)} entries, expected {_EXPECTED_PATCH_COUNT}. "
        "Update _EXPECTED_PATCH_COUNT after adding or removing entries."
    )

    print(f"Loading {INPUT_FILE}")
    with open(INPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["data"]
    blank_before = sum(1 for e in entries if not e.get("source_title"))
    print(f"Blank source_title entries before patch: {blank_before}")

    patched = 0
    skipped = 0
    confidence_counts: Counter = Counter()
    patched_titles: Counter = Counter()
    unresolved: list[str] = []

    for entry in entries:
        entry_id = entry["entry_id"]
        if entry.get("source_title"):
            skipped += 1
            continue
        if entry_id in OVERRIDES:
            title, confidence = OVERRIDES[entry_id]
            entry["source_title"] = title
            patched += 1
            confidence_counts[confidence] += 1
            patched_titles[title] += 1
        else:
            unresolved.append(entry_id)

    blank_after = sum(1 for e in entries if not e.get("source_title"))

    print(f"Already populated (skipped): {skipped}")
    print(f"Patched: {patched}")
    print(f"  HIGH confidence:   {confidence_counts[HIGH]}")
    print(f"  MEDIUM confidence: {confidence_counts[MEDIUM]}")
    print(f"  LOW confidence:    {confidence_counts[LOW]}")
    print(f"Blank source_title entries after patch: {blank_after}")

    if unresolved:
        print(f"UNRESOLVED ({len(unresolved)}):")
        for eid in unresolved:
            print(f"  {eid}")
    else:
        print("All blank entries resolved.")

    if patched == 0 and not unresolved:
        print("No changes needed -- all entries already fully patched (idempotent re-run).")
        return

    if patched_titles:
        print("\nAssignment summary (titles patched this run):")
        for title, count in sorted(patched_titles.items(), key=lambda x: -x[1]):
            print(f"  {count:3d}  {title}")

    print(f"\nWriting {OUTPUT_FILE}")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("Done.")


if __name__ == "__main__":
    main()
