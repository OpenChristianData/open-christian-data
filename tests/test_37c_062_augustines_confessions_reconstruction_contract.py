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
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/augustines-confessions.source-manifest.json"
SOURCE_SHA256 = "5a036498dc7c546a98b9e7a31952e030ca74db7dd111b30029354efe12bcd691"
TEI = {"t": "http://www.tei-c.org/ns/1.0", "xml": "http://www.w3.org/XML/1998/namespace"}


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="module")
def producer() -> ModuleType:
    return _load(ROOT / "build/tei/augustines_confessions_reconstruction.py", "_confessions_producer_test")


@pytest.fixture(scope="module")
def oracle() -> ModuleType:
    return _load(ROOT / "build/tei/augustines_confessions_oracle.py", "_confessions_oracle_test")


@pytest.fixture(scope="module")
def candidate(tmp_path_factory: pytest.TempPathFactory, manifest: SourceManifest, producer: ModuleType) -> CandidatePackage:
    return reconstruct(manifest, tmp_path_factory.mktemp("c062") / "candidate", producer._convert)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    package_manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in package_manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    (path / "manifest.json").write_bytes(_canonical(package_manifest))
    return CandidatePackage.load(path)


def test_source_manifest_pins_exact_retained_witness_and_work(manifest: SourceManifest) -> None:
    manifest.verify()
    source = manifest.authority_path("retained-text").read_bytes()
    assert len(source) == 632167
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256
    assert manifest.record["work_id"] == "augustines-confessions"
    assert manifest.record["ticket_id"] == "LIB-077"


def test_candidate_accounts_whole_source_and_ordered_books(manifest: SourceManifest, candidate: CandidatePackage, oracle: ModuleType) -> None:
    report = validate(manifest, candidate, oracle._oracle)
    assert report.status == "pass"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["source_bytes"] == 632167
    assert accountability["source_sha256"] == SOURCE_SHA256
    assert accountability["physical_line_count"] == 9724
    assert accountability["book_order"] == ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII"]
    assert len(accountability["line_inventory"]) == 9724
    assert accountability["omitted_count"] == accountability["duplicate_count"] == 0
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    xsd = compiled_tei_schema(manifest.authority_path("tei-p5-xsd"))
    assert xsd.validate(tei), str(xsd.error_log)
    assert len(tei.xpath("//t:div[@type='book']", namespaces=TEI)) == 13
    assert tei.xpath("//t:div[@subtype='project-gutenberg-license']/t:p", namespaces=TEI)
    assert "not-authorized" == json.loads(candidate.member_bytes("provenance.json"))["publication_status"]


def test_candidate_preserves_centered_terminal_doxology(candidate: CandidatePackage) -> None:
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    target = tei.xpath("//t:p[@xml:id='confessions-book-XIII-p-0053']", namespaces=TEI)
    assert len(target) == 1
    assert target[0].text == "GRATIAS TIBI DOMINE"
    assert target[0].get("rend") == "align-center"


@pytest.mark.parametrize("mutation", ["remove-book", "change-paragraph", "change-terminal-alignment", "change-accounting"])
def test_independent_oracle_rejects_resealed_mutations(tmp_path: Path, manifest: SourceManifest, candidate: CandidatePackage, oracle: ModuleType, mutation: str) -> None:
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    if mutation == "change-accounting":
        account = json.loads((target / "source-accountability.json").read_bytes())
        account["book_order"].reverse()
        changed = _reseal(target, "source-accountability.json", _canonical(account))
    else:
        tree = etree.fromstring((target / "content.tei.xml").read_bytes())
        if mutation == "remove-book":
            tree.xpath("//t:div[@type='book']", namespaces=TEI)[0].getparent().remove(tree.xpath("//t:div[@type='book']", namespaces=TEI)[0])
        elif mutation == "change-paragraph":
            tree.xpath("//t:div[@type='book']/t:p", namespaces=TEI)[0].text = "invented text"
        elif mutation == "change-terminal-alignment":
            target_node = tree.xpath("//t:p[@xml:id='confessions-book-XIII-p-0053']", namespaces=TEI)
            assert len(target_node) == 1
            target_node[0].attrib.pop("rend", None)
        else:
            raise AssertionError(f"unknown mutation: {mutation}")
        changed = _reseal(target, "content.tei.xml", etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    with pytest.raises(ValueError):
        validate(manifest, changed, oracle._oracle)


def test_candidate_reproduces_byte_identically_in_fresh_process(tmp_path: Path, manifest: SourceManifest, producer: ModuleType, candidate: CandidatePackage) -> None:
    again = reconstruct(manifest, tmp_path / "again", producer._convert)
    assert again.sha256 == candidate.sha256
    fresh = tmp_path / "fresh-process-candidate"
    result = subprocess.run([sys.executable, "build/tools/reconstruct_candidate.py", "--manifest", MANIFEST.relative_to(ROOT).as_posix(), "--destination", str(fresh), "--repository-root", str(ROOT)], cwd=ROOT, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["candidate"]["sha256"] == candidate.sha256


def test_oracle_is_independent_of_work_producer() -> None:
    code = (ROOT / "build/tei/augustines_confessions_oracle.py").read_text(encoding="utf-8")
    assert "augustines_confessions_reconstruction" not in code
