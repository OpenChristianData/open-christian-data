from __future__ import annotations

import json
import hashlib
from pathlib import Path
from copy import deepcopy

from lxml import etree
import pytest

from build.tei.jps_reconstruction import convert, reconstruct
from build.tei.jps_oracle import check_content, oracle
from ocd_kernel.reconstruction.contract import (
    CandidatePackage, SourceManifest, reconstruct as reconstruct_package, validate,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPOSITORY_ROOT / "raw/bible_databases/formats/json/JPS.json"
TEI_NS = "http://www.tei-c.org/ns/1.0"
MANIFEST_PATH = REPOSITORY_ROOT / 'tests/fixtures/reconstruction-runtime/jps.source-manifest.json'


def test_bound_package_validates_and_rejects_resealed_wording(tmp_path: Path) -> None:
    source = SourceManifest.load(MANIFEST_PATH, repository_root=REPOSITORY_ROOT)
    package = reconstruct_package(source, tmp_path / "package", convert)
    assert validate(source, package, oracle).status == "pass"
    content_path = package.path / "content.tei.xml"
    content = content_path.read_bytes()
    assert b"beginning" in content
    changed = content.replace(b"beginning", b"invention", 1)
    content_path.write_bytes(changed)
    package_manifest = package.path / "manifest.json"
    record = json.loads(package_manifest.read_bytes())
    member = next(row for row in record["members"] if row["name"] == "content.tei.xml")
    member.update(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest())
    package_manifest.write_bytes(
        (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )
    with pytest.raises(ValueError, match="JPS oracle: source text changed"):
        validate(source, CandidatePackage.load(package.path), oracle)


def test_complete_jps_json_carriers_have_a_readable_source_ordered_representation():
    source_bytes = SOURCE_PATH.read_bytes()

    tei_bytes, accounting_bytes = reconstruct(source_bytes)
    counts = check_content(source_bytes, tei_bytes, accounting_bytes)

    tree = etree.fromstring(tei_bytes)
    ns = {"tei": TEI_NS}
    assert counts == {"books": 39, "chapters": 929, "verses": 23_213, "empty_text": 19}
    assert (
        len(
            tree.xpath(
                "/tei:TEI/tei:text/tei:body/tei:div[@type='book']", namespaces=ns
            )
        )
        == 39
    )
    assert len(tree.xpath("//tei:div[@type='chapter']", namespaces=ns)) == 929
    assert len(tree.xpath("//tei:ab[@type='verse']", namespaces=ns)) == 23_213
    assert (
        len(tree.xpath("//tei:ab[@type='verse' and not(text())]", namespaces=ns)) == 19
    )

    accounting = json.loads(accounting_bytes)
    assert (
        accounting["source_sha256"]
        == "cb698cfbf2e97843dd4357b725c96ac6e9b2f3f23c5e3e3f6a3cdb5912ca183a"
    )
    assert accounting["selector"] == "/books"
    assert len(accounting["empty_text_carriers"]) == 19


@pytest.fixture(scope="module")
def jps_representation():
    source_bytes = SOURCE_PATH.read_bytes()
    tei_bytes, accounting_bytes = reconstruct(source_bytes)
    assert check_content(source_bytes, tei_bytes, accounting_bytes)["verses"] == 23_213
    tree = etree.fromstring(tei_bytes)
    return source_bytes, tree, accounting_bytes


def _tei_bytes(tree):
    return etree.tostring(tree, encoding="utf-8", xml_declaration=True) + b"\n"


def test_actual_jps_teI_tree_is_valid_against_the_bound_tei_schema(jps_representation):
    _, tree, _ = jps_representation
    schema_path = REPOSITORY_ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
    schema = etree.XMLSchema(etree.parse(str(schema_path)))

    schema.assertValid(tree)


def test_oracle_rejects_omitted_nonempty_verse_carrier(jps_representation):
    source_bytes, tree, accounting = jps_representation
    mutated = deepcopy(tree)
    verse = mutated.xpath(
        "//*[@xml:id='jps-b1-c1-v1']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    verse.getparent().remove(verse)
    with pytest.raises(ValueError, match="verse carrier omission"):
        check_content(source_bytes, _tei_bytes(mutated), accounting)


def test_oracle_rejects_changed_source_wording(jps_representation):
    source_bytes, tree, accounting = jps_representation
    mutated = deepcopy(tree)
    verse = mutated.xpath(
        "//*[@xml:id='jps-b1-c1-v1']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    verse.text += " changed"

    with pytest.raises(ValueError, match="source text changed"):
        check_content(source_bytes, _tei_bytes(mutated), accounting)


def test_oracle_rejects_reordered_source_sibling_verses(jps_representation):
    source_bytes, tree, accounting = jps_representation
    mutated = deepcopy(tree)
    chapter = mutated.xpath(
        "//*[@xml:id='jps-b1-c1']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    original = [
        node.get("{http://www.w3.org/XML/1998/namespace}id") for node in chapter
    ]
    first = chapter[0]
    chapter.remove(first)
    chapter.insert(1, first)

    assert len(chapter) == len(original)
    assert [
        node.get("{http://www.w3.org/XML/1998/namespace}id") for node in chapter
    ] != original
    with pytest.raises(ValueError, match="verse order"):
        check_content(source_bytes, _tei_bytes(mutated), accounting)


def test_oracle_rejects_removal_of_an_explicit_empty_verse_carrier(jps_representation):
    source_bytes, tree, accounting = jps_representation
    mutated = deepcopy(tree)
    verse = mutated.xpath(
        "//*[@xml:id='jps-b2-c20-v24']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    assert verse.text in (None, "")
    verse.getparent().remove(verse)

    with pytest.raises(ValueError, match="verse carrier omission"):
        check_content(source_bytes, _tei_bytes(mutated), accounting)


def test_oracle_rejects_duplicated_verse_carrier(jps_representation):
    source_bytes, tree, accounting = jps_representation
    mutated = deepcopy(tree)
    chapter = mutated.xpath(
        "//*[@xml:id='jps-b1-c1']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    chapter.append(deepcopy(chapter[0]))

    assert len(chapter) == 32
    with pytest.raises(ValueError, match="invalid XML: ID"):
        check_content(source_bytes, _tei_bytes(mutated), accounting)


def test_oracle_rejects_a_verse_attached_to_the_wrong_chapter(jps_representation):
    source_bytes, tree, accounting = jps_representation
    mutated = deepcopy(tree)
    first_chapter = mutated.xpath(
        "//*[@xml:id='jps-b1-c1']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    second_chapter = mutated.xpath(
        "//*[@xml:id='jps-b1-c2']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    moved = first_chapter[0]
    first_chapter.remove(moved)
    second_chapter.append(moved)

    with pytest.raises(
        ValueError, match="verse carrier omission/duplication/invention"
    ):
        check_content(source_bytes, _tei_bytes(mutated), accounting)


def test_oracle_rejects_invented_verse_and_changed_numbering(jps_representation):
    source_bytes, tree, accounting = jps_representation
    invented = deepcopy(tree)
    chapter = invented.xpath(
        "//*[@xml:id='jps-b1-c1']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    invented_verse = deepcopy(chapter[-1])
    invented_verse.set("{http://www.w3.org/XML/1998/namespace}id", "jps-invented-verse")
    chapter.append(invented_verse)
    with pytest.raises(
        ValueError, match="verse carrier omission/duplication/invention"
    ):
        check_content(source_bytes, _tei_bytes(invented), accounting)

    renumbered = deepcopy(tree)
    verse = renumbered.xpath(
        "//*[@xml:id='jps-b1-c1-v1']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    verse.set("n", "77")
    with pytest.raises(ValueError, match="verse order/identity/number"):
        check_content(source_bytes, _tei_bytes(renumbered), accounting)


def test_oracle_rejects_unaccounted_or_structural_tail_text(jps_representation):
    source_bytes, tree, accounting = jps_representation
    broken_accounting = json.loads(accounting)
    broken_accounting["fields"].pop()
    with pytest.raises(ValueError, match="source field/container accounting mismatch"):
        check_content(
            source_bytes, _tei_bytes(tree), json.dumps(broken_accounting).encode()
        )

    tailed = deepcopy(tree)
    title_stmt = tailed.xpath("//*[local-name()='titleStmt']")[0]
    title_stmt.tail = "invented structural text"
    with pytest.raises(ValueError, match="unexpected XML tail text"):
        check_content(source_bytes, _tei_bytes(tailed), accounting)


def test_oracle_rejects_a_stale_retained_source_binding(jps_representation):
    source_bytes, tree, accounting = jps_representation
    changed_source = source_bytes + b" "
    assert changed_source != source_bytes

    with pytest.raises(ValueError, match="pinned JPS witness"):
        check_content(changed_source, _tei_bytes(tree), accounting)


def test_producer_rejects_duplicate_json_keys_and_unknown_root_fields():
    duplicate_keys = b'{"translation":"JPS: Jewish Publication Society Old Testament","translation":"duplicate","books":[]}'
    with pytest.raises(ValueError, match="duplicate JSON key"):
        reconstruct(duplicate_keys)

    unknown_field = b'{"translation":"JPS: Jewish Publication Society Old Testament","books":[],"extra":"not in the source envelope"}'
    with pytest.raises(ValueError, match="root envelope"):
        reconstruct(unknown_field)


def test_existing_39_file_segmentation_is_accounted_without_becoming_source_authority():
    profile = json.loads(
        (
            REPOSITORY_ROOT / "sources/bible-text/jps/jps.reconstruction-profile.json"
        ).read_bytes()
    )
    expected = profile["downstream_segmentation_observation"]["source_order_crosswalk"]
    assert len(expected) == 39
    observed_paths = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (REPOSITORY_ROOT / "data/bible-text/jps").glob("*.json")
    }
    assert observed_paths == {row[2] for row in expected}

    total_rows = 0
    for source_name, projection_label, relative_path in expected:
        payload = json.loads((REPOSITORY_ROOT / relative_path).read_bytes())
        assert payload["meta"]["scope"]["book"] == projection_label, source_name
        total_rows += len(payload["data"])
    assert total_rows == 23_194


def test_work_manifest_binds_only_the_exact_jps_json_member_and_local_route():
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=REPOSITORY_ROOT)
    authorities = {item["name"]: item for item in manifest.record["authorities"]}
    primary = [
        item for item in authorities.values() if item["role"] == "primary-source"
    ]

    assert manifest.record["ticket_id"] == "37c-236"
    assert manifest.record["work_id"] == "jps"
    assert len(primary) == 1
    assert primary[0]["path"] == "raw/bible_databases/formats/json/JPS.json"
    assert primary[0]["bytes"] == 6_374_024
    assert (
        primary[0]["sha256"]
        == "cb698cfbf2e97843dd4357b725c96ac6e9b2f3f23c5e3e3f6a3cdb5912ca183a"
    )
    assert manifest.record["scope"]["content_selector"] == "/books"
    assert (
        authorities["jps-upstream-license"]["role"]
        == "repository-level-license-evidence"
    )
    assert authorities["jps-profile"]["role"] == "complete-source-feature-profile"
    assert authorities["jps-policy"]["role"] == "independent-validation-policy"


def test_work_specific_converter_emits_bound_members_in_memory_only():
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=REPOSITORY_ROOT)

    members = convert(manifest)

    assert set(members) == {
        "content.tei.xml",
        "source-accountability.json",
        "provenance.json",
        "unresolved.jsonl",
        "README.source.md",
    }
    assert (
        check_content(
            SOURCE_PATH.read_bytes(),
            members["content.tei.xml"],
            members["source-accountability.json"],
        )["empty_text"]
        == 19
    )
    unresolved = [json.loads(line) for line in members["unresolved.jsonl"].splitlines()]
    assert {item["status"] for item in unresolved} == {"unresolved"}
    assert any(
        item["question_id"] == "jps-rights-and-attribution" for item in unresolved
    )
    assert b"applicability to the JPS text is unresolved" in members["README.source.md"]
    assert b"Copyright (c) 2024 Scrollmapper" in members["README.source.md"]
