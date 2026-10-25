from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.marrant_prince_hall_african_lodge_sermon_oracle import (
    _closure_digest,
    _closure_paths,
    _oracle,
)
from build.tei.marrant_prince_hall_african_lodge_sermon_reconstruction import (
    _convert,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(
    r"D:\Library\Open Christian Data\raw\clean-ready-acquisition-to-tei\master-2\15"
    r"\marrant-prince-hall-african-lodge-sermon\N17016.xml"
)
MANIFEST = (
    ROOT / "tests/fixtures/reconstruction-runtime/marrant-prince-hall-african-lodge-sermon.source-manifest.json"
)
SOURCE_SHA256 = "cec45792f758853c291b79aaba32f79bb12360e1247e9d3e0e9271fa3b577434"
TEI = {"tei": "http://www.tei-c.org/ns/1.0"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _clone_candidate(candidate: CandidatePackage, target: Path) -> Path:
    target.mkdir()
    for name in candidate.member_names:
        (target / name).write_bytes(candidate.member_bytes(name))
    return target


def _reseal_member(path: Path, member_name: str, content: bytes) -> CandidatePackage:
    (path / member_name).write_bytes(content)
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _assert_oracle_rejects(source: SourceManifest, candidate: CandidatePackage) -> None:
    with pytest.raises(ValueError, match="^candidate validation failed$"):
        validate(source, candidate, _oracle)


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(
        source, tmp_path_factory.mktemp("marrant-candidate") / "package", _convert
    )
    report = validate(source, candidate, _oracle)
    assert report.status == "pass"
    return source, candidate, report


def test_exact_retained_source_identity_and_complete_census() -> None:
    content = SOURCE.read_bytes()
    tree = etree.fromstring(
        content,
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    elements = list(tree.iter())

    assert len(content) == 48_484
    assert _sha(content) == SOURCE_SHA256
    assert tree.xpath(
        "string(/tei:TEI/tei:teiHeader//tei:idno[@type='TCP'])", namespaces=TEI
    ) == "N17016"
    assert tree.xpath(
        "string(/tei:TEI/tei:teiHeader//tei:titleStmt/tei:author)", namespaces=TEI
    ) == "Marrant, John, 1755-1791."
    assert "sermon preached on the 24th day of June 1789" in tree.xpath(
        "string(/tei:TEI/tei:teiHeader//tei:titleStmt/tei:title)", namespaces=TEI
    )
    assert len(elements) == 256
    assert sum(len(element.attrib) for element in elements) == 189
    assert sum(element.text is not None for element in elements) == 144
    assert sum(element.tail is not None for element in elements) == 255
    assert sum(
        len((element.text or "") + (element.tail or "")) for element in elements
    ) == 40_645


def test_candidate_is_byte_exact_nonaccepted_and_fully_accounted(
    verified_candidate,
) -> None:
    _, candidate, report = verified_candidate
    source_bytes = SOURCE.read_bytes()
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))

    assert candidate.manifest["status"] == "nonaccepted"
    assert candidate.member_bytes("content.tei.xml") == source_bytes
    assert accountability["source_content_bytes"] == 48_484
    assert accountability["candidate_content_bytes"] == 48_484
    assert accountability["source_content_sha256"] == SOURCE_SHA256
    assert accountability["candidate_content_sha256"] == SOURCE_SHA256
    assert accountability["omitted_elements"] == 0
    assert accountability["duplicated_elements"] == 0
    assert accountability["unresolved_elements"] == 0
    assert {
        name: accountability["element_counts"][name]
        for name in ("TEI", "div", "epigraph", "g", "gap", "note", "pb", "q")
    } == {"TEI": 1, "div": 2, "epigraph": 1, "g": 94, "gap": 9, "note": 5, "pb": 24, "q": 2}
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]
    assert [row["status"] for row in unresolved] == ["unresolved"] * 4
    assert report.findings == ()


def test_oracle_rejects_resealed_text_mutation(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / "mutated-text")
    content = candidate.member_bytes("content.tei.xml")
    assert b"A SERMON." in content
    resealed = _reseal_member(
        target, "content.tei.xml", content.replace(b"A SERMON.", b"A SERM0N.", 1)
    )
    _assert_oracle_rejects(source, resealed)


@pytest.mark.parametrize("mutation", ["omit", "alter", "extra"])
def test_oracle_rejects_unresolved_ledger_mutations(
    verified_candidate, tmp_path: Path, mutation: str
) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / f"unresolved-{mutation}")
    rows = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
    if mutation == "omit":
        rows.pop(1)
    elif mutation == "alter":
        rows[1]["status"] = "resolved"
    else:
        rows.append(dict(rows[0]))
    resealed = _reseal_member(
        target, "unresolved.jsonl", b"".join(_canonical(row) for row in rows)
    )
    _assert_oracle_rejects(source, resealed)


@pytest.mark.parametrize(
    ("member_name", "old", "new"),
    [
        ("provenance.json", b'"date":"1789"', b'"date":"1788"'),
        ("source-accountability.json", b'"omitted_elements":0', b'"omitted_elements":1'),
        ("README.source.md", b"N17016", b"N1701X"),
    ],
)
def test_oracle_rejects_nontext_member_mutations(
    verified_candidate, tmp_path: Path, member_name: str, old: bytes, new: bytes
) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / member_name.replace(".", "-"))
    content = candidate.member_bytes(member_name)
    assert old in content
    resealed = _reseal_member(target, member_name, content.replace(old, new, 1))
    _assert_oracle_rejects(source, resealed)


@pytest.mark.parametrize(
    ("field_path", "replacement"),
    [
        (("status",), "accepted"),
        (("source_id",), "wrong-source"),
        (("source_manifest", "sha256"), "0" * 64),
        (("source_manifest", "path"), "sources/structured-text/marrant-prince-hall-african-lodge-sermon/marrant-prince-hall-african-lodge-sermon.source-manifest.json"),
        (("converter", "version"), "wrong-version"),
        (("package_schema", "sha256"), "0" * 64),
    ],
)
def test_oracle_rejects_candidate_manifest_binding_mutations(
    verified_candidate, tmp_path: Path, field_path: tuple[str, ...], replacement: str
) -> None:
    source, candidate, _ = verified_candidate
    target = _clone_candidate(candidate, tmp_path / ("manifest-" + "-".join(field_path)))
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    owner = manifest
    for key in field_path[:-1]:
        owner = owner[key]
    owner[field_path[-1]] = replacement
    manifest_path.write_bytes(_canonical(manifest))
    mutated = CandidatePackage.load(target)
    if field_path in {
        ("source_id",),
        ("source_manifest", "sha256"),
        ("source_manifest", "path"),
    }:
        # Shared source binding is checked before the work-specific oracle.
        with pytest.raises(
            ValueError, match="^candidate source manifest binding mismatch$"
        ):
            validate(source, mutated, _oracle)
    else:
        _assert_oracle_rejects(source, mutated)


def test_oracle_import_closure_is_complete_and_manifest_bound() -> None:
    expected = {
        ROOT / "build/tei/marrant_prince_hall_african_lodge_sermon_oracle.py",
        ROOT / "ocd_kernel/__init__.py",
        ROOT / "ocd_kernel/reconstruction/__init__.py",
        ROOT / "ocd_kernel/reconstruction/contract.py",
    }
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    assert set(_closure_paths()) == expected
    assert source.record["validator"]["import_closure_sha256"] == _closure_digest()


def test_candidate_is_tei_p5_valid_and_keeps_source_structure(verified_candidate) -> None:
    _, candidate, _ = verified_candidate
    tree = etree.fromstring(
        candidate.member_bytes("content.tei.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    schema = etree.XMLSchema(etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")))
    assert schema.validate(tree), str(schema.error_log)
    assert tree.xpath("//tei:div/@type", namespaces=TEI) == ["title_page", "sermon"]
    assert len(tree.xpath("//tei:pb", namespaces=TEI)) == 24
    assert len(tree.xpath("//tei:g[@ref='char:EOLhyphen']", namespaces=TEI)) == 86
    assert len(tree.xpath("//tei:g[@ref='char:punc']", namespaces=TEI)) == 8
    assert len(tree.xpath("//tei:gap[@reason='illegible'][@resp='#AELD']", namespaces=TEI)) == 9
    assert len(tree.xpath("//tei:epigraph", namespaces=TEI)) == 1
    assert len(tree.xpath("//tei:q", namespaces=TEI)) == 2
    assert len(tree.xpath("//tei:note[@place='bottom'][@n='*']", namespaces=TEI)) == 1
    assert "".join(tree.itertext()).count("ſ") == 868
    assert "part no more for ever and ever—Amen." in " ".join("".join(tree.itertext()).split())


def test_fresh_process_from_different_cwd_is_byte_identical(
    verified_candidate, tmp_path: Path
) -> None:
    _, candidate, _ = verified_candidate
    output = tmp_path / "fresh-package"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    command = (
        "from pathlib import Path;"
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct;"
        "from build.tei.marrant_prince_hall_african_lodge_sermon_reconstruction import _convert;"
        f"r=Path({str(ROOT)!r});"
        f"m=Path({str(MANIFEST)!r});"
        "s=SourceManifest.load(m,repository_root=r);"
        "reconstruct(s,Path(__import__('sys').argv[1]),_convert)"
    )
    run = subprocess.run(
        [sys.executable, "-c", command, str(output)], cwd=tmp_path, env=env,
        check=False, capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr
    fresh = CandidatePackage.load(output)
    assert fresh.sha256 == candidate.sha256
    assert all(
        fresh.member_bytes(name) == candidate.member_bytes(name)
        for name in candidate.member_names
    )
