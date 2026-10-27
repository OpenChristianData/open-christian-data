"""Focused LIB-083 reconstruction, authority, and mutation tests."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

from lxml import etree
import pytest

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/schleitheim-confession-1527.source-manifest.json"
DURABLE_RAW = Path(r"D:/Library/Open Christian Data/raw/anabaptists.org/schleitheim-confession-1527.html")
MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}
TEI = {"t": "http://www.tei-c.org/ns/1.0", "xml": "http://www.w3.org/XML/1998/namespace"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_LOCAL_GOVERNED_TEXT = (
    MANIFEST,
    ROOT / "sources/doctrinal-documents/schleitheim-confession-1527/schleitheim-confession-1527.reconstruction-profile.json",
    ROOT / "sources/doctrinal-documents/schleitheim-confession-1527/schleitheim-confession-1527.validation-policy.json",
    ROOT / "sources/doctrinal-documents/schleitheim-confession-1527/README.md",
    ROOT / "sources/doctrinal-documents/schleitheim-confession-1527/schleitheim-confession-1527.source-accountability.schema.json",
    ROOT / "build/tei/schleitheim_confession_reconstruction.py",
    ROOT / "build/tei/schleitheim_confession_oracle.py",
    Path(__file__).resolve(),
)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_schleitheim_source_local_governed_text_materializes_as_canonical_lf() -> None:
    record = json.loads(MANIFEST.read_bytes())
    authorities = {item["name"]: item for item in record["authorities"]}

    for path in SOURCE_LOCAL_GOVERNED_TEXT:
        content = path.read_bytes()
        assert content.endswith(b"\n"), path
        assert b"\r" not in content, path

    for name in (
        "reconstruction-profile",
        "validation-policy",
        "source-attribution-readme",
        "source-accountability-schema",
    ):
        authority = authorities[name]
        content = ROOT.joinpath(authority["path"]).read_bytes()
        assert len(content) == authority["bytes"]
        assert _sha(content) == authority["sha256"]
    assert _sha(
        ROOT.joinpath(record["converter"]["implementation_path"]).read_bytes()
    ) == record["converter"]["implementation_sha256"]
    assert _sha(
        ROOT.joinpath(record["validator"]["implementation_path"]).read_bytes()
    ) == record["validator"]["implementation_sha256"]


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _copy_validation_mirror(mirror: Path) -> Path:
    if not DURABLE_RAW.is_file():
        pytest.fail(f"retained Schleitheim HTML is unavailable: {DURABLE_RAW}")
    source = ROOT / "sources/doctrinal-documents/schleitheim-confession-1527"
    shutil.copytree(source, mirror / "sources/doctrinal-documents/schleitheim-confession-1527")
    manifest = mirror / MANIFEST.relative_to(ROOT)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MANIFEST, manifest)
    raw_path = mirror / "raw/anabaptists.org/schleitheim-confession-1527.html"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DURABLE_RAW, raw_path)
    for relative in (
        "build/tei/schleitheim_confession_reconstruction.py",
        "build/tei/schleitheim_confession_oracle.py",
        "ocd_kernel/__init__.py",
        "ocd_kernel/lib/__init__.py",
        "ocd_kernel/lib/path_io.py",
        "ocd_kernel/lib/storage_topology.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    ):
        destination = mirror / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    shutil.copytree(ROOT / "ocd_kernel/tei/vendor/xsd", mirror / "ocd_kernel/tei/vendor/xsd")
    return mirror


@pytest.fixture(scope="module")
def validation_mirror(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _copy_validation_mirror(
        tmp_path_factory.mktemp("schleitheim-validation-mirror")
    )


@pytest.fixture(scope="module")
def schleitheim_manifest(validation_mirror: Path) -> SourceManifest:
    return SourceManifest.load(
        validation_mirror / MANIFEST.relative_to(ROOT), repository_root=validation_mirror
    )


@pytest.fixture(scope="module")
def schleitheim_route(validation_mirror: Path) -> ModuleType:
    return _load_module(
        validation_mirror / "build/tei/schleitheim_confession_reconstruction.py",
        "_schleitheim_route",
    )


@pytest.fixture(scope="module")
def schleitheim_oracle(validation_mirror: Path) -> ModuleType:
    return _load_module(
        validation_mirror / "build/tei/schleitheim_confession_oracle.py",
        "_schleitheim_oracle",
    )


@pytest.fixture(scope="module")
def schleitheim_candidate(
    tmp_path_factory: pytest.TempPathFactory,
    schleitheim_manifest: SourceManifest,
    schleitheim_route: ModuleType,
) -> CandidatePackage:
    return reconstruct(
        schleitheim_manifest,
        tmp_path_factory.mktemp("schleitheim") / "candidate",
        schleitheim_route._convert,
    )


def _copy(tmp_path: Path, candidate: CandidatePackage, label: str) -> Path:
    destination = tmp_path / label
    shutil.copytree(candidate.path, destination)
    return destination


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _tei_mutation(path: Path, mutate) -> CandidatePackage:
    tree = etree.fromstring((path / "content.tei.xml").read_bytes())
    mutate(tree)
    return _reseal(
        path,
        "content.tei.xml",
        etree.tostring(tree, encoding="utf-8", xml_declaration=True, pretty_print=False),
    )


def test_retained_source_manifest_is_exact_and_external_route_is_explicit(
    schleitheim_manifest: SourceManifest,
) -> None:
    schleitheim_manifest.verify()
    record = json.loads(schleitheim_manifest.path.read_bytes())
    assert record["ticket_id"] == "LIB-083"
    assert record["work_id"] == "schleitheim-confession-1527"
    assert record["external_library_root"] == "D:/Library/Open Christian Data"
    assert record["authorities"][0] == {
        "name": "retained-html",
        "path": "raw/anabaptists.org/schleitheim-confession-1527.html",
        "role": "primary-source",
        "bytes": 21064,
        "sha256": "5a7f3b112e2bd074c9eb8626fd58d13086870ebb0be52a3036781ce9077f3750",
    }


def test_complete_candidate_passes_independent_oracle_and_is_nonaccepted(
    schleitheim_manifest: SourceManifest,
    schleitheim_candidate: CandidatePackage,
    schleitheim_oracle: ModuleType,
) -> None:
    assert {item["name"] for item in schleitheim_candidate.manifest["members"]} | {"manifest.json"} == MEMBERS
    assert schleitheim_candidate.manifest["status"] == "nonaccepted"
    report = validate(schleitheim_manifest, schleitheim_candidate, schleitheim_oracle._oracle)
    assert report.status == "pass"
    assert report.findings == ()
    assert report.candidate_sha256 == schleitheim_candidate.sha256
    assert report.attestation["oracle_id"] == "ocd-schleitheim-confession-independent-oracle"


def test_source_accountability_and_tei_shape_are_exact(
    schleitheim_manifest: SourceManifest,
    schleitheim_candidate: CandidatePackage,
) -> None:
    accountability = json.loads(schleitheim_candidate.member_bytes("source-accountability.json"))
    assert accountability["source_bytes"] == 21064
    assert accountability["source_sha256"] == "5a7f3b112e2bd074c9eb8626fd58d13086870ebb0be52a3036781ce9077f3750"
    assert accountability["article_count"] == 7
    assert accountability["paragraph_count"] == 24
    assert accountability["article_word_count"] == 2341
    assert accountability["closing_imprint"]["word_count"] == 11
    assert accountability["work_word_count"] == 2352
    assert accountability["omitted_count"] == 0
    assert accountability["duplicate_count"] == 0
    assert accountability["unresolved_count"] == 3
    assert [item["number"] for item in accountability["articles"]] == ["I", "II", "III", "IV", "V", "VI", "VII"]
    assert [item["paragraph_count"] for item in accountability["articles"]] == [1, 1, 2, 5, 3, 7, 5]

    tei = etree.fromstring(schleitheim_candidate.member_bytes("content.tei.xml"))
    xsd = compiled_tei_schema(schleitheim_manifest.authority_path("tei-p5-xsd"))
    assert xsd.validate(tei), xsd.error_log
    assert tei.get(XML_ID) == "schleitheim-confession-1527-candidate"
    articles = tei.xpath("/t:TEI/t:text/t:body/t:div[@type='article']", namespaces=TEI)
    assert len(articles) == 7
    assert [item.get("n") for item in articles] == ["I", "II", "III", "IV", "V", "VI", "VII"]
    assert len(
        tei.xpath(
            "/t:TEI/t:text/t:body/t:div[@type='article']/t:p", namespaces=TEI
        )
    ) == 24


def test_complete_outer_boundary_preface_contents_closer_and_dispositions_are_explicit(
    schleitheim_candidate: CandidatePackage,
) -> None:
    accountability = json.loads(
        schleitheim_candidate.member_bytes("source-accountability.json")
    )
    segments = accountability["source_segments"]
    assert segments == [
        {
            "id": "page-prefix",
            "bytes": 902,
            "sha256": "4278e1d0f6d60fb986d707ca477ef20d8eb53db32bc6d7a57dd819c74d5f3a5f",
            "disposition": "excluded-site-container",
        },
        {
            "id": "work-preface",
            "bytes": 619,
            "sha256": "b9fd5bf18eab7452ab4364e8bf4a8cbdcb73a19e81024469820f9682de08d5cb",
            "disposition": "represented",
        },
        {
            "id": "articles-and-closing-imprint",
            "bytes": 13471,
            "sha256": "143e575a1d462db4d3ea29f061ec9f9a25eb33bfe96528348488ab3ef27fc658",
            "disposition": "represented",
        },
        {
            "id": "post-terminal-wrapper",
            "bytes": 146,
            "sha256": "604c98e5267c8178ec5c98f90130ed88b24570374046af356af0ed371241621e",
            "disposition": "accounted-source-context",
        },
        {
            "id": "page-suffix",
            "bytes": 5926,
            "sha256": "302c936ca49352c379c26f080312cd01cd7a3550c2783f6c698814a1ed9c1946",
            "disposition": "excluded-site-chrome",
        },
    ]
    assert sum(item["bytes"] for item in segments) == 21064

    tei = etree.fromstring(schleitheim_candidate.member_bytes("content.tei.xml"))
    preface = tei.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='preface']", namespaces=TEI
    )
    assert len(preface) == 1
    assert preface[0].get(XML_ID) == "schleitheim-preface"
    assert preface[0].xpath("string(./t:head)", namespaces=TEI) == (
        "The Schleitheim Confession"
    )
    assert " ".join(
        preface[0].xpath("string(./t:p[@rend='imprint'])", namespaces=TEI).split()
    ) == (
        "printed by Rod and Staff Publishers, Inc., Crockett, KY "
        "Sixth Printing, 1985"
    )
    assert " ".join(
        preface[0].xpath("string(./t:p[@rend='adoption'])", namespaces=TEI).split()
    ) == (
        "Adopted by a Swiss Brethren Conference, February 24, 1527 "
        "Brotherly Union of a Number of Children of God concerning Seven Articles"
    )
    assert preface[0].xpath(
        "string(./t:p[@rend='introduction'])", namespaces=TEI
    ) == "The articles which we discussed and on which we were of one mind are these:"
    contents = preface[0].xpath("./t:list[@type='contents']/t:item", namespaces=TEI)
    assert [item.get("n") for item in contents] == [
        "I",
        "II",
        "III",
        "IV",
        "V",
        "VI",
        "VII",
    ]
    assert [item.text for item in contents] == [
        "Baptism;",
        "The Ban (Excommunication);",
        "Breaking of Bread;",
        "Separation from the Abomination;",
        "Pastors in the Church;",
        "The Sword;",
        "The Oath.",
    ]

    closer = tei.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='closing-imprint']", namespaces=TEI
    )
    assert len(closer) == 1
    assert closer[0].get(XML_ID) == "schleitheim-closing-imprint"
    assert " ".join(closer[0].xpath("string(./t:p)", namespaces=TEI).split()) == (
        "The Seven Articles of Schleitheim Canton Schaffhausen, Switzerland, "
        "February 24, 1527"
    )
    assert len(closer[0].xpath("./t:p/t:lb", namespaces=TEI)) == 2


def test_candidate_is_byte_identical_in_process_and_fresh_process(
    tmp_path: Path,
    schleitheim_manifest: SourceManifest,
    schleitheim_candidate: CandidatePackage,
    schleitheim_route: ModuleType,
    validation_mirror: Path,
) -> None:
    again = reconstruct(schleitheim_manifest, tmp_path / "again", schleitheim_route._convert)
    assert again.sha256 == schleitheim_candidate.sha256
    destination = tmp_path / "fresh"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "build/tools/reconstruct_candidate.py"),
            "--manifest",
            MANIFEST.relative_to(ROOT).as_posix(),
            "--destination",
            str(destination),
            "--repository-root",
            str(validation_mirror),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout)["candidate"]["sha256"] == schleitheim_candidate.sha256


def test_oracle_is_independent_from_schleitheim_producer() -> None:
    oracle_text = (ROOT / "build/tei/schleitheim_confession_oracle.py").read_text(encoding="utf-8")
    assert "schleitheim_confession_reconstruction" not in oracle_text


def _remove_last_article(root: etree._Element) -> None:
    article = root.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='article'][last()]", namespaces=TEI
    )[0]
    article.getparent().remove(article)


def _duplicate_first_article(root: etree._Element) -> None:
    body = root.find(f"{{{TEI['t']}}}text/{{{TEI['t']}}}body")
    assert body is not None
    article = root.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='article'][1]", namespaces=TEI
    )[0]
    duplicate = copy.deepcopy(article)
    for node in [duplicate, *duplicate.xpath(".//*[@xml:id]", namespaces=TEI)]:
        node.set(XML_ID, (node.get(XML_ID) or "duplicate") + "-copy")
    body.append(duplicate)


def _reorder_articles(root: etree._Element) -> None:
    body = root.find(f"{{{TEI['t']}}}text/{{{TEI['t']}}}body")
    assert body is not None
    first, second = root.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='article'][position() <= 2]",
        namespaces=TEI,
    )
    insertion = body.index(first)
    body.remove(first)
    body.remove(second)
    body.insert(insertion, second)
    body.insert(insertion + 1, first)


def _remove_preface(root: etree._Element) -> None:
    preface = root.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='preface']", namespaces=TEI
    )[0]
    preface.getparent().remove(preface)


def _remove_contents_item(root: etree._Element) -> None:
    item = root.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='preface']/t:list[@type='contents']/t:item[1]",
        namespaces=TEI,
    )[0]
    item.getparent().remove(item)


def _remove_closing_imprint(root: etree._Element) -> None:
    closer = root.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='closing-imprint']", namespaces=TEI
    )[0]
    closer.getparent().remove(closer)


def _invent_text(root: etree._Element) -> None:
    paragraph = root.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='article']/t:p", namespaces=TEI
    )[0]
    assert paragraph.text is not None
    paragraph.text += " INVENTED"


def _invent_attribute(root: etree._Element) -> None:
    article = root.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='article']", namespaces=TEI
    )[0]
    article.set("subtype", "invented-article-type")


def _drift_metadata(root: etree._Element) -> None:
    title = root.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=TEI)[0]
    title.text = "Invented Schleitheim title"


def _drift_evidence(candidate_dir: Path) -> None:
    path = candidate_dir / "source-accountability.json"
    record = json.loads(path.read_bytes())
    record["articles"][0]["title"] += " invented"
    path.write_bytes(_canonical(record))


def _drift_outer_segment_disposition(candidate_dir: Path) -> None:
    path = candidate_dir / "source-accountability.json"
    record = json.loads(path.read_bytes())
    record["source_segments"][3]["disposition"] = "excluded-site-chrome"
    path.write_bytes(_canonical(record))


def _drift_provenance(candidate_dir: Path) -> None:
    path = candidate_dir / "provenance.json"
    record = json.loads(path.read_bytes())
    record["status"] = "accepted"
    path.write_bytes(_canonical(record))


def _drift_unresolved(candidate_dir: Path) -> None:
    (candidate_dir / "unresolved.jsonl").write_bytes(b"{}\n")


@pytest.mark.parametrize(
    "mutate",
    [
        _remove_last_article,
        _duplicate_first_article,
        _reorder_articles,
        _remove_preface,
        _remove_contents_item,
        _remove_closing_imprint,
        _invent_text,
        _invent_attribute,
        _drift_metadata,
        _drift_evidence,
        _drift_outer_segment_disposition,
        _drift_provenance,
        _drift_unresolved,
    ],
)
def test_oracle_rejects_required_mutations(
    tmp_path: Path,
    schleitheim_manifest: SourceManifest,
    schleitheim_candidate: CandidatePackage,
    schleitheim_oracle: ModuleType,
    mutate,
) -> None:
    path = _copy(tmp_path, schleitheim_candidate, mutate.__name__)
    if mutate in {
        _drift_evidence,
        _drift_outer_segment_disposition,
        _drift_provenance,
        _drift_unresolved,
    }:
        mutate(path)
        if mutate in {_drift_evidence, _drift_outer_segment_disposition}:
            mutated = _reseal(path, "source-accountability.json", (path / "source-accountability.json").read_bytes())
        elif mutate is _drift_provenance:
            mutated = _reseal(path, "provenance.json", (path / "provenance.json").read_bytes())
        else:
            mutated = _reseal(path, "unresolved.jsonl", (path / "unresolved.jsonl").read_bytes())
    else:
        mutated = _tei_mutation(path, mutate)
    with pytest.raises(ValueError):
        validate(schleitheim_manifest, mutated, schleitheim_oracle._oracle)


def test_stale_retained_source_hash_is_rejected(
    tmp_path: Path,
) -> None:
    stale_mirror = _copy_validation_mirror(tmp_path / "s")
    source = stale_mirror / "raw/anabaptists.org/schleitheim-confession-1527.html"
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="authority bytes drifted"):
        SourceManifest.load(
            stale_mirror / MANIFEST.relative_to(ROOT), repository_root=stale_mirror
        )
