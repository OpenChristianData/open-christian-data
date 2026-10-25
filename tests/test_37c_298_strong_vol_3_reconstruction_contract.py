from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.strong_systematic_theology_vol_3_oracle import _oracle
from build.tei.strong_systematic_theology_vol_3_reconstruction import _convert
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources/strong-systematic-theology-vol-3/strong-systematic-theology-vol-3.source-manifest.json"
CONFIG = ROOT / "sources/structured-text/strong-systematic-theology-vol-3/config.json"
SOURCE = ROOT / "raw/gutenberg/pg45283.txt"
WORK = "strong-systematic-theology-vol-3"
EDITION = "Revised and enlarged edition, Volume 3: The Doctrine of Salvation (Philadelphia: The Griffith & Rowland Press, 1909), Project Gutenberg #45283."
TITLE_PAGE_LINES = {
    "44": "Revised and Enlarged",
    "46": "In Three Volumes",
    "48": "Volume 3",
    "50": "The Doctrine of Salvation",
    "52": "The Griffith & Rowland Press",
    "54": "Philadelphia",
    "56": "1909",
}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI_URI = "http://www.tei-c.org/ns/1.0"
TEI = {"tei": TEI_URI}


def _q(name: str) -> str:
    return f"{{{TEI_URI}}}{name}"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _line_id(number: int) -> str:
    return f"{WORK}-line-{number:05d}"


def _line_number(node: etree._Element) -> int:
    value = node.get(XML_ID, "")
    assert value.startswith(f"{WORK}-line-")
    return int(value.rsplit("-", 1)[1])


def _text_with_line_breaks(node: etree._Element) -> str:
    parts: list[str] = []

    def visit(current: etree._Element) -> None:
        if current.text:
            parts.append(current.text)
        for child in current:
            if child.tag == _q("lb"):
                parts.append(" ")
            else:
                visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(node)
    return "".join(parts)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory):
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(manifest, tmp_path_factory.mktemp("37c298") / "candidate", _convert)
    report = validate(manifest, candidate, _oracle)
    return manifest, candidate, report


def _rewrite_candidate(built, tmp_path: Path, name: str, mutate):
    manifest, candidate, _report = built
    target = tmp_path / name
    shutil.copytree(candidate.path, target)
    content_path = target / "content.tei.xml"
    root = etree.fromstring(content_path.read_bytes())
    mutate(root)
    content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    content_path.write_bytes(content)
    package_manifest_path = target / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_bytes())
    member = next(item for item in package_manifest["members"] if item["name"] == "content.tei.xml")
    member.update(bytes=len(content), sha256=_sha(content))
    package_manifest_path.write_text(
        json.dumps(package_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return manifest, target


def _assert_mutation_rejected(built, tmp_path: Path, name: str, mutate, message: str) -> None:
    manifest, target = _rewrite_candidate(built, tmp_path, name, mutate)
    with pytest.raises(ValueError, match=message):
        validate(manifest, CandidatePackage.load(target), _oracle)


def test_source_manifest_binds_the_declared_work_identity() -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)

    assert manifest.record["work_id"] == WORK


def test_exact_non_ocr_source_and_full_file_accounting(built) -> None:
    manifest, candidate, report = built
    source = SOURCE.read_bytes()
    assert manifest.record["source_id"] == "strong-systematic-theology-vol-3-pg45283-retained"
    assert len(source) == 1_868_543
    assert _sha(source) == "103dc623072326111214078015dfbe8cb8f97197cba6e5e6faffede8bb1a20fe"
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accounting["physical_line_count"] == 42_140
    assert accounting["nonblank_line_count"] == 32_475
    assert accounting["blank_line_count"] == 9_665
    assert len(accounting["lines"]) == 42_140
    assert report.status == "pass" and report.findings == ()
    assert candidate.manifest["status"] == "nonaccepted"


def test_candidate_preserves_every_ordered_physical_line_anchor(built) -> None:
    _manifest, candidate, _report = built
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    transcript = document.xpath(
        "./tei:text/tei:body/tei:div[@type='retained-file-transcription']",
        namespaces=TEI,
    )[0]
    actual_ids = [
        node.get(XML_ID)
        for node in transcript.iter()
        if node.get(XML_ID, "").startswith(f"{WORK}-line-")
    ]
    source_lines = SOURCE.read_bytes().decode("utf-8-sig").splitlines()
    expected_ids = [_line_id(index) for index, line in enumerate(source_lines, 1) if line]
    assert actual_ids == expected_ids
    assert document.xpath("string(//tei:idno[@type='gutenberg'])", namespaces=TEI) == "45283"


def test_whitespace_only_source_lines_separate_adjacent_paragraphs(built) -> None:
    _manifest, candidate, _report = built
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    transcript = document.xpath(
        "./tei:text/tei:body/tei:div[@type='retained-file-transcription']",
        namespaces=TEI,
    )[0]
    line1 = transcript.xpath("./*[@xml:id=$line]", namespaces={**TEI, "xml": "http://www.w3.org/XML/1998/namespace"}, line=_line_id(1))[0]
    separator = transcript.xpath("./tei:ab[@type='source-whitespace-line'][@xml:id=$line]", namespaces={**TEI, "xml": "http://www.w3.org/XML/1998/namespace"}, line=_line_id(2))[0]
    line3 = transcript.xpath("./*[@xml:id=$line]", namespaces={**TEI, "xml": "http://www.w3.org/XML/1998/namespace"}, line=_line_id(3))[0]

    assert line1.tag == _q("ab")
    assert line1.getparent() is transcript
    assert separator.text == "    "
    assert line3.tag == _q("ab") and line3.get("type") == "source-block"
    assert line1 is not line3 and separator.getparent() is transcript
    assert candidate.sha256 == _report.candidate_sha256


def test_independent_oracle_rejects_folding_whitespace_separator_into_line_break(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        ns = {**TEI, "xml": "http://www.w3.org/XML/1998/namespace"}
        separator = root.xpath(
            "//tei:ab[@type='source-whitespace-line'][@xml:id=$line]",
            namespaces=ns,
            line=_line_id(2),
        )[0]
        parent = separator.getparent()
        previous = parent[parent.index(separator) - 1]
        parent.remove(separator)
        line_break = etree.SubElement(previous, _q("lb"), n="2")
        line_break.set(XML_ID, _line_id(2))
        line_break.tail = "    "

    _assert_mutation_rejected(built, tmp_path, "whitespace-separator-folded", mutate, "readable source lines")


def test_volume_3_imprint_is_separate_from_unestablished_original_year(built) -> None:
    manifest, candidate, _report = built
    config = json.loads(CONFIG.read_bytes())
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    policy = json.loads(manifest.authority_path("validation-policy").read_bytes())
    source_lines = SOURCE.read_bytes().decode("utf-8-sig").splitlines()
    assert {line: source_lines[int(line) - 1].strip() for line in TITLE_PAGE_LINES} == TITLE_PAGE_LINES
    assert config["source_edition"] == EDITION
    assert config["original_publication_year"] is None
    assert profile["edition_evidence"] == {
        "original_publication_year": None,
        "source_edition": EDITION,
        "title_page_lines": TITLE_PAGE_LINES,
    }
    assert {
        "volume-specific-edition-imprint-and-original-publication-date-separation",
        "source-indented-contents-hierarchy-and-wrapped-entry-accounting",
        "contents-derived-body-heading-hierarchy-and-wrapped-heading-accounting",
        "explicit-transcriber-notes-and-cover-art-placeholder",
        "balanced-underscore-emphasis-across-physical-lines",
        "four-source-quoted-mottos-are-mapped-as-epigraphs",
        "citation-and-page-reference-semantics-remain-uninferred",
        "neutral-source-sequence-containers-preserve-unheaded-groups",
        "scripture-index-book-headings-group-related-reference-entries",
        "scripture-and-apocryphal-index-book-headings-group-related-reference-entries",
    }.issubset(set(policy["required_checks"]))
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert document.xpath("string(//tei:idno[@type='edition'])", namespaces=TEI) == EDITION
    assert not document.xpath("./tei:teiHeader//tei:date", namespaces=TEI)
    assert candidate.member_bytes("README.source.md") == manifest.authority_path("attribution-readme").read_bytes()
    assert b"1907 edition claim; that claim remains unadopted pending review" not in candidate.member_bytes("README.source.md")
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()]
    original_year = next(item for item in unresolved if item["id"] == f"{WORK}-original-publication-year")
    assert original_year["status"] == "unresolved"


def test_independent_oracle_rejects_the_obsolete_1907_volume_edition(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        node = root.xpath("//tei:idno[@type='edition']", namespaces=TEI)[0]
        node.text = "Revised and enlarged edition (Judson Press, 1907), PG#45283 (Vol. 3 of 3 files)"

    _assert_mutation_rejected(built, tmp_path, "obsolete-edition", mutate, "edition")


def test_printed_contents_indentation_and_wrapped_entries_are_structured(built) -> None:
    manifest, candidate, _report = built
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    contents = document.xpath(
        "./tei:text/tei:body/tei:div[@type='retained-file-transcription']/tei:div[@type='contents']",
        namespaces=TEI,
    )[0]
    list_node = contents.find(_q("list"))
    assert list_node is not None
    assert _line_number(contents.find(_q("head"))) == 62

    paragraphs = list_node.xpath(".//tei:item/tei:p", namespaces=TEI)
    assert len(paragraphs) == profile["contents_outline"]["entry_count"] == 140
    wrapped = [paragraph for paragraph in paragraphs if paragraph.xpath(".//tei:lb", namespaces=TEI)]
    assert len(wrapped) == profile["contents_outline"]["wrapped_entry_count"] == 29

    by_line = {_line_number(paragraph): paragraph for paragraph in paragraphs}
    for first, continuation in ((65, 66), (67, 68), (69, 70), (77, 78), (97, 98)):
        paragraph = by_line[first]
        assert [int(lb.get("n")) for lb in paragraph.xpath(".//tei:lb", namespaces=TEI)] == [continuation]

    item65 = by_line[65].getparent()
    item67 = by_line[67].getparent()
    item69 = by_line[69].getparent()
    assert item67.getparent().getparent() is item65
    assert item69.getparent().getparent() is item67
    assert profile["contents_outline"]["first_entry_line"] == 65
    assert profile["contents_outline"]["last_entry_line"] == 234


def test_body_heading_hierarchy_and_wrapped_heads_follow_the_contents(built) -> None:
    manifest, candidate, _report = built
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    transcript = document.xpath(
        "./tei:text/tei:body/tei:div[@type='retained-file-transcription']",
        namespaces=TEI,
    )[0]
    outline_body = transcript.xpath("./tei:div[@type='source-outline-body']", namespaces=TEI)[0]
    tail = outline_body.xpath("./tei:div[@type='source-envelope-tail']", namespaces=TEI)[0]
    tail_anchors = [node for node in tail.iter() if node.get(XML_ID, "").startswith(f"{WORK}-line-")]
    assert _line_number(tail_anchors[0]) == 41_790
    all_heads = transcript.xpath(".//tei:div/tei:head", namespaces=TEI)
    source_native_addition_lines = {
        item["start_line"]
        for item in profile["source_native_body_outline"]["headings"]
        if not item["matched_contents_entry"]
    }
    body_heads = [
        head
        for head in all_heads
        if head.getparent().get("type") not in {"contents", "index-group"}
        and _line_number(head) not in source_native_addition_lines
    ]
    wrapped_heads = [head for head in body_heads if head.xpath(".//tei:lb", namespaces=TEI)]
    assert len(body_heads) == profile["body_outline"]["matched_heading_count"] == 140
    assert len(wrapped_heads) == profile["body_outline"]["wrapped_heading_count"] == 23
    assert profile["body_outline"]["unresolved_toc_entry_count"] == 0
    assert profile["body_outline"]["unresolved_toc_entries"] == []

    part6 = outline_body.xpath("./tei:div[@type='part'][@n='VI']", namespaces=TEI)[0]
    chapter2 = part6.xpath("./tei:div[@type='chapter'][@n='II']", namespaces=TEI)[0]
    section1 = chapter2.xpath("./tei:div[@type='section'][@n='I']", namespaces=TEI)[0]
    assert _line_number(part6.find(_q("head"))) == 267
    assert [int(lb.get("n")) for lb in part6.find(_q("head")).xpath(".//tei:lb", namespaces=TEI)] == [268]
    assert _line_number(chapter2.find(_q("head"))) == 277
    assert [int(lb.get("n")) for lb in chapter2.find(_q("head")).xpath(".//tei:lb", namespaces=TEI)] == [278]
    assert _line_number(section1.find(_q("head"))) == 282
    assert chapter2.xpath("./tei:div[@type='section'][@n='II']", namespaces=TEI)

    part7 = outline_body.xpath("./tei:div[@type='part'][@n='VII']", namespaces=TEI)[0]
    assert {node.get("n") for node in part7.xpath("./tei:div[@type='chapter']", namespaces=TEI)} == {"I", "II"}
    assert outline_body.xpath("./tei:div[@type='part'][@n='VIII']/tei:head", namespaces=TEI)
    indexes = outline_body.xpath("./tei:div[@type='indexes']", namespaces=TEI)[0]
    assert _line_number(indexes.find(_q("head"))) == 24565
    assert _line_number(indexes.xpath("./tei:div[@type='index'][@n='Subjects']/tei:head", namespaces=TEI)[0]) == 24577


def test_source_native_headings_follow_the_retained_hierarchy(built) -> None:
    manifest, candidate, _report = built
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    source_lines = manifest.authority_path("retained-source").read_text(encoding="utf-8").splitlines()
    outline = profile["source_native_body_outline"]
    expected = outline["headings"]
    assert outline["heading_count"] == len(expected) == 405
    assert outline["structure_start_line"] == 267
    assert outline["structure_end_line_exclusive"] == 24565
    assert outline["marker_counts"] == {
        "uppercase": 50,
        "underscore-parenthetical": 353,
        "parenthetical": 2,
    }
    canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    assert outline["heading_inventory_sha256"] == _sha(canonical.encode("utf-8"))

    for item in expected:
        line = item["start_line"]
        assert " ".join(source_lines[line - 1 : item["end_line"]]).split() == item["source_text"].split()
        assert not source_lines[line - 2].strip()
        if item["end_line"] < outline["structure_end_line_exclusive"]:
            assert not source_lines[item["end_line"]].strip()
        assert not item["matched_contents_entry"]

    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    transcript = document.xpath(
        "./tei:text/tei:body/tei:div[@type='retained-file-transcription']",
        namespaces=TEI,
    )[0]
    for item in expected:
        division = transcript.xpath(
            ".//tei:div[tei:head[@n=$line]]",
            namespaces=TEI,
            line=str(item["start_line"]),
        )[0]
        heading = division.find(_q("head"))
        parent_heading = division.getparent().find(_q("head"))
        assert division.get("type") == item["type"]
        assert division.get("n") == item["n"]
        assert _line_number(heading) == item["start_line"]
        assert _text_with_line_breaks(heading) == item["source_text"].replace("_", "")
        assert parent_heading is not None
        assert _line_number(parent_heading) == item["parent_start_line"]

    for line, expected_text in ((466, "A. From Scripture."), (863, "B. From Reason."), (3356, "(e) It is a change wrought in connection with the use of truth as a means.")):
        heading = transcript.xpath(
            ".//tei:head[@n=$line]",
            namespaces=TEI,
            line=str(line),
        )[0]
        assert _text_with_line_breaks(heading) == expected_text


def test_scripture_and_apocryphal_indexes_group_entries_under_book_headings(built) -> None:
    manifest, candidate, _report = built
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    text_index_groups = profile["text_index_groups"]
    assert text_index_groups["book_group_count"] == 75
    sections = {section["title"]: section for section in text_index_groups["sections"]}
    assert sections["Scripture Texts"]["book_group_count"] == 62
    assert sections["Apocryphal Texts"]["book_group_count"] == 13

    actual_groups = {}
    for title, section in sections.items():
        index = document.xpath(
            ".//tei:div[@type='index'][@n=$title]",
            namespaces=TEI,
            title=title,
        )[0]
        groups = index.xpath("./tei:div[@type='index-group']", namespaces=TEI)
        assert len(groups) == section["book_group_count"]
        actual_heads = [
            (_line_number(group.find(_q("head"))), "".join(group.find(_q("head")).itertext()))
            for group in groups
        ]
        assert actual_heads == [
            (item["start_line"], item["label"])
            for item in section["book_groups"]
        ]
        for index_in_section, (group, spec) in enumerate(
            zip(groups, section["book_groups"], strict=True)
        ):
            next_line = (
                section["book_groups"][index_in_section + 1]["start_line"]
                if index_in_section + 1 < len(groups)
                else section["end_line_exclusive"]
            )
            line_numbers = [
                _line_number(node)
                for node in group.iter()
                if node.get(XML_ID, "").startswith(f"{WORK}-line-")
            ]
            assert line_numbers[0] == spec["start_line"]
            assert all(spec["start_line"] <= line < next_line for line in line_numbers)
        actual_groups[title] = groups

    genesis, exodus = actual_groups["Scripture Texts"][:2]
    genesis_lines = {_line_number(node) for node in genesis.iter() if node.get(XML_ID)}
    exodus_lines = {_line_number(node) for node in exodus.iter() if node.get(XML_ID)}
    assert 34778 in genesis_lines and 34782 not in genesis_lines
    assert 34782 in exodus_lines and 34778 not in exodus_lines
    judges, first_samuel = actual_groups["Scripture Texts"][6:8]
    judges_lines = {_line_number(node) for node in judges.iter() if node.get(XML_ID)}
    first_samuel_lines = {_line_number(node) for node in first_samuel.iter() if node.get(XML_ID)}
    assert 35049 not in judges_lines and 35050 not in judges_lines
    assert 35050 in first_samuel_lines and 35084 not in first_samuel_lines
    apocrypha_groups = actual_groups["Apocryphal Texts"]
    assert "".join(apocrypha_groups[4].find(_q("head")).itertext()) == "Esther, Continuation of."
    assert "".join(apocrypha_groups[6].find(_q("head")).itertext()) == "Ecclesiasticus, or Sirach."


@pytest.mark.parametrize(
    ("index_title", "group_title", "mutation_name"),
    [
        ("Scripture Texts", "1 Samuel", "numbered-scripture-heading-demotion"),
        ("Apocryphal Texts", "Esther, Continuation of", "apocryphal-heading-demotion"),
    ],
)
def test_independent_oracle_rejects_demoted_index_book_heading(
    built,
    tmp_path: Path,
    index_title: str,
    group_title: str,
    mutation_name: str,
) -> None:
    def mutate(root: etree._Element) -> None:
        head = root.xpath(
            ".//tei:div[@type='index'][@n=$index_title]/tei:div[@type='index-group'][@n=$group_title]/tei:head",
            namespaces=TEI,
            index_title=index_title,
            group_title=group_title,
        )[0]
        head.tag = _q("p")

    _assert_mutation_rejected(
        built,
        tmp_path,
        mutation_name,
        mutate,
        "body-heading hierarchy",
    )


def test_only_explicit_transcriber_notes_and_cover_placeholder_are_typed(built) -> None:
    manifest, candidate, _report = built
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    notes = document.xpath(".//tei:note", namespaces=TEI)
    assert [_line_number(note) for note in notes] == [243, 271]
    assert [note.get("type") for note in notes] == ["transcribers-note", "transcribers-note"]
    assert [[int(lb.get("n")) for lb in note.xpath(".//tei:lb", namespaces=TEI)] for note in notes] == [[244], [272]]
    assert notes[0].getparent().get("type") == "source-outline-body"
    assert notes[1].getparent().get("type") == "part"
    assert _line_number(notes[1].getparent().find(_q("head"))) == 267
    assert profile["note_blocks"] == [
        {"end_line": 244, "parent_start_line": None, "start_line": 243, "type": "transcribers-note"},
        {"end_line": 272, "parent_start_line": 267, "start_line": 271, "type": "transcribers-note"},
    ]

    placeholders = document.xpath(".//tei:ab[@type='source-figure-placeholder']", namespaces=TEI)
    assert len(placeholders) == 1
    assert _line_number(placeholders[0]) == profile["figure_placeholder_line"] == 241
    assert "".join(placeholders[0].itertext()).strip() == "[Cover Art]"
    assert placeholders[0].getparent().get("type") == "source-outline-body"
    assert not document.xpath(".//tei:graphic", namespaces=TEI)


def test_four_source_quoted_mottos_are_epigraphs_with_line_anchors(built) -> None:
    _manifest, candidate, _report = built
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    transcript = document.xpath(
        "./tei:text/tei:body/tei:div[@type='retained-file-transcription']",
        namespaces=TEI,
    )[0]
    epigraphs = transcript.xpath(
        "./tei:div[@type='source-outline-body']/tei:quote[@type='epigraph']",
        namespaces=TEI,
    )
    expected_lines = (250, 253, 256, 259)
    assert [_line_number(node) for node in epigraphs] == list(expected_lines)
    source_lines = SOURCE.read_bytes().decode("utf-8-sig").splitlines()
    for node, first_line in zip(epigraphs, expected_lines, strict=True):
        source_block = []
        line = first_line
        while line <= len(source_lines) and source_lines[line - 1]:
            source_block.append(source_lines[line - 1])
            line += 1
        assert " ".join(_text_with_line_breaks(node).split()) == " ".join(
            " ".join(source_block).replace("_", "").split()
        )
        assert [int(lb.get("n")) for lb in node.xpath(".//tei:lb", namespaces=TEI)] == list(
            range(first_line + 1, line)
        )


def test_independent_oracle_rejects_epigraph_demotion(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        node = root.xpath(".//tei:quote[@type='epigraph']", namespaces=TEI)[0]
        parent = node.getparent()
        position = parent.index(node)
        parent.remove(node)
        replacement = etree.Element(_q("ab"), type="source-block")
        replacement.attrib.update(node.attrib)
        replacement.text = node.text
        for child in list(node):
            replacement.append(child)
        parent.insert(position, replacement)

    _assert_mutation_rejected(built, tmp_path, "epigraph-demoted", mutate, "epigraph")


def test_balanced_underscore_emphasis_spans_physical_lines(built) -> None:
    manifest, candidate, _report = built
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    emphasis = document.xpath(".//tei:hi", namespaces=TEI)
    cross_line = [node for node in emphasis if node.xpath(".//tei:lb", namespaces=TEI)]
    assert len(emphasis) == profile["inline_emphasis"]["span_count"] == 5_613
    assert len(cross_line) == profile["inline_emphasis"]["cross_physical_line_span_count"] == 1_974
    assert all(node.get("rend") == "italic" for node in emphasis)
    assert profile["inline_emphasis"]["marker_count"] == 11_226
    assert profile["inline_emphasis"]["blank_delimited_blocks"] == 1_359
    assert profile["inline_emphasis"]["span_positions_sha256"] == "e618f285116c04a3a82792d0d0f74ce6223da4e58f8664dc23fe3c96041c7954"


@pytest.mark.parametrize("mutation", ["omit", "reorder", "invent"])
def test_independent_oracle_rejects_source_content_mutations(built, tmp_path: Path, mutation: str) -> None:
    def mutate(root: etree._Element) -> None:
        transcript = root.xpath(
            "./tei:text/tei:body/tei:div[@type='retained-file-transcription']",
            namespaces=TEI,
        )[0]
        anchored = [child for child in transcript if child.get(XML_ID, "").startswith(f"{WORK}-line-")]
        if mutation == "omit":
            anchored[0].getparent().remove(anchored[0])
        elif mutation == "reorder":
            parent = anchored[0].getparent()
            first_index = parent.index(anchored[0])
            second = anchored[1]
            parent.remove(second)
            parent.insert(first_index, second)
        else:
            first = root.xpath(f"//*[@xml:id='{_line_id(1)}']", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})[0]
            first.text = (first.text or "") + " invented"

    _assert_mutation_rejected(built, tmp_path, mutation, mutate, "source|readable")


def test_independent_oracle_rejects_contents_reparenting(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        list_node = root.xpath(
            "./tei:text/tei:body/tei:div[@type='retained-file-transcription']/tei:div[@type='contents']/tei:list",
            namespaces=TEI,
        )[0]
        item65 = next(item for item in list_node.xpath("./tei:item", namespaces=TEI) if _line_number(item.find(_q("p"))) == 65)
        nested = item65.find(_q("list"))
        assert nested is not None
        moved = list(nested)
        position = list_node.index(item65) + 1
        for item in moved:
            nested.remove(item)
            list_node.insert(position, item)
            position += 1
        item65.remove(nested)

    _assert_mutation_rejected(built, tmp_path, "contents-reparent", mutate, "contents nesting")


def test_independent_oracle_rejects_body_heading_reparenting(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        transcript = root.xpath(
            "./tei:text/tei:body/tei:div[@type='retained-file-transcription']",
            namespaces=TEI,
        )[0]
        outline_body = transcript.xpath("./tei:div[@type='source-outline-body']", namespaces=TEI)[0]
        indexes = outline_body.xpath("./tei:div[@type='indexes']", namespaces=TEI)[0]
        hebrew_index = indexes.xpath("./tei:div[@type='index'][@n='Hebrew Words']", namespaces=TEI)[0]
        indexes.remove(hebrew_index)
        outline_body.insert(outline_body.index(indexes) + 1, hebrew_index)

    _assert_mutation_rejected(built, tmp_path, "heading-reparent", mutate, "body-heading hierarchy")


def test_independent_oracle_rejects_transcriber_note_reclassification(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        note = root.xpath(".//tei:note[@type='transcribers-note']", namespaces=TEI)[0]
        note.set("type", "source-note")

    _assert_mutation_rejected(built, tmp_path, "note-reclassified", mutate, "transcriber-note")


def test_independent_oracle_rejects_transcriber_note_detachment(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        note = root.xpath(".//tei:note[@xml:id=$line]", namespaces=TEI, line=_line_id(271))[0]
        parent = note.getparent()
        position = parent.index(note)
        parent.remove(note)
        wrapper = etree.Element(_q("div"), type="note-wrapper")
        wrapper.append(note)
        parent.insert(position, wrapper)

    _assert_mutation_rejected(built, tmp_path, "note-detached", mutate, "transcriber-note")


def test_independent_oracle_rejects_changed_emphasis_rendition(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        root.xpath(".//tei:hi[@rend='italic']", namespaces=TEI)[0].set("rend", "bold")

    _assert_mutation_rejected(built, tmp_path, "emphasis-rendition", mutate, "underscore emphasis")


def test_independent_oracle_rejects_heading_demotion(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        node = root.xpath(".//tei:div[@type='part'][@n='VII']", namespaces=TEI)[0]
        node.set("type", "source-block")

    _assert_mutation_rejected(built, tmp_path, "heading-demotion", mutate, "body-heading hierarchy")


def test_independent_oracle_rejects_source_native_heading_demotion(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        head = root.xpath(
            ".//tei:div[tei:head[@n='466']]/tei:head",
            namespaces=TEI,
        )[0]
        head.tag = _q("p")

    _assert_mutation_rejected(
        built,
        tmp_path,
        "source-native-heading-demotion",
        mutate,
        "body-heading hierarchy",
    )


def test_independent_oracle_rejects_unlisted_parenthetical_heading_demotion(
    built, tmp_path: Path
) -> None:
    def mutate(root: etree._Element) -> None:
        head = root.xpath(
            ".//tei:div[tei:head[@n='522']]/tei:head",
            namespaces=TEI,
        )[0]
        head.tag = _q("p")

    _assert_mutation_rejected(
        built,
        tmp_path,
        "unlisted-parenthetical-heading-demotion",
        mutate,
        "body-heading hierarchy",
    )


def test_independent_oracle_rejects_source_native_heading_reparenting(built, tmp_path: Path) -> None:
    def mutate(root: etree._Element) -> None:
        proof = root.xpath(".//tei:div[tei:head[@n='463']]", namespaces=TEI)[0]
        reason = root.xpath(".//tei:div[tei:head[@n='863']]", namespaces=TEI)[0]
        election = root.xpath(".//tei:div[tei:head[@n='454']]", namespaces=TEI)[0]
        assert reason.getparent() is proof
        proof.remove(reason)
        election.insert(election.index(proof) + 1, reason)

    _assert_mutation_rejected(
        built,
        tmp_path,
        "source-native-heading-reparenting",
        mutate,
        "body-heading hierarchy",
    )


def test_fresh_process_reconstruction_is_byte_identical(built, tmp_path: Path) -> None:
    _manifest, candidate, _report = built
    destination = tmp_path / "fresh-candidate"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "from pathlib import Path;"
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct;"
        "from build.tei.strong_systematic_theology_vol_3_reconstruction import _convert;"
        f"root=Path({str(ROOT)!r});"
        "source=SourceManifest.load(root/'sources/strong-systematic-theology-vol-3/strong-systematic-theology-vol-3.source-manifest.json',repository_root=root);"
        f"candidate=reconstruct(source,Path({str(destination)!r}),_convert);"
        "print(candidate.sha256)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == candidate.sha256
    for name in candidate.member_names:
        assert (destination / name).read_bytes() == candidate.member_bytes(name)


def test_index_group_labels_match_retained_source_lines(built) -> None:
    manifest, _candidate, _report = built
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    source_lines = (
        manifest.authority_path("retained-source")
        .read_bytes()
        .decode("utf-8-sig")
        .splitlines()
    )

    for section in profile["text_index_groups"]["sections"]:
        for group in section["book_groups"]:
            start_line = group["start_line"]
            assert 1 <= start_line <= len(source_lines), (
                f"{section['title']} group start_line {start_line} is outside the retained source"
            )
            source_label = source_lines[start_line - 1].strip()
            assert source_label == group["label"], (
                f"{section['title']} group at source line {start_line}: "
                f"profile label {group['label']!r} differs from source line {source_label!r}"
            )
