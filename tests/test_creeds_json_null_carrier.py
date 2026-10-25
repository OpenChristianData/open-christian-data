"""The retained Apostles member has an explicit JSON null at Metadata/Location."""

from __future__ import annotations

from lxml import etree
import pytest

from build.tei.creeds_json_lib063_oracle import _verify_json_node
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.creeds_json_carrier import _decode, _null_paths, _receipt


TEI = "http://www.tei-c.org/ns/1.0"
PATH = "$/Metadata/Location"
NODE_ID = "lib063-apostles-creed-node-00001"


def _node(*, kind: str = "json-null", text: str = "") -> etree._Element:
    return etree.fromstring(
        f'<div xmlns="{TEI}" xml:id="{NODE_ID}" type="{kind}">'
        f'<ab type="json-scalar">{text}</ab></div>'.encode("utf-8")
    )


def _state() -> dict[str, object]:
    return {"next_ordinal": 1, "objects": 0, "arrays": 0, "members": 0,
            "items": 0, "strings": 0, "numbers": 0, "booleans": 0,
            "nulls": 0, "crosswalk": []}


def test_typed_null_preserves_source_path_and_receipt_type() -> None:
    loci: dict[str, str] = {}
    assert _decode(_node(), PATH, loci) is None
    assert loci == {PATH: NODE_ID}
    state = _state()
    _verify_json_node(_node(), None, work_id="apostles-creed", path=PATH, state=state)
    assert state["nulls"] == 1
    assert state["crosswalk"] == [{"ordinal": 1, "json_path": PATH, "kind": "null",
                                   "tei_xml_id": NODE_ID, "value_sha256":
                                   "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                                   "value_characters": 0}]
    document = {"Metadata": {"Location": None}, "Data": {"Content": "text"}}
    assert _null_paths(document) == [PATH]
    receipt = _receipt({"document": document, "identity": {"work_id": "apostles-creed",
                        "textual_form_id": "apostles-creed-retained-electronic",
                        "edition_id": "apostles-creed-creeds-json"}, "master_bytes": b"master",
                        "source_bytes": b"source", "source_path": "raw/Creeds.json/creeds/apostles_creed.json",
                        "kind": "creed"}, [], loci)
    assert receipt["null_carriers"] == [{"json_path": PATH, "kind": "null", "tei_xml_id": NODE_ID}]
    assert receipt["retained_metadata"]["Location"] is None


@pytest.mark.parametrize("kind,text", [("json-string", ""), ("json-null", "null")])
def test_independent_oracle_rejects_changed_null_type_or_value(kind: str, text: str) -> None:
    with pytest.raises(ValueError, match="LIB-063 TEI"):
        _verify_json_node(_node(kind=kind, text=text), None,
                          work_id="apostles-creed", path=PATH, state=_state())
    if text:
        with pytest.raises(PipelineError, match="null carrier"):
            _decode(_node(kind=kind, text=text), PATH, {})


def test_null_path_is_distinct_from_empty_string_false_and_zero() -> None:
    assert _null_paths({"Metadata": {"Location": None, "Alias": "", "Visible": False,
                                      "Year": 0}, "Data": [None]}) == [PATH, "$/Data/0"]
