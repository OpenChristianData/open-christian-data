"""test_osis_integration.py
Integration tests for OSIS existence checking in validate.py.

These tests verify that the warning path actually fires when invalid OSIS refs
are present -- a path that is never triggered by current clean data and would
otherwise only be proven by reading the code.

Covers:
  1. validate_catechism_qa_file: proof ref with out-of-range verse -> warning
  2. validate_doctrinal_document_file: unit proof with out-of-range verse -> warning
  3. validate_commentary_file: cross_reference with out-of-range verse -> warning
  4. All three: valid refs produce no OSIS existence warning (positive test)
  5. validate_osis_ref: standalone unit tests (valid, invalid, range, index unavailable)
  6. Deuterocanonical OSIS refs: known apocryphal codes return valid (not in verse index)

Usage:
    py -3 build/scripts/test_osis_integration.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# Import the validators directly (not via subprocess) so we exercise the real code paths.
from build.validate import (  # noqa: E402
    validate_catechism_qa_file,
    validate_commentary_file,
    validate_doctrinal_document_file,
)
from build.scripts.validate_osis import validate_osis_ref, validate_osis_array  # noqa: E402

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"\n        {detail}"
        print(msg)


# ---------------------------------------------------------------------------
# Helpers: minimal valid data structures
# ---------------------------------------------------------------------------

def _catechism_with_proof(osis_list: list) -> dict:
    """Build a minimal catechism_qa file dict with one proof containing given OSIS refs."""
    return {
        "meta": {
            "id": "test-catechism",
            "title": "Test",
            "schema_type": "catechism_qa",
            "schema_version": "2.1.0",
            "license": "public-domain",
            "completeness": "partial",
        },
        "data": [
            {
                "item_id": "1",
                "sort_key": 1,
                "question": "Test question?",
                "answer": "Test answer.",
                "proofs": [
                    {
                        "id": 1,
                        "references": [
                            {"raw": o, "osis": [o]} for o in osis_list
                        ],
                    }
                ],
            }
        ],
    }


def _doctrinal_with_proof(osis_list: list) -> dict:
    """Build a minimal doctrinal_document dict with one unit containing given OSIS proof refs."""
    return {
        "meta": {
            "id": "test-doc",
            "title": "Test",
            "schema_type": "doctrinal_document",
            "schema_version": "2.1.0",
            "license": "public-domain",
        },
        "data": {
            "document_id": "test-doc",
            "document_kind": "confession",
            "revision_history": [],
            "units": [
                {
                    "unit_id": "1",
                    "unit_type": "chapter",
                    "title": "Chapter 1",
                    "content": "Test content.",
                    "proofs": [
                        {
                            "id": 1,
                            "references": [
                                {"raw": o, "osis": [o]} for o in osis_list
                            ],
                        }
                    ],
                    "children": [],
                }
            ],
        },
    }


def _commentary_with_cross_refs(osis_list: list) -> dict:
    """Build a minimal commentary dict with one entry containing given cross_reference OSIS refs."""
    return {
        "meta": {
            "id": "test-commentary",
            "title": "Test Commentary",
            "author": "Test Author",
            "schema_type": "commentary",
            "schema_version": "2.1.0",
            "license": "public-domain",
            "completeness": "partial",
        },
        "data": [
            {
                "entry_id": "test.Gen.1.1",
                "book": "Genesis",
                "book_osis": "Gen",
                "book_number": 1,
                "chapter": 1,
                "verse_range": "1",
                "anchor_ref": {"raw": "Gen.1.1", "osis": ["Gen.1.1"]},
                "commentary_text": "Test commentary text here.",
                "cross_references": [
                    {"raw": o, "osis": [o]} for o in osis_list
                ],
                "word_count": 4,
                "summary_review_status": "withheld",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

path_placeholder = Path("test-in-memory.json")

print()
print("--- 1. validate_osis_ref: unit tests ---")

valid, reason = validate_osis_ref("Gen.1.1")
check("Gen.1.1 is valid", valid, reason)

valid, reason = validate_osis_ref("Rev.22.21")
check("Rev.22.21 is valid", valid, reason)

valid, reason = validate_osis_ref("Ezek.48.35")
check("Ezek.48.35 is valid (last verse in chapter)", valid, reason)

valid, reason = validate_osis_ref("Ezek.48.36")
check("Ezek.48.36 is invalid (chapter has 35 verses)", not valid,
      f"expected invalid, got valid (reason={reason!r})")

valid, reason = validate_osis_ref("Gen.1.1-Gen.1.31")
check("Gen.1.1-Gen.1.31 range is valid", valid, reason)

valid, reason = validate_osis_ref("Gen.1.1-Gen.1.32")
check("Gen.1.1-Gen.1.32 range is invalid (Gen.1 has 31 verses)", not valid,
      f"expected invalid, got valid (reason={reason!r})")

valid, reason = validate_osis_ref("Gen.51.1")
check("Gen.51.1 is invalid (Gen has 50 chapters)", not valid,
      f"expected invalid, got valid (reason={reason!r})")

valid, reason = validate_osis_ref("Obad.1.21")
check("Obad.1.21 is valid (single-chapter book, 21 verses)", valid, reason)

valid, reason = validate_osis_ref("Obad.1.22")
check("Obad.1.22 is invalid (Obad has 21 verses)", not valid,
      f"expected invalid, got valid (reason={reason!r})")

print()
print("--- 2. validate_catechism_qa_file: OSIS existence warning path ---")

# Negative test: bad OSIS ref in proof should produce a warning
bad_cat = _catechism_with_proof(["Ezek.48.36"])
errors, warnings = validate_catechism_qa_file(path_placeholder, bad_cat)
osis_warnings = [w for w in warnings if "OSIS existence" in w]
check(
    "Bad catechism proof OSIS triggers existence warning",
    len(osis_warnings) == 1,
    f"warnings={warnings}",
)
check(
    "Warning mentions the bad ref",
    osis_warnings and "Ezek.48.36" in osis_warnings[0],
    f"warning text: {osis_warnings}",
)

# Positive test: valid ref should produce no existence warning
good_cat = _catechism_with_proof(["Gen.1.1", "Rev.22.21"])
errors, warnings = validate_catechism_qa_file(path_placeholder, good_cat)
osis_warnings = [w for w in warnings if "OSIS existence" in w]
check(
    "Valid catechism proof OSIS produces no existence warning",
    len(osis_warnings) == 0,
    f"unexpected warnings: {osis_warnings}",
)

print()
print("--- 3. validate_doctrinal_document_file: OSIS existence warning path ---")

# Negative test
bad_doc = _doctrinal_with_proof(["Ezek.48.36"])
errors, warnings = validate_doctrinal_document_file(path_placeholder, bad_doc)
osis_warnings = [w for w in warnings if "OSIS existence" in w]
check(
    "Bad doctrinal proof OSIS triggers existence warning",
    len(osis_warnings) == 1,
    f"warnings={warnings}",
)
check(
    "Warning mentions the bad ref",
    osis_warnings and "Ezek.48.36" in osis_warnings[0],
    f"warning text: {osis_warnings}",
)

# Positive test
good_doc = _doctrinal_with_proof(["Gen.1.1", "Ps.119.176"])
errors, warnings = validate_doctrinal_document_file(path_placeholder, good_doc)
osis_warnings = [w for w in warnings if "OSIS existence" in w]
check(
    "Valid doctrinal proof OSIS produces no existence warning",
    len(osis_warnings) == 0,
    f"unexpected warnings: {osis_warnings}",
)

print()
print("--- 4. validate_commentary_file: cross_references Reference object handling ---")

# Negative test: bad OSIS in cross_reference object
bad_com = _commentary_with_cross_refs(["Ezek.48.36"])
errors, warnings = validate_commentary_file(path_placeholder, bad_com)
check(
    "Commentary with bad cross_reference OSIS does not crash",
    True,  # reaching here means no TypeError
)
osis_warnings = [w for w in warnings if "OSIS existence" in w]
check(
    "Bad cross_reference OSIS triggers existence warning",
    len(osis_warnings) == 1,
    f"warnings={warnings}",
)

# Positive test: valid cross_references
good_com = _commentary_with_cross_refs(["Gen.1.1", "Rev.22.21"])
errors, warnings = validate_commentary_file(path_placeholder, good_com)
osis_warnings = [w for w in warnings if "OSIS existence" in w]
check(
    "Valid cross_reference OSIS produces no existence warning",
    len(osis_warnings) == 0,
    f"unexpected warnings: {osis_warnings}",
)

# Verify the old plain-string TypeError path is gone: dict ref must not crash
try:
    _ = validate_commentary_file(path_placeholder, _commentary_with_cross_refs(["Gen.1.1"]))
    check("Reference object in cross_references does not raise TypeError", True)
except TypeError as exc:
    check("Reference object in cross_references does not raise TypeError", False, str(exc))

print()
print("--- 5. validate_osis_array ---")

valid_count, invalid = validate_osis_array(["Gen.1.1", "Ezek.48.36", "Rev.22.21", "Gen.51.1"])
check("validate_osis_array: correct valid count", valid_count == 2,
      f"expected 2 valid, got {valid_count}")
check("validate_osis_array: correct invalid count", len(invalid) == 2,
      f"expected 2 invalid, got {len(invalid)}: {invalid}")
invalid_refs = [s for s, _ in invalid]
check("validate_osis_array: Ezek.48.36 in invalid list", "Ezek.48.36" in invalid_refs,
      f"invalid: {invalid_refs}")
check("validate_osis_array: Gen.51.1 in invalid list", "Gen.51.1" in invalid_refs,
      f"invalid: {invalid_refs}")

print()
print("--- 6. Deuterocanonical OSIS refs ---")

# Known deuterocanonical codes should pass (not in BSB verse index, but valid OSIS codes).
# validate_osis_ref returns (True, "deuterocanonical - not in verse index") for these.
for ref in ["Tob.1.1", "Sir.24.1", "1Macc.2.1", "Wis.7.1", "Bar.3.1", "PrAzar.1.1"]:
    valid, reason = validate_osis_ref(ref)
    check(
        f"{ref} is valid (deuterocanonical)",
        valid and reason == "deuterocanonical - not in verse index",
        f"valid={valid}, reason={reason!r}",
    )

# Range ref spanning a deuterocanonical book should also pass
valid, reason = validate_osis_ref("Bar.3.24-Bar.3.25")
check(
    "Bar.3.24-Bar.3.25 range is valid (deuterocanonical)",
    valid,
    f"valid={valid}, reason={reason!r}",
)

# Truly unknown book code (not Protestant, not deuterocanonical) still fails
valid, reason = validate_osis_ref("Unknown.1.1")
check(
    "Unknown.1.1 is invalid (not in index, not deuterocanonical)",
    not valid and "unknown book code" in reason,
    f"expected invalid, got valid={valid}, reason={reason!r}",
)

# validate_osis_array: deuterocanonical refs count as valid, not invalid
valid_count, invalid = validate_osis_array(["Gen.1.1", "Tob.1.1", "Sir.24.1"])
check(
    "validate_osis_array: deuterocanonical refs counted as valid",
    valid_count == 3 and len(invalid) == 0,
    f"valid_count={valid_count}, invalid={invalid}",
)

# Mixed: one canonical, one deuterocanonical, one truly bad
valid_count, invalid = validate_osis_array(["Gen.1.1", "Tob.1.1", "Ezek.48.36"])
check(
    "validate_osis_array: canonical + deuterocanonical + bad ref",
    valid_count == 2 and len(invalid) == 1 and invalid[0][0] == "Ezek.48.36",
    f"valid_count={valid_count}, invalid={invalid}",
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
total = PASS + FAIL
print(f"Results: {PASS}/{total} passed, {FAIL} failed")
if FAIL:
    sys.exit(1)
