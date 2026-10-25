"""Source-contract refinement requires a unique expected source preimage."""

import pytest

from build.tools.watson_strengthen_source_contract import once


def test_once_replaces_exact_preimage_and_preserves_surrounding_code():
    assert once("before retained after", "retained", "refined") == "before refined after"


@pytest.mark.parametrize("source", ["unmatched source", "retained retained"])
def test_once_rejects_missing_or_duplicate_source_preimage(source):
    with pytest.raises(ValueError, match="Expected unique Watson preimage"):
        once(source, "retained", "refined")
