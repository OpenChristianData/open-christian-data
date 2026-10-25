"""Contract and mutation tests for the complete retained HelloAO Keil-Delitzsch witness."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei import helloao_keil_delitzsch_oracle as oracle_module
from build.tei.helloao_keil_delitzsch_oracle import _oracle
from build.tei.helloao_keil_delitzsch_reconstruction import _convert
from build.tools.count_dataset_records import collect_work_catalog
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    ValidationReport,
    reconstruct,
    validate,
)
from ocd_kernel.reconstruction.decision import load_verified_review


ROOT = Path(__file__).resolve().parents[1]
RETAINED_MANIFEST = (
    ROOT / "sources/commentaries/keil-delitzsch/keil-delitzsch.source-manifest.json"
)
SOURCE_MANIFEST = (
    ROOT / "tests/fixtures/reconstruction-runtime/keil-delitzsch.source-manifest.json"
)
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
FORMAL_SOURCE_SHA = "c1162721788883e57518966d52ad770fe20ed19bd354ed02dc71cb102d80a789"
CANONICAL_XML_DECLARATION = b"<?xml version='1.0' encoding='UTF-8'?>\n"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def test_runtime_fixture_preserves_retained_inputs_and_only_updates_storage_closure():
    raw = RETAINED_MANIFEST.read_bytes()
    assert _sha(raw) == "f64fa4be7be388d830f0d87555dd7398b2721c4d3d2436d466a51c281ad5c4c1"
    expected = json.loads(raw)
    policy_path = next(
        item["path"] for item in expected["authorities"]
        if item["name"] == "validation-policy"
    )
    policy = json.loads((ROOT / policy_path).read_bytes())
    expected["validator"]["import_closure_sha256"] = oracle_module._closure_digest(ROOT, policy)
    assert json.loads(SOURCE_MANIFEST.read_bytes()) == expected


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
def keil_delitzsch_source() -> SourceManifest:
    return SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="session")
def keil_delitzsch_candidate(
    keil_delitzsch_source: SourceManifest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[CandidatePackage, object]:
    destination = tmp_path_factory.mktemp("lib081-candidate") / "candidate"
    candidate = reconstruct(keil_delitzsch_source, destination, _convert)
    report = validate(keil_delitzsch_source, candidate, _oracle)
    return candidate, report


def _copy_candidate(candidate: CandidatePackage, target: Path) -> Path:
    shutil.copytree(candidate.path, target)
    return target


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
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(target)


def _write_tei(target: Path, root: etree._Element) -> CandidatePackage:
    (target / "content.tei.xml").write_bytes(
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    )
    return _reseal(target, "content.tei.xml")


def _write_tei_document(target: Path, root: etree._Element) -> CandidatePackage:
    (target / "content.tei.xml").write_bytes(
        etree.tostring(
            root.getroottree(),
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )
    )
    return _reseal(target, "content.tei.xml")


def test_keil_delitzsch_source_manifest_binds_the_exact_retained_member_set(
    keil_delitzsch_source: SourceManifest,
) -> None:
    authorities = keil_delitzsch_source.record["authorities"]
    primary = [item for item in authorities if item["role"] == "primary-source"]
    assert len(primary) == 911
    assert [item["name"] for item in primary] == [
        f"retained-{i:04d}" for i in range(1, 912)
    ]
    assert sum(item["bytes"] for item in primary) == 47_103_116
    assert len({item["path"] for item in primary}) == 911
    assert {Path(item["path"]).name for item in primary} >= {
        "books.json",
        "profiles.json",
    }
    for authority in primary:
        content = (ROOT / authority["path"]).read_bytes()
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
    lineage = keil_delitzsch_source.record["catalog_claim_lineage"]
    assert lineage["retained_source_sha256"] == FORMAL_SOURCE_SHA
    assert lineage["claim_count"] == len(lineage["claims"]) == 38
    assert [item["source_path"] for item in lineage["claims"]] == sorted(
        item["source_path"] for item in lineage["claims"]
    )


def test_keil_delitzsch_structure_inventory_preserves_sections_and_paragraphs(
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
) -> None:
    candidate, _ = keil_delitzsch_candidate
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"tei": TEI_NS}
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    structure = accountability["meaningful_structure"]
    assert structure["carrier_count"] == 85
    assert structure["rendered_carrier_count"] == 4
    assert structure["evidence_only_carrier_count"] == 81
    assert structure["heading_span_count"] == 421
    assert structure["paragraph_policy"] == {
        "contract": "ocd-source-paragraph-segmentation-v1",
        "delimiter": "\n\n",
        "mode": "split-every-exact-double-newline",
        "carrier_total_count": 6_949,
        "carrier_count_with_delimiter": 594,
        "delimiter_count": 1_826,
    }
    source = json.loads(
        (ROOT / "raw/helloao_local/api/c/keil-delitzsch/books.json").read_bytes()
    )
    isa_text = source["books"][22]["introduction"]
    isa_intro = root.xpath(
        "tei:text/tei:body/tei:div[@n='ISA']/tei:div[@type='book-introduction']",
        namespaces=ns,
    )[0]
    assert isa_intro.xpath(
        "tei:div[@type='commentary-section']/tei:head/text()", namespaces=ns
    ) == [
        "The Prophecies of Isaiah",
        "Introduction",
        "Time of the Prophet",
        "I. Historical Account of Uzziah-Jotham",
        "II. Historical Account of Ahaz and the Syro-Ephraimitish War.",
    ]
    assert "".join(isa_intro.itertext()) == isa_text
    gen_text = source["books"][0]["introduction"]
    gen_intro = root.xpath(
        "tei:text/tei:body/tei:div[@n='GEN']/tei:div[@type='book-introduction']",
        namespaces=ns,
    )[0]
    assert len(gen_intro.xpath("tei:p", namespaces=ns)) == gen_text.count("\n\n") + 1
    assert "".join(gen_intro.itertext()) == gen_text


def test_keil_delitzsch_candidate_is_complete_valid_nonaccepted_and_not_ready(
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
) -> None:
    candidate, report = keil_delitzsch_candidate
    assert report.status == "pass"
    assert report.candidate_sha256 == candidate.sha256
    assert candidate.manifest["status"] == "nonaccepted"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["member_count"] == 911
    assert accountability["included_member_count"] == 911
    assert accountability["excluded_member_count"] == 0
    assert accountability["total_bytes"] == 47_103_116
    assert accountability["census"] == {
        "books": 39,
        "chapters": 909,
        "commentary_occurrences": 6_516,
        "book_introductions": 39,
        "chapter_introductions_present": 394,
        "chapter_introductions_absent": 515,
        "profiles": 0,
    }
    assert len(accountability["anomalies"]["chapter_introduction_absent_paths"]) == 515
    assert accountability["anomalies"]["nonmonotonic_occurrence_paths"] == [
        "JDG/12.json",
        "2KI/10.json",
        "ISA/38.json",
    ]
    assert accountability["anomalies"]["duplicate_occurrence_numbers"] == [
        {"path": "ISA/38.json", "number": 21, "count": 2}
    ]
    assert (
        accountability["source_shapes"]["object_key_order_census"]["object_count"]
        == 10_195
    )
    assert (
        accountability["source_shapes"]["object_key_order_census"]["variant_count"] == 8
    )
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["status"] == "nonaccepted"
    assert provenance["accepted_ir"] == "not_accepted"
    assert provenance["publication"] == "not_ready"
    assert provenance["human_decision"] is None


def test_keil_delitzsch_tei_preserves_order_introductions_links_and_anomalies(
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
) -> None:
    candidate, _ = keil_delitzsch_candidate
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"tei": TEI_NS}
    assert (
        len(root.xpath("tei:text/tei:body/tei:div[@type='book']", namespaces=ns)) == 39
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
        == 39
    )
    assert (
        len(
            root.xpath(
                "tei:text/tei:body/tei:div/tei:div/tei:div[@type='chapter-introduction']",
                namespaces=ns,
            )
        )
        == 394
    )
    assert (
        len(
            root.xpath(
                "tei:text/tei:body/tei:div/tei:div/tei:div[@type='commentary-occurrence']",
                namespaces=ns,
            )
        )
        == 6_516
    )
    numbers = root.xpath(
        "tei:text/tei:body/tei:div[@n='ISA']/tei:div[@type='chapter'][@n='38']/tei:div[@type='commentary-occurrence']/@n",
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
    malachi = root.xpath(
        "tei:text/tei:body/tei:div[@n='MAL']/tei:div[@type='chapter'][@n='4']",
        namespaces=ns,
    )[0]
    following = malachi.xpath(
        "tei:note[@type='chapter-link'][@subtype='next']", namespaces=ns
    )[0]
    assert following.get("ana") == "null" and following.text is None
    song = root.xpath("tei:text/tei:body/tei:div[@n='SNG']", namespaces=ns)[0]
    assert len(song.xpath("tei:div[@type='book-introduction']", namespaces=ns)) == 1
    assert not song.xpath("tei:div[@type='chapter']", namespaces=ns)
    isa_numbers = [int(value) for value in numbers]
    assert isa_numbers.count(21) == 2


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
def test_keil_delitzsch_oracle_rejects_textual_and_structural_mutations(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = keil_delitzsch_candidate
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
        validate(keil_delitzsch_source, mutated, _oracle)


@pytest.mark.parametrize("mutation", ["false-complete", "rights", "edition"])
def test_keil_delitzsch_oracle_rejects_provenance_mutations(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = keil_delitzsch_candidate
    target = _copy_candidate(candidate, tmp_path / mutation)
    provenance = json.loads((target / "provenance.json").read_bytes())
    if mutation == "false-complete":
        provenance["scope"]["canonical_bible_complete"] = False
    elif mutation == "rights":
        provenance["rights"]["retained_mark"] = "CC0 1.0"
    else:
        provenance["identity"]["original_publication_year"] = 1748
    (target / "provenance.json").write_bytes(_canonical(provenance))
    mutated = _reseal(target, "provenance.json")
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


def test_keil_delitzsch_oracle_rejects_accountability_omission(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
) -> None:
    candidate, _ = keil_delitzsch_candidate
    target = _copy_candidate(candidate, tmp_path / "accountability-omission")
    accountability = json.loads((target / "source-accountability.json").read_bytes())
    accountability["members"] = accountability["members"][:-1]
    (target / "source-accountability.json").write_bytes(_canonical(accountability))
    mutated = _reseal(target, "source-accountability.json")
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


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
def test_keil_delitzsch_oracle_rejects_schema_valid_invented_header_metadata(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = keil_delitzsch_candidate
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
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(root), schema.error_log
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


def test_keil_delitzsch_oracle_rejects_schema_valid_nested_body_invention(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
) -> None:
    candidate, _ = keil_delitzsch_candidate
    target = _copy_candidate(candidate, tmp_path / "nested-body-note")
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    paragraph = root.find(
        f".//{{{TEI_NS}}}div[@type='commentary-occurrence']/{{{TEI_NS}}}p"
    )
    assert paragraph is not None
    note = etree.SubElement(paragraph, f"{{{TEI_NS}}}note", {"type": "editorial"})
    note.text = "Invented body note"
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(root), schema.error_log
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    ["nested-seg", "nested-tail", "comment", "processing-instruction", "sibling"],
)
def test_keil_delitzsch_oracle_rejects_unaccounted_schema_valid_body_nodes(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = keil_delitzsch_candidate
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
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(root), schema.error_log
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


def test_keil_delitzsch_oracle_accepts_expected_namespace_semantics(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
) -> None:
    candidate, _ = keil_delitzsch_candidate
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    elements = [item for item in root.iter() if isinstance(item.tag, str)]
    assert root.nsmap == {None: TEI_NS}
    assert all(item.nsmap == {None: TEI_NS} for item in elements)
    assert any(f"{{{XML_NS}}}id" in item.attrib for item in elements)
    assert validate(keil_delitzsch_source, candidate, _oracle).status == "pass"


@pytest.mark.parametrize("location", ["root", "body"])
def test_keil_delitzsch_oracle_rejects_unexpected_namespace_declarations(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    location: str,
) -> None:
    candidate, _ = keil_delitzsch_candidate
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
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(root), schema.error_log
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


def test_keil_delitzsch_oracle_rejects_explicit_reserved_xml_namespace_declaration(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
) -> None:
    candidate, _ = keil_delitzsch_candidate
    target = _copy_candidate(candidate, tmp_path / "explicit-reserved-xml-namespace")
    tei_path = target / "content.tei.xml"
    content = tei_path.read_bytes()
    root_start = b'<TEI xmlns="http://www.tei-c.org/ns/1.0">'
    replacement = (
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0" '
        b'xmlns:xml="http://www.w3.org/XML/1998/namespace">'
    )
    assert content.count(root_start) == 1
    tei_path.write_bytes(content.replace(root_start, replacement, 1))
    root = etree.fromstring(tei_path.read_bytes())
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(root), schema.error_log
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


@pytest.mark.parametrize(
    ("node_kind", "position"),
    [
        ("comment", "before"),
        ("comment", "after"),
        ("processing-instruction", "before"),
        ("processing-instruction", "after"),
    ],
)
def test_keil_delitzsch_oracle_rejects_document_level_siblings(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    node_kind: str,
    position: str,
) -> None:
    candidate, _ = keil_delitzsch_candidate
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
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(root), schema.error_log
    mutated = _write_tei_document(target, root)
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-declaration",
        "standalone-yes",
        "standalone-no",
        "encoding-case",
        "declaration-spacing",
        "bom-before-declaration",
        "doctype",
        "pre-root-comment",
        "pre-root-processing-instruction",
        "blank-line-after-declaration",
        "two-spaces-before-root",
        "extra-newline-after-root",
        "trailing-space-after-root",
    ],
)
def test_keil_delitzsch_oracle_rejects_noncanonical_lexical_document_shell(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = keil_delitzsch_candidate
    target = _copy_candidate(candidate, tmp_path / mutation)
    tei_path = target / "content.tei.xml"
    content = tei_path.read_bytes()
    assert content.startswith(CANONICAL_XML_DECLARATION)
    body = content.removeprefix(CANONICAL_XML_DECLARATION)
    if mutation == "missing-declaration":
        mutated_bytes = body
    elif mutation == "standalone-yes":
        mutated_bytes = (
            b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + body
        )
    elif mutation == "standalone-no":
        mutated_bytes = (
            b"<?xml version='1.0' encoding='UTF-8' standalone='no'?>\n" + body
        )
    elif mutation == "encoding-case":
        mutated_bytes = b"<?xml version='1.0' encoding='utf-8'?>\n" + body
    elif mutation == "declaration-spacing":
        mutated_bytes = b"<?xml version = '1.0' encoding = 'UTF-8'?>\n" + body
    elif mutation == "bom-before-declaration":
        mutated_bytes = b"\xef\xbb\xbf" + content
    elif mutation == "doctype":
        mutated_bytes = CANONICAL_XML_DECLARATION + b"<!DOCTYPE TEI>\n" + body
    elif mutation == "pre-root-comment":
        mutated_bytes = (
            CANONICAL_XML_DECLARATION + b"<!-- invented pre-root node -->\n" + body
        )
    elif mutation == "pre-root-processing-instruction":
        mutated_bytes = CANONICAL_XML_DECLARATION + b"<?invented pre-root?>\n" + body
    elif mutation == "blank-line-after-declaration":
        mutated_bytes = CANONICAL_XML_DECLARATION + b"\n" + body
    elif mutation == "two-spaces-before-root":
        mutated_bytes = CANONICAL_XML_DECLARATION + b"  " + body
    elif mutation == "extra-newline-after-root":
        mutated_bytes = content + b"\n"
    else:
        mutated_bytes = content + b" "
    parsed = etree.parse(
        BytesIO(mutated_bytes),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(parsed.getroot()), schema.error_log
    tei_path.write_bytes(mutated_bytes)
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


def test_keil_delitzsch_oracle_rejects_invented_readme_rights_claim(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
) -> None:
    candidate, _ = keil_delitzsch_candidate
    target = _copy_candidate(candidate, tmp_path / "invented-readme-rights")
    readme_path = target / "README.source.md"
    readme_path.write_bytes(
        readme_path.read_bytes()
        + b"\nInvented rights claim: this digital witness is licensed CC BY 4.0.\n"
    )
    mutated = _reseal(target, "README.source.md")
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


@pytest.mark.parametrize("mutation", ["omission", "reorder"])
def test_keil_delitzsch_oracle_rejects_readme_omission_or_reordering(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = keil_delitzsch_candidate
    target = _copy_candidate(candidate, tmp_path / f"readme-{mutation}")
    readme_path = target / "README.source.md"
    lines = readme_path.read_text(encoding="utf-8").splitlines(keepends=True)
    census_index = lines.index(
        "- The retained census is exactly 911 members and 47,103,116 bytes.\n"
    )
    if mutation == "omission":
        lines.pop(census_index)
    else:
        lines[census_index], lines[census_index + 1] = (
            lines[census_index + 1],
            lines[census_index],
        )
    readme_path.write_text("".join(lines), encoding="utf-8", newline="")
    mutated = _reseal(target, "README.source.md")
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


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
def test_keil_delitzsch_oracle_rejects_existing_header_metadata_drift(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate, _ = keil_delitzsch_candidate
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
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(root), schema.error_log
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


def test_keil_delitzsch_schema_rejects_an_extra_header_title(
    keil_delitzsch_source: SourceManifest,
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
    tmp_path: Path,
) -> None:
    candidate, _ = keil_delitzsch_candidate
    target = _copy_candidate(candidate, tmp_path / "extra-title")
    root = etree.fromstring((target / "content.tei.xml").read_bytes())
    title_stmt = root.find(f".//{{{TEI_NS}}}titleStmt")
    assert title_stmt is not None
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = "Invented Alternate Title"
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert not schema.validate(root)
    mutated = _write_tei(target, root)
    with pytest.raises(ValueError):
        validate(keil_delitzsch_source, mutated, _oracle)


def test_keil_delitzsch_oracle_is_independent_and_bound_to_its_closure(
    keil_delitzsch_candidate: tuple[CandidatePackage, object],
) -> None:
    _, report = keil_delitzsch_candidate
    oracle_source = (ROOT / "build/tei/helloao_keil_delitzsch_oracle.py").read_text(
        encoding="utf-8"
    )
    assert "helloao_keil_delitzsch_reconstruction" not in oracle_source
    assert "helloao_commentary" not in oracle_source
    assert "data/commentaries/keil-delitzsch" not in oracle_source
    assert len(report.attestation["import_closure_sha256"]) == 64


def test_keil_delitzsch_retained_candidate_and_validation_sidecar_bind(
    keil_delitzsch_candidate,
    tmp_path: Path,
) -> None:
    candidate, report = keil_delitzsch_candidate
    validation_path = _write_validation_report(report, tmp_path / "validation.json")
    review = load_verified_review(
        SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT),
        candidate_path=candidate.path,
        validation_path=validation_path,
    )
    assert review.candidate_sha256 == candidate.sha256
    assert review.validation.status == "pass"
    assert review.validation.sha256 == report.sha256


def test_keil_delitzsch_catalog_claim_lineage_and_work_map_route(
    keil_delitzsch_candidate,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from build.tools import count_dataset_records

    selection = SOURCE_MANIFEST.relative_to(ROOT).as_posix()

    def selected_manifest_paths(sources_root: Path, selections):
        assert sources_root == ROOT / "sources"
        assert tuple(selections) == (selection,)
        return sources_root, (SOURCE_MANIFEST,)

    original_identity = count_dataset_records._runtime_policy_identity

    def identity(source, record, path, sources_root, **kwargs):
        # Retain source-directory classification while verifying the runtime fixture.
        return original_identity(
            source, record, RETAINED_MANIFEST if path == SOURCE_MANIFEST else path,
            sources_root, **kwargs
        )

    monkeypatch.setattr(
        count_dataset_records, "_resolve_source_manifest_allowlist", selected_manifest_paths
    )
    monkeypatch.setattr(count_dataset_records, "_runtime_policy_identity", identity)
    manifest = json.loads(SOURCE_MANIFEST.read_bytes())
    lineage = manifest["catalog_claim_lineage"]
    current = {}
    for path in sorted((ROOT / "data/commentaries/keil-delitzsch").glob("*.json")):
        if path.name == "_manifest.json":
            continue
        document = json.loads(path.read_bytes())
        current["commentaries/keil-delitzsch/" + path.name] = document["meta"][
            "provenance"
        ]["source_hash"].removeprefix("sha256:")
    declared = {
        item["source_path"]: item["legacy_source_sha256"] for item in lineage["claims"]
    }
    assert len(current) == len(declared) == lineage["claim_count"] == 38
    assert declared == current
    candidate, report = keil_delitzsch_candidate
    validation_path = _write_validation_report(report, tmp_path / "validation.json")
    evidence = {
        ("helloao-keil-delitzsch-complete-retained-json", "keil-delitzsch"): (
            candidate.path,
            validation_path,
        )
    }
    catalog = collect_work_catalog(
        ROOT / "data",
        reconstruction_evidence=evidence,
        source_manifest_allowlist=[SOURCE_MANIFEST.relative_to(ROOT).as_posix()],
        data_resource_allowlist=[f"data/{path}" for path in sorted(declared)],
    )
    assert catalog.summary["work_units"] == 1
    assert {item["work_id"] for item in catalog.works} == {"keil-delitzsch"}
    work = next(item for item in catalog.works if item["work_id"] == "keil-delitzsch")
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
            "manifest": SOURCE_MANIFEST.relative_to(ROOT).as_posix(),
            "scope": "work",
            "source_id": "helloao-keil-delitzsch-complete-retained-json",
            "verification": "verified",
            "candidate_verification": "verified",
            "validation_verification": "verified",
        }
    ]


def test_keil_delitzsch_candidate_is_byte_identical_across_fresh_processes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    code = (
        "from pathlib import Path; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.helloao_keil_delitzsch_reconstruction import _convert; "
        f"r=Path({str(ROOT)!r}); "
        f"s=SourceManifest.load(r/{str(SOURCE_MANIFEST.relative_to(ROOT))!r},repository_root=r); "
        "reconstruct(s,Path(__import__('sys').argv[1]),_convert)"
    )
    try:
        for destination in (first, second):
            subprocess.run(
                [sys.executable, "-c", code, str(destination)],
                cwd=ROOT,
                check=True,
                timeout=120,
            )
        first_members = {path.name: path.read_bytes() for path in sorted(first.iterdir())}
        second_members = {path.name: path.read_bytes() for path in sorted(second.iterdir())}
        assert first_members == second_members
    finally:
        for destination in (first, second):
            if destination.exists():
                shutil.rmtree(destination)
