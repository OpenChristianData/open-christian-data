"""Bounded admission checks for the retained Catholic Encyclopedia route."""

import json
from pathlib import Path

import pytest
from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import reference_entries
from ocd_kernel.tei import acceptance
from ocd_kernel.tei.lib025_stream_header_facts import IDENTITY, parse_bound_header


def test_dispatch_requires_all_four_identity_fields(monkeypatch):
    document = {"identity": dict(IDENTITY)}
    monkeypatch.setattr(acceptance, "load_acceptance", lambda path: document)
    assert reference_entries._native_catholic_acceptance(Path("unused.json"))
    for key in IDENTITY:
        document["identity"] = {**IDENTITY, key: "another-identity"}
        assert not reference_entries._native_catholic_acceptance(Path("unused.json"))
        document["identity"] = {k: v for k, v in IDENTITY.items() if k != key}
        assert not reference_entries._native_catholic_acceptance(Path("unused.json"))


def test_streaming_header_rejects_wrong_acquisition_before_reading():
    with pytest.raises(PipelineError, match="exact identity differs"):
        parse_bound_header(Path("absent.xml"), identity={**IDENTITY, "acquisition_id": "other"})


def test_invalid_root_rejects_with_candidate_path():
    candidate = Path("invalid-root.xml")
    tree = etree.ElementTree(etree.fromstring(b"<not-tei/>"))
    with pytest.raises(PipelineError, match="candidate is not a TEI P5 document") as error:
        acceptance._tei_facts_from_tree(tree, source_path=candidate)
    assert str(candidate) in str(error.value)


def test_reference_schema_preserves_existing_profile_and_exact_native_identity():
    schema = json.loads(reference_entries.SCHEMA.read_text(encoding="utf-8"))
    profile = schema["x-ocd-profile"]
    assert profile["private_receipt_anchors"] == ["xml_id", "tei_path", "source_order"]
    assert profile["unsupported_behavior"] == (
        "Visible unsupported structure is rejected and accounted for; it is never silently flattened."
    )
    assert profile["original_branch_preserved"] is True
    native = schema["oneOf"][1]["properties"]
    for key in ("work_id", "textual_form_id", "edition_id"):
        assert native[key] == {"const": IDENTITY[key]}
