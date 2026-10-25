from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import shutil

from lxml import etree
from lxml.isoschematron import Schematron
import pytest

from ocd_kernel.tei.conformance import load_fixture_package, parse_xml
from ocd_kernel.tei.profile import ProfileError, load_profile, render_schematron
from ocd_kernel.tei.projection_profile import classify_base, drop_reason
from ocd_kernel.tei.validation import validate_tei


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "tei-conformance"
ARCHIVED_PROFILE_V01 = (
    ROOT
    / "plans"
    / "2026-08-31-library-pipeline-redesign"
    / "artifacts"
    / "TEI-003"
    / "revision-02"
    / "previous-profile-v0.1"
)
ARCHIVED_PROFILE_V02 = (
    ROOT
    / "plans"
    / "2026-08-31-library-pipeline-redesign"
    / "artifacts"
    / "TEI-003"
    / "revision-03"
    / "previous-profile-v0.2"
)
ARCHIVED_FIXTURES_V02 = (
    ROOT
    / "plans"
    / "2026-08-31-library-pipeline-redesign"
    / "artifacts"
    / "TEI-003"
    / "revision-03"
    / "previous-fixtures-v2"
)
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _hastings_tree() -> etree._ElementTree:
    tree = parse_xml((FIXTURES / "positive" / "hastings-dictionary-entry.tei.xml").read_bytes())
    for node in tree.getroot().iter():
        node.attrib.pop("ana", None)
        node.attrib.pop("subtype", None)
    return tree


def _profile_rule_ids(tree: etree._ElementTree, profile) -> list[str]:
    rules = Schematron(
        etree.fromstring(render_schematron(profile)),
        error_finder=Schematron.ASSERTS_AND_REPORTS,
        store_report=True,
    )
    rules.validate(tree)
    assert rules.validation_report is not None
    return [
        failure.get("id")
        for failure in rules.validation_report.xpath("//*[local-name()='failed-assert']")
    ]


def test_v03_profile_adds_dictionary_vocabulary_and_keeps_canonical_labels() -> None:
    profile = load_profile()

    assert profile.version == "0.3"
    assert profile.controlled_values["div/@type"][-1] == "dictionary-entry"
    assert profile.controlled_values["head/@type"] == ["headword"]
    assert {
        "title-page",
        "half-title-page",
        "subsection",
    } <= set(profile.controlled_values["div/@type"])
    assert {"subscript", "small-caps"} <= set(profile.controlled_values["hi/@rend"])

    tree = _hastings_tree()
    section = tree.xpath("//tei:div[@type='section']", namespaces=NS)[0]
    for value in ("title-page", "half-title-page", "subsection"):
        section.set("type", value)
        assert "ocd-controlled-div-type" not in _profile_rule_ids(tree, profile)
    for value in ("titlepage", "halftitlepage"):
        section.set("type", value)
        assert "ocd-controlled-div-type" in _profile_rule_ids(tree, profile)


def test_dictionary_entry_accepts_a_nonfirst_own_headword() -> None:
    profile = load_profile()
    tree = _hastings_tree()
    entry = tree.xpath("//tei:div[@type='dictionary-entry']", namespaces=NS)[0]
    headword = entry.xpath("./tei:head[@type='headword']", namespaces=NS)[0]
    entry.insert(0, etree.Element(f"{{{NS['tei']}}}pb", {"n": "2047"}))

    assert entry.index(headword) > 0
    result = validate_tei(etree.tostring(tree), profile=profile)
    assert result.p5_valid, result.issues
    assert result.semantic_valid, result.issues


def test_dictionary_entry_cannot_use_a_nested_entry_headword() -> None:
    profile = load_profile()
    tree = _hastings_tree()
    entry = tree.xpath("//tei:div[@type='dictionary-entry']", namespaces=NS)[0]
    headword = entry.xpath("./tei:head[@type='headword']", namespaces=NS)[0]
    entry.remove(headword)
    nested = etree.Element(f"{{{NS['tei']}}}div", {"type": "dictionary-entry"})
    nested_headword = etree.SubElement(nested, f"{{{NS['tei']}}}head", {"type": "headword"})
    nested_headword.text = "NESTED"
    entry.insert(0, nested)

    rule_ids = _profile_rule_ids(tree, profile)
    assert rule_ids.count("ocd-dictionary-entry-headword") == 1


def test_dictionary_entry_requires_a_nonempty_headword() -> None:
    profile = load_profile()
    tree = _hastings_tree()
    headword = tree.xpath("//tei:div[@type='dictionary-entry']/tei:head", namespaces=NS)[0]
    headword.text = " \n  "

    assert "ocd-dictionary-entry-headword" in _profile_rule_ids(tree, profile)


def test_previous_profile_package_is_complete_and_remains_loadable() -> None:
    current = load_profile()
    previous_v02 = load_profile(ARCHIVED_PROFILE_V02)
    previous_v01 = load_profile(ARCHIVED_PROFILE_V01)

    assert current.version == "0.3"
    assert previous_v02.version == "0.2"
    assert previous_v01.version == "0.1"
    assert "head/@type" in previous_v02.controlled_values
    assert "head/@type" not in previous_v01.controlled_values
    assert "dictionary-entry" in previous_v02.controlled_values["div/@type"]
    assert "dictionary-entry" not in previous_v01.controlled_values["div/@type"]
    assert (ARCHIVED_PROFILE_V02 / "common-rules.sch").read_bytes() == render_schematron(previous_v02)
    assert (ARCHIVED_PROFILE_V01 / "common-rules.sch").read_bytes() == render_schematron(previous_v01)


def test_previous_v02_fixture_outcomes_replay_under_archived_profile() -> None:
    package = load_fixture_package(ARCHIVED_FIXTURES_V02 / "manifest.json")
    profile = load_profile(ARCHIVED_PROFILE_V02)

    assert len(package.manifest["fixtures"]) == 27
    for record in package.manifest["fixtures"]:
        result = validate_tei(
            package.reference(record["id"]),
            profile=profile,
            package=package,
            fixture_id=record["id"],
        )
        expected = record["expected"]
        assert result.p5_valid == (expected["p5"] == "expected-pass"), record["id"]
        assert result.semantic_valid == (expected["semantic"] == "provisional-pass"), record["id"]
        assert {issue.rule_id for issue in result.issues} == set(
            expected["required_common_rule_ids"]
        ), record["id"]


@pytest.mark.parametrize(
    ("attribute", "value", "rule_id", "xpath"),
    [
        ("subtype", "one-session-invention", "ocd-undeclared-subtype", "//tei:div"),
        ("style", "font-weight: bold", "ocd-undeclared-style", "//tei:p"),
        ("rendition", "#one-session-invention", "ocd-undeclared-rendition", "//tei:p"),
    ],
)
def test_v03_rejects_unbound_global_attributes(
    attribute: str, value: str, rule_id: str, xpath: str
) -> None:
    profile = load_profile()
    tree = parse_xml((FIXTURES / "positive" / "eusebius-subscript.tei.xml").read_bytes())
    node = tree.xpath(xpath, namespaces=NS)[0]
    node.set(attribute, value)

    result = validate_tei(etree.tostring(tree), profile=profile)

    assert result.p5_valid, result.issues
    assert rule_id in {issue.rule_id for issue in result.issues}


def test_combined_hi_rendition_is_represented_by_nested_hi_elements() -> None:
    profile = load_profile()
    tree = parse_xml((FIXTURES / "positive" / "eusebius-subscript.tei.xml").read_bytes())
    outer = tree.xpath("//tei:hi", namespaces=NS)[0]
    original_text = outer.text
    original_tail = outer.tail
    outer.set("rend", "bold")
    inner = etree.Element(f"{{{NS['tei']}}}hi", {"rend": "italic"})
    inner.text = original_text
    inner.tail = original_tail
    outer.text = None
    outer.tail = None
    outer.append(inner)

    result = validate_tei(etree.tostring(tree), profile=profile)

    assert result.p5_valid, result.issues
    assert result.semantic_valid, result.issues


def test_combined_hi_rendition_token_is_rejected_without_nested_markup() -> None:
    profile = load_profile()
    tree = parse_xml((FIXTURES / "positive" / "eusebius-subscript.tei.xml").read_bytes())
    tree.xpath("//tei:hi", namespaces=NS)[0].set("rend", "bold italic")

    result = validate_tei(etree.tostring(tree), profile=profile)

    assert result.p5_valid, result.issues
    assert "ocd-controlled-hi-rend" in {issue.rule_id for issue in result.issues}


@pytest.mark.parametrize("div_type", ["title-page", "half-title-page"])
def test_canonical_title_page_divisions_are_dropped_by_projection_profile(div_type: str) -> None:
    root = etree.fromstring(
        f'<TEI xmlns="{NS["tei"]}"><text><front><div type="{div_type}"><p>matter</p></div></front></text></TEI>'
    )
    paragraph = root.xpath("//tei:p", namespaces=NS)[0]

    assert classify_base(paragraph) == "dropped"
    assert drop_reason(paragraph) == "drop.ancestor.div-type"


def test_profile_rejects_mixed_version_members(tmp_path) -> None:
    current = load_profile()
    destination = tmp_path / "mixed-profile"
    shutil.copytree(ARCHIVED_PROFILE_V01, destination)

    current_controlled = current.root / "controlled-values.json"
    shutil.copyfile(current_controlled, destination / "controlled-values.json")
    manifest_path = destination / "profile-registry.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    controlled_member = next(member for member in manifest["members"]
                             if member["role"] == "controlled-values")
    controlled_member["sha256"] = sha256(current_controlled.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ProfileError, match="controlled-values.schema_version"):
        load_profile(destination)


def test_extensions_are_inert_until_explicitly_selected_and_stay_provisional() -> None:
    package = load_fixture_package(FIXTURES / "manifest.json")
    profile = load_profile()
    fixture_id = "bcp1662-liturgy"
    raw = package.reference(fixture_id)

    plain = validate_tei(raw, profile=profile)
    selected = validate_tei(
        raw,
        profile=profile,
        package=package,
        fixture_id=fixture_id,
        extension_ids=("ext-liturgy-rubric",),
    )
    assert not plain.semantic_valid
    assert selected.p5_valid and selected.semantic_valid, selected.issues
    assert selected.status == "provisional"
    assert selected.adoption == "not-established"

    tree = parse_xml(raw)
    tree.xpath("//tei:p[@rend='rubric']", namespaces=NS)[0].set("ana", "one-session:invention")
    mutated = validate_tei(
        etree.tostring(tree),
        profile=profile,
        package=package,
        fixture_id=fixture_id,
        extension_ids=("ext-liturgy-rubric",),
    )
    assert not mutated.semantic_valid
    assert "ocd-undeclared-annotation" in {issue.rule_id for issue in mutated.issues}


def test_complete_tei_note_pointer_closure_resolves_and_rejects_missing() -> None:
    package = load_fixture_package(FIXTURES / "manifest.json")
    profile = load_profile()
    tree = parse_xml(package.reference("calvin-chapter-notes"))
    refs = tree.xpath("//tei:ref[@type='note']", namespaces=NS)
    for ref in refs:
        ref.set("target", "#pg45001-note-61")
    note = etree.Element(
        f"{{{NS['tei']}}}note",
        {XML_ID: "pg45001-note-61", "place": "foot"},
    )
    etree.SubElement(note, f"{{{NS['tei']}}}p").text = "resolved note"
    tree.xpath("//tei:div[@type='section']", namespaces=NS)[0].append(note)

    resolved = validate_tei(etree.tostring(tree), profile=profile)
    assert resolved.p5_valid, resolved.issues
    assert resolved.semantic_valid, resolved.issues

    refs[0].set("target", "#missing-note")
    missing = validate_tei(etree.tostring(tree), profile=profile)
    assert missing.p5_valid, missing.issues
    assert not missing.semantic_valid
    assert "ocd-note-target-resolves" in {issue.rule_id for issue in missing.issues}
