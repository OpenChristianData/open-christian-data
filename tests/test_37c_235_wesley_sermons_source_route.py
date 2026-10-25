from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from jsonschema import Draft202012Validator
from lxml import etree

from build.tei.john_wesley_sermons_oracle import (
    _assert_projection,
    _closure_paths,
    _import_closure_sha256,
    _source_census,
    _expected_projection,
)
from build.tei.john_wesley_sermons_reconstruction import (
    TAG_MAP,
    _project_document,
    _producer_import_closure_paths,
    _producer_import_closure_sha256,
)
from ocd_kernel.reconstruction import SourceManifest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "sources/sermons/john-wesley-sermons"
MANIFEST_PATH = ROOT / 'tests/fixtures/reconstruction-runtime/john_wesley_sermons_oracle.source-manifest.json'
PROFILE_PATH = SOURCE_DIR / "john-wesley-sermons.reconstruction-profile.json"
SOURCE_PATH = ROOT / "raw/ccel/wesley_sermons.xml"
EXPECTED_SOURCE_SHA256 = (
    "70f4b1d44754ae01889c52aeeb6a1b6f92b9444d016cef35f4c0b40e33ea375a"
)
TEI = "{http://www.tei-c.org/ns/1.0}"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _profile() -> dict[str, object]:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def _fixture() -> tuple[bytes, dict[str, object], dict[str, object]]:
    raw = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b"<!DOCTYPE ThML>\n"
        b"<ThML><ThML.head><DC.Title>Fixture sermons</DC.Title></ThML.head>"
        b'<ThML.body><div1 id="series-a" title="Series A">'
        b'<h1>Series A</h1><div2 id="sermon-a" title="Sermon A">'
        b'<p>Text <i>in order</i>.</p><note id="note-a">A note.</note>'
        b'<a href="#note-a">See note</a></div2></div1>'
        b'<div1 id="series-b" title="Series B"><div2 id="sermon-b" title="Sermon B">'
        b"<verse><l>Line one.</l><l>Line two.</l></verse><table><tr><td>Cell</td></tr></table>"
        b"</div2></div1></ThML.body></ThML>"
    )
    profile = _profile()
    profile["source_inventory"] = _source_census(raw)
    member = {
        "logical_path": "raw/ccel/wesley_sermons.xml",
        "bytes": len(raw),
        "sha256": _sha(raw),
    }
    return raw, profile, member


def test_manifest_binds_the_exact_current_retained_member_and_route_authorities() -> (
    None
):
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    record = manifest.record
    member = record["source_member"]
    raw = SOURCE_PATH.read_bytes()

    assert member == {
        "logical_path": "raw/ccel/wesley_sermons.xml",
        "bytes": 4_340_943,
        "sha256": EXPECTED_SOURCE_SHA256,
    }
    assert len(raw) == member["bytes"]
    assert _sha(raw) == member["sha256"]
    assert manifest.authority_path("retained-source").read_bytes() == raw
    assert (
        len(
            [item for item in record["authorities"] if item["role"] == "primary-source"]
        )
        == 1
    )
    assert record["work_id"] == "john-wesley-sermons"
    assert record["ticket_id"] == "LIB-059"
    assert record["producer_import_closure_sha256"] == _producer_import_closure_sha256()
    assert set(_producer_import_closure_paths()) == {
        ROOT / "build/tei/john_wesley_sermons_reconstruction.py",
        ROOT / "ocd_kernel/__init__.py",
        ROOT / "ocd_kernel/reconstruction/__init__.py",
        ROOT / "ocd_kernel/reconstruction/contract.py",
    }


def test_independent_stdlib_census_matches_the_complete_declared_envelope() -> None:
    profile = _profile()
    census = _source_census(SOURCE_PATH.read_bytes())

    assert census == profile["source_inventory"]
    assert census["root"] == "ThML"
    assert census["ordered_root_children"] == ["ThML.head", "ThML.body"]
    assert census["element_count"] == 15_636
    assert census["attribute_count"] == 22_125
    assert [row["id"] for row in census["body_carriers"]] == [
        "i",
        "ii",
        "iii",
        "iv",
        "v",
        "vi",
        "vii",
        "viii",
        "ix",
        "xi",
    ]
    assert census["sermon_div2_count"] == 141
    assert census["index_div2_ids"] == ["xi.i", "xi.ii", "xi.iii", "xi.iv"]
    assert census["unique_source_id_count"] == 10_846
    assert census["duplicate_source_id_count"] == 0
    assert census["internal_fragment_link_count"] == 561
    assert census["resolved_internal_fragment_link_count"] == 561


def test_source_profile_keeps_identity_and_editional_questions_open() -> None:
    profile = _profile()
    questions = {item["id"]: item for item in profile["candidate_questions"]}

    assert profile["source_scope"]["member_set_status"].startswith(
        "one exact member is bound"
    )
    assert {
        "identity-work",
        "identity-edition",
        "identity-parts",
        "identity-witnesses",
    } <= set(questions)
    assert all(
        questions[name]["status"] == "unresolved"
        for name in (
            "identity-work",
            "identity-edition",
            "identity-parts",
            "identity-witnesses",
        )
    )
    assert "1771" in questions["identity-edition"]["evidence"]
    assert "1872" in questions["identity-edition"]["evidence"]


def test_profile_names_every_retained_tag_mapping_or_explicit_fallback() -> None:
    profile = _profile()
    source_tags = set(profile["source_inventory"]["tag_counts"])
    explicit_tags = set(TAG_MAP) | {"ThML"}

    assert source_tags - explicit_tags
    assert profile["projection"]["unknown_elements"] == (
        "Use seg with type thml-{exact-source-tag}; preserve content, order, "
        "attributes in crosswalk, and source element identity without claiming semantic equivalence."
    )
    assert profile["projection"]["tag_mapping"]["all-other-source-tags"] == (
        "seg @type=thml-{exact-source-tag}"
    )
    assert profile["projection"]["tag_mapping"]["verse"] == "lg"


def test_synthetic_projection_matches_independent_oracle_before_mutations() -> None:
    raw, profile, member = _fixture()
    content, accountability = _project_document(raw, member, profile)

    _assert_projection(raw, content, member, profile)
    assert (
        accountability["element_count"] == profile["source_inventory"]["element_count"]
    )
    assert accountability["internal_links"] == {
        "count": 1,
        "resolved_count": 1,
        "unresolved": [],
    }
    assert [row["id"] for row in accountability["body_carriers"]] == [
        "series-a",
        "series-b",
    ]
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"), parser)
    )
    tei = etree.fromstring(content, parser)
    assert schema.validate(tei), str(schema.error_log)


def test_source_accountability_schema_is_valid_json_schema() -> None:
    schema = json.loads(
        (
            SOURCE_DIR / "john-wesley-sermons.source-accountability.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)


def test_full_retained_source_projection_validates_against_pinned_tei_p5() -> None:
    """Exercise real full-source output in memory, without packaging a candidate."""
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    raw = manifest.authority_path("retained-source").read_bytes()
    profile = _profile()
    content, accountability = _project_document(
        raw, manifest.record["source_member"], profile
    )
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    schema = etree.XMLSchema(
        etree.parse(str(manifest.authority_path("tei-p5-xsd")), parser)
    )
    tei = etree.fromstring(content, parser)
    assert schema.validate(tei), str(schema.error_log)
    expected, expected_accountability = _expected_projection(
        raw, manifest.record["source_member"], profile
    )
    assert ET.canonicalize(content) == ET.canonicalize(expected)
    assert accountability == expected_accountability
    accountability_schema = json.loads(
        manifest.authority_path("source-accountability-schema").read_bytes()
    )
    Draft202012Validator(accountability_schema).validate(accountability)

    # Locate the reported failure independently by retained native IDs.
    source = etree.fromstring(raw, parser)
    source_nodes = [node for node in source.iter() if isinstance(node.tag, str)]
    generated = {
        node: f"src-{number:05d}" for number, node in enumerate(source_nodes, 1)
    }
    targets = {
        node.get("{http://www.w3.org/XML/1998/namespace}id"): node
        for node in tei.iter()
    }
    # Source-led checks corroborate the producer/oracle's shared mapping policy.
    # Every heading retains its own carrier and mixed content, in source order.
    headings = [node for node in source_nodes if node.tag in {"h1", "h2", "h3"}]
    heading_ids = {generated[node] for node in headings}
    assert [
        node.get("{http://www.w3.org/XML/1998/namespace}id")
        for node in tei.iter()
        if node.get("{http://www.w3.org/XML/1998/namespace}id") in heading_ids
    ] == [generated[node] for node in headings]
    for heading in headings:
        actual = targets[generated[heading]]
        assert actual.tag in {TEI + "head", TEI + "ab"}
        assert list(actual.itertext()) == list(heading.itertext())
        assert actual.tail == heading.tail
        assert actual.getparent() is targets[generated[heading.getparent()]]
        if heading.get("class"):
            assert actual.get("rend") == heading.get("class")
    history = source.find(".//revisionHistory")
    assert history is not None
    assert targets[generated[history]].tag == TEI + "note"
    assert targets[generated[history]].get("type") == "thml-revisionHistory"
    assert targets[generated[history[0]]].tag == TEI + "p"
    sermon = source.xpath(".//div2[@id='ix.viii']")[0]
    actual_sermon = targets[generated[sermon]]
    assert [
        node.get("{http://www.w3.org/XML/1998/namespace}id")
        for node in actual_sermon.iter()
        if node.get("{http://www.w3.org/XML/1998/namespace}id")
    ] == [generated[node] for node in sermon.iter()]
    for native_id in ("ix.viii-p0.2", "ix.viii-p0.6", "ix.viii-p1.1"):
        heading = source.xpath(f".//*[@id='{native_id}']")[0]
        actual = targets[generated[heading]]
        assert actual.tag == TEI + "ab"
        assert actual.get("type") == "thml-" + heading.tag
        assert actual.getparent() is actual_sermon
        assert list(actual.itertext()) == list(heading.itertext())
        assert actual.tail == heading.tail
    assert len(tei.findall(f".//{TEI}div")) == sum(
        node.tag in {"div", "div1", "div2", "div3"} for node in source_nodes
    )

    # Reintroducing the original mapping must fail both schema and oracle.
    targets["src-13123"].tag = TEI + "head"
    assert not schema.validate(tei)
    with pytest.raises(ValueError, match="independent source projection"):
        _assert_projection(
            raw, etree.tostring(tei), manifest.record["source_member"], profile
        )


@pytest.mark.parametrize("heading_tag", ["h1", "h2", "h3"])
def test_later_heading_preserves_inline_content_without_new_division(
    heading_tag: str,
) -> None:
    raw, profile, member = _fixture()
    raw = raw.replace(
        b"<p>Text",
        (
            f"<{heading_tag}>Opening</{heading_tag}><p>Before</p>"
            f'<{heading_tag} class="heading">Later <i>emphasis</i> '
            f'<a href="#note-a">reference</a><note>Attached</note> tail</{heading_tag}>'
            "<p>Text"
        ).encode(),
    )
    profile["source_inventory"] = _source_census(raw)
    member.update(bytes=len(raw), sha256=_sha(raw))
    content, _ = _project_document(raw, member, profile)
    _assert_projection(raw, content, member, profile)
    root = etree.fromstring(content)
    sermon = root.find(f".//{TEI}div/{TEI}div")
    assert sermon is not None
    assert [node.tag for node in sermon][:4] == [
        TEI + "head",
        TEI + "head",
        TEI + "p",
        TEI + "ab",
    ]
    later = sermon[3]
    assert later.get("type") == "thml-" + heading_tag
    assert later.get("rend") == "heading"
    assert [node.tag for node in later] == [TEI + "hi", TEI + "ref", TEI + "note"]
    assert "".join(later.itertext()) == "Later emphasis referenceAttached tail"


@pytest.mark.parametrize(
    "mutation", ["omit", "duplicate", "reorder", "text", "attachment", "link"]
)
def test_independent_oracle_rejects_source_projection_mutations(mutation: str) -> None:
    raw, profile, member = _fixture()
    content, _ = _project_document(raw, member, profile)
    tree = ET.fromstring(content)
    body = tree.find(f".//{TEI}body")
    assert body is not None
    series = list(body)
    first_sermon = series[0].find(f"{TEI}div")
    assert first_sermon is not None

    if mutation == "omit":
        first_sermon.remove(first_sermon.find(f"{TEI}p"))
    elif mutation == "duplicate":
        first_sermon.append(copy.deepcopy(first_sermon.find(f"{TEI}p")))
    elif mutation == "reorder":
        body[:] = list(reversed(series))
    elif mutation == "text":
        paragraph = first_sermon.find(f"{TEI}p")
        assert paragraph is not None
        paragraph.text = "Invented wording"
    elif mutation == "attachment":
        paragraph = first_sermon.find(f"{TEI}p")
        note = first_sermon.find(f"{TEI}note")
        assert paragraph is not None and note is not None
        first_sermon.remove(note)
        paragraph.append(note)
    elif mutation == "link":
        ref = first_sermon.find(f".//{TEI}ref")
        assert ref is not None
        ref.set("target", "#src-99999")

    altered = ET.tostring(tree, encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="independent source projection"):
        _assert_projection(raw, altered, member, profile)


def test_oracle_import_closure_is_explicit_and_manifest_bound() -> None:
    manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)

    assert set(_closure_paths()) == {
        ROOT / "build/tei/john_wesley_sermons_oracle.py",
        ROOT / "ocd_kernel/__init__.py",
        ROOT / "ocd_kernel/reconstruction/__init__.py",
        ROOT / "ocd_kernel/reconstruction/contract.py",
        ROOT / "ocd_kernel/tei/validate.py",
    }
    assert (
        manifest.record["validator"]["import_closure_sha256"]
        == _import_closure_sha256()
    )
