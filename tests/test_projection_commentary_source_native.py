"""Focused source-native commentary correspondence and mutation checks."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import commentary as core
from ocd_kernel.projection.categories import commentary_source_native as native
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.native_content_check import observe_content, verify_content

ROOT = Path(__file__).resolve().parents[1]
TEI = "{http://www.tei-c.org/ns/1.0}"


def _master(work_id: str) -> ET.Element:
    work = ROOT / "library/works" / work_id
    paths = list(work.glob("forms/*/editions/*/master.tei.xml"))
    if len(paths) != 1:
        pytest.skip(f"installed accepted master unavailable for {work_id}")
    return ET.fromstring(io_path(paths[0]).read_bytes())


@pytest.fixture(scope="module")
def barnes() -> ET.Element:
    return _master("barnes-nt-notes")


@pytest.fixture(scope="module")
def robertson() -> ET.Element:
    return _master("robertson-word-pictures-vol1")




def test_barnes_native_envelope_rejects_unselected_content(barnes: ET.Element) -> None:
    root = copy.deepcopy(barnes)
    text = root.find(f"{TEI}text")
    assert text is not None
    body = text.find(f"{TEI}body")
    assert body is not None
    slots = native._profile(body, "barnes")
    native._envelope(root, body, slots, "barnes")

    front = ET.Element(f"{TEI}front")
    front.text = "Omitted front"
    text.insert(0, front)
    with pytest.raises(PipelineError, match="front, back"):
        native._envelope(root, body, slots, "barnes")
    text.remove(front)

    back = ET.Element(f"{TEI}back")
    back.text = "Omitted back"
    text.append(back)
    with pytest.raises(PipelineError, match="front, back"):
        native._envelope(root, body, slots, "barnes")
    text.remove(back)

    for node, attribute, label in (
        (root, "text", "TEI root"),
        (root[0], "tail", "teiHeader tail"),
        (text, "text", "text wrapper"),
        (body, "text", "body wrapper"),
        (body[0], "text", "SWORD module wrapper"),
        (body[0], "tail", "body child tail"),
        (slots[0], "tail", "SWORD slot tail"),
    ):
        original = getattr(node, attribute)
        setattr(node, attribute, "UNACCOUNTED")
        with pytest.raises(PipelineError, match=label):
            native._envelope(root, body, slots, "barnes")
        setattr(node, attribute, original)


def test_robertson_native_envelope_rejects_member_tails(robertson: ET.Element) -> None:
    root = copy.deepcopy(robertson)
    text = root.find(f"{TEI}text")
    assert text is not None
    body = text.find(f"{TEI}body")
    assert body is not None
    members = native._profile(body, "robertson")
    native._envelope(root, body, members, "robertson")
    body.tail = "UNPROJECTED AFTER BODY"
    with pytest.raises(PipelineError, match="body tail"):
        native._envelope(root, body, members, "robertson")
    body.tail = None
    members[0].tail = "UNACCOUNTED"
    with pytest.raises(PipelineError, match="body child tail"):
        native._envelope(root, body, members, "robertson")


def test_barnes_all_source_slots_have_exact_order_and_empty_slots(barnes: ET.Element) -> None:
    body = barnes.find(f"{TEI}text/{TEI}body")
    assert body is not None
    slots = native._profile(body, "barnes")
    assert len(slots) == 8246
    assert sum(slot.get("ana") == "#empty-source-slot" for slot in slots) == 783

    shortened = copy.deepcopy(body)
    shortened[0].remove(shortened[0][5])
    with pytest.raises(PipelineError, match="8246"):
        native._profile(shortened, "barnes")

    reordered = copy.deepcopy(body)
    first, second = reordered[0][0], reordered[0][1]
    reordered[0].remove(first)
    reordered[0].remove(second)
    reordered[0].insert(0, second)
    reordered[0].insert(1, first)
    with pytest.raises(PipelineError, match="slot order"):
        native._profile(reordered, "barnes")


def test_barnes_byte_gap_marker_hash_and_adjacent_text(barnes: ET.Element) -> None:
    body = barnes.find(f"{TEI}text/{TEI}body")
    assert body is not None
    source_slot = next(slot for slot in body[0] if any(node.tag == f"{TEI}gap" for node in slot.iter()))
    slot = copy.deepcopy(source_slot)
    projected = project_content(slot)
    text = readable_content(projected)
    observed, observed_text = observe_content(ET.tostring(slot, encoding="utf-8"))
    assert (projected, text) == (observed, observed_text)
    assert "[unrepresentable source bytes]" in text

    gap = next(node for node in slot.iter() if node.tag == f"{TEI}gap")
    gap.set("n", "0" * 64)
    assert verify_content(ET.tostring(slot, encoding="utf-8"), projected, text)
    gap.set("n", "not-a-hash")
    with pytest.raises(PipelineError, match="gap"):
        project_content(slot)
    gap.set("n", next(node for node in source_slot.iter() if node.tag == f"{TEI}gap").get("n"))
    gap.tail = (gap.tail or "") + " MUTATED"
    assert verify_content(ET.tostring(slot, encoding="utf-8"), projected, text)


def test_robertson_member_links_and_literal_multi_targets(robertson: ET.Element) -> None:
    body = robertson.find(f"{TEI}text/{TEI}body")
    assert body is not None
    units = native._profile(body, "robertson")
    assert [unit.get("n") for unit in units] == ["matthew", "mark"]
    paths = native._paths(robertson)
    inventory, references, _warnings = native._evidence(units, paths, "robertson")
    links = [item for item in inventory if item["disposition"] == "source-division-link"]
    divisions = [item for item in inventory if item["disposition"] in {"source-division", "source-division-link"}]
    profile = next(item for item in inventory if item["disposition"] == "source-native-profile")
    assert len(links) == 54
    assert len(divisions) == 62
    assert profile["paragraphs"] == 1531
    assert len(references) == 166
    assert any(item["original_target"] == "Bible:Matt.9.9 Bible:Matt.10.3" for item in references)

    modified = copy.deepcopy(robertson)
    modified_units = native._profile(modified.find(f"{TEI}text/{TEI}body"), "robertson")
    linked = next(node for unit in modified_units for node in unit.iter() if node.get("next") is not None)
    linked.set("next", "#changed-source-link")
    changed_inventory, _, _ = native._evidence(modified_units, native._paths(modified), "robertson")
    assert [item for item in changed_inventory if item["disposition"] == "source-division-link"] != links

    modified = copy.deepcopy(robertson)
    modified_units = native._profile(modified.find(f"{TEI}text/{TEI}body"), "robertson")
    multiple = next(node for unit in modified_units for node in unit.iter() if node.tag == f"{TEI}ref" and len((node.get("target") or "").split()) > 1)
    multiple.set("target", "Bible:Matt.10.3 Bible:Matt.9.9")
    _, changed_references, _ = native._evidence(modified_units, native._paths(modified), "robertson")
    assert changed_references != references

    reordered = copy.deepcopy(body)
    first, second = reordered[0], reordered[1]
    reordered.remove(first)
    reordered.remove(second)
    reordered.extend((second, first))
    with pytest.raises(PipelineError, match="ordered Matthew and Mark"):
        native._profile(reordered, "robertson")


def test_native_row_order_schema_and_private_receipt(robertson: ET.Element) -> None:
    body = robertson.find(f"{TEI}text/{TEI}body")
    assert body is not None
    metadata = {
        "acceptance": {"identity": {"work_id": "robertson-word-pictures-vol1", "textual_form_id": "robertson-form",
                                    "edition_id": "robertson-edition"},
                       "representation_revision": {"id": "test-revision"}},
        "edition": type("Edition", (), {"title": "Source-defined Matthew and Mark"})(),
        "language": "en",
    }
    rows = []
    for ordinal, unit in enumerate(native._profile(body, "robertson"), 1):
        structure = project_content(unit)
        rows.append(native._row(metadata, structure, readable_content(structure), ordinal))
    core._validate_rows(rows)
    expected = {"rows": rows, "receipt": {"links": ["#matthew-ii"], "targets": ["Bible:Matt.9.9 Bible:Matt.10.3"]}}
    assert native._compare(expected, rows, expected["receipt"]) == []

    assert native._compare(expected, rows[:-1], expected["receipt"])
    assert native._compare(expected, list(reversed(rows)), expected["receipt"])
    changed_receipt = copy.deepcopy(expected["receipt"])
    changed_receipt["links"] = []
    assert native._compare(expected, rows, changed_receipt)

    changed_rows = copy.deepcopy(rows)
    changed_rows[0]["locator"]["unit"] = 0
    errors = native._compare(expected, changed_rows, expected["receipt"])
    assert errors == ["native commentary row 1 differs"]
    with pytest.raises(PipelineError, match="invalid commentary public row"):
        core._validate_rows(changed_rows)



@pytest.mark.requires_local_artifacts
def test_canonical_robertson_independent_receipt_rejects_link_target_and_row_mutations() -> None:
    work = ROOT / "library/works/robertson-word-pictures-vol1"
    paths = list(work.glob("forms/*/editions/*/acceptance.json"))
    if len(paths) != 1:
        pytest.skip("installed Robertson acceptance unavailable")
    metadata = core._accepted_metadata(ROOT, paths[0])
    expected = native._projection(metadata, "robertson", independent=True)
    assert len(expected["rows"]) == 2
    assert native._compare(expected, expected["rows"], expected["receipt"]) == []

    changed_receipt = copy.deepcopy(expected["receipt"])
    link = next(item for item in changed_receipt["inventory"] if item["disposition"] == "source-division-link")
    link["attributes"]["next"] = "#wrong-order"
    assert "native commentary private receipt differs" in native._compare(expected, expected["rows"], changed_receipt)

    changed_receipt = copy.deepcopy(expected["receipt"])
    changed_receipt["references"][0]["original_target"] = "Bible:Matt.10.3 Bible:Matt.9.9"
    assert "native commentary private receipt differs" in native._compare(expected, expected["rows"], changed_receipt)

    changed_rows = copy.deepcopy(expected["rows"])
    changed_rows[0]["sequence"] = 2
    assert any("native commentary row 1 differs" in error for error in native._compare(expected, changed_rows, expected["receipt"]))


@pytest.mark.requires_local_artifacts
@pytest.mark.parametrize(
    ("work_id", "source_native_route"),
    [
        ("lightfoot-colossians-philemon", "lightfoot"),
        ("ryle-expository-thoughts-matthew", None),
        ("barnes-nt-notes", "barnes"),
        ("robertson-word-pictures-vol1", "robertson"),
    ],
)
def test_installed_commentary_acceptance_route_respects_optional_source_kind(
    work_id: str, source_native_route: str | None
) -> None:
    acceptances = list((ROOT / "library/works" / work_id).glob("forms/*/editions/*/acceptance.json"))
    assert len(acceptances) == 1
    acceptance = json.loads(io_path(acceptances[0]).read_text(encoding="utf-8"))
    assert acceptance["source"].get("source_kind") == (
        "retained-member-set" if source_native_route in {"barnes", "robertson"} else None
    )
    assert native.route({"acceptance": acceptance}) == source_native_route
    changed = copy.deepcopy(acceptance)
    changed["source"]["source_kind"] = "other-source-kind"
    assert native.route({"acceptance": changed}) is None


@pytest.fixture(scope="module")
def lightfoot() -> ET.Element:
    return _master("lightfoot-colossians-philemon")


def test_lightfoot_requires_complete_ordered_source_envelope(lightfoot: ET.Element) -> None:
    root = copy.deepcopy(lightfoot)
    text = root.find(f"{TEI}text")
    assert text is not None
    body = text.find(f"{TEI}body")
    assert body is not None
    regions = native._profile(body, "lightfoot")
    assert len(regions) == 17
    native._envelope(root, body, regions, "lightfoot")
    envelope = body[0]
    license_region = envelope[-1]
    envelope.remove(license_region)
    with pytest.raises(PipelineError, match="region count"):
        native._profile(body, "lightfoot")
    envelope.append(license_region)
    first = envelope[0]
    envelope.remove(first)
    envelope.insert(1, first)
    with pytest.raises(PipelineError, match="identity or order"):
        native._profile(body, "lightfoot")
    envelope.remove(first)
    envelope.insert(0, first)
    envelope.text = "UNACCOUNTED"
    with pytest.raises(PipelineError, match="envelope wrapper"):
        native._envelope(root, body, native._profile(body, "lightfoot"), "lightfoot")
    envelope.text = None
    license_region.tail = "UNACCOUNTED"
    with pytest.raises(PipelineError, match="source-region tail"):
        native._envelope(root, body, native._profile(body, "lightfoot"), "lightfoot")


def test_lightfoot_native_content_and_private_digest_preserve_source_features(lightfoot: ET.Element) -> None:
    root = copy.deepcopy(lightfoot)
    body = root.find(f"{TEI}text/{TEI}body")
    assert body is not None
    regions = native._profile(body, "lightfoot")
    nodes = [node for region in regions for node in region.iter()]
    examples = [
        next(node for node in nodes if node.tag == f"{TEI}seg" and node.get("ana") and node.get("n")),
        next(node for node in nodes if node.tag == f"{TEI}hi" and node.get("n")),
        next(node for node in nodes if node.tag == f"{TEI}table"),
        next(node for node in nodes if node.tag == f"{TEI}ab" and node.get("type") == "source-line-gap"),
    ]
    for node in examples:
        structure = project_content(node)
        fragment = copy.deepcopy(node)
        fragment.tail = None
        observed, observed_text = observe_content(ET.tostring(fragment, encoding="utf-8"))
        assert structure == observed
        assert readable_content(structure) == observed_text
        changed = copy.deepcopy(structure)
        changed["attributes"][next(iter(changed["attributes"]))] = "mutated-source-marker"
        assert verify_content(ET.tostring(fragment, encoding="utf-8"), changed, observed_text)
    table = examples[2]
    assert any(node.tag == f"{TEI}cell" and node.get("role") for node in table.iter())

    region = next(region for region in regions if any(node.get("corresp") for node in region.iter()))
    paths = native._paths(root)
    original = native._lightfoot_source_digest(region, paths)
    marked = next(node for node in region.iter() if node.get("corresp"))
    old_corresp = marked.get("corresp")
    marked.set("corresp", "#mutated-source-correspondence")
    assert native._lightfoot_source_digest(region, paths) != original
    marked.set("corresp", old_corresp)
    assert native._lightfoot_source_digest(region, paths) == original
    table_region = next(item for item in regions if table in list(item.iter()))
    table_digest = native._lightfoot_source_digest(table_region, paths)
    table_parent = next(parent for parent in table_region.iter() if table in list(parent))
    table_parent.remove(table)
    assert native._lightfoot_source_digest(table_region, paths) != table_digest
