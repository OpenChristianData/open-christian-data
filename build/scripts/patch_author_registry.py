"""
patch_author_registry.py
------------------------
Applies verified corrections to the author registry after a systematic
cross-check of all 250 church-father entries against Wikipedia, Britannica,
CCEL, Catholic Encyclopedia, and OrthodoxWiki (March 2026).

Run with:  py -3 build/scripts/patch_author_registry.py

Idempotent: each patch checks the current value before writing; if the
registry already holds the correct value, the change is skipped.

Sources cited inline per correction.
"""

import json
import copy
import os
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = str(REPO_ROOT / "data" / "authors" / "registry.json")

# ---------------------------------------------------------------------------
# Patches
# Each entry is a dict:
#   author_id   : str
#   field       : str  -- the top-level key to update
#   old_value   : any  -- expected current value (skip if mismatch)
#   new_value   : any  -- replacement value
#   reason      : str  -- human-readable justification + source
# ---------------------------------------------------------------------------
PATCHES = [

    # =========================================================================
    # ANDREAS OF CAESAREA
    # Death year 637 is wrong.  Wikipedia gives c.563-614; Britannica says
    # "fl. early 6th century"; scholarly dates are genuinely disputed
    # (Karl Krumbacher places him 5th-9th c).  We clear the death year to null
    # and update the notes to reflect the uncertainty and the better estimate.
    # Source: https://en.wikipedia.org/wiki/Andreas_of_Caesarea
    # =========================================================================
    {
        "author_id": "andreas-of-caesarea",
        "field": "death_year",
        "old_value": 637,
        "new_value": None,
        "reason": (
            "Wikipedia gives c.563-614; Britannica says 'early 6th c.'; "
            "637 is unsupported. Dates genuinely disputed. Cleared to null. "
            "Source: en.wikipedia.org/wiki/Andreas_of_Caesarea"
        ),
    },
    {
        "author_id": "andreas-of-caesarea",
        "field": "birth_year",
        "old_value": 563,
        "new_value": None,
        "reason": (
            "Birth year also uncertain. Wikipedia gives c.563 as one estimate "
            "but scholarly opinion ranges widely. Cleared to null consistent "
            "with death_year. "
            "Source: en.wikipedia.org/wiki/Andreas_of_Caesarea"
        ),
    },
    {
        "author_id": "andreas-of-caesarea",
        "field": "notes",
        "old_value": (
            "Bishop of Caesarea in Cappadocia; author of an important commentary "
            "on Revelation. Dates approximate."
        ),
        "new_value": (
            "Bishop of Caesarea in Cappadocia; author of an important commentary "
            "on Revelation. Exact dates unknown; scholarly estimates range from "
            "the 5th to the 7th century; Wikipedia gives c.563-614 as one "
            "estimate. His commentary on Revelation became the standard Eastern "
            "text type."
        ),
        "reason": (
            "Updated notes to reflect scholarly uncertainty. "
            "Source: en.wikipedia.org/wiki/Andreas_of_Caesarea"
        ),
    },

    # =========================================================================
    # ARETHAS OF CAESAREA
    # Death year 935 is wrong. Wikipedia gives c.939; Catholic Encyclopedia
    # gives 932 as the latest known date. 935 is unsupported.
    # Source: https://en.wikipedia.org/wiki/Arethas_of_Caesarea
    # =========================================================================
    {
        "author_id": "arethas-of-caesarea",
        "field": "death_year",
        "old_value": 935,
        "new_value": 939,
        "reason": (
            "Wikipedia gives c.939; Cath. Enc. gives last known date as 932. "
            "935 is not supported by either. Closest rounded figure is 939. "
            "Source: en.wikipedia.org/wiki/Arethas_of_Caesarea"
        ),
    },

    # =========================================================================
    # THEOPHYLACT OF OHRID
    # Death year 1126 is wrong. Wikipedia says 'after 1107'; Britannica says
    # c.1109; OrthodoxWiki says latest evidence is 1108. No source supports 1126.
    # Source: https://en.wikipedia.org/wiki/Theophylact_of_Ohrid
    # =========================================================================
    {
        "author_id": "theophylact-of-ohrid",
        "field": "death_year",
        "old_value": 1126,
        "new_value": None,
        "reason": (
            "Wikipedia says 'died after 1107'; Britannica c.1109; OrthodoxWiki "
            "says last evidence is 1108. No source supports 1126. Cleared to "
            "null with note. "
            "Source: en.wikipedia.org/wiki/Theophylact_of_Ohrid"
        ),
    },
    {
        "author_id": "theophylact-of-ohrid",
        "field": "notes",
        "old_value": (
            "Archbishop of Ohrid; Byzantine exegete; wrote commentaries on "
            "the NT and on several OT books. Dates approximate."
        ),
        "new_value": (
            "Archbishop of Ohrid; Byzantine exegete; wrote commentaries on "
            "the NT and on several OT books. Exact death date unknown; "
            "Wikipedia says 'after 1107', Britannica gives c.1109; "
            "no source supports 1126."
        ),
        "reason": (
            "Updated notes to flag that 1126 is wrong and document the "
            "conflicting scholarly dates. "
            "Source: en.wikipedia.org/wiki/Theophylact_of_Ohrid"
        ),
    },

    # =========================================================================
    # WALAFRID STRABO
    # Notes incorrectly state he 'compiled the Glossa Ordinaria'. This
    # attribution is now rejected: the Glossa Ordinaria was produced at the
    # school of Anselm of Laon in the 12th century. Medieval misattribution
    # goes back to Trithemius (1494/1496). Wikipedia and modern scholarship
    # are clear on this.
    # Source: https://en.wikipedia.org/wiki/Walafrid_Strabo
    #         https://en.wikipedia.org/wiki/Glossa_Ordinaria
    # =========================================================================
    {
        "author_id": "walafrid-strabo",
        "field": "notes",
        "old_value": (
            "Benedictine monk and abbot of Reichenau; compiled the Glossa "
            "Ordinaria; poet and theologian."
        ),
        "new_value": (
            "Benedictine monk and abbot of Reichenau; poet and theologian. "
            "The Glossa Ordinaria is now attributed to the school of Anselm "
            "of Laon (12th century), not to Strabo; the misattribution goes "
            "back to Trithemius (c.1494). Some of Strabo's Carolingian "
            "glosses were absorbed into the later Glossa. "
            "Source: en.wikipedia.org/wiki/Walafrid_Strabo"
        ),
        "reason": (
            "Corrected wrong attribution of the Glossa Ordinaria to Strabo. "
            "Modern scholarship (and Wikipedia) clearly attributes it to "
            "Anselm of Laon's school. "
            "Sources: en.wikipedia.org/wiki/Walafrid_Strabo, "
            "en.wikipedia.org/wiki/Glossa_Ordinaria"
        ),
    },

    # =========================================================================
    # AGAPIUS OF HIERAPOLIS
    # Tradition is ['patristic'] but Agapius died after 942 -- well past the
    # 1054 schism AND well past the 'patristic' era. He was a Melkite bishop
    # (Eastern Christian in communion with Constantinople). Per the edge-case
    # rules, post-schism Eastern figures should have 'orthodox'. As a 10th-c
    # figure he should not be 'patristic' at all.
    # Also: notes say "10th-century" which is correct but should be more specific.
    # Source: https://en.wikipedia.org/wiki/Agapius_of_Hierapolis
    # =========================================================================
    {
        "author_id": "agapius-of-hierapolis",
        "field": "tradition",
        "old_value": ["patristic"],
        "new_value": ["orthodox"],
        "reason": (
            "Agapius died after 942, a 10th-century Melkite bishop. Per spec "
            "rules: (1) post-schism Eastern figures get 'orthodox', not "
            "'patristic'; (2) he lived 500 years after the patristic era. "
            "Melkite = Eastern in communion with Constantinople = orthodox. "
            "Source: en.wikipedia.org/wiki/Agapius_of_Hierapolis"
        ),
    },

    # =========================================================================
    # JOHN WESLEY
    # Tradition is ['methodist', 'arminian']. Wesley was ordained as an
    # Anglican priest and never formally left the Church of England; he
    # consistently identified as Anglican throughout his life. 'wesleyan'
    # should also be included as it is the tradition he founded. Adding
    # 'anglican' and 'wesleyan'.
    # Source: https://en.wikipedia.org/wiki/John_Wesley
    # =========================================================================
    {
        "author_id": "john-wesley",
        "field": "tradition",
        "old_value": ["methodist", "arminian"],
        "new_value": ["methodist", "wesleyan", "arminian", "anglican"],
        "reason": (
            "Wesley was ordained Anglican, remained Anglican his entire life, "
            "and never separated from the Church of England. He is also the "
            "founder of the Wesleyan tradition. Both 'wesleyan' and 'anglican' "
            "should be present. "
            "Source: en.wikipedia.org/wiki/John_Wesley"
        ),
    },

    # =========================================================================
    # CS LEWIS
    # Nationality is 'British'. Lewis was born in Belfast (then part of Ireland,
    # now Northern Ireland) and self-identified as Irish/Ulsterman throughout
    # his life, correcting people who called him English.  Wikipedia describes
    # him as a 'British-Irish author' in the opening sentence. The more accurate
    # single-word nationality for this registry is 'Irish' (he held a British
    # passport as a Northern Irish subject, but his self-identification was Irish).
    # Source: https://en.wikipedia.org/wiki/C._S._Lewis
    # =========================================================================
    {
        "author_id": "cs-lewis",
        "field": "nationality",
        "old_value": "British",
        "new_value": "Irish",
        "reason": (
            "Lewis was born in Belfast, Ireland (pre-partition), and "
            "self-identified as Irish/Ulsterman his whole life. Wikipedia "
            "opens with 'British-Irish author'. Single-word 'Irish' is "
            "more precise and matches his self-identification. "
            "Source: en.wikipedia.org/wiki/C._S._Lewis"
        ),
    },

    # =========================================================================
    # HAIMO OF AUXERRE
    # Birth year 840 appears to be fabricated -- no source gives a birth year
    # for Haimo. He is known only from his work, which places him as active
    # at Saint-Germain d'Auxerre; the approximate death is c.865 (Wikipedia)
    # or c.855 (some sources). Birth year cleared to null.
    # Source: https://en.wikipedia.org/wiki/Haimo_of_Auxerre
    # =========================================================================
    {
        "author_id": "haimo-of-auxerre",
        "field": "birth_year",
        "old_value": 840,
        "new_value": None,
        "reason": (
            "No source gives a birth year for Haimo of Auxerre. The '840' "
            "is likely a fabricated estimate. Birth year cleared to null. "
            "Source: en.wikipedia.org/wiki/Haimo_of_Auxerre"
        ),
    },

    # =========================================================================
    # AGAPIUS OF HIERAPOLIS -- notes
    # Notes say 'author of Kitab al-Unwan' which is correct; also update
    # the tradition note to reflect he was Melkite.
    # =========================================================================
    {
        "author_id": "agapius-of-hierapolis",
        "field": "notes",
        "old_value": (
            "10th-century Arab Christian bishop and historian; author of "
            "'Kitab al-Unwan'. Exact dates unknown."
        ),
        "new_value": (
            "10th-century Melkite Arab Christian bishop of Manbij (Hierapolis) "
            "and historian; author of the universal history 'Kitab al-Unwan' "
            "(Book of the Title), written in Arabic. Died after 942. "
            "Source: en.wikipedia.org/wiki/Agapius_of_Hierapolis"
        ),
        "reason": (
            "Corrected 'bishop' to be more specific (bishop of Manbij); "
            "added 'Melkite' for precision; added confirmed death constraint "
            "(after 942). "
            "Source: en.wikipedia.org/wiki/Agapius_of_Hierapolis"
        ),
    },

    # =========================================================================
    # SEVERUS OF ANTIOCH
    # Tradition is ['patristic', 'orthodox']. Severus died 538 (before 1054
    # schism), so per spec rules he should be 'patristic' only UNLESS there is
    # strong reason. He is, however, the defining theologian of Oriental
    # Orthodoxy (Miaphysitism / Syriac Orthodox tradition) -- he is venerated
    # specifically by Oriental Orthodox, not Eastern Orthodox (Chalcedonian).
    # 'orthodox' in the enum is intended for Eastern Orthodox (Chalcedonian).
    # For pre-schism figures like Severus who define a separate tradition,
    # 'patristic' alone is appropriate per spec. However, since he is
    # specifically foundational to the Syriac Orthodox / Oriental Orthodox
    # tradition, adding a note is preferable to changing the tradition array
    # (which would mean removing 'orthodox'). This is a spec-edge-case.
    # DECISION: Keep ['patristic', 'orthodox'] but fix notes to clarify.
    # Actually per spec: "pre-schism figures (died before 1054): tradition =
    # ['patristic'] only". Severus died 538. Correcting to ['patristic'].
    # =========================================================================
    {
        "author_id": "severus-of-antioch",
        "field": "tradition",
        "old_value": ["patristic", "orthodox"],
        "new_value": ["patristic"],
        "reason": (
            "Per spec: pre-schism figures (died before 1054) use 'patristic' "
            "only. Severus died 538. He is foundational to Oriental Orthodoxy "
            "(Miaphysite), not Eastern Orthodoxy (Chalcedonian) -- so 'orthodox' "
            "in the Chalcedonian-tradition sense is a mismatch anyway. "
            "Tradition corrected to ['patristic']; note remains. "
            "Source: en.wikipedia.org/wiki/Severus_of_Antioch"
        ),
    },

    # =========================================================================
    # JACOB OF EDESSA
    # Tradition ['patristic', 'orthodox']. Jacob died 708, before the 1054
    # schism. Per spec: pre-schism figures use 'patristic' only unless there
    # is a strong reason. He was Syriac Orthodox (miaphysite), not Eastern
    # Orthodox (Chalcedonian). Correcting to ['patristic'].
    # Source: https://en.wikipedia.org/wiki/Jacob_of_Edessa
    # =========================================================================
    {
        "author_id": "jacob-of-edessa",
        "field": "tradition",
        "old_value": ["patristic", "orthodox"],
        "new_value": ["patristic"],
        "reason": (
            "Per spec: pre-schism figures (died 708, before 1054) use "
            "'patristic' only. Jacob was Syriac Orthodox (miaphysite), "
            "not Eastern Orthodox (Chalcedonian). "
            "Source: en.wikipedia.org/wiki/Jacob_of_Edessa"
        ),
    },

    # =========================================================================
    # COSMAS OF MAIUMA
    # Tradition ['patristic', 'orthodox']. Cosmas died c.752, before 1054.
    # Per spec: pre-schism figures use 'patristic' only. He was Byzantine
    # but his death predates the schism.
    # Source: https://en.wikipedia.org/wiki/Cosmas_of_Jerusalem
    # =========================================================================
    {
        "author_id": "cosmas-of-maiuma",
        "field": "tradition",
        "old_value": ["patristic", "orthodox"],
        "new_value": ["patristic"],
        "reason": (
            "Per spec: pre-schism figures (died c.752, before 1054) use "
            "'patristic' only, unless strong reason. Cosmas is a Byzantine "
            "hymnographer but pre-dates the schism. "
            "Source: en.wikipedia.org/wiki/Cosmas_of_Jerusalem"
        ),
    },

    # =========================================================================
    # JOHN DAMASCENE
    # Tradition ['patristic', 'orthodox']. John died c.749, before 1054.
    # Per spec: pre-schism use 'patristic' only. He is closely associated
    # with Eastern Orthodoxy but his death predates the schism.
    # HOWEVER: spec says "unless there is a strong reason." John Damascene
    # is perhaps the strongest possible case -- he is the last of the Church
    # Fathers and is considered the great systematiser of Eastern Orthodoxy.
    # The Orthodox Church venerates him specifically as a Father of Orthodoxy.
    # DECISION: The spec wording acknowledges exceptions. Keeping ['patristic',
    # 'orthodox'] for John Damascene, John of Dalyatha, Andrew of Crete,
    # Maximus the Confessor, Romanos the Melodist, and Sophronius -- all of whom
    # are deeply formative for Eastern Orthodoxy specifically. These are the
    # "strong reason" exceptions. The others (Cosmas, Jacob of Edessa, Severus)
    # do not have the same justification.
    # =========================================================================
    # NO CHANGE for john-damascene, maximus-the-confessor, andrew-of-crete,
    # john-of-dalyatha, romanos-the-melodist, sophronius-of-jerusalem
    # They are pre-schism but have strong reason to retain 'orthodox'.

    # =========================================================================
    # ABBA POEMEN
    # Tradition ['patristic', 'orthodox']. Poemen was c.4th-5th century
    # (estimated birth c.340, death c.450), solidly pre-schism. Desert Fathers
    # are quintessentially "patristic". However, Abba Poemen is venerated in
    # Eastern Orthodoxy and his sayings are foundational to the Orthodox
    # monastic tradition -- a stronger argument for keeping 'orthodox'.
    # DECISION: This is a boundary case. The spec says "strong reason" applies.
    # Poemen is not as doctrinally Orthodox-defining as Damascene. Correcting
    # to ['patristic'] per the spec default.
    # Source: https://en.wikipedia.org/wiki/Poemen
    # =========================================================================
    {
        "author_id": "abba-poemen",
        "field": "tradition",
        "old_value": ["patristic", "orthodox"],
        "new_value": ["patristic"],
        "reason": (
            "Per spec: pre-schism figures use 'patristic' only. Poemen lived "
            "c.4th-5th century, well before 1054. He is a Desert Father "
            "(Egyptian monastic) -- the 'strong reason' exception does not "
            "apply here as clearly as for Damascene. "
            "Source: en.wikipedia.org/wiki/Poemen"
        ),
    },

    # =========================================================================
    # ISAAC OF NINEVEH
    # Tradition ['patristic', 'orthodox']. Isaac died c.700, before 1054.
    # He was a bishop of the Church of the East (Nestorian / East Syriac),
    # NOT Eastern Orthodox (Chalcedonian). Adding 'orthodox' to his tradition
    # is historically inaccurate for him specifically. Correcting to ['patristic'].
    # Source: https://en.wikipedia.org/wiki/Isaac_the_Syrian
    # =========================================================================
    {
        "author_id": "isaac-of-nineveh",
        "field": "tradition",
        "old_value": ["patristic", "orthodox"],
        "new_value": ["patristic"],
        "reason": (
            "Isaac of Nineveh was a bishop of the Church of the East "
            "(East Syriac / Nestorian), not Eastern Orthodox (Chalcedonian). "
            "Per spec: pre-schism (died c.700) use 'patristic' only. "
            "Source: en.wikipedia.org/wiki/Isaac_the_Syrian"
        ),
    },

    # =========================================================================
    # PHOTIOS I OF CONSTANTINOPLE
    # Tradition ['patristic', 'orthodox']. Photios died 893, before 1054.
    # He is deeply central to Eastern Orthodoxy (Photian Schism, patriarch).
    # DECISION: This is a "strong reason" exception -- keep ['patristic',
    # 'orthodox']. No change.
    # =========================================================================

    # =========================================================================
    # DESERT FATHERS
    # Tradition ['patristic', 'orthodox']. The Desert Fathers tradition (c.3rd-
    # 5th centuries) is pre-schism. However it IS foundational to Orthodox
    # monasticism. DECISION: keep ['patristic', 'orthodox'] as exception.
    # =========================================================================

    # =========================================================================
    # MAXIMUS THE CONFESSOR (no change -- strong reason exception applies)
    # ANDREW OF CRETE (no change -- strong reason exception applies)
    # JOHN OF DALYATHA (no change -- strong reason exception applies)
    # ROMANOS THE MELODIST (no change -- strong reason exception applies)
    # =========================================================================

    # =========================================================================
    # DHUODA OF SEPTIMANIA
    # Tradition ['patristic'] but she died c.843, well after the patristic era
    # (which is generally considered to end by the 8th century at the latest).
    # She was a medieval Frankish laywoman writer. Per spec: post-schism Western
    # figures in communion with Rome use 'catholic'. She died before 1054 but
    # is clearly medieval, not patristic. However the spec only says to add
    # 'catholic' for post-1054 figures. For pre-1054 medieval (post-patristic)
    # figures the spec doesn't give a rule. Keeping 'patristic' for now as the
    # closest available enum value. No change.
    # =========================================================================

    # =========================================================================
    # ANSELM OF CANTERBURY
    # Tradition ['patristic', 'catholic']. Per spec: post-1054 Western figures
    # in communion with Rome should have 'catholic'. He died 1109, post-schism.
    # 'patristic' is debatable for 11th-century scholastics -- the spec doesn't
    # prohibit it and CCEL includes him in patristic collections. Keeping as-is.
    # =========================================================================

    # =========================================================================
    # MAXIMUS OF TURIN
    # Notes and death year: the registry has d=423. Wikipedia confirms there
    # are two bishops named Maximus; the one whose homilies are in CCEL is
    # generally the one associated with the early 5th century (d. c.408-423).
    # The death_year of 423 is defensible as an approximate for the earlier
    # Maximus. No change.
    # =========================================================================

    # =========================================================================
    # THOMAS AQUINAS -- no nationality recorded (null). He was Italian.
    # Per spec: modern/Reformation figures should have known nationality.
    # Thomas Aquinas (1225-1274) is medieval, not post-1500, so null is correct
    # per the "ancient/medieval = null" rule. No change.
    # =========================================================================

]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def apply_patches(authors, patches):
    """Apply each patch if the current value matches old_value. Returns counts."""
    # Build lookup: author_id -> index in list
    index = {a["author_id"]: i for i, a in enumerate(authors)}

    applied = 0
    skipped_mismatch = 0
    skipped_already_correct = 0
    not_found = 0
    log = []

    for patch in patches:
        aid = patch["author_id"]
        field = patch["field"]
        old_v = patch["old_value"]
        new_v = patch["new_value"]
        reason = patch["reason"]

        if aid not in index:
            not_found += 1
            log.append(f"NOT FOUND: {aid}")
            continue

        author = authors[index[aid]]
        current = author.get(field)

        # Already at new value -- skip (idempotent)
        if current == new_v:
            skipped_already_correct += 1
            log.append(f"SKIP (already correct): {aid}.{field} = {repr(new_v)}")
            continue

        # Current doesn't match expected old value -- skip (safety)
        if current != old_v:
            skipped_mismatch += 1
            log.append(
                f"SKIP (mismatch): {aid}.{field} "
                f"expected {repr(old_v)!s:.80} "
                f"but got {repr(current)!s:.80}"
            )
            continue

        # Apply patch
        author[field] = new_v
        applied += 1
        log.append(f"PATCHED: {aid}.{field}: {repr(old_v)!s:.60} -> {repr(new_v)!s:.60}")
        log.append(f"  reason: {reason[:120]}")

    return applied, skipped_mismatch, skipped_already_correct, not_found, log


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    start = time.time()

    print("patch_author_registry.py -- applying verified corrections")
    print(f"Registry: {REGISTRY_PATH}")
    print(f"Patches defined: {len(PATCHES)}")
    print("")

    # Load registry
    if not os.path.exists(REGISTRY_PATH):
        print(f"ERROR: Registry file not found at {REGISTRY_PATH}")
        return

    with open(REGISTRY_PATH, encoding="utf-8") as f:
        data = json.load(f)

    authors = data["authors"]
    print(f"Loaded {len(authors)} authors from registry.")
    print("")

    # Take a deep copy for comparison / rollback
    original_authors = copy.deepcopy(authors)

    # Apply patches
    applied, skipped_mismatch, skipped_correct, not_found, log = apply_patches(
        authors, PATCHES
    )

    # Print patch log
    for line in log:
        print(line)

    print("")
    print("-" * 60)
    print(f"Applied  : {applied}")
    print(f"Skip (already correct): {skipped_correct}")
    print(f"Skip (mismatch -- current value unexpected): {skipped_mismatch}")
    print(f"Not found: {not_found}")
    print("")

    if applied == 0:
        print("No changes to write -- registry already up to date.")
    else:
        # Save
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Registry saved with {applied} corrections applied.")

    elapsed = time.time() - start
    print(f"Done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
