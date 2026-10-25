"""Historical notice fixtures require the complete original byte identity."""

from hashlib import sha256

import pytest

from tests.historical_notice_fixture import CURRENT_TARGET_APPENDIX, frozen_source_note


@pytest.mark.parametrize("with_appendix", (False, True))
def test_complete_original_bytes_are_preserved(with_appendix):
    original = b"Retained rights and credits.\n"
    raw = original + CURRENT_TARGET_APPENDIX + b"Current rights remain qualified.\n" if with_appendix else original
    assert frozen_source_note(raw, sha256(original).hexdigest()) == original


@pytest.mark.parametrize("change", ("changed-prefix", "unknown-appendix", "duplicate-marker"))
def test_unproven_history_fails_closed(change):
    original = b"Retained rights and credits.\n"
    if change == "changed-prefix":
        raw = b"Changed rights and credits.\n" + CURRENT_TARGET_APPENDIX
    elif change == "unknown-appendix":
        raw = original + b"\n## Unknown amendment\n"
    else:
        raw = original + CURRENT_TARGET_APPENDIX + CURRENT_TARGET_APPENDIX
    with pytest.raises(ValueError, match="frozen notice-index preimage"):
        frozen_source_note(raw, sha256(original).hexdigest())
