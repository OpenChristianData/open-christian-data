from __future__ import annotations

import hashlib
import json
from pathlib import Path
from collections.abc import Iterator

from lxml import etree
import pytest

from build.lib.pytest_candidate_clone import (
    candidate_package_fingerprint,
    clone_candidate_package,
)
from build.tei.npnf105_oracle import validate_candidate, validation_record
from build.tei.npnf105_reconstruction import (
    ASSIGNED,
    EXPECTED_COUNTS,
    reconstruct_candidate,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.decision import load_verified_review
from ocd_kernel.lib.storage_topology import resolve_repo_path


pytestmark = [
    pytest.mark.slow,
    pytest.mark.xdist_group(name="npnf105-reconstruction"),
]


ROOT = Path(__file__).resolve().parents[1]
RETAINED_MANIFEST_PATH = (
    ROOT / "sources/structured-text/augustine-npnf105/npnf105.source-manifest.json"
)
MANIFEST_PATH = ROOT / "tests/fixtures/reconstruction-runtime/npnf105.source-manifest.json"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI = {"tei": "http://www.tei-c.org/ns/1.0"}


def _manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)


def test_runtime_fixture_preserves_retained_authorities_and_only_updates_closure() -> None:
    from build.tei.npnf105_oracle import _closure

    retained = RETAINED_MANIFEST_PATH.read_bytes()
    assert hashlib.sha256(retained).hexdigest() == (
        "fc1824fc52a968aff16cdfe42246a1f69fa3d3e2cd659d82aefbbf98dfd50d12"
    )
    expected = json.loads(retained)
    expected["validator"]["implementation_sha256"] = hashlib.sha256(
        (ROOT / "build/tei/npnf105_oracle.py").read_bytes()
    ).hexdigest()
    expected["validator"]["import_closure_sha256"] = _closure(ROOT)[0]
    assert json.loads(MANIFEST_PATH.read_bytes()) == expected


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _replace_nested(
    value: object, path: tuple[str | int, ...], replacement: object
) -> None:
    current = value
    for part in path[:-1]:
        assert isinstance(current, (dict, list))
        current = current[part]
    assert isinstance(current, (dict, list))
    current[path[-1]] = replacement


def _reseal(path: Path, member: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    content = (path / member).read_bytes()
    entry = next(item for item in manifest["members"] if item["name"] == member)
    entry["bytes"] = len(content)
    entry["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _clone_for_mutation(
    candidate: CandidatePackage,
    target: Path,
    *,
    mutable_members: tuple[str, ...],
) -> Path:
    package_members = set(candidate.member_names)
    mutable = set(mutable_members)
    if not mutable or not mutable <= package_members:
        raise AssertionError(f"invalid mutable candidate members: {sorted(mutable)}")
    clone_candidate_package(
        candidate.path,
        target,
        hardlink_members=tuple(sorted(package_members - mutable)),
    )
    for member in mutable:
        assert not (candidate.path / member).samefile(target / member)
    return target


@pytest.fixture(scope="module")
def p5_schema():
    record = json.loads(MANIFEST_PATH.read_bytes())
    authority = next(row for row in record["authorities"] if row["name"] == "tei-p5-xsd")
    schema_path = resolve_repo_path(ROOT, authority["path"], strict=True)
    paths = [schema_path, *(schema_path.parent / name for name in
                            ("tei_all_teix.xsd", "tei_all_xml.xsd"))]
    original = {path: path.read_bytes() for path in paths}
    assert len(original[schema_path]) == authority["bytes"]
    assert hashlib.sha256(original[schema_path]).hexdigest() == authority["sha256"]
    schema = etree.XMLSchema(etree.parse(str(schema_path)))
    yield schema
    assert {path: path.read_bytes() for path in paths} == original


@pytest.fixture(scope="module")
def verified_candidate(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[SourceManifest, CandidatePackage, Path]]:
    root = tmp_path_factory.mktemp("npnf105-candidate")
    manifest = _manifest()
    candidate = reconstruct_candidate(manifest, root / "candidate")
    report = validate_candidate(manifest, candidate)
    report_path = root / "validation.json"
    report_path.write_bytes(_canonical(validation_record(report)))
    baseline = candidate_package_fingerprint(candidate.path)
    yield manifest, candidate, report_path
    assert candidate_package_fingerprint(candidate.path) == baseline


def test_schema_fixture_does_not_need_raw_sources(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("independent XSD compilation must not read the corpus")

    monkeypatch.setattr(SourceManifest, "load", classmethod(refuse))
    fixture = p5_schema.__wrapped__()
    schema = next(fixture)
    try:
        assert isinstance(schema, etree.XMLSchema)
    finally:
        with pytest.raises(StopIteration):
            next(fixture)


@pytest.mark.requires_local_artifacts
def test_retained_source_scope_inventory_and_comments_are_exact() -> None:
    source = ROOT / "raw/ccel/npnf1/npnf105.xml"
    assert (
        hashlib.sha256(source.read_bytes()).hexdigest()
        == "224f0e6a188ddfe691c1433c8db9a883755a9f030b71fede644d4af6c18ee63f"
    )
    tree = etree.parse(
        str(source),
        etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False),
    )
    body = tree.getroot().find("ThML.body")
    assert body is not None
    divisions = [
        child for child in body if isinstance(child.tag, str) and child.tag == "div1"
    ]
    assert [node.get("id") for node in divisions] == [
        "i",
        "ii",
        "iii",
        "iv",
        "v",
        "vi",
        "vii",
        "viii",
        "ix",
        *[scope for scope, _ in ASSIGNED],
        "xxii",
        "xxiii",
    ]
    selected = divisions[9:21]
    counts: dict[str, int] = {}
    for node in [
        item
        for division in selected
        for item in division.iter()
        if isinstance(item.tag, str)
    ]:
        counts[node.tag] = counts.get(node.tag, 0) + 1
    assert counts == EXPECTED_COUNTS
    assert sum(counts.values()) == 16648
    comments = [
        comment for division in selected for comment in division.xpath(".//comment()")
    ]
    assert len(comments) == 4
    assert [comment.tail for comment in comments] == ["[1609]", None, " [3415]", None]


@pytest.mark.requires_local_artifacts
def test_candidate_validates_and_is_reloadable_as_current_review(
    verified_candidate: tuple[SourceManifest, CandidatePackage, Path],
) -> None:
    manifest, candidate, report_path = verified_candidate
    review = load_verified_review(
        manifest, candidate_path=candidate.path, validation_path=report_path
    )
    assert review.validation.status == "pass"
    assert review.candidate_sha256 == candidate.sha256
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["feature_count"] == 16648
    assert accountability["omitted_feature_count"] == 0
    assert len(accountability["division_accounting"]) == 23
    assert len(accountability["comment_accounting"]) == 8


@pytest.mark.requires_local_artifacts
def test_same_process_repeated_generation_has_identical_path_set_and_bytes(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    first = reconstruct_candidate(manifest, tmp_path / "first")
    second = reconstruct_candidate(manifest, tmp_path / "second")
    assert first.member_names == second.member_names
    assert first.sha256 == second.sha256
    assert {name: first.member_bytes(name) for name in first.member_names} == {
        name: second.member_bytes(name) for name in second.member_names
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reorder",
        "invention",
        "invention-without-id",
        "comment-tail",
        "comment-relocation",
        "header-rights",
        "header-editor-role",
        "header-translator-role",
        "header-publisher",
        "root-id",
        "header-extra-editor",
        "header-extra-date",
        "header-extra-source-note",
        "header-warfield-omission",
        "header-warfield-role",
        "root-extra-attribute",
        "header-tail",
        "header-extra-container",
        "nested-unused-namespace",
        "nested-processing-instruction",
        "nested-header-unused-namespace",
        "header-processing-instruction",
        "body-invented-comment",
        "document-leading-processing-instruction",
        "document-trailing-comment",
    ],
)
@pytest.mark.requires_local_artifacts
def test_independent_oracle_rejects_tei_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage, Path],
    tmp_path: Path,
    mutation: str,
    p5_schema,
) -> None:
    manifest, candidate, _ = verified_candidate
    target = tmp_path / mutation
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("content.tei.xml", "manifest.json"),
    )
    xml_path = target / "content.tei.xml"
    tree = etree.parse(str(xml_path), etree.XMLParser(remove_comments=False))
    body = tree.xpath("/tei:TEI/tei:text/tei:body", namespaces=TEI)[0]
    if mutation == "omission":
        node = tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=TEI)[0]
        node.getparent().remove(node)
    elif mutation == "duplication":
        node = tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=TEI)[0]
        duplicate = etree.fromstring(etree.tostring(node))
        for ordinal, descendant in enumerate(duplicate.iter(), start=1):
            if descendant.get(XML_ID) is not None:
                descendant.set(XML_ID, f"npnf105-invented-duplicate-{ordinal}")
        node.getparent().append(duplicate)
    elif mutation == "reorder":
        first, second = list(body)[:2]
        body.remove(second)
        body.insert(0, second)
        assert list(body)[1] is first
    elif mutation == "invention":
        invented_div = etree.Element("{http://www.tei-c.org/ns/1.0}div")
        invented_div.set(XML_ID, "npnf105-invented")
        invented = etree.SubElement(invented_div, "{http://www.tei-c.org/ns/1.0}p")
        invented.set(XML_ID, "npnf105-invented-p")
        invented.text = "invented text"
        body.append(invented_div)
    elif mutation == "invention-without-id":
        paragraph = tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=TEI)[0]
        invented = etree.Element("{http://www.tei-c.org/ns/1.0}hi")
        invented.text = "INVENTED BUT VALID"
        paragraph.append(invented)
    elif mutation == "comment-tail":
        comment = tree.xpath("/tei:TEI/tei:text/tei:body//comment()", namespaces=TEI)[0]
        comment.tail = "[wrong]"
    elif mutation == "comment-relocation":
        paragraph = tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=TEI)[0]
        comments = tree.xpath("/tei:TEI/tei:text/tei:body//comment()", namespaces=TEI)
        for comment in comments:
            paragraph.append(comment)
    elif mutation == "header-rights":
        rights = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability/tei:p",
            namespaces=TEI,
        )[0]
        rights.text = "Public domain without qualification."
    elif mutation == "header-editor-role":
        role = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt[1]/tei:resp",
            namespaces=TEI,
        )[0]
        role.text = "translator"
    elif mutation == "header-translator-role":
        role = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt[2]/tei:resp",
            namespaces=TEI,
        )[0]
        role.text = "editor"
    elif mutation == "header-publisher":
        publisher = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:publisher",
            namespaces=TEI,
        )[0]
        publisher.text = "Invented Publisher"
    elif mutation == "root-id":
        tree.getroot().set(XML_ID, "npnf105-invented-root")
    elif mutation == "header-extra-editor":
        title_stmt = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt", namespaces=TEI
        )[0]
        editor = etree.Element("{http://www.tei-c.org/ns/1.0}editor")
        editor.text = "Invented Header Contributor"
        title_stmt.append(editor)
    elif mutation == "header-extra-date":
        publication_stmt = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt", namespaces=TEI
        )[0]
        date = etree.Element("{http://www.tei-c.org/ns/1.0}date")
        date.text = "1887"
        publication_stmt.append(date)
    elif mutation == "header-extra-source-note":
        bibl = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl",
            namespaces=TEI,
        )[0]
        note = etree.Element("{http://www.tei-c.org/ns/1.0}note")
        note.text = "Invented source metadata"
        bibl.append(note)
    elif mutation == "header-warfield-omission":
        title_stmt = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt", namespaces=TEI
        )[0]
        warfield = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt[4]",
            namespaces=TEI,
        )[0]
        title_stmt.remove(warfield)
    elif mutation == "header-warfield-role":
        role = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt[4]/tei:resp",
            namespaces=TEI,
        )[0]
        role.text = "editor"
    elif mutation == "root-extra-attribute":
        tree.getroot().set("n", "invented")
    elif mutation == "header-tail":
        publisher = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:publisher",
            namespaces=TEI,
        )[0]
        publisher.tail = " "
    elif mutation == "nested-unused-namespace":
        node = tree.xpath("/tei:TEI/tei:text/tei:body/tei:div[1]", namespaces=TEI)[0]
        replacement = etree.Element(
            node.tag,
            nsmap={
                None: "http://www.tei-c.org/ns/1.0",
                "invented": "urn:ocd:invented",
            },
        )
        replacement.attrib.update(node.attrib)
        replacement.text = node.text
        replacement.tail = node.tail
        for child in list(node):
            replacement.append(child)
        node.getparent().replace(node, replacement)
    elif mutation == "nested-processing-instruction":
        paragraph = tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=TEI)[0]
        paragraph.insert(
            0,
            etree.ProcessingInstruction("invented-editorial", "status=false"),
        )
    elif mutation == "nested-header-unused-namespace":
        node = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt", namespaces=TEI
        )[0]
        replacement = etree.Element(
            node.tag,
            nsmap={
                None: "http://www.tei-c.org/ns/1.0",
                "invented": "urn:ocd:invented",
            },
        )
        replacement.attrib.update(node.attrib)
        replacement.text = node.text
        replacement.tail = node.tail
        for child in list(node):
            replacement.append(child)
        node.getparent().replace(node, replacement)
    elif mutation == "header-processing-instruction":
        title_stmt = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt", namespaces=TEI
        )[0]
        title_stmt.insert(
            0,
            etree.ProcessingInstruction("invented-editorial", "status=false"),
        )
    elif mutation == "body-invented-comment":
        paragraph = tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=TEI)[0]
        paragraph.insert(0, etree.Comment("invented editorial comment"))
    elif mutation == "document-leading-processing-instruction":
        tree.getroot().addprevious(
            etree.ProcessingInstruction("invented-editorial", "status=false")
        )
    elif mutation == "document-trailing-comment":
        tree.getroot().addnext(etree.Comment("invented document comment"))
    else:
        file_desc = tree.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc", namespaces=TEI)[0]
        source_desc = tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc", namespaces=TEI
        )[0]
        notes_stmt = etree.Element("{http://www.tei-c.org/ns/1.0}notesStmt")
        note = etree.SubElement(notes_stmt, "{http://www.tei-c.org/ns/1.0}note")
        note.text = "Invented header container"
        file_desc.insert(file_desc.index(source_desc), notes_stmt)
    xml_path.write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    written_tree = etree.parse(
        str(xml_path),
        etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False),
    )
    xsd = p5_schema
    assert xsd.validate(written_tree), xsd.error_log.last_error
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError):
        validate_candidate(manifest, mutated)


@pytest.mark.parametrize(
    "mutation",
    [
        "doctype-insertion",
        "xml-declaration-omission",
        "standalone-yes",
        "standalone-no",
    ],
)
@pytest.mark.requires_local_artifacts
def test_independent_oracle_rejects_document_prolog_drift(
    verified_candidate: tuple[SourceManifest, CandidatePackage, Path],
    tmp_path: Path,
    mutation: str,
    p5_schema,
) -> None:
    manifest, candidate, _ = verified_candidate
    target = tmp_path / mutation
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("content.tei.xml", "manifest.json"),
    )
    xml_path = target / "content.tei.xml"
    content = xml_path.read_bytes()
    declaration_end = content.index(b"?>") + 2
    declaration = content[:declaration_end]
    remainder = content[declaration_end:]
    assert declaration == b"<?xml version='1.0' encoding='UTF-8'?>"
    assert remainder.startswith(b"\n<TEI ")

    if mutation == "doctype-insertion":
        content = declaration + b"<!DOCTYPE TEI>" + remainder
    elif mutation == "xml-declaration-omission":
        content = remainder.lstrip(b"\r\n")
    elif mutation == "standalone-yes":
        content = b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>" + remainder
    else:
        content = b"<?xml version='1.0' encoding='UTF-8' standalone='no'?>" + remainder
    xml_path.write_bytes(content)

    written_tree = etree.parse(
        str(xml_path),
        etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False),
    )
    xsd = p5_schema
    assert xsd.validate(written_tree), xsd.error_log.last_error
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="TEI document prolog drift"):
        validate_candidate(manifest, mutated)


@pytest.mark.requires_local_artifacts
def test_retained_credits_and_known_work_allocations_are_exact(
    verified_candidate: tuple[SourceManifest, CandidatePackage, Path],
) -> None:
    _, candidate, _ = verified_candidate
    source = etree.parse(
        str(ROOT / "raw/ccel/npnf1/npnf105.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False),
    )
    exact_source_text = {
        "ii-p2": "translated by",
        "ii-p3": "PETER HOLMES, D.D., F.R.A.S.,",
        "ii-p7": "REV. ROBERT ERNEST WALLIS, Ph.d.,",
        "ii-p9": "THE TRANSLATION REVISED, AND AN INTRODUCTION PREFIXED, BY",
        "ii-p10": "BENJAMIN B. WARFIELD, D.D.,",
    }
    for source_id, expected in exact_source_text.items():
        nodes = source.xpath(f"//*[@id='{source_id}']")
        assert len(nodes) == 1
        assert "".join(nodes[0].itertext()) == expected
    allocation = source.xpath("//*[@id='ix-p14']")
    assert len(allocation) == 1
    assert "only the first was from the pen of Dr. Holmes" in "".join(
        allocation[0].itertext()
    )
    assert "the rest being the work of Dr. Robert Ernest Wallis" in "".join(
        allocation[0].itertext()
    )

    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    contributors = [
        (
            node.findtext("tei:resp", namespaces=TEI),
            node.findtext("tei:name", namespaces=TEI),
        )
        for node in tree.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt",
            namespaces=TEI,
        )
    ]
    assert contributors == [
        ("editor", "Philip Schaff"),
        ("translator", "Peter Holmes"),
        ("translator", "Robert Ernest Wallis"),
        ("translation reviser and introduction author", "Benjamin B. Warfield"),
    ]

    provenance = json.loads(candidate.member_bytes("provenance.json"))
    allocations = {
        work["div1_id"]: work["translator_allocation"] for work in provenance["works"]
    }
    assert allocations["xix"]["credited_to"] == "Peter Holmes"
    for scope in ("xviii", "xx", "xxi"):
        assert allocations[scope]["credited_to"] == "Robert Ernest Wallis"
    assert allocations["xxi"]["retained_scope_titles"] == [
        "A Treatise on the Predestination of the Saints.",
        "A Treatise on the Gift of Perseverance.",
    ]
    assert [
        scope
        for scope, allocation in allocations.items()
        if allocation["status"] == "unresolved"
    ] == [
        "x",
        "xi",
        "xii",
        "xiii",
        "xiv",
        "xv",
        "xvi",
        "xvii",
    ]


@pytest.mark.parametrize(
    "mutation", ["wrong-source", "rights", "translator", "work-order"]
)
@pytest.mark.requires_local_artifacts
def test_independent_oracle_rejects_evidence_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage, Path],
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest, candidate, _ = verified_candidate
    target = tmp_path / mutation
    member = (
        "source-accountability.json"
        if mutation == "wrong-source"
        else "provenance.json"
    )
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=(member, "manifest.json"),
    )
    path = target / member
    value = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "wrong-source":
        value["source_member"]["sha256"] = "0" * 64
    elif mutation == "rights":
        value["rights"]["retained_statement"] = "Copyrighted"
    elif mutation == "translator":
        value["works"][9]["translator_allocation"]["credited_to"] = (
            "Robert Ernest Wallis"
        )
    else:
        value["works"][0], value["works"][1] = value["works"][1], value["works"][0]
    path.write_bytes(_canonical(value))
    mutated = _reseal(target, member)
    with pytest.raises(ValueError):
        validate_candidate(manifest, mutated)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("contract",), "invented-contract"),
        (("status",), "accepted"),
        (("source_id",), "invented-source"),
        (("source", "path"), "raw/invented.xml"),
        (("source", "sha256"), "0" * 64),
        (("source", "scope"), "div1 x only"),
        (("works", 0, "ordinal"), 99),
        (("works", 0, "div1_id"), "invented"),
        (("works", 0, "work_id"), "invented-work"),
        *[
            (("works", index, "title"), f"Invented work title {index + 1}")
            for index in range(12)
        ],
        (("edition", "title"), "Invented edition title"),
        (("edition", "editor"), "Invented editor"),
        (("edition", "publication"), "Invented publication"),
        (("edition", "source_identifier"), "/invented/source.html"),
        *[
            (("works", index, "translator_allocation", "status"), "invented-status")
            for index in range(12)
        ],
        *[
            (
                ("works", index, "translator_allocation", "credited_to"),
                "Invented translator",
            )
            for index in range(12)
        ],
        *[
            (
                ("works", index, "translator_allocation", "source_xml_id"),
                "invented-source",
            )
            for index in range(12)
        ],
        *[
            (
                ("works", index, "translator_allocation", "retained_scope_titles"),
                ["Invented retained scope"],
            )
            for index in range(12)
        ],
        (
            ("translation_credit", "retained_title_page_credits", 0, "name"),
            "Invented translator",
        ),
        (
            ("translation_credit", "retained_title_page_credits", 0, "role"),
            "editor",
        ),
        (
            (
                "translation_credit",
                "retained_title_page_credits",
                0,
                "name_source_xml_id",
            ),
            "invented-source",
        ),
        (
            (
                "translation_credit",
                "retained_title_page_credits",
                0,
                "role_source_xml_id",
            ),
            "invented-source",
        ),
        (
            ("translation_credit", "retained_title_page_credits", 1, "name"),
            "Invented translator",
        ),
        (
            ("translation_credit", "retained_title_page_credits", 1, "role"),
            "editor",
        ),
        (
            (
                "translation_credit",
                "retained_title_page_credits",
                1,
                "name_source_xml_id",
            ),
            "invented-source",
        ),
        (
            (
                "translation_credit",
                "retained_title_page_credits",
                1,
                "role_source_xml_id",
            ),
            "invented-source",
        ),
        (
            ("translation_credit", "retained_title_page_credits", 2, "name"),
            "Invented reviser",
        ),
        (
            ("translation_credit", "retained_title_page_credits", 2, "role"),
            "editor",
        ),
        (
            (
                "translation_credit",
                "retained_title_page_credits",
                2,
                "name_source_xml_id",
            ),
            "invented-source",
        ),
        (
            (
                "translation_credit",
                "retained_title_page_credits",
                2,
                "role_source_xml_ids",
            ),
            ["invented-source"],
        ),
        (("translation_credit", "work_specific_allocation"), "Invented allocation"),
        (
            (
                "translation_credit",
                "work_specific_allocation_evidence",
                "source_xml_id",
            ),
            "invented-source",
        ),
        (
            ("translation_credit", "work_specific_allocation_evidence", "text"),
            "Invented evidence",
        ),
        (("translation_credit", "schaff_translator_claim"), "Invented Schaff claim"),
        (("rights", "retained_statement"), "Copyrighted"),
        (("rights", "ccel_formatting_condition"), "Invented condition"),
        (("rights", "publication_state"), "ready"),
        (("canonical_data_written",), True),
    ],
)
@pytest.mark.requires_local_artifacts
def test_independent_oracle_rejects_every_provenance_semantic_field_mutation(
    verified_candidate: tuple[SourceManifest, CandidatePackage, Path],
    tmp_path: Path,
    path: tuple[str | int, ...],
    replacement: object,
) -> None:
    manifest, candidate, _ = verified_candidate
    target = tmp_path / ("provenance-" + "-".join(str(part) for part in path))
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("provenance.json", "manifest.json"),
    )
    member_path = target / "provenance.json"
    value = json.loads(member_path.read_text(encoding="utf-8"))
    _replace_nested(value, path, replacement)
    member_path.write_bytes(_canonical(value))
    mutated = _reseal(target, "provenance.json")
    with pytest.raises(ValueError, match="provenance semantic drift"):
        validate_candidate(manifest, mutated)


@pytest.mark.parametrize(
    ("record_index", "field", "replacement"),
    [
        (record_index, field, f"invented-{record_index}-{field}")
        for record_index in range(3)
        for field in ("id", "scope", "status", "question", "evidence")
    ]
    + [(0, "work_ids", ["invented-work"])],
)
@pytest.mark.requires_local_artifacts
def test_independent_oracle_rejects_every_unresolved_semantic_field_mutation(
    verified_candidate: tuple[SourceManifest, CandidatePackage, Path],
    tmp_path: Path,
    record_index: int,
    field: str,
    replacement: object,
) -> None:
    manifest, candidate, _ = verified_candidate
    target = tmp_path / f"unresolved-{record_index}-{field}"
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("unresolved.jsonl", "manifest.json"),
    )
    member_path = target / "unresolved.jsonl"
    value = [
        json.loads(line)
        for line in member_path.read_text(encoding="utf-8").splitlines()
    ]
    value[record_index][field] = replacement
    member_path.write_bytes(b"".join(_canonical(record) for record in value))
    mutated = _reseal(target, "unresolved.jsonl")
    with pytest.raises(ValueError, match="unresolved evidence drift"):
        validate_candidate(manifest, mutated)


@pytest.mark.parametrize("mutation", ["omission", "invention", "reorder"])
@pytest.mark.requires_local_artifacts
def test_independent_oracle_rejects_attribution_readme_drift(
    verified_candidate: tuple[SourceManifest, CandidatePackage, Path],
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest, candidate, _ = verified_candidate
    target = tmp_path / f"readme-attribution-{mutation}"
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("README.source.md", "manifest.json"),
    )
    member_path = target / "README.source.md"
    paragraphs = member_path.read_text(encoding="utf-8").split("\n\n")
    if mutation == "omission":
        paragraphs.pop(2)
    elif mutation == "invention":
        paragraphs.append("Invented attribution statement.\n")
    else:
        paragraphs[2], paragraphs[3] = paragraphs[3], paragraphs[2]
    member_path.write_text("\n\n".join(paragraphs), encoding="utf-8")
    mutated = _reseal(target, "README.source.md")
    with pytest.raises(ValueError, match="README attribution drift"):
        validate_candidate(manifest, mutated)


@pytest.mark.requires_local_artifacts
def test_source_local_attribution_readme_is_exact_and_manifest_bound() -> None:
    manifest = _manifest()
    authorities = manifest.record["authorities"]
    authority = next(
        item
        for item in authorities
        if item["name"] == "source-local-attribution-readme"
    )
    assert authority["role"] == "source-attribution-readme"
    assert authority["path"] == ("sources/structured-text/augustine-npnf105/README.md")
    readme = manifest.authority_path("source-local-attribution-readme").read_bytes()
    assert authority["bytes"] == len(readme)
    assert authority["sha256"] == hashlib.sha256(readme).hexdigest()
    text = readme.decode("utf-8")
    for retained_name in (
        "Philip Schaff",
        "Peter Holmes",
        "Robert Ernest Wallis",
        "Benjamin B. Warfield",
    ):
        assert retained_name in text
    assert "four works" in text
    assert "other eight assigned works" in text


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("assigned-comment-outside-scope", "comment accounting drift"),
        ("comment-ordinal", "comment accounting drift"),
        ("comment-scope", "comment accounting drift"),
        ("invented-attribute-destination", "crosswalk accountability drift"),
        ("tei-attributes", "crosswalk accountability drift"),
        ("tei-child-ordinal", "crosswalk accountability drift"),
        ("parent-feature-id", "crosswalk accountability drift"),
        ("assertion-destination", "crosswalk accountability drift"),
        ("assertion-subject", "crosswalk accountability drift"),
        ("work-id", "crosswalk accountability drift"),
    ],
)
@pytest.mark.requires_local_artifacts
def test_independent_oracle_rejects_schema_valid_accountability_mutations(
    verified_candidate: tuple[SourceManifest, CandidatePackage, Path],
    tmp_path: Path,
    mutation: str,
    expected_error: str,
) -> None:
    manifest, candidate, _ = verified_candidate
    target = tmp_path / mutation
    _clone_for_mutation(
        candidate,
        target,
        mutable_members=("source-accountability.json", "manifest.json"),
    )
    path = target / "source-accountability.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "assigned-comment-outside-scope":
        value["comment_accounting"][2]["assigned"] = False
        value["comment_accounting"][2]["disposition"] = "outside-assigned-work-scope"
    elif mutation == "comment-ordinal":
        value["comment_accounting"][2]["ordinal"] = 99
    elif mutation == "comment-scope":
        value["comment_accounting"][2]["scope"] = "x"
    elif mutation == "invented-attribute-destination":
        value["crosswalk"][0]["attribute_dispositions"][0]["destination"] = "@invented"
    elif mutation == "tei-attributes":
        value["crosswalk"][0]["tei_attributes"]["invented"] = "schema-valid-stale-value"
    elif mutation == "tei-child-ordinal":
        value["crosswalk"][0]["tei_child_ordinal"] += 1
    elif mutation == "parent-feature-id":
        value["crosswalk"][1]["parent_feature_id"] = None
    elif mutation == "assertion-destination":
        value["crosswalk"][0]["assertion"]["destination"] = "#npnf105-invented"
    elif mutation == "assertion-subject":
        value["crosswalk"][0]["assertion"]["subject"] = "npnf105-feature-99999"
    else:
        value["crosswalk"][0]["work_id"] = "augustine-spirit-and-letter"
    path.write_bytes(_canonical(value))
    mutated = _reseal(target, "source-accountability.json")
    with pytest.raises(ValueError, match=expected_error):
        validate_candidate(manifest, mutated)


@pytest.mark.requires_local_artifacts
def test_manifest_and_oracle_preserve_contract_boundaries() -> None:
    manifest = _manifest()
    assert manifest.record["source_id"] == "ccel-npnf105-retained-xml"
    oracle_source = (ROOT / "build/tei/npnf105_oracle.py").read_text(encoding="utf-8")
    for forbidden in (
        "from build.tei.npnf105_reconstruction",
        "import build.tei.npnf105_reconstruction",
        "from build.lib.ccel_thml",
        "from build.tei.thml_to_tei",
        "from build.tei.ccel_work_config",
    ):
        assert forbidden not in oracle_source
    with pytest.raises(ValueError, match="governed storage"):
        reconstruct_candidate(manifest, ROOT / "data/npnf105-candidate")


@pytest.mark.requires_local_artifacts
def test_six_member_review_package_is_nonaccepted(
    verified_candidate: tuple[SourceManifest, CandidatePackage, Path],
) -> None:
    _, candidate, _ = verified_candidate
    assert candidate.member_names == (
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )
    assert candidate.manifest["status"] == "nonaccepted"
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["rights"]["publication_state"] == "not_ready"
    assert (
        provenance["translation_credit"]["work_specific_allocation"]
        == "partially resolved from retained div1 ix"
    )


@pytest.mark.requires_local_artifacts
def test_metadata_refusal_precedes_schema_compilation(verified_candidate, tmp_path, monkeypatch):
    from build.tei import npnf105_oracle as oracle_module

    manifest, candidate, _ = verified_candidate
    target = tmp_path / "forged-metadata"
    _clone_for_mutation(candidate, target, mutable_members=("provenance.json", "manifest.json"))
    provenance = json.loads((target / "provenance.json").read_bytes())
    provenance["canonical_data_written"] = True
    (target / "provenance.json").write_bytes(_canonical(provenance))
    altered = _reseal(target, "provenance.json")

    def unnecessary_compile(*args, **kwargs):
        raise AssertionError("Incorrect metadata should be refused before compiling the schema")

    monkeypatch.setattr(oracle_module.etree, "XMLSchema", unnecessary_compile)
    monkeypatch.setattr(oracle_module, "_selector", unnecessary_compile)
    with pytest.raises(ValueError, match="provenance semantic drift"):
        validate_candidate(manifest, altered)


@pytest.mark.requires_local_artifacts
def test_valid_candidate_still_requires_complete_schema_validation(verified_candidate, monkeypatch):
    from types import SimpleNamespace
    from build.tei import npnf105_oracle as oracle_module

    manifest, candidate, _ = verified_candidate
    calls = []

    def refuse_complete_document(tree):
        assert etree.tostring(tree.getroot()) == etree.tostring(
            etree.fromstring(candidate.member_bytes("content.tei.xml"))
        )
        calls.append(True)
        return False

    def schema(_document):
        return SimpleNamespace(validate=refuse_complete_document,
                               error_log=SimpleNamespace(last_error="schema refusal probe"))

    monkeypatch.setattr(oracle_module.etree, "XMLSchema", schema)
    with pytest.raises(ValueError, match="TEI P5 XSD failure: schema refusal probe"):
        validate_candidate(manifest, candidate)
    assert calls == [True]


def test_shared_p5_schema_still_rejects_invalid_documents(p5_schema):
    invalid = etree.ElementTree(etree.fromstring(b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><invented/></TEI>'))
    assert not p5_schema.validate(invalid)
