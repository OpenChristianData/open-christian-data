"""selftest.py -- standalone selftest for the OCR error scanner.

Run: py -3 build/tools/ocr_scanner/selftest.py
Exit non-zero on any failure.

This selftest is written BEFORE the implementation (TDD). It will fail with
ImportError until Tasks 2-4 provide patterns.py and scanner.py.
"""
import sys
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

# These imports will fail until Tasks 2-4 are complete -- expected.
from build.tools.ocr_scanner import patterns, scanner  # noqa: E402

PASS = 0
FAIL = 0


def ok(label: str) -> None:
    global PASS
    PASS += 1
    print(f"  PASS  {label}")


def fail(label: str, detail: str = "") -> None:
    global FAIL
    FAIL += 1
    msg = f"  FAIL  {label}"
    if detail:
        msg += f": {detail}"
    print(msg)


# ===========================================================================
# SECTION 1: Regex sanity block -- runs first, before fixture-based tests.
# Each compiled detector regex tested against ONE match + ONE non-match.
# Catches character-class typos, flag-bleed, boundary surprises early.
# ===========================================================================

def _regex_sanity():
    print("\n-- Regex sanity block --")

    # digit_in_letter
    r = patterns._DIGIT_IN_LETTER_RE
    if r.match("THE0T0K0S"):
        ok("_DIGIT_IN_LETTER_RE matches THE0T0K0S")
    else:
        fail("_DIGIT_IN_LETTER_RE matches THE0T0K0S", "expected match, got none")
    if not r.match("ZWINGLI"):
        ok("_DIGIT_IN_LETTER_RE does not match ZWINGLI")
    else:
        fail("_DIGIT_IN_LETTER_RE does not match ZWINGLI", "expected no match, got match")

    # ligature_bracket
    r = patterns._LIGATURE_BRACKET_RE
    if r.match("(ECOLAMPADIUS"):
        ok("_LIGATURE_BRACKET_RE matches (ECOLAMPADIUS")
    else:
        fail("_LIGATURE_BRACKET_RE matches (ECOLAMPADIUS", "expected match, got none")
    if not r.match("OECOLAMPADIUS"):
        ok("_LIGATURE_BRACKET_RE does not match OECOLAMPADIUS")
    else:
        fail("_LIGATURE_BRACKET_RE does not match OECOLAMPADIUS", "expected no match, got match")

    # ligature_ae_loss
    r = patterns._LIGATURE_AE_LOSS_RE
    if r.search("C(ESAR"):
        ok("_LIGATURE_AE_LOSS_RE matches C(ESAR")
    else:
        fail("_LIGATURE_AE_LOSS_RE matches C(ESAR", "expected match, got none")
    if not r.search("CAESAR"):
        ok("_LIGATURE_AE_LOSS_RE does not match CAESAR")
    else:
        fail("_LIGATURE_AE_LOSS_RE does not match CAESAR", "expected no match, got match")

    # stray_pipe_backslash
    r = patterns._STRAY_PIPE_RE
    if r.search("CHR|ST"):
        ok("_STRAY_PIPE_RE matches CHR|ST")
    else:
        fail("_STRAY_PIPE_RE matches CHR|ST", "expected match, got none")
    if not r.search("CHRIST"):
        ok("_STRAY_PIPE_RE does not match CHRIST")
    else:
        fail("_STRAY_PIPE_RE does not match CHRIST", "expected no match, got match")

    # pg_header (field-level)
    r = patterns._PG_HEADER_RE
    if r.search("This eBook is from the Project Gutenberg archive."):
        ok("_PG_HEADER_RE matches 'Project Gutenberg'")
    else:
        fail("_PG_HEADER_RE matches 'Project Gutenberg'", "expected match, got none")
    if r.search("Produced by Distributed Proofreaders"):
        ok("_PG_HEADER_RE matches 'Distributed Proofreaders'")
    else:
        fail("_PG_HEADER_RE matches 'Distributed Proofreaders'", "expected match, got none")
    if not r.search("Johann Gutenberg invented the printing press."):
        ok("_PG_HEADER_RE does not match bare 'Gutenberg'")
    else:
        fail("_PG_HEADER_RE does not match bare 'Gutenberg'", "expected no match, got match")
    if not r.search("The Gutenberg Bible is a landmark of printing history."):
        ok("_PG_HEADER_RE does not match 'Gutenberg Bible'")
    else:
        fail("_PG_HEADER_RE does not match 'Gutenberg Bible'", "expected no match, got match")


# ===========================================================================
# SECTION 2: Synthetic corpus fixture
# 10 entries with injected corruptions and clean control cases.
# ===========================================================================

SYNTHETIC_CORPUS = [
    # Entry 0 -- Tier 1 true positives: digit_in_letter, ligature_bracket, ligature_ae_loss, stray_pipe_backslash
    {
        "entry_id": "test.entry0",
        "term": "THE0T0K0S",
        "definition_blocks": [
            "(ECOLAMPADIUS was a reformer. C(ESAR was a Roman. CHR|ST is the Lord.",
        ],
    },
    # Entry 1 -- Tier 2 true positives: apparent_space_insertion, apparent_space_deletion
    {
        "entry_id": "test.entry1",
        "term": "CLEAN",
        "definition_blocks": [
            "THE ATINES were a Catholic order. ANDTHE Lord said.",
        ],
    },
    # Entry 2 -- digit in body text
    {
        "entry_id": "test.entry2",
        "term": "GLORY",
        "definition_blocks": [
            "To the gl0ry of God alone.",
        ],
    },
    # Entry 3 -- true negatives: ZWINGLI, A.D., D.D., THEATINES (single), 1 John 3:16
    {
        "entry_id": "test.entry3",
        "term": "ZWINGLI",
        "definition_blocks": [
            "ZWINGLI lived from A.D. 1484. He held a D.D. degree. THEATINES were founded later. See 1 John 3:16.",
        ],
    },
]

# Flatten the list comprehension at the end
SYNTHETIC_CORPUS = SYNTHETIC_CORPUS[:4] + [
    # Entry 4 -- pg_header true positive: "Project Gutenberg" in body
    {
        "entry_id": "test.entry4",
        "term": "AUGUSTINE",
        "definition_blocks": [
            "This text is from the Project Gutenberg archive and may be freely shared.",
        ],
    },
    # Entry 5 -- pg_header true negative: "Gutenberg Bible" should NOT trigger
    {
        "entry_id": "test.entry5",
        "term": "PRINTING",
        "definition_blocks": [
            "The Gutenberg Bible of 1455 is a landmark of Western printing history.",
        ],
    },
] + [
    {
        "entry_id": f"test.entry{i}",
        "term": "AUGUSTINE",
        "definition_blocks": ["Augustine of Hippo wrote the Confessions."],
    }
    for i in range(6, 10)
]


def _run_synthetic_scan():
    """Run scanner on synthetic corpus and return ScanResult."""
    # Build a minimal config matching what scanner.load_config returns
    config = {
        "source_id": "test-selftest",
        "pattern_set": "ia_djvu",
        "pattern_set_version": "1",
        "scan_fields": ["term", "definition_blocks"],
        "ignore_fields": [],
        "whitelist_terms": ["THEATINES"],
        "whitelist_patterns": [],
        "tier3_enabled": False,
    }
    # Seed dictionary with words needed for Tier 2 tests
    known_words = {"THEATINES", "AND", "THE", "LORD", "SAID", "GOD"}
    dictionary = patterns.DictionaryStack(
        whitelist_terms=set(config["whitelist_terms"]),
        lexicon_terms=known_words,
        enable_enchant=False,  # no enchant dependency in selftest
    )
    result = scanner.scan_entries(
        entries=SYNTHETIC_CORPUS,
        config=config,
        source_id="test-selftest",
        dictionary=dictionary,
    )
    return result


def _section2_fixture_tests(result):
    print("\n-- Fixture tests: true positives --")

    reasons_found = {c.reason for c in result.candidates}
    values_found = {c.value for c in result.candidates}

    # TP 1: digit_in_letter on term THE0T0K0S
    if any(c.value == "THE0T0K0S" and c.reason == "digit_in_letter" and c.tier == 1 for c in result.candidates):
        ok("TP1: THE0T0K0S flagged as digit_in_letter tier 1")
    else:
        fail("TP1: THE0T0K0S not flagged as digit_in_letter tier 1",
             f"candidates found: {[(c.value, c.reason) for c in result.candidates]}")

    # TP 2: ligature_bracket on (ECOLAMPADIUS in body
    if any(c.value == "(ECOLAMPADIUS" and c.reason == "ligature_bracket" and c.tier == 1 for c in result.candidates):
        ok("TP2: (ECOLAMPADIUS flagged as ligature_bracket tier 1")
    else:
        fail("TP2: (ECOLAMPADIUS not flagged", f"values found: {values_found}")

    # TP 3: ligature_ae_loss is Tier 3 -- only fires when tier3_enabled=True.
    # Run a separate one-entry scan with tier3_enabled=True to verify the detector fires.
    _t3_config = {
        "source_id": "test-selftest",
        "pattern_set": "ia_djvu",
        "pattern_set_version": "1",
        "scan_fields": ["term"],
        "ignore_fields": [],
        "whitelist_terms": [],
        "whitelist_patterns": [],
        "tier3_enabled": True,
    }
    _t3_entries = [{"entry_id": "test.t3", "term": "C(ESAR", "definition_blocks": []}]
    _t3_dict = patterns.DictionaryStack(whitelist_terms=set(), lexicon_terms=set(), enable_enchant=False)
    _t3_result = scanner.scan_entries(_t3_entries, _t3_config, "test-selftest", _t3_dict)
    if any("C(ESAR" in c.value and c.reason == "ligature_ae_loss" and c.tier == 3 for c in _t3_result.candidates):
        ok("TP3: C(ESAR flagged as ligature_ae_loss tier 3 (when tier3_enabled=True)")
    else:
        fail("TP3: C(ESAR not flagged as ligature_ae_loss tier 3",
             f"values found: {[c.value for c in _t3_result.candidates]}")

    # TP 4: stray_pipe_backslash on CHR|ST in body
    if any("CHR|ST" in c.value and c.reason == "stray_pipe_backslash" and c.tier == 1 for c in result.candidates):
        ok("TP4: CHR|ST flagged as stray_pipe_backslash tier 1")
    else:
        fail("TP4: CHR|ST not flagged", f"values found: {values_found}")

    # TP 5: apparent_space_insertion: THE + ATINES -> THEATINES
    if any(c.reason == "apparent_space_insertion" and c.tier == 2 for c in result.candidates):
        ok("TP5: apparent_space_insertion detected (THE ATINES -> THEATINES)")
    else:
        fail("TP5: apparent_space_insertion not detected", f"reasons found: {reasons_found}")

    # TP 6: apparent_space_deletion: ANDTHE -> AND + THE
    if any(c.reason == "apparent_space_deletion" and "ANDTHE" in c.value and c.tier == 2 for c in result.candidates):
        ok("TP6: ANDTHE flagged as apparent_space_deletion tier 2")
    else:
        fail("TP6: ANDTHE not flagged", f"values found: {values_found}")

    # TP 7: digit_in_letter on gl0ry in body sentence
    if any("gl0ry" in c.value.lower() and c.reason == "digit_in_letter" and c.tier == 1 for c in result.candidates):
        ok("TP7: gl0ry flagged as digit_in_letter tier 1")
    else:
        fail("TP7: gl0ry not flagged", f"values found: {values_found}")

    print("\n-- Fixture tests: true negatives (must NOT appear as candidates) --")

    # TN 1: ZWINGLI must not be flagged
    if not any(c.value == "ZWINGLI" for c in result.candidates):
        ok("TN1: ZWINGLI not flagged")
    else:
        fail("TN1: ZWINGLI was incorrectly flagged")

    # TN 2: A.D. must not be flagged
    if not any("A.D." in c.value for c in result.candidates):
        ok("TN2: A.D. not flagged")
    else:
        fail("TN2: A.D. was incorrectly flagged")

    # TN 3: D.D. must not be flagged
    if not any("D.D." in c.value for c in result.candidates):
        ok("TN3: D.D. not flagged")
    else:
        fail("TN3: D.D. was incorrectly flagged")

    # TN 4: THEATINES (single token) must not be flagged
    if not any(c.value == "THEATINES" for c in result.candidates):
        ok("TN4: THEATINES (single token) not flagged")
    else:
        fail("TN4: THEATINES was incorrectly flagged")

    # TN 5: 3:16 must not trigger digit_in_letter
    if not any(c.value == "3:16" and c.reason == "digit_in_letter" for c in result.candidates):
        ok("TN5: 3:16 not flagged as digit_in_letter")
    else:
        fail("TN5: 3:16 was incorrectly flagged as digit_in_letter")

    print("\n-- Fixture tests: pg_header field-level detector --")

    # TP 8: "Project Gutenberg" in definition_blocks flagged as pg_header tier 1
    if any(c.reason == "pg_header" and c.tier == 1 and c.entry_id == "test.entry4"
           for c in result.candidates):
        ok("TP8: 'Project Gutenberg' in body flagged as pg_header tier 1")
    else:
        fail("TP8: 'Project Gutenberg' not flagged",
             f"pg_header candidates: {[(c.entry_id, c.value) for c in result.candidates if c.reason == 'pg_header']}")

    # TN 6: "Gutenberg Bible" must NOT trigger pg_header
    if not any(c.reason == "pg_header" and c.entry_id == "test.entry5"
               for c in result.candidates):
        ok("TN6: 'Gutenberg Bible' not flagged as pg_header")
    else:
        fail("TN6: 'Gutenberg Bible' was incorrectly flagged as pg_header")


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("OCR Scanner selftest")
    print("=" * 50)

    _regex_sanity()

    result = _run_synthetic_scan()
    _section2_fixture_tests(result)

    print("\n" + "=" * 50)
    print(f"Results: {PASS} passed, {FAIL} failed")

    if FAIL > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
