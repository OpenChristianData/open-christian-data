from __future__ import annotations

import copy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from ocd_kernel.tei.conformance import (
    ConformanceError, FixturePackage, compare_reference, load_fixture_package, parse_xml,
    verify_live_origin,
)
from ocd_kernel.tei.profile import ProfileError, load_profile, render_schematron
from ocd_kernel.tei.extensions import validate_extension_record
from ocd_kernel.tei.validation import validate_tei


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "tei-conformance"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


@pytest.fixture(scope="module")
def package():
    return load_fixture_package(FIXTURES / "manifest.json")


@pytest.fixture(scope="module")
def profile():
    return load_profile()


def _example_with(package, expression):
    for record in package.manifest["fixtures"]:
        raw = package.reference(record["id"])
        tree = parse_xml(raw)
        nodes = tree.xpath(expression, namespaces=NS)
        if nodes:
            return record, raw, tree, nodes
    pytest.fail(f"real fixture coverage missing: {expression}")


def _write_manifest(root, manifest):
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def test_all_references_are_bound_and_comparison_is_not_source_acceptance(package):
    for record in package.manifest["fixtures"]:
        result = compare_reference(package.reference(record["id"]), package, record["id"])
        assert result.status == "matches-frozen-reference"
        assert not result.issues
        assert result.source_fidelity == "not-assessed-by-reference-comparison"


@pytest.mark.parametrize("fixture_id", [record["id"] for record in json.loads(
    (FIXTURES / "manifest.json").read_text(encoding="utf-8"))["fixtures"]])
def test_every_fixture_matches_its_declared_common_profile_outcome(package, profile, fixture_id):
    record = package.fixture(fixture_id)
    expected = record["expected"]
    assert expected["p5"] == "expected-pass"
    assert expected["semantic"] in ("provisional-pass", "expected-common-profile-failure")
    result = validate_tei(package.reference(fixture_id), profile=profile)
    assert result.p5_valid, result.issues
    assert result.semantic_valid == (expected["semantic"] == "provisional-pass")
    assert {issue.rule_id for issue in result.issues} == set(expected["required_common_rule_ids"])


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "reorder"])
def test_real_structure_corruption_is_visible_even_when_p5_allows_it(package, profile, mutation):
    record, original, tree, nodes = _example_with(package, "//tei:table[tei:row[2]]")
    table = nodes[0]
    rows = table.findall("tei:row", NS)
    if mutation == "omit":
        table.remove(rows[-1])
        expected = "reference-content-omitted-or-changed"
    elif mutation == "duplicate":
        duplicate = copy.deepcopy(rows[-1])
        # XML IDs are distinct-identity constraints, not a row-count oracle.
        for node in duplicate.iter():
            node.attrib.pop("{http://www.w3.org/XML/1998/namespace}id", None)
        table.append(duplicate)
        expected = "reference-content-added-duplicated-or-changed"
    else:
        table.remove(rows[-1])
        table.insert(0, rows[-1])
        expected = "reference-order-or-attachment-changed"
    mutated = etree.tostring(tree)
    result = validate_tei(mutated, profile=profile, package=package, fixture_id=record["id"])
    assert result.p5_valid, result.issues
    assert expected in result.reference_accounting["issues"]
    assert result.reference_accounting["reference_sha256"] == sha256(original).hexdigest()
    assert result.reference_accounting["candidate_sha256"] == sha256(mutated).hexdigest()
    assert package.reference(record["id"]) == original


def test_p5_element_misspelling_is_separate_from_accounting(package, profile):
    record, _, tree, nodes = _example_with(package, "//tei:table/tei:row/tei:cell")
    nodes[0].tag = "{http://www.tei-c.org/ns/1.0}Cell"
    result = validate_tei(etree.tostring(tree), profile=profile, package=package, fixture_id=record["id"])
    assert not result.p5_valid
    assert not result.semantic_valid
    assert any(issue.stage == "p5" for issue in result.issues)
    assert result.reference_accounting["issues"]


def test_invented_division_value_cannot_hide_behind_p5(package, profile):
    _, _, tree, nodes = _example_with(package, "//tei:div[@type]")
    nodes[0].set("type", "one-session-invention")
    result = validate_tei(etree.tostring(tree), profile=profile)
    assert result.p5_valid, result.issues
    assert not result.semantic_valid
    assert any(issue.stage == "semantic" and "one-session-invention" in issue.message
               or issue.stage == "semantic" and "div" in issue.message.lower()
               for issue in result.issues)
    assert result.reference_accounting["status"] == "not-assessed"


def test_fixture_hash_tamper_fails_closed(tmp_path, package):
    destination = tmp_path / "f"
    shutil.copytree(FIXTURES, destination)
    record = package.manifest["fixtures"][0]
    path = destination / record["path"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ConformanceError, match="stale SHA-256"):
        load_fixture_package(destination / "manifest.json")


@pytest.mark.parametrize("path", [".", "../escape.xml", "/escape.xml", "x/../escape.xml", "x\\escape.xml", "x:escape.xml"])
def test_manifest_paths_cannot_escape(tmp_path, package, path):
    manifest = copy.deepcopy(package.manifest)
    manifest["fixtures"][0]["path"] = path
    _write_manifest(tmp_path, manifest)
    with pytest.raises(ConformanceError, match="path"):
        load_fixture_package(tmp_path / "manifest.json")


def test_duplicate_manifest_keys_rejected(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('{"status":"provisional","status":"adopted"}', encoding="utf-8")
    with pytest.raises(ConformanceError, match="duplicate JSON key"):
        load_fixture_package(path)


def test_entity_input_has_visible_failure(profile):
    data = b'<!DOCTYPE TEI [<!ENTITY payload SYSTEM "file:///not-read">]><TEI>&payload;</TEI>'
    result = validate_tei(data, profile=profile)
    assert not result.p5_valid and not result.semantic_valid
    assert result.issues[0].rule_id == "well-formed-safe-xml"
    assert result.source_fidelity == "not-assessed"


def test_partial_reference_arguments_are_rejected(package, profile):
    data = package.reference(package.manifest["fixtures"][0]["id"])
    with pytest.raises(ValueError, match="supplied together"):
        validate_tei(data, profile=profile, package=package)


def test_checked_in_schematron_is_generated_from_the_bound_profile(profile):
    assert (profile.root / "common-rules.sch").read_bytes() == render_schematron(profile)


@pytest.mark.parametrize("mutation", ["missing", "stale", "extra"])
def test_profile_member_closure_fails_closed(tmp_path, profile, mutation):
    destination = tmp_path / "profile"
    shutil.copytree(profile.root, destination)
    if mutation == "missing":
        (destination / "controlled-values.json").unlink()
    elif mutation == "stale":
        path = destination / "controlled-values.json"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        (destination / "undeclared.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(destination)


def test_safe_xml_parse_does_not_normalize_source_wording():
    tree = parse_xml(b'<p xmlns="http://www.tei-c.org/ns/1.0">Old  spelling <hi>and</hi> tail.</p>')
    assert tree.getroot().text == "Old  spelling "
    assert tree.getroot()[0].tail == " tail."


@pytest.mark.parametrize("context", ["div/@type", "note/@place", "ref/@type", "list/@type", "hi/@rend", "idno/@type", "head/@type"])
def test_each_controlled_context_rejects_unregistered_value(package, profile, context):
    element, attribute = context.split("/@")
    _, _, tree, nodes = _example_with(package, f"//tei:{element}[@{attribute}]")
    nodes[0].set(attribute, "one-session-invention")
    result = validate_tei(etree.tostring(tree), profile=profile)
    assert result.p5_valid, result.issues
    assert f"ocd-controlled-{element}-{attribute}" in {issue.rule_id for issue in result.issues}


def test_note_reference_runs_all_overlapping_context_rules(package, profile):
    _, _, tree, nodes = _example_with(package, "//tei:ref[@type='note']")
    node = nodes[0]
    node.set("target", "#missing-note")
    node.set("cRef", "John.3.16")
    result = validate_tei(etree.tostring(tree), profile=profile)
    rules = {issue.rule_id for issue in result.issues}
    assert "ocd-note-target-resolves" in rules
    assert "ocd-ref-target-cRef-exclusive" in rules
    assert "ocd-ref-cRef-scripture" in rules


def test_source_digest_format_and_placement_both_run(package, profile):
    _, _, tree, nodes = _example_with(package, "//tei:sourceDesc//tei:idno[@type='sha256']")
    node = nodes[0]
    node.text = "a" * 40
    node.getparent().remove(node)
    paragraph = tree.xpath("//tei:body//tei:p", namespaces=NS)[0]
    paragraph.append(node)
    result = validate_tei(etree.tostring(tree), profile=profile)
    assert result.p5_valid, result.issues
    rules = {issue.rule_id for issue in result.issues}
    assert "ocd-sha256-format" in rules
    assert "ocd-source-idno-context" in rules


def test_source_only_header_probe_checks_bound_ids_without_claiming_master(package, profile):
    fixture_id = "lightfoot-source-only-header-probe"
    raw = package.reference(fixture_id)
    with pytest.raises(ConformanceError, match="header-probe"):
        validate_tei(raw, profile=profile, mode="master", package=package, fixture_id=fixture_id)
    result = validate_tei(raw, profile=profile, mode="header-probe", package=package, fixture_id=fixture_id)
    assert result.p5_valid
    assert not {"master-identity-cardinality", "master-revision-binding", "fixture-identity-mismatch"} & {i.rule_id for i in result.issues}
    tree = parse_xml(raw)
    tree.xpath("//tei:idno[@type='ocd-work-id']", namespaces=NS)[0].text = "unbound-work"
    result = validate_tei(etree.tostring(tree), profile=profile, mode="excerpt", package=package, fixture_id=fixture_id)
    assert "fixture-identity-mismatch" in {issue.rule_id for issue in result.issues}


@pytest.mark.parametrize("mutation", ["stale-source", "empty-selector", "scalar-selector"])
def test_live_binding_rejects_stale_bytes_and_nonselecting_origin(tmp_path, package, mutation):
    # A local copy of a real excerpt serves as the input to this synthetic
    # binding-corruption probe; no historical retained source is changed.
    record = copy.deepcopy(package.manifest["fixtures"][0])
    raw = package.reference(record["id"])
    source = tmp_path / "origin.xml"
    source.write_bytes(raw)
    digest = sha256(raw).hexdigest()
    record["origin"].update({"tei_path": "origin.xml", "tei_sha256": digest,
                             "selector": "/tei:TEI", "source_authorities": [],
                             "source_members": [{"path": "origin.xml", "sha256": digest,
                                                 "locator": "complete copied excerpt"}]})
    local = FixturePackage(package.root, {"fixtures": [record]}, package.manifest_sha256)
    if mutation == "stale-source":
        source.write_bytes(raw + b"\n")
        expected = "stale SHA-256"
    else:
        record["origin"]["selector"] = "//tei:no-such-element" if mutation == "empty-selector" else "string(/tei:TEI)"
        expected = "selects no element evidence"
    with pytest.raises(ConformanceError, match=expected):
        verify_live_origin(local, record["id"], tmp_path)


@pytest.mark.parametrize("extension_id", ["ext-liturgy-rubric", "ext-sermon-primary-reference", "ext-standard-ebooks-analytical-annotation"])
def test_bound_extension_is_inert_by_default_and_explicitly_provisional(package, profile, extension_id):
    extension = next(record for record in profile.extensions if record["extension_id"] == extension_id)
    fixture_id = extension["real_examples"][0]["fixture"]["id"]
    raw = package.reference(fixture_id)
    assert not validate_tei(raw, profile=profile).semantic_valid
    result = validate_tei(raw, profile=profile, package=package, fixture_id=fixture_id,
                          extension_ids=(extension_id,))
    assert result.p5_valid and result.semantic_valid, result.issues
    assert result.reference_accounting["status"] == "matches-frozen-reference"
    assert result.status == "provisional" and result.adoption == "not-established"
    assert result.projector_readiness
    assert all(row["admission"] == "provisional-fixture-test-only" for row in result.projector_readiness)


def test_extension_cannot_be_activated_by_id_without_evidence(package, profile):
    raw = package.reference("bcp1662-liturgy")
    with pytest.raises(ConformanceError, match="bound fixture"):
        validate_tei(raw, profile=profile, extension_ids=("ext-liturgy-rubric",))
    with pytest.raises(ConformanceError, match="not bound to fixture"):
        validate_tei(raw, profile=profile, package=package, fixture_id="athanasius-table",
                     extension_ids=("ext-liturgy-rubric",))


@pytest.mark.parametrize("mutation", ["extra-annotation", "wrong-placement", "zero-witness"])
def test_rubric_extension_does_not_admit_unrelated_vocabulary_or_scope(package, profile, mutation):
    tree = parse_xml(package.reference("bcp1662-liturgy"))
    node = tree.xpath("//tei:p[@rend='rubric']", namespaces=NS)[0]
    if mutation == "extra-annotation":
        node.set("ana", "invented:rubric")
    elif mutation == "wrong-placement":
        node.getparent().remove(node)
        tree.xpath("//tei:sourceDesc/tei:bibl", namespaces=NS)[0].append(node)
    else:
        node.attrib.pop("rend")
    result = validate_tei(etree.tostring(tree), profile=profile, package=package,
                          fixture_id="bcp1662-liturgy", extension_ids=("ext-liturgy-rubric",))
    assert not result.semantic_valid, result.issues
    assert any(issue.stage == "semantic" for issue in result.issues)


def test_external_annotation_extension_rejects_one_session_token(package, profile):
    fixture_id = "augustine-standard-ebooks-annotations"
    tree = parse_xml(package.reference(fixture_id))
    tree.xpath("//*[@ana]")[0].set("ana", "one-session:invention")
    result = validate_tei(etree.tostring(tree), profile=profile, package=package, fixture_id=fixture_id,
                          extension_ids=("ext-standard-ebooks-analytical-annotation",))
    assert not result.semantic_valid
    assert "ocd-undeclared-annotation" in {issue.rule_id for issue in result.issues}


def test_sermon_quote_order_is_checked_in_addition_to_reference_accounting(package, profile):
    fixture_id = "spurgeon-primary-references"
    tree = parse_xml(package.reference(fixture_id))
    quote = tree.xpath("//tei:quote[@type='primary-reference']", namespaces=NS)[0]
    second = quote[1]
    quote.remove(second)
    quote.insert(0, second)
    result = validate_tei(etree.tostring(tree), profile=profile, package=package, fixture_id=fixture_id,
                          extension_ids=("ext-sermon-primary-reference",))
    assert result.p5_valid
    assert not result.semantic_valid
    assert any(issue.stage == "semantic" for issue in result.issues)
    assert "reference-order-or-attachment-changed" in result.reference_accounting["issues"]


def test_in_memory_vocabulary_edit_cannot_reuse_a_verified_profile_hash(package, profile):
    values = copy.deepcopy(profile.controlled_values)
    values["div/@type"].append("one-session-invention")
    altered = replace(profile, controlled_values=values)
    with pytest.raises(ProfileError, match="hash-bound"):
        validate_tei(package.reference("athanasius-table"), profile=altered)


@pytest.mark.parametrize("field", ["owner", "real_examples", "projection", "independent_checks", "decision"])
def test_incomplete_extension_records_are_not_admitted(profile, field):
    record = copy.deepcopy(profile.extensions[0])
    del record[field]
    with pytest.raises(ProfileError, match="missing"):
        validate_extension_record(record)


def test_unsupported_extension_order_is_rejected_instead_of_ignored(profile):
    record = copy.deepcopy(profile.extensions[0])
    record["representation"]["order"] = ["invented-category-order"]
    with pytest.raises(ProfileError, match="unsupported order"):
        validate_extension_record(record)


@pytest.mark.parametrize("mutation", ["extra-rule", "missing-rule", "reserved-rule"])
def test_extension_rule_declarations_match_executable_rules(profile, mutation):
    record = copy.deepcopy(profile.extensions[1])
    if mutation == "extra-rule":
        record["validation_rule_ids"].append("unexecuted-rule")
    elif mutation == "missing-rule":
        record["validation_rule_ids"].pop()
    else:
        record["validation_rule_ids"][0] = "ocd-note-target-resolves"
    with pytest.raises(ProfileError):
        validate_extension_record(record)


@pytest.mark.parametrize("mutation", ["schema-version", "extra-field", "missing-title"])
def test_fixture_manifest_rejects_an_incompatible_contract(tmp_path, package, mutation):
    destination = tmp_path / "f"
    shutil.copytree(FIXTURES, destination)
    manifest = copy.deepcopy(package.manifest)
    if mutation == "schema-version":
        manifest["schema_version"] = "future-incompatible-v99"
    elif mutation == "extra-field":
        manifest["source_approval"] = "invented"
    else:
        del manifest["fixtures"][0]["title"]
    _write_manifest(destination, manifest)
    with pytest.raises(ConformanceError):
        load_fixture_package(destination / "manifest.json")


@pytest.mark.parametrize("fixture_id,legacy", [
    ("kempis-title-page", "titlepage"),
    ("underhill-title-page", "titlepage"),
    ("kempis-half-title-page", "halftitlepage"),
    ("underhill-half-title-page", "halftitlepage"),
])
def test_source_page_alias_cannot_replace_canonical_spelling(package, profile, fixture_id, legacy):
    tree = parse_xml(package.reference(fixture_id))
    page = tree.xpath("//tei:div[@type='title-page' or @type='half-title-page']", namespaces=NS)[0]
    page.set("type", legacy)
    result = validate_tei(etree.tostring(tree), profile=profile)
    assert result.p5_valid
    assert not result.semantic_valid
    assert "ocd-controlled-div-type" in {issue.rule_id for issue in result.issues}


@pytest.mark.parametrize("fixture_id,preferred,misspelling", [
    ("stokes-subscript", "subscript", "sub-script"),
    ("greenleaf-small-caps", "small-caps", "smallcaps"),
])
def test_real_typography_requires_preferred_spelling(package, profile, fixture_id, preferred, misspelling):
    tree = parse_xml(package.reference(fixture_id))
    tree.xpath("//tei:hi[@rend=$rend]", namespaces=NS, rend=preferred)[0].set("rend", misspelling)
    result = validate_tei(etree.tostring(tree), profile=profile)
    assert result.p5_valid
    assert not result.semantic_valid
    assert "ocd-controlled-hi-rend" in {issue.rule_id for issue in result.issues}


def test_nave_reference_list_cannot_move_after_second_sense(package, profile):
    fixture_id = "nave-dictionary-entry-pure"
    tree = parse_xml(package.reference(fixture_id))
    entry = tree.xpath("//tei:div[@type='dictionary-entry']", namespaces=NS)[0]
    listing = entry.find("tei:list", NS)
    assert listing is not None
    assert [etree.QName(node).localname for node in entry] == ["head", "p", "list", "p"]
    entry.remove(listing)
    entry.append(listing)
    result = validate_tei(etree.tostring(tree), profile=profile,
                          package=package, fixture_id=fixture_id)
    assert result.p5_valid and result.semantic_valid
    assert "reference-order-or-attachment-changed" in result.reference_accounting["issues"]


def test_new_source_examples_pass_with_bound_identity_checks(package, profile):
    revised = [record for record in package.manifest["fixtures"]
               if record["origin"]["identity"].get("canonical_identity_status")
               == "source-local labels only; canonical pipeline identity is not asserted"]
    assert len(revised) == 10
    for record in revised:
        assert record["origin"]["identity"]["work_id"] is None
        assert record["origin"]["identity"]["legacy_slug"]
        result = validate_tei(package.reference(record["id"]), profile=profile,
                              package=package, fixture_id=record["id"])
        assert result.p5_valid and result.semantic_valid, (record["id"], result.issues)
        assert result.reference_accounting["status"] == "matches-frozen-reference"
        assert result.adoption == "not-established"
