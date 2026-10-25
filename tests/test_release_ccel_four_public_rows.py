"""Focused guards for four exact CCEL formatting-only accepted scopes."""

from copy import deepcopy
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release import public_rows as policy


def row(style: str) -> list[dict]:
    return [{
        "record_id": "accepted-native", "text": "The historical words", "language": "en",
        "provenance": {"source_location": "raw/ccel/npnf2/npnf211.xml"},
        "structure": [{"kind": "native-unit", "attributes": {}, "content": [{
            "kind": "table-cell",
            "attributes": {"style": style, "language": "el", "source_target": "https://example.org/text",
                           "row_span": "2", "source_id": "original-42"},
            "content": [{"kind": "text", "text": "The historical words"}],
        }]}],
    }]


def authority(item_id: str) -> dict[str, str]:
    acceptance, master = policy.HISTORICAL_ITEMS[item_id]
    return {"acceptance_sha256": acceptance, "master_sha256": master}


@pytest.mark.parametrize("item_id,style", [
    ("gregory-the-great-pastoral-rule-and-epistles--gregory-the-great-pastoral-rule-and-epistles-ccel-npnf212-electronic", "width:25%"),
    ("john-cassian-selected-works--john-cassian-selected-works-npnf211-electronic-witness", "style:text-align:center; width:15%"),
    ("sulpitius-severus-selected-works--sulpitius-severus-selected-works-npnf211-electronic-witness", "style:margin-top:48pt"),
    ("vincent-of-lerins-commonitory--vincent-of-lerins-commonitory-npnf211-electronic-witness", "border:0"),
])
def test_exact_scope_removes_only_layout_and_restores_private_row(item_id: str, style: str) -> None:
    original = row(style)
    before = deepcopy(original)
    public, receipt = policy.public_rows_with_omissions(original, item_id=item_id, **authority(item_id))
    assert original == before
    assert receipt["authority"] == {**authority(item_id),
                                    "formatting_scope_sha256": policy.HISTORICAL_FORMATTING_SCOPE_SHA256}
    assert [field["path"][-1] for field in receipt["omissions"][0]["fields"]] == [
        "source_location", "style"]
    cell = public[0]["structure"][0]["content"][0]
    assert "style" not in cell["attributes"]
    assert {key: cell["attributes"][key] for key in (
        "language", "source_target", "row_span", "source_id")} == {
        "language": "el", "source_target": "https://example.org/text",
        "row_span": "2", "source_id": "original-42"}
    assert cell["content"] == original[0]["structure"][0]["content"][0]["content"]
    assert policy.restore_private_source_locations(public, receipt, item_id=item_id,
                                                   **authority(item_id)) == original


@pytest.mark.parametrize("style", [
    "class:c23", "class:Greek", "class:font-style:normal", "dir:rtl;class:Greek",
])
def test_source_class_and_text_direction_remain_public(style: str) -> None:
    item_id = "john-cassian-selected-works--john-cassian-selected-works-npnf211-electronic-witness"
    original = row(style)
    public, receipt = policy.public_rows_with_omissions(original, item_id=item_id, **authority(item_id))
    assert public[0]["structure"][0]["content"][0]["attributes"]["style"] == style
    assert [field["path"][-1] for field in receipt["omissions"][0]["fields"]] == ["source_location"]
    assert policy.restore_private_source_locations(public, receipt, item_id=item_id,
                                                   **authority(item_id)) == original


def test_old_six_keep_their_original_rights_binding() -> None:
    item_id = "ryle-expository-thoughts-matthew--ccel-matthew-electronic-witness"
    original = row("width:25%")
    _, receipt = policy.public_rows_with_omissions(original, item_id=item_id, **authority(item_id))
    assert receipt["authority"] == {**authority(item_id),
                                    "rights_disposition_sha256": policy.HISTORICAL_RIGHTS_SHA256}


@pytest.mark.parametrize("part", ["acceptance", "master"])
def test_new_scope_refuses_authority_drift(part: str) -> None:
    item_id = "vincent-of-lerins-commonitory--vincent-of-lerins-commonitory-npnf211-electronic-witness"
    args = authority(item_id)
    args[f"{part}_sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="authority differs"):
        policy.public_rows_with_omissions(row("border:0"), item_id=item_id, **args)


@pytest.mark.parametrize("mutation", ["text", "language", "link", "span", "field", "digest", "incomplete"])
def test_new_scope_inverse_rejects_mutation(mutation: str) -> None:
    item_id = "vincent-of-lerins-commonitory--vincent-of-lerins-commonitory-npnf211-electronic-witness"
    original = row("border:0")
    public, receipt = policy.public_rows_with_omissions(original, item_id=item_id, **authority(item_id))
    public, receipt = deepcopy(public), deepcopy(receipt)
    cell = public[0]["structure"][0]["content"][0]
    if mutation == "text":
        cell["content"][0]["text"] = "Changed"
    elif mutation == "language":
        cell["attributes"]["language"] = "la"
    elif mutation == "link":
        cell["attributes"]["source_target"] = "https://example.org/other"
    elif mutation == "span":
        cell["attributes"]["row_span"] = "3"
    elif mutation == "field":
        receipt["omissions"][0]["fields"][-1]["path"] = ["text"]
    elif mutation == "digest":
        receipt["authority"]["formatting_scope_sha256"] = "0" * 64
    else:
        cell["attributes"]["style"] = "border:0"
        receipt["omissions"][0]["fields"] = receipt["omissions"][0]["fields"][:-1]
        receipt["omissions"][0]["public_row_sha256"] = policy._digest(public[0])
    with pytest.raises(PipelineError):
        policy.restore_private_source_locations(public, receipt, item_id=item_id,
                                                **authority(item_id))


def test_new_scope_rejects_legacy_receipt_and_unknown_format() -> None:
    item_id = "john-cassian-selected-works--john-cassian-selected-works-npnf211-electronic-witness"
    public, receipt = policy.public_rows_with_omissions(row("style:margin-top:48pt"),
                                                        item_id=item_id, **authority(item_id))
    receipt["contract"] = policy.CONTRACT
    with pytest.raises(PipelineError, match="historical public-row transform required"):
        policy.restore_private_source_locations(public, receipt, item_id=item_id,
                                                **authority(item_id))
    with pytest.raises(PipelineError, match="unclassified native presentation"):
        policy.public_rows_with_omissions(row("unclassified:decorative"),
                                          item_id=item_id, **authority(item_id))
