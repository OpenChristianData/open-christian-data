"""Only explicit, valid dataset book codes enter reference interpretation."""
import json

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.scripture_authority import load_book_codes


@pytest.mark.parametrize("document", [[], {}, {"_note": "comment only"}, {"John": "John 3"}, {"John": 3}])
def test_invalid_authority_cannot_supply_book_codes(tmp_path, document):
    path = tmp_path / "codes.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PipelineError):
        load_book_codes(path)


def test_authority_comments_are_not_interpreted_as_book_codes(tmp_path):
    path = tmp_path / "codes.json"
    path.write_text(json.dumps({"_provenance": {"note": "retained"}, "Genesis": "Gen", "John": "John"}), encoding="utf-8")
    assert load_book_codes(path) == {"Gen", "John"}
