"""Contract and mutation tests for the complete retained HelloAO John Gill witness."""

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

from build.tei.helloao_john_gill_oracle import _oracle
from build.tei.helloao_john_gill_reconstruction import _convert
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    ValidationReport,
    reconstruct,
    validate,
)
from ocd_kernel.reconstruction.decision import load_verified_review
from tests.runtime_candidate_baselines import current_runtime_catalog
from build.lib.tei_xsd import compiled_tei_schema


pytestmark = [
    pytest.mark.requires_local_artifacts,
    pytest.mark.slow,
    pytest.mark.xdist_group(name="helloao-john-gill-reconstruction"),
]

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/john-gill.source-manifest.json"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
FORMAL_SOURCE_SHA = "b874cf092641aa83722204ef765750cda69c1841cf355a57fc3d5d2134129549"
CANONICAL_XML_DECLARATION = b"<?xml version='1.0' encoding='UTF-8'?>\n"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _write_validation_report(report: ValidationReport, path: Path) -> Path:
    path.write_bytes(
        _canonical(
            {
                "contract": "ocd-validation-report-v1",
                "status": report.status,
                "candidate_sha256": report.candidate_sha256,
                "source_manifest_sha256": report.source_manifest_sha256,
                "attestation": dict(report.attestation),
                "findings": list(report.findings),
                "report_sha256": report.sha256,
            }
        )
    )
    return path


@pytest.fixture(scope="session")
def john_gill_source() -> SourceManifest:
    return SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="session")
def john_gill_candidate(
    john_gill_source: SourceManifest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[CandidatePackage, ValidationReport]:
    destination = tmp_path_factory.mktemp("lib080-candidate") / "candidate"
    candidate = reconstruct(john_gill_source, destination, _convert)
    report = validate(john_gill_source, candidate, _oracle)
    return candidate, report


def _copy_candidate(candidate: CandidatePackage, target: Path) -> Path:
    shutil.copytree(candidate.path, target, copy_function=os.link)
    return target


def _write_member(target: Path, member_name: str, content: bytes) -> None:
    replacement = target / f".{member_name}.replacement"
    replacement.write_bytes(content)
    replacement.replace(target / member_name)


def _reseal(target: Path, member_name: str) -> CandidatePackage:
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (target / member_name).read_bytes()
    for member in manifest["members"]:
        if member["name"] == member_name:
            member["bytes"] = len(content)
            member["sha256"] = _sha(content)
            break
    else:
        raise AssertionError(f"candidate manifest lacks {member_name}")
    _write_member(target, "manifest.json", _canonical(manifest))
    return CandidatePackage.load(target)


def _write_tei(target: Path, root: etree._Element) -> CandidatePackage:
    _write_member(
        target,
        "content.tei.xml",
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True),
    )
    return _reseal(target, "content.tei.xml")


def _write_tei_document(target: Path, root: etree._Element) -> CandidatePackage:
    _write_member(
        target,
        "content.tei.xml",
        etree.tostring(
            root.getroottree(),
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        ),
    )
    return _reseal(target, "content.tei.xml")


def test_john_gill_source_manifest_binds_the_exact_retained_member_set(
    john_gill_source: SourceManifest,
) -> None:
    authorities = john_gill_source.record["authorities"]
    primary = [item for item in authorities if item["role"] == "primary-source"]
    assert len(primary) == 1191
    assert [item["name"] for item in primary] == [
        f"retained-{i:04d}" for i in range(1, 1192)
    ]
    assert sum(item["bytes"] for item in primary) == 54_866_016
    assert len({item["path"] for item in primary}) == 1191
    assert {Path(item["path"]).name for item in primary} >= {
        "books.json",
        "profiles.json",
    }
    for authority in primary:
        content = resolve_repo_path(ROOT, authority["path"]).read_bytes()
        assert len(content) == authority["bytes"]
        assert _sha(content) == authority["sha256"]
    member_records = [
        {
            "name": item["name"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in sorted(primary, key=lambda value: (value["path"], value["name"]))
    ]
    digest = _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": member_records})
    )
    assert digest == FORMAL_SOURCE_SHA
    lineage = john_gill_source.record["catalog_claim_lineage"]
    assert lineage["retained_source_sha256"] == FORMAL_SOURCE_SHA
    assert lineage["claim_count"] == len(lineage["claims"]) == 66
    assert [item["source_path"] for item in lineage["claims"]] == sorted(
        item["source_path"] for item in lineage["claims"]
    )


def test_john_gill_candidate_is_complete_valid_nonaccepted_and_not_ready(
    john_gill_candidate: tuple[CandidatePackage, object],
) -> None:
    candidate, report = john_gill_candidate
    assert report.status == "pass"
    assert report.candidate_sha256 == candidate.sha256
    assert candidate.manifest["status"] == "nonaccepted"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["member_count"] == 1191
    assert accountability["included_member_count"] == 1191
    assert accountability["excluded_member_count"] == 0
    assert accountability["total_bytes"] == 54_866_016
    assert accountability["census"] == {
        "books": 66,
        "chapters": 1189,
        "commentary_occurrences": 28_300,
        "book_introductions": 66,
        "chapter_introductions_present": 1186,
        "chapter_introductions_absent": 3,
        "profiles": 0,
    }
    assert accountability["anomalies"]["chapter_introduction_absent_paths"] == [
        "ZEP/1.json",
        "ZEP/2.json",
        "ZEP/3.json",
    ]
    assert len(accountability["anomalies"]["nonmonotonic_occurrence_paths"]) == 19
    assert accountability["anomalies"]["duplicate_occurrence_numbers"] == []
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["status"] == "nonaccepted"
    assert provenance["accepted_ir"] == "not_accepted"
    assert provenance["publication"] == "not_ready"
    assert provenance["human_decision"] is None


def test_john_gill_candidate_has_exact_canonical_lexical_document_shell(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
) -> None:
    candidate, _ = john_gill_candidate
    content = candidate.member_bytes("content.tei.xml")
    assert validate(john_gill_source, candidate, _oracle).status == "pass"
    assert not content.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in content
    assert content.startswith(CANONICAL_XML_DECLARATION + b"<TEI")
    assert content.endswith(b"</TEI>\n")
    assert not content.endswith(b"</TEI>\n\n")


@pytest.mark.parametrize(
    "mutation",
    [
        "bom",
        "carriage-return",
        "declaration-omitted",
        "standalone-yes",
        "standalone-no",
        "double-quotes",
        "encoding-alias",
        "encoding-case",
        "declaration-order",
        "leading-whitespace",
        "blank-line-before-root",
        "space-before-root",
        "pre-root-comment",
        "pre-root-processing-instruction",
        "doctype",
        "missing-terminal-lf",
        "extra-terminal-lf",
        "trailing-space",
        "post-root-comment",
        "post-root-processing-instruction",
        "surplus-bytes",
    ],
)
def test_john_gill_oracle_rejects_noncanonical_lexical_document_shell(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, baseline_report = john_gill_candidate
    assert baseline_report.status == "pass"
    assert validate(john_gill_source, candidate, _oracle).status == "pass"
    target = _copy_candidate(candidate, tmp_path / f"lexical-shell-{mutation}")
    tei_path = target / "content.tei.xml"
    content = tei_path.read_bytes()
    assert content.startswith(CANONICAL_XML_DECLARATION + b"<TEI")
    assert content.endswith(b"</TEI>\n")
    document = content.removeprefix(CANONICAL_XML_DECLARATION)
    if mutation == "bom":
        mutated_bytes = b"\xef\xbb\xbf" + content
    elif mutation == "carriage-return":
        mutated_bytes = (
            CANONICAL_XML_DECLARATION.removesuffix(b"\n") + b"\r\n" + document
        )
    elif mutation == "declaration-omitted":
        mutated_bytes = document
    elif mutation == "standalone-yes":
        mutated_bytes = (
            b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + document
        )
    elif mutation == "standalone-no":
        mutated_bytes = (
            b"<?xml version='1.0' encoding='UTF-8' standalone='no'?>\n" + document
        )
    elif mutation == "double-quotes":
        mutated_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + document
    elif mutation == "encoding-alias":
        mutated_bytes = b"<?xml version='1.0' encoding='UTF8'?>\n" + document
    elif mutation == "encoding-case":
        mutated_bytes = b"<?xml version='1.0' encoding='utf-8'?>\n" + document
    elif mutation == "declaration-order":
        mutated_bytes = b"<?xml encoding='UTF-8' version='1.0'?>\n" + document
    elif mutation == "leading-whitespace":
        mutated_bytes = b" " + content
    elif mutation == "blank-line-before-root":
        mutated_bytes = CANONICAL_XML_DECLARATION + b"\n" + document
    elif mutation == "space-before-root":
        mutated_bytes = CANONICAL_XML_DECLARATION + b" " + document
    elif mutation == "pre-root-comment":
        mutated_bytes = CANONICAL_XML_DECLARATION + b"<!-- invented -->\n" + document
    elif mutation == "pre-root-processing-instruction":
        mutated_bytes = CANONICAL_XML_DECLARATION + b"<?invented value?>\n" + document
    elif mutation == "doctype":
        mutated_bytes = CANONICAL_XML_DECLARATION + b"<!DOCTYPE TEI>\n" + document
    elif mutation == "missing-terminal-lf":
        mutated_bytes = content.removesuffix(b"\n")
    elif mutation == "extra-terminal-lf":
        mutated_bytes = content + b"\n"
    elif mutation == "trailing-space":
        mutated_bytes = content + b" "
    elif mutation == "post-root-comment":
        mutated_bytes = content.removesuffix(b"\n") + b"<!-- invented -->\n"
    elif mutation == "post-root-processing-instruction":
        mutated_bytes = content.removesuffix(b"\n") + b"<?invented value?>\n"
    else:
        mutated_bytes = content + b"surplus"
    assert mutated_bytes != content
    _write_member(target, "content.tei.xml", mutated_bytes)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(
        ValueError, match="^John Gill TEI lexical document shell drifted$"
    ):
        validate(john_gill_source, mutated, _oracle)


def test_john_gill_tei_preserves_order_introductions_links_and_anomalies(
    john_gill_candidate: tuple[CandidatePackage, object],
) -> None:
    candidate, _ = john_gill_candidate
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"tei": TEI_NS}
    assert (
        len(root.xpath("tei:text/tei:body/tei:div[@type='book']", namespaces=ns)) == 66
    )
    assert (
        root.xpath(
            "string(tei:teiHeader/tei:fileDesc/tei:notesStmt/tei:note[@type='retained-text-direction'])",
            namespaces=ns,
        )
        == "rtl"
    )
    assert (
        len(
            root.xpath(
                "tei:text/tei:body/tei:div/tei:div[@type='book-introduction']",
                namespaces=ns,
            )
        )
        == 66
    )

    assert (
        len(
            root.xpath(
                "tei:text/tei:body/tei:div/tei:div/tei:div[@type='chapter-introduction']",
                namespaces=ns,
            )
        )
        == 1186
    )
    assert (
        len(
            root.xpath(
                "tei:text/tei:body/tei:div/tei:div/tei:div[@type='commentary-occurrence']",
                namespaces=ns,
            )
        )
        == 28_300
    )
    numbers = root.xpath(
        "tei:text/tei:body/tei:div[@n='1KI']/tei:div[@type='chapter'][@n='22']/tei:div[@type='commentary-occurrence']/@n",
        namespaces=ns,
    )
    assert numbers != sorted(numbers)
    genesis = root.xpath(
        "tei:text/tei:body/tei:div[@n='GEN']/tei:div[@type='chapter'][@n='1']",
        namespaces=ns,
    )[0]
    previous = genesis.xpath(
        "tei:note[@type='chapter-link'][@subtype='previous']", namespaces=ns
    )[0]
    assert previous.get("ana") == "null" and previous.text is None
    revelation = root.xpath(
        "tei:text/tei:body/tei:div[@n='REV']/tei:div[@type='chapter'][@n='22']",
        namespaces=ns,
    )[0]
    following = revelation.xpath(
        "tei:note[@type='chapter-link'][@subtype='next']", namespaces=ns
    )[0]
    assert following.get("ana") == "null" and following.text is None
    absent = root.xpath(
        "tei:text/tei:body/tei:div[@n='ZEP']/tei:div[@type='chapter']", namespaces=ns
    )
    assert all(
        not item.xpath("tei:div[@type='chapter-introduction']", namespaces=ns)
        for item in absent
    )


def test_john_gill_structure_inventory_preserves_all_source_paragraph_boundaries(
    john_gill_candidate: tuple[CandidatePackage, object],
) -> None:
    candidate, _ = john_gill_candidate
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"tei": TEI_NS}
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    structure = accountability["meaningful_structure"]
    assert structure["carrier_count"] == 0
    assert structure["rendered_carrier_count"] == 0
    assert structure["heading_span_count"] == 0
    assert structure["paragraph_policy"] == {
        "contract": "ocd-source-paragraph-segmentation-v1",
        "delimiter": "\n\n",
        "mode": "split-every-exact-double-newline",
        "carrier_total_count": 29_552,
        "carrier_count_with_delimiter": 29_389,
        "delimiter_count": 85_387,
    }
    source = json.loads(
        resolve_repo_path(
            ROOT, "raw/helloao_local/api/c/john-gill/books.json"
        ).read_bytes()
    )
    book_text = next(item["introduction"] for item in source["books"] if item["id"] == "1CH")
    book_intro = root.xpath(
        "tei:text/tei:body/tei:div[@n='1CH']/tei:div[@type='book-introduction']",
        namespaces=ns,
    )[0]
    # A terminal separator closes the last paragraph; it adds no empty paragraph.
    expected_parts = max(1, book_text.count("\n\n") + int(not book_text.endswith("\n\n")))
    assert len(book_intro.xpath("tei:p", namespaces=ns)) == expected_parts
    assert "".join(book_intro.itertext()) == book_text


@pytest.mark.parametrize(
    "mutation",
    [
        "omit-occurrence",
        "reorder-occurrences",
        "invent-range",
        "inject-text",
        "wrong-link",
    ],
)
def test_john_gill_oracle_rejects_textual_and_structural_mutations(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / mutation)
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    ns = {"tei": TEI_NS}
    chapter = root.xpath(
        "tei:text/tei:body/tei:div[@n='GEN']/tei:div[@type='chapter'][@n='1']",
        namespaces=ns,
    )[0]
    occurrences = chapter.xpath("tei:div[@type='commentary-occurrence']", namespaces=ns)
    if mutation == "omit-occurrence":
        chapter.remove(occurrences[0])
    elif mutation == "reorder-occurrences":
        first_index = chapter.index(occurrences[0])
        chapter.remove(occurrences[1])
        chapter.insert(first_index, occurrences[1])
    elif mutation == "invent-range":
        occurrences[0].set("n", "1-3")
    elif mutation == "inject-text":
        paragraph = occurrences[0].find(f"{{{TEI_NS}}}p")
        assert paragraph is not None
        paragraph.text = (paragraph.text or "") + " Invented Bible or BSB text."
    else:
        previous = chapter.xpath(
            "tei:note[@type='chapter-link'][@subtype='previous']", namespaces=ns
        )[0]
        previous.attrib.pop("ana", None)
        previous.text = "/invented/previous"
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


@pytest.mark.parametrize("mutation", ["false-complete", "rights", "edition"])
def test_john_gill_oracle_rejects_provenance_mutations(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / mutation)
    provenance = json.loads((target / "provenance.json").read_bytes())
    if mutation == "false-complete":
        provenance["scope"]["canonical_bible_complete"] = False
    elif mutation == "rights":
        provenance["rights"]["retained_mark"] = "CC0 1.0"
    else:
        provenance["identity"]["original_publication_year"] = 1748
    _write_member(target, "provenance.json", _canonical(provenance))
    mutated = _reseal(target, "provenance.json")
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


def test_john_gill_oracle_rejects_accountability_omission(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / "accountability-omission")
    accountability = json.loads((target / "source-accountability.json").read_bytes())
    accountability["members"] = accountability["members"][:-1]
    _write_member(target, "source-accountability.json", _canonical(accountability))
    mutated = _reseal(target, "source-accountability.json")
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra-author",
        "extra-publisher",
        "encoding-desc",
        "profile-desc",
        "revision-desc",
    ],
)
def test_john_gill_oracle_rejects_schema_valid_invented_header_metadata(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / mutation)
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    header = root.find(f"{{{TEI_NS}}}teiHeader")
    assert header is not None
    if mutation == "extra-author":
        title_stmt = header.find(f".//{{{TEI_NS}}}titleStmt")
        assert title_stmt is not None
        etree.SubElement(title_stmt, f"{{{TEI_NS}}}author").text = "Invented Coauthor"
    elif mutation == "extra-publisher":
        publication_stmt = header.find(f".//{{{TEI_NS}}}publicationStmt")
        assert publication_stmt is not None
        etree.SubElement(
            publication_stmt, f"{{{TEI_NS}}}publisher"
        ).text = "Invented Publisher"
    elif mutation == "encoding-desc":
        encoding_desc = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
        project_desc = etree.SubElement(encoding_desc, f"{{{TEI_NS}}}projectDesc")
        etree.SubElement(
            project_desc, f"{{{TEI_NS}}}p"
        ).text = "Invented project metadata"
    elif mutation == "profile-desc":
        profile_desc = etree.SubElement(header, f"{{{TEI_NS}}}profileDesc")
        language_usage = etree.SubElement(profile_desc, f"{{{TEI_NS}}}langUsage")
        language = etree.SubElement(language_usage, f"{{{TEI_NS}}}language")
        language.set("ident", "en")
        language.text = "Invented language metadata"
    else:
        revision_desc = etree.SubElement(header, f"{{{TEI_NS}}}revisionDesc")
        etree.SubElement(revision_desc, f"{{{TEI_NS}}}change").text = "Invented change"
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert schema.validate(root), schema.error_log
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


def test_john_gill_oracle_rejects_schema_valid_nested_body_invention(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / "nested-body-note")
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    paragraph = root.find(
        f".//{{{TEI_NS}}}div[@type='commentary-occurrence']/{{{TEI_NS}}}p"
    )
    assert paragraph is not None
    note = etree.SubElement(paragraph, f"{{{TEI_NS}}}note", {"type": "editorial"})
    note.text = "Invented body note"
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert schema.validate(root), schema.error_log
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    ["nested-seg", "nested-tail", "comment", "processing-instruction", "sibling"],
)
def test_john_gill_oracle_rejects_unaccounted_schema_valid_body_nodes(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / mutation)
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    paragraph = root.find(
        f".//{{{TEI_NS}}}div[@type='commentary-occurrence']/{{{TEI_NS}}}p"
    )
    assert paragraph is not None
    if mutation in {"nested-seg", "nested-tail"}:
        segment = etree.SubElement(paragraph, f"{{{TEI_NS}}}seg")
        segment.text = "Invented nested text"
        if mutation == "nested-tail":
            segment.tail = "Invented tail text"
    elif mutation == "comment":
        paragraph.append(etree.Comment("Invented body comment"))
    elif mutation == "processing-instruction":
        paragraph.append(etree.ProcessingInstruction("invented", "body-metadata"))
    else:
        occurrence = paragraph.getparent()
        assert occurrence is not None
        etree.SubElement(
            occurrence, f"{{{TEI_NS}}}p"
        ).text = "Invented sibling paragraph"
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert schema.validate(root), schema.error_log
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


def test_john_gill_oracle_accepts_expected_namespace_semantics(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
) -> None:
    candidate, _ = john_gill_candidate
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    elements = [item for item in root.iter() if isinstance(item.tag, str)]
    assert root.nsmap == {None: TEI_NS}
    assert all(item.nsmap == {None: TEI_NS} for item in elements)
    assert any(f"{{{XML_NS}}}id" in item.attrib for item in elements)
    assert validate(john_gill_source, candidate, _oracle).status == "pass"


@pytest.mark.parametrize("location", ["root", "body"])
def test_john_gill_oracle_rejects_unexpected_namespace_declarations(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    location: str,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / f"unexpected-namespace-{location}")
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    if location == "root":
        replacement = etree.Element(
            root.tag,
            dict(root.attrib),
            nsmap={None: TEI_NS, "invented": "urn:ocd:invented"},
        )
        replacement.text = root.text
        replacement.tail = root.tail
        for child in list(root):
            root.remove(child)
            replacement.append(child)
        root = replacement
    else:
        body = root.find(f".//{{{TEI_NS}}}body")
        assert body is not None
        replacement = etree.Element(
            body.tag,
            dict(body.attrib),
            nsmap={"invented": "urn:ocd:invented-body"},
        )
        replacement.text = body.text
        replacement.tail = body.tail
        for child in list(body):
            body.remove(child)
            replacement.append(child)
        parent = body.getparent()
        assert parent is not None
        parent.replace(body, replacement)
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert schema.validate(root), schema.error_log
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


def test_john_gill_oracle_rejects_explicit_reserved_xml_namespace_declaration(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / "explicit-reserved-xml-namespace")
    tei_path = target / "content.tei.xml"
    content = tei_path.read_bytes()
    root_start = b'<TEI xmlns="http://www.tei-c.org/ns/1.0">'
    replacement = (
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0" '
        b'xmlns:xml="http://www.w3.org/XML/1998/namespace">'
    )
    assert content.count(root_start) == 1
    _write_member(
        target, "content.tei.xml", content.replace(root_start, replacement, 1)
    )
    root = etree.fromstring(tei_path.read_bytes())
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert schema.validate(root), schema.error_log
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


@pytest.mark.parametrize(
    ("node_kind", "position"),
    [
        ("comment", "before"),
        ("comment", "after"),
        ("processing-instruction", "before"),
        ("processing-instruction", "after"),
    ],
)
def test_john_gill_oracle_rejects_document_level_siblings(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    node_kind: str,
    position: str,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / f"document-{node_kind}-{position}")
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    node = (
        etree.Comment("Invented document-level comment")
        if node_kind == "comment"
        else etree.ProcessingInstruction("invented", "document-metadata")
    )
    if position == "before":
        root.addprevious(node)
    else:
        root.addnext(node)
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert schema.validate(root), schema.error_log
    mutated = _write_tei_document(target, root)
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


def test_john_gill_oracle_rejects_invented_readme_rights_claim(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / "invented-readme-rights")
    readme_path = target / "README.source.md"
    _write_member(
        target,
        "README.source.md",
        readme_path.read_bytes()
        + b"\nInvented rights claim: this digital witness is licensed CC BY 4.0.\n",
    )
    mutated = _reseal(target, "README.source.md")
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


@pytest.mark.parametrize("mutation", ["omission", "reorder"])
def test_john_gill_oracle_rejects_readme_omission_or_reordering(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / f"readme-{mutation}")
    readme_path = target / "README.source.md"
    lines = readme_path.read_text(encoding="utf-8").splitlines(keepends=True)
    census_index = lines.index(
        "- The retained census is exactly 1,191 members and 54,866,016 bytes.\n"
    )
    if mutation == "omission":
        lines.pop(census_index)
    else:
        lines[census_index], lines[census_index + 1] = (
            lines[census_index + 1],
            lines[census_index],
        )
    _write_member(target, "README.source.md", "".join(lines).encode("utf-8"))
    mutated = _reseal(target, "README.source.md")
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    [
        "author-text",
        "title-type",
        "availability-status",
        "source-pointer",
        "metadata-note-rend",
        "reorder-notes",
        "header-comment",
        "source-witness-text",
    ],
)
def test_john_gill_oracle_rejects_existing_header_metadata_drift(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / mutation)
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    header = root.find(f"{{{TEI_NS}}}teiHeader")
    assert header is not None
    if mutation == "author-text":
        author = header.find(f".//{{{TEI_NS}}}author")
        assert author is not None
        author.text = "Invented Author"
    elif mutation == "title-type":
        title = header.find(f".//{{{TEI_NS}}}title")
        assert title is not None
        title.set("type", "invented")
    elif mutation == "availability-status":
        availability = header.find(f".//{{{TEI_NS}}}availability")
        assert availability is not None
        availability.set("status", "free")
    elif mutation == "source-pointer":
        pointer = header.find(
            f".//{{{TEI_NS}}}sourceDesc/{{{TEI_NS}}}bibl/{{{TEI_NS}}}ptr"
        )
        assert pointer is not None
        pointer.set("target", "/invented/source.json")
    elif mutation == "metadata-note-rend":
        note = header.find(f".//{{{TEI_NS}}}note[@type='commentary-metadata']")
        assert note is not None
        note.set("rend", "invented")
    elif mutation == "reorder-notes":
        notes_stmt = header.find(f".//{{{TEI_NS}}}notesStmt")
        assert notes_stmt is not None and len(notes_stmt) == 4
        notes_stmt.insert(0, notes_stmt[-1])
    elif mutation == "header-comment":
        header.append(etree.Comment("Invented header comment"))
    else:
        witness = header.find(f".//{{{TEI_NS}}}note[@type='source-witness']")
        assert witness is not None
        witness.text = "Invented witness"
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert schema.validate(root), schema.error_log
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


def test_john_gill_schema_rejects_an_extra_header_title(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
) -> None:
    candidate, _ = john_gill_candidate
    target = _copy_candidate(candidate, tmp_path / "extra-title")
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    title_stmt = root.find(f".//{{{TEI_NS}}}titleStmt")
    assert title_stmt is not None
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = "Invented Alternate Title"
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert not schema.validate(root)
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(john_gill_source, mutated, _oracle)


def test_john_gill_oracle_is_independent_and_bound_to_its_closure(
    john_gill_candidate: tuple[CandidatePackage, object],
) -> None:
    _, report = john_gill_candidate
    oracle_source = (ROOT / "build/tei/helloao_john_gill_oracle.py").read_text(
        encoding="utf-8"
    )
    assert "helloao_john_gill_reconstruction" not in oracle_source
    assert "helloao_commentary" not in oracle_source
    assert "data/commentaries/john-gill" not in oracle_source
    assert len(report.attestation["import_closure_sha256"]) == 64


def test_john_gill_candidate_is_byte_identical_after_one_fresh_process(
    john_gill_candidate: tuple[CandidatePackage, ValidationReport],
    tmp_path: Path,
) -> None:
    fresh_cwd = tmp_path / "external-cwd"
    fresh_cwd.mkdir()
    fresh = fresh_cwd / "candidate"
    code = (
        "from pathlib import Path; import sys; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.helloao_john_gill_reconstruction import _convert; "
        f"r=Path({str(ROOT)!r}); "
        f"s=SourceManifest.load(r/{str(SOURCE_MANIFEST.relative_to(ROOT))!r},repository_root=r); "
        "reconstruct(s,Path(sys.argv[1]),_convert)"
    )
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "23"
    environment["PYTHONPATH"] = (
        str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    )
    subprocess.run(
        [sys.executable, "-c", code, str(fresh)],
        cwd=fresh_cwd,
        env=environment,
        check=True,
        timeout=300,
    )
    candidate, _ = john_gill_candidate
    expected_members = {
        path.relative_to(candidate.path).as_posix(): path.read_bytes()
        for path in sorted(candidate.path.rglob("*"))
        if path.is_file()
    }
    fresh_members = {
        path.relative_to(fresh).as_posix(): path.read_bytes()
        for path in sorted(fresh.rglob("*"))
        if path.is_file()
    }
    assert fresh_members == expected_members


def test_john_gill_current_candidate_and_validation_sidecar_bind(
    john_gill_source: SourceManifest,
    john_gill_candidate: tuple[CandidatePackage, ValidationReport],
    tmp_path: Path,
) -> None:
    candidate, report = john_gill_candidate
    validation_path = _write_validation_report(report, tmp_path / "validation.json")
    review = load_verified_review(
        john_gill_source,
        candidate_path=candidate.path,
        validation_path=validation_path,
    )
    assert review.candidate_sha256 == candidate.sha256
    assert review.validation.status == "pass"
    assert review.validation.sha256 == report.sha256


def test_john_gill_catalog_claim_lineage_and_work_map_route(
    john_gill_candidate: tuple[CandidatePackage, ValidationReport],
    tmp_path: Path,
) -> None:
    manifest = json.loads(SOURCE_MANIFEST.read_bytes())
    lineage = manifest["catalog_claim_lineage"]
    current = {}
    for path in sorted((ROOT / "data/commentaries/john-gill").glob("*.json")):
        if path.name == "_manifest.json":
            continue
        document = json.loads(path.read_bytes())
        current["commentaries/john-gill/" + path.name] = document["meta"]["provenance"][
            "source_hash"
        ].removeprefix("sha256:")
    declared = {
        item["source_path"]: item["legacy_source_sha256"] for item in lineage["claims"]
    }
    assert len(current) == len(declared) == lineage["claim_count"] == 66
    assert declared == current
    candidate, report = john_gill_candidate
    validation_path = _write_validation_report(report, tmp_path / "validation.json")
    evidence = {
        ("helloao-john-gill-complete-retained-json", "john-gill"): (
            candidate.path,
            validation_path,
        )
    }
    catalog = current_runtime_catalog(
        root=ROOT,
        manifest=SOURCE_MANIFEST,
        work_ids=("john-gill",),
        reconstruction_evidence=evidence,
        data_resource_allowlist=[f"data/{path}" for path in sorted(declared)],
    )
    assert catalog.summary["work_units"] == 1
    assert {item["work_id"] for item in catalog.works} == {"john-gill"}
    work = next(item for item in catalog.works if item["work_id"] == "john-gill")
    state = work["reconstruction_state"]
    assert state["retained_source"] == "manifest_bound"
    assert state["tei_candidate"] == "verified"
    assert state["validation"] == "verified"
    assert state["accepted_ir"] == "not_accepted"
    assert state["publication"] == "not_ready"
    assert state["human_review"] == "required"
    assert state["routes"] == [
        {
            "association": "catalog_claim_lineage+exact_id",
            "manifest": "tests/fixtures/reconstruction-runtime/john-gill.source-manifest.json",
            "scope": "work",
            "source_id": "helloao-john-gill-complete-retained-json",
            "verification": "verified",
            "candidate_verification": "verified",
            "validation_verification": "verified",
        }
    ]
