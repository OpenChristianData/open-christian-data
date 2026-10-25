"""Focused private-path transformations for offline public rows."""

from copy import deepcopy
from hashlib import sha256
import json
from urllib.parse import quote, unquote

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.release.public_rows import (
    HISTORICAL_ITEMS,
    public_rows_with_omissions,
    restore_private_source_locations,
)


def _rows() -> list[dict]:
    return [
        {"record_id": "one", "text": "First", "provenance": {
            "edition_title": "Example", "source_location": "raw/private/source.xml",
            "source_url": "https://example.org/source",
        }},
        {"record_id": "two", "text": "Second", "provenance": {
            "edition_title": "Example", "source_location": "Page 4",
        }},
    ]


@pytest.mark.parametrize("location", [
    "raw/private/source.xml",
    r"C:\private\source.xml",
    "/home/user/source.xml",
    "file:///home/user/source.xml",
])
def test_private_path_is_omitted_and_restored_exactly(location: str) -> None:
    original = _rows()
    original[0]["provenance"]["source_location"] = location
    before = deepcopy(original)
    public, artifact = public_rows_with_omissions(original, item_id="example")
    assert original == before
    assert "source_location" not in public[0]["provenance"]
    assert public[1]["provenance"]["source_location"] == "Page 4"
    assert artifact is not None
    assert len(artifact["omissions"]) == 1
    assert restore_private_source_locations(public, artifact, item_id="example") == original


def test_meaningful_locator_does_not_create_transform() -> None:
    public, artifact = public_rows_with_omissions(_rows()[1:], item_id="example")
    assert public[0]["provenance"]["source_location"] == "Page 4"
    assert artifact is None


def test_shared_input_provenance_is_omitted_and_bound_for_every_row() -> None:
    provenance = {
        "edition_title": "Example",
        "source_location": "raw/private/source.xml",
    }
    original = [
        {"record_id": "one", "text": "First", "provenance": provenance},
        {"record_id": "two", "text": "Second", "provenance": provenance},
        {"record_id": "three", "text": "Third", "provenance": provenance},
    ]
    public, artifact = public_rows_with_omissions(original, item_id="example")
    assert artifact is not None
    assert [entry["row_index"] for entry in artifact["omissions"]] == [0, 1, 2]
    assert all("source_location" not in row["provenance"] for row in public)
    assert len({id(row["provenance"]) for row in public}) == 3
    assert provenance["source_location"] == "raw/private/source.xml"
    assert restore_private_source_locations(public, artifact, item_id="example") == original


@pytest.mark.parametrize("tamper", ["field", "value", "extra", "digest", "duplicate"])
def test_unknown_or_unbound_transform_is_rejected(tamper: str) -> None:
    public, artifact = public_rows_with_omissions(_rows(), item_id="example")
    assert artifact is not None
    changed = deepcopy(artifact)
    omission = changed["omissions"][0]
    if tamper == "field":
        omission["field"] = "text"
    elif tamper == "value":
        omission["value"] = "Page 4"
    elif tamper == "extra":
        omission["unapproved"] = True
    elif tamper == "digest":
        omission["original_row_sha256"] = "0" * 64
    else:
        changed["omissions"].append(deepcopy(omission))
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, changed, item_id="example")


def test_already_public_location_cannot_be_restored_again() -> None:
    public, artifact = public_rows_with_omissions(_rows(), item_id="example")
    assert artifact is not None
    public[0]["provenance"]["source_location"] = "raw/private/source.xml"
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, artifact, item_id="example")


def _historical_row(style: str, *, annotation: str | None = None) -> list[dict]:
    attributes = {"style": style, "language": "en", "source_target": "https://example.org/page",
                  "row_span": "2"}
    if annotation is not None:
        attributes["source_annotations"] = annotation
    return [{"record_id": "bound-native", "text": "Historical text", "language": "en",
             "provenance": {"source_location": "raw/private/source.xml"},
             "structure": [{"kind": "native-unit", "attributes": {}, "content": [
                 {"kind": "table-cell", "attributes": attributes,
                  "content": [{"kind": "text", "text": "Historical text"}]}
             ]}]}]


def _authority(item_id: str) -> dict[str, str]:
    acceptance, master = HISTORICAL_ITEMS[item_id]
    return {"acceptance_sha256": acceptance, "master_sha256": master}


def test_renamed_label_preserves_accepted_identity_transform_and_inverse():
    key = "hodge-systematic-theology-vol-1--hodge-systematic-theology-vol-1-retained-electronic-witness"
    identity = {"work_id": "hodge-systematic-theology-vol-1", "edition_id": "hodge-systematic-theology-vol-1-retained-electronic-witness"}
    private = _historical_row("border=0; style=margin-left:.25in; margin-top:9pt")
    expected, _ = public_rows_with_omissions(private, item_id=key, **_authority(key))
    renamed, artifact = public_rows_with_omissions(private, item_id="readable-new-label", accepted_identity=identity, **_authority(key))
    assert renamed == expected
    assert restore_private_source_locations(renamed, artifact, item_id="readable-new-label", accepted_identity=identity, **_authority(key)) == private
    with pytest.raises(PipelineError):
        public_rows_with_omissions(private, item_id="readable-new-label", accepted_identity=identity,
                                  acceptance_sha256="0" * 64, master_sha256=_authority(key)["master_sha256"])
    with pytest.raises(PipelineError):
        restore_private_source_locations(renamed, artifact, item_id="readable-new-label",
                                         accepted_identity=dict(identity, edition_id="wrong-edition"), **_authority(key))


@pytest.mark.parametrize(("item_id", "style", "expected"), [
    ("cyril-of-jerusalem-catechetical-lectures--cyril-of-jerusalem-catechetical-lectures-retained-electronic-witness",
     "c32 width:369; vertical-align:top", "c32"),
    ("expositors-bible--g-a-chadwick--expositors-bible--g-a-chadwick-mark-retained-electronic",
     "source-style:font-size:large; font-weight:bold", "bold"),
    ("expositors-bible--g-a-chadwick--expositors-bible--g-a-chadwick-mark-retained-electronic",
     "source-class:SectionInfo2; source-style:margin-top:9pt", "source-class:SectionInfo2"),
    ("hodge-systematic-theology-vol-1--hodge-systematic-theology-vol-1-retained-electronic-witness",
     "border=0; style=margin-left:.25in; margin-top:9pt", None),
    ("hodge-systematic-theology-vol-2--hodge-systematic-theology-vol-2-retained-electronic-witness",
     "style=width:20%; margin-top:1in; margin-bottom:1in", None),
    ("hodge-systematic-theology-vol-3--hodge-systematic-theology-vol-3-retained-electronic-witness",
     "width:90%; margin-left:10%", None),
    ("ryle-expository-thoughts-matthew--ccel-matthew-electronic-witness",
     "MsoNormal | source-style=tab-stops:252.0pt", "MsoNormal"),
])
def test_pinned_ccel_layout_is_omitted_with_exact_private_inverse(
    item_id: str, style: str, expected: str | None
) -> None:
    original = _historical_row(style)
    before = deepcopy(original)
    public, artifact = public_rows_with_omissions(original, item_id=item_id, **_authority(item_id))
    assert original == before
    cell = public[0]["structure"][0]["content"][0]
    assert cell["attributes"].get("style") == expected
    assert cell["content"] == original[0]["structure"][0]["content"][0]["content"]
    assert cell["attributes"]["language"] == "en"
    assert cell["attributes"]["source_target"] == "https://example.org/page"
    assert cell["attributes"]["row_span"] == "2"
    assert "source_location" not in public[0]["provenance"]
    assert artifact is not None and artifact["contract"] == "ocd-public-historical-format-omissions-v1"
    assert restore_private_source_locations(public, artifact, item_id=item_id,
                                            **_authority(item_id)) == original


@pytest.mark.parametrize("item_id,prefix", [
    ("hodge-systematic-theology-vol-1--hodge-systematic-theology-vol-1-retained-electronic-witness",
     "urn:ocd:hodge-theology1:ThML:"),
    ("hodge-systematic-theology-vol-2--hodge-systematic-theology-vol-2-retained-electronic-witness",
     "urn:ocd:hodge-theology2:ThML:"),
])
def test_hodge_annotation_keeps_source_links_language_and_spans(item_id: str, prefix: str) -> None:
    private = {"tag": "td", "attributes": [["id", "source-cell"], ["href", "https://example.org/link"],
                                           ["lang", "grc"], ["rowspan", "2"], ["colspan", "3"],
                                           ["style", "width:10%; text-align:right"], ["border", "0"]]}
    annotation = prefix + quote(json.dumps(private, ensure_ascii=False, separators=(",", ":")), safe="")
    original = _historical_row("font-size:medium", annotation=annotation)
    public, artifact = public_rows_with_omissions(original, item_id=item_id, **_authority(item_id))
    assert artifact is not None
    public_annotation = public[0]["structure"][0]["content"][0]["attributes"]["source_annotations"]
    assert public_annotation.startswith("source-annotation:")
    decoded = json.loads(unquote(public_annotation.removeprefix("source-annotation:")))
    assert decoded == {"tag": "td", "attributes": private["attributes"][:5]}
    assert restore_private_source_locations(public, artifact, item_id=item_id,
                                            **_authority(item_id)) == original


def test_hodge_source_insert_index_type_survives_annotation_rewrite() -> None:
    item_id = "hodge-systematic-theology-vol-1--hodge-systematic-theology-vol-1-retained-electronic-witness"
    private = {"tag": "insertIndex", "attributes": [["type", "scripRef"], ["id", "source-index"]]}
    annotation = "urn:ocd:hodge-theology1:ThML:" + quote(
        json.dumps(private, separators=(",", ":")), safe="")
    original = _historical_row("font-size:medium", annotation=annotation)
    public, artifact = public_rows_with_omissions(original, item_id=item_id, **_authority(item_id))
    assert artifact is not None
    output = public[0]["structure"][0]["content"][0]["attributes"]["source_annotations"]
    assert json.loads(unquote(output.removeprefix("source-annotation:"))) == private
    assert restore_private_source_locations(public, artifact, item_id=item_id,
                                            **_authority(item_id)) == original


def test_ccel_formatting_policy_requires_exact_accepted_authority() -> None:
    item_id = "hodge-systematic-theology-vol-1--hodge-systematic-theology-vol-1-retained-electronic-witness"
    with pytest.raises(PipelineError, match="authority differs"):
        public_rows_with_omissions(_historical_row("width:10%"), item_id=item_id,
                                   acceptance_sha256="0" * 64,
                                   master_sha256=_authority(item_id)["master_sha256"])


def test_historical_item_rejects_legacy_source_location_receipt_substitution() -> None:
    item_id = "expositors-bible--g-a-chadwick--expositors-bible--g-a-chadwick-mark-retained-electronic"
    public, historical = public_rows_with_omissions(
        _historical_row("source-class:SectionInfo2; source-style:margin-top:9pt"),
        item_id=item_id, **_authority(item_id))
    assert historical is not None
    forged = deepcopy(public)
    forged[0]["provenance"]["source_location"] = "raw/private/source.xml"
    legacy = {
        "contract": "ocd-public-source-location-omissions-v1", "item_id": item_id,
        "row_count": 1, "omissions": [{
            "row_index": 0, "record_id": public[0]["record_id"],
            "field": "provenance.source_location", "value": "raw/private/source.xml",
            "original_row_sha256": sha256(canonical_bytes(forged)).hexdigest(),
            "public_row_sha256": sha256(canonical_bytes(public[0])).hexdigest(),
        }],
    }
    with pytest.raises(PipelineError, match="historical public-row transform required"):
        restore_private_source_locations(public, legacy, item_id=item_id,
                                         **_authority(item_id))


@pytest.mark.parametrize("tamper", ["text", "language", "link", "span", "annotation", "field", "authority"])
def test_historical_private_inverse_rejects_mutation(tamper: str) -> None:
    item_id = "hodge-systematic-theology-vol-1--hodge-systematic-theology-vol-1-retained-electronic-witness"
    private = {"tag": "td", "attributes": [["href", "https://example.org/link"], ["style", "width:10%"]]}
    annotation = "urn:ocd:hodge-theology1:ThML:" + quote(
        json.dumps(private, separators=(",", ":")), safe="")
    public, artifact = public_rows_with_omissions(_historical_row("width:10%", annotation=annotation),
                                                  item_id=item_id, **_authority(item_id))
    assert artifact is not None
    public, artifact = deepcopy(public), deepcopy(artifact)
    cell = public[0]["structure"][0]["content"][0]
    if tamper == "text":
        cell["content"][0]["text"] = "Changed"
    elif tamper == "language":
        cell["attributes"]["language"] = "fr"
    elif tamper == "link":
        cell["attributes"]["source_target"] = "https://example.org/other"
    elif tamper == "span":
        cell["attributes"]["row_span"] = "3"
    elif tamper == "annotation":
        cell["attributes"]["source_annotations"] += "%20"
    elif tamper == "field":
        artifact["omissions"][0]["fields"][0]["path"] = ["text"]
    else:
        artifact["authority"]["master_sha256"] = "0" * 64
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, artifact, item_id=item_id,
                                         **_authority(item_id))


def test_historical_transform_refuses_semantic_gap_or_unknown_annotation() -> None:
    item_id = "hodge-systematic-theology-vol-1--hodge-systematic-theology-vol-1-retained-electronic-witness"
    rows = _historical_row("font-size:medium")
    rows[0]["structure"][0]["content"][0]["kind"] = "gap"
    with pytest.raises(PipelineError, match="semantic"):
        public_rows_with_omissions(rows, item_id=item_id, **_authority(item_id))
    rows = _historical_row("font-size:medium", annotation="urn:ocd:unknown:private")
    with pytest.raises(PipelineError, match="unapproved source annotation"):
        public_rows_with_omissions(rows, item_id=item_id, **_authority(item_id))


def test_historical_inverse_rejects_an_unreported_layout_field() -> None:
    item_id = "hodge-systematic-theology-vol-1--hodge-systematic-theology-vol-1-retained-electronic-witness"
    original = _historical_row("width:10%")
    public, artifact = public_rows_with_omissions(original, item_id=item_id, **_authority(item_id))
    assert artifact is not None
    public[0]["structure"][0]["content"][0]["attributes"]["style"] = "width:10%"
    entry = artifact["omissions"][0]
    entry["fields"] = [field for field in entry["fields"]
                       if field["path"] == ["provenance", "source_location"]]
    entry["public_row_sha256"] = sha256(canonical_bytes(public[0])).hexdigest()
    with pytest.raises(PipelineError, match="incomplete"):
        restore_private_source_locations(public, artifact, item_id=item_id,
                                         **_authority(item_id))
