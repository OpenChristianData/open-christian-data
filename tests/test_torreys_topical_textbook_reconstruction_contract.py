from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import shutil

import pytest
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/torreys_topical_textbook_oracle.source-manifest.json'
SOURCE_SHA256 = "8211c20290e951f60e21187e3bdaea639c8cf59343675b6518c6c17423906a1c"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mirror(tmp_path: Path) -> tuple[Path, object, object]:
    mirror = tmp_path / "external-mirror"
    for relative in [
        SOURCE_MANIFEST.relative_to(ROOT),
        Path("sources/torreys-topical-textbook"),
        Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"),
        Path("ocd_kernel/tei/vendor/xsd"),
        Path("build/__init__.py"), Path("build/tei/__init__.py"),
        Path("build/tei/torreys_topical_textbook_reconstruction.py"),
        Path("build/tei/torreys_topical_textbook_oracle.py"),
        Path("ocd_kernel/__init__.py"), Path("ocd_kernel/reconstruction/__init__.py"),
        Path("ocd_kernel/reconstruction/contract.py"),
        Path("ocd_kernel/lib/__init__.py"),
        Path("ocd_kernel/lib/path_io.py"),
        Path("ocd_kernel/lib/storage_topology.py"),
    ]:
        target = mirror / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.is_dir():
            shutil.copytree(ROOT / relative, target)
        else:
            shutil.copy2(ROOT / relative, target)
    (mirror / "raw/bible_dictionaries").mkdir(parents=True)
    shutil.copy2(Path("D:/Library/Open Christian Data/raw/bible_dictionaries/torreys.jsonl"), mirror / "raw/bible_dictionaries/torreys.jsonl")
    shutil.copy2(Path("D:/Library/Open Christian Data/raw/bible_dictionaries/manifest.json"), mirror / "raw/bible_dictionaries/manifest.json")
    producer = _load(mirror / "build/tei/torreys_topical_textbook_reconstruction.py", "torrey_mirror_producer")
    oracle = _load(mirror / "build/tei/torreys_topical_textbook_oracle.py", "torrey_mirror_oracle")
    return mirror, producer._convert, oracle._oracle


def test_torreys_public_contract_and_fresh_process_determinism(tmp_path: Path) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    source_manifest = mirror / SOURCE_MANIFEST.relative_to(ROOT)
    source = SourceManifest.load(source_manifest, repository_root=mirror)
    destination = tmp_path / "candidate"
    candidate = reconstruct(source, destination, convert)
    report = validate(source, candidate, oracle)

    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"
    assert candidate.manifest["source_id"] == "jwbickel-bible-dictionaries-torreys-jsonl"
    assert candidate.member_names == (
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    )
    assert _sha(source.authority_path("torreys-jsonl")) == SOURCE_SHA256

    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    assert len(root.xpath(".//tei:entry", namespaces=ns)) == 623
    assert len(root.xpath(".//tei:sense/tei:def", namespaces=ns)) == 23549
    assert root.xpath(".//tei:entry[1]/tei:form/tei:orth/text()", namespaces=ns)

    script = (
        "from pathlib import Path; "
        "import sys; sys.path.insert(0, __import__('sys').argv[2]); "
        "from build.tei.torreys_topical_textbook_reconstruction import _convert; "
        "from ocd_kernel.reconstruction import SourceManifest, reconstruct; "
        f"s=SourceManifest.load(Path(r'{SOURCE_MANIFEST.relative_to(ROOT)}'), repository_root=Path(__import__('sys').argv[2])); "
        "reconstruct(s, Path(__import__('sys').argv[1]), _convert)"
    )
    fresh = tmp_path / "fresh"
    subprocess.run([sys.executable, "-c", script, str(fresh), str(mirror)], check=True, cwd=mirror)
    for name in candidate.member_names:
        assert (destination / name).read_bytes() == (fresh / name).read_bytes(), name


def test_torreys_oracle_rejects_mutated_candidate_text(tmp_path: Path) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    source = SourceManifest.load(mirror / SOURCE_MANIFEST.relative_to(ROOT), repository_root=mirror)
    original = reconstruct(source, tmp_path / "original", convert)
    mutated_path = tmp_path / "mutated"
    shutil.copytree(original.path, mutated_path)
    content_path = mutated_path / "content.tei.xml"
    content_path.write_bytes(content_path.read_bytes().replace(b"Access to God", b"Access to Cod", 1))
    manifest_path = mutated_path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for member in manifest["members"]:
        if member["name"] == "content.tei.xml":
            member["bytes"] = content_path.stat().st_size
            member["sha256"] = _sha(content_path)
    manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    mutated = CandidatePackage.load(mutated_path)
    try:
        validate(source, mutated, oracle)
    except ValueError as exc:
        assert "term or definition" in str(exc) or "definition text" in str(exc)
    else:
        raise AssertionError("oracle accepted mutated TEI text")


def _reseal_member(destination: Path, name: str, content: bytes) -> CandidatePackage:
    member_path = destination / name
    member_path.write_bytes(content)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for member in manifest["members"]:
        if member["name"] == name:
            member["bytes"] = len(content)
            member["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return CandidatePackage.load(destination)


@pytest.mark.parametrize("mutation", ["title", "source-description", "provenance", "unresolved", "manifest"])
def test_torreys_oracle_rejects_metadata_and_boundary_mutations(tmp_path: Path, mutation: str) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    source = SourceManifest.load(mirror / SOURCE_MANIFEST.relative_to(ROOT), repository_root=mirror)
    original = reconstruct(source, tmp_path / "original", convert)
    mutated_path = tmp_path / f"mutated-{mutation}"
    shutil.copytree(original.path, mutated_path)
    if mutation == "title":
        content = (mutated_path / "content.tei.xml").read_bytes().replace(
            b"Torrey's New Topical Textbook", b"Torrey's Altered Topical Textbook", 1
        )
        mutated = _reseal_member(mutated_path, "content.tei.xml", content)
    elif mutation == "source-description":
        content = (mutated_path / "content.tei.xml").read_bytes().replace(
            b"JWBickel/BibleDictionaries retained TorreysTopicalTextbook.jsonl.",
            b"JWBickel/BibleDictionaries altered source description.",
            1,
        )
        mutated = _reseal_member(mutated_path, "content.tei.xml", content)
    elif mutation == "provenance":
        provenance_path = mutated_path / "provenance.json"
        provenance = json.loads(provenance_path.read_bytes())
        provenance["source_sha256"] = "0" * 64
        content = (json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        mutated = _reseal_member(mutated_path, "provenance.json", content)
    elif mutation == "unresolved":
        mutated = _reseal_member(mutated_path, "unresolved.jsonl", b"")
    else:
        manifest_path = mutated_path / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["unexpected"] = "metadata drift"
        manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
        mutated = CandidatePackage.load(mutated_path)
    with pytest.raises(ValueError):
        validate(source, mutated, oracle)


def test_torreys_oracle_parser_rejects_duplicate_source_keys(tmp_path: Path) -> None:
    mirror, _, oracle = _mirror(tmp_path)
    _ = mirror
    with pytest.raises(ValueError, match="duplicate key"):
        oracle.__globals__["_source_records"](b'{"term":"same","term":"different","definitions":["d"]}\n')


def test_torreys_rejects_sibling_scope_mutation(tmp_path: Path) -> None:
    mirror, convert, oracle = _mirror(tmp_path)
    manifest_path = mirror / SOURCE_MANIFEST.relative_to(ROOT)
    original_source = SourceManifest.load(manifest_path, repository_root=mirror)
    original = reconstruct(original_source, tmp_path / "original", convert)
    record = json.loads(manifest_path.read_bytes())
    record["source_order_members"][0]["disposition"] = "include"
    manifest_path.write_bytes((json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    mutated_source = SourceManifest.load(manifest_path, repository_root=mirror)
    # The current route can reject this drift at the manifest-binding guard
    # before the deeper scope guard; both are fail-closed outcomes for the
    # same mutation.
    with pytest.raises(ValueError, match="(?:scope|candidate source manifest binding mismatch)"):
        reconstruct(mutated_source, tmp_path / "mutated", convert)
    with pytest.raises(ValueError, match="(?:scope|candidate source manifest binding mismatch)"):
        validate(mutated_source, original, oracle)
