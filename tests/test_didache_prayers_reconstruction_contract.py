"""Focused LIB-066 source-bound reconstruction and oracle contract tests."""

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
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/didache_prayers_oracle.source-manifest.json'
DURABLE_RAW = Path(r"D:/Library/Open Christian Data/raw/wikisource/didache.json")
SOURCE_SHA256 = "9ba0420fc2f1ef3d960335c100e31f8edbe7343b7fc5eab66dcce075744db764"
MEMBERS = {"manifest.json", "content.tei.xml", "source-accountability.json", "provenance.json", "unresolved.jsonl", "README.source.md"}
TEI = {"t": "http://www.tei-c.org/ns/1.0", "xml": "http://www.w3.org/XML/1998/namespace"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_LOCAL_GOVERNED_TEXT = (
    MANIFEST,
    ROOT / "sources/didache-prayers/didache-prayers.reconstruction-profile.json",
    ROOT / "sources/didache-prayers/didache-prayers.validation-policy.json",
    ROOT / "sources/didache-prayers/README.source.md",
    ROOT / "sources/didache-prayers/didache-prayers.source-accountability.schema.json",
    ROOT / "build/tei/didache_prayers_reconstruction.py",
    ROOT / "build/tei/didache_prayers_oracle.py",
    Path(__file__).resolve(),
)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_didache_source_local_governed_text_materializes_as_canonical_lf() -> None:
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
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def validation_mirror(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not DURABLE_RAW.is_file():
        pytest.fail(f"retained Didache JSON is unavailable: {DURABLE_RAW}")
    mirror = tmp_path_factory.mktemp("didache-prayers-mirror")
    shutil.copytree(ROOT / "sources/didache-prayers", mirror / "sources/didache-prayers")
    raw = mirror / "raw/wikisource/didache.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DURABLE_RAW, raw)
    for relative in (MANIFEST.relative_to(ROOT).as_posix(), "ocd_kernel/lib/__init__.py", "ocd_kernel/lib/path_io.py", "ocd_kernel/lib/storage_topology.py", "build/tei/didache_prayers_reconstruction.py", "build/tei/didache_prayers_oracle.py", "ocd_kernel/__init__.py", "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/__init__.py", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"):
        destination = mirror / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    shutil.copytree(ROOT / "ocd_kernel/tei/vendor/xsd", mirror / "ocd_kernel/tei/vendor/xsd")
    return mirror


@pytest.fixture(scope="module")
def manifest(validation_mirror: Path) -> SourceManifest:
    return SourceManifest.load(validation_mirror / MANIFEST.relative_to(ROOT), repository_root=validation_mirror)


@pytest.fixture(scope="module")
def route(validation_mirror: Path) -> ModuleType:
    return _load_module(validation_mirror / "build/tei/didache_prayers_reconstruction.py", "_didache_prayers_route")


@pytest.fixture(scope="module")
def oracle(validation_mirror: Path) -> ModuleType:
    return _load_module(validation_mirror / "build/tei/didache_prayers_oracle.py", "_didache_prayers_oracle")


@pytest.fixture(scope="module")
def candidate(tmp_path_factory: pytest.TempPathFactory, manifest: SourceManifest, route: ModuleType) -> CandidatePackage:
    return reconstruct(manifest, tmp_path_factory.mktemp("didache-prayers") / "candidate", route._convert)


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
    return _reseal(path, "content.tei.xml", etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False))


def test_manifest_binds_exact_retained_witness_and_single_work(manifest: SourceManifest) -> None:
    manifest.verify()
    record = json.loads(MANIFEST.read_bytes())
    assert record["ticket_id"] == "LIB-066"
    assert record["work_id"] == "didache-prayers"
    assert record["source_id"] == "wikisource-didache-lake-retained"
    authority = next(item for item in record["authorities"] if item["name"] == "retained-json")
    assert authority["bytes"] == 23668
    assert authority["sha256"] == SOURCE_SHA256


def test_candidate_passes_independent_oracle_and_preserves_structure(manifest: SourceManifest, candidate: CandidatePackage, oracle: ModuleType) -> None:
    assert {item["name"] for item in candidate.manifest["members"]} | {"manifest.json"} == MEMBERS
    report = validate(manifest, candidate, oracle._oracle)
    assert report.status == "pass"
    assert report.findings == ()
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["source_bytes"] == 23668
    assert accountability["source_sha256"] == SOURCE_SHA256
    assert accountability["chapter_count"] == 16
    assert accountability["row_count"] == 30
    assert accountability["verse_count"] == 100
    assert accountability["footnote_count"] == 10
    assert accountability["omitted_count"] == accountability["duplicate_count"] == 0
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert compiled_tei_schema(manifest.authority_path("tei-p5-xsd")).validate(tei)
    assert len(tei.xpath("/t:TEI/t:text/t:body/t:div[@type='chapter']", namespaces=TEI)) == 16
    assert len(tei.xpath("//t:div[@type='row']", namespaces=TEI)) == 30
    assert len(tei.xpath("//t:ab[@type='verse']", namespaces=TEI)) == 100
    assert len(tei.xpath("//t:note[@type='footnote']", namespaces=TEI)) == 10


def test_mid_verse_footnote_is_preserved_in_source_position(candidate: CandidatePackage) -> None:
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    verse = tei.xpath("//t:ab[@type='verse' and @n='2.7']", namespaces=TEI)
    assert len(verse) == 1
    node = verse[0]
    assert node.text == "Thou shalt hate no man; but some thou shalt reprove,"
    assert len(node) == 1
    assert node[0].get("type") == "footnote"
    assert node[0].tail == " and for some shalt thou pray, and some thou shalt love more than thine own life."


def test_candidate_is_byte_deterministic_in_process_and_fresh_process(tmp_path: Path, manifest: SourceManifest, route: ModuleType, candidate: CandidatePackage, validation_mirror: Path) -> None:
    again = reconstruct(manifest, tmp_path / "again", route._convert)
    assert again.sha256 == candidate.sha256
    fresh = tmp_path / "fresh"
    result = subprocess.run([sys.executable, str(ROOT / "build/tools/reconstruct_candidate.py"), "--manifest", MANIFEST.relative_to(ROOT).as_posix(), "--destination", str(fresh), "--repository-root", str(validation_mirror)], cwd=ROOT, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["candidate"]["sha256"] == candidate.sha256


def test_oracle_does_not_import_producer() -> None:
    assert "didache_prayers_reconstruction" not in (ROOT / "build/tei/didache_prayers_oracle.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "reorder", "invent", "metadata"])
def test_oracle_rejects_content_and_metadata_mutations(tmp_path: Path, manifest: SourceManifest, candidate: CandidatePackage, oracle: ModuleType, mutation: str) -> None:
    path = _copy(tmp_path, candidate, mutation)
    def mutate(root: etree._Element) -> None:
        rows = root.xpath("//t:div[@type='row']", namespaces=TEI)
        if mutation == "omit":
            rows[0].getparent().remove(rows[0])
        elif mutation == "duplicate":
            rows[0].getparent().append(copy.deepcopy(rows[0]))
        elif mutation == "reorder":
            parent = rows[0].getparent(); first, second = rows[0], rows[1]; parent.remove(first); parent.remove(second); parent.insert(0, second); parent.insert(1, first)
        elif mutation == "invent":
            root.xpath("//t:ab[@type='verse']", namespaces=TEI)[0].text = "INVENTED"
        else:
            root.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=TEI)[0].text = "Invented"
    mutated = _tei_mutation(path, mutate)
    with pytest.raises(ValueError):
        validate(manifest, mutated, oracle._oracle)


def test_oracle_rejects_accountability_provenance_and_unresolved_mutations(tmp_path: Path, manifest: SourceManifest, candidate: CandidatePackage, oracle: ModuleType) -> None:
    for name, change in (("source-accountability.json", {"verse_count": 99}), ("provenance.json", {"status": "accepted"}), ("unresolved.jsonl", None)):
        path = _copy(tmp_path, candidate, name.replace(".", "-"))
        target = path / name
        if change is None:
            target.write_bytes(b"{}\n")
        else:
            record = json.loads(target.read_bytes()); record.update(change); target.write_bytes(_canonical(record))
        mutated = _reseal(path, name, target.read_bytes())
        with pytest.raises(ValueError):
            validate(manifest, mutated, oracle._oracle)
