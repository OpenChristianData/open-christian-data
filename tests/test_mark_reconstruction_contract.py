from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

import build.tei.mark_oracle as mark_oracle_module
from build.tei.mark_oracle import _closure_digest, _oracle
from build.tei.mark_reconstruction import _convert
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/mark.source-manifest.json"
EXPECTED_MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}
SOURCE_LOCAL_GOVERNED_TEXT = (
    SOURCE_MANIFEST,
    ROOT / "sources/commentaries/expositors-bible/mark.reconstruction-profile.json",
    ROOT / "sources/commentaries/expositors-bible/mark.validation-policy.json",
    ROOT / "sources/commentaries/expositors-bible/mark.source-accountability.schema.json",
    ROOT / "build/tei/mark_reconstruction.py",
    ROOT / "build/tei/mark_oracle.py",
    Path(__file__).resolve(),
)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_mark_source_local_governed_text_materializes_as_canonical_lf() -> None:
    manifest = json.loads(SOURCE_MANIFEST.read_bytes())
    authorities = {item["name"]: item for item in manifest["authorities"]}

    for path in SOURCE_LOCAL_GOVERNED_TEXT:
        content = path.read_bytes()
        assert content.endswith(b"\n"), path
        assert b"\r" not in content, path

    assert _sha(
        ROOT.joinpath(authorities["reconstruction-profile"]["path"]).read_bytes()
    ) == authorities["reconstruction-profile"]["sha256"]
    assert _sha(
        ROOT.joinpath(authorities["validation-policy"]["path"]).read_bytes()
    ) == authorities["validation-policy"]["sha256"]
    assert _sha(
        ROOT.joinpath(authorities["source-accountability-schema"]["path"]).read_bytes()
    ) == authorities["source-accountability-schema"]["sha256"]
    assert _sha(
        ROOT.joinpath(manifest["converter"]["implementation_path"]).read_bytes()
    ) == manifest["converter"]["implementation_sha256"]
    assert _sha(
        ROOT.joinpath(manifest["validator"]["implementation_path"]).read_bytes()
    ) == manifest["validator"]["implementation_sha256"]
    policy = json.loads(
        ROOT.joinpath(authorities["validation-policy"]["path"]).read_bytes()
    )
    assert _closure_digest(ROOT, policy) == manifest["validator"]["import_closure_sha256"]


@pytest.fixture(scope="module")
def mark_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)
    candidate = reconstruct(source, tmp_path_factory.mktemp("mark") / "candidate", _convert)
    report = validate(source, candidate, _oracle)
    return source, candidate, report


def test_mark_candidate_is_exact_complete_six_member_package(mark_candidate) -> None:
    source, candidate, report = mark_candidate
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))

    assert set(candidate.member_names) == EXPECTED_MEMBERS
    assert accountability["feature_count"] == 2405
    assert len(accountability["crosswalk"]) == 2405
    assert accountability["omitted_feature_count"] == 0
    assert all(item["assertion"]["status"] == "represented" for item in accountability["crosswalk"])
    assert report.status == "pass"
    assert "comparison" not in provenance
    assert "mark-json-comparator" not in provenance["authorities"]
    assert "mark.json" not in candidate.member_names
    assert "ccel-permission.md" not in candidate.member_names
    assert b"sourced via CCEL.org" in candidate.member_bytes("README.source.md")


def test_mark_useful_output_matches_accepted_pre_retirement_baseline(mark_candidate) -> None:
    _, candidate, _ = mark_candidate
    new_accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    new_tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    namespace = {"tei": "http://www.tei-c.org/ns/1.0"}
    stripped_crosswalk = [
        {key: value for key, value in item.items() if key != "assertion"}
        for item in new_accountability["crosswalk"]
    ]
    text = etree.tostring(new_tei.find("tei:text", namespace), method="c14n")

    # Frozen from the accepted old/new equality gate immediately before the
    # obsolete Mark wave runtime was retired. These compact fingerprints keep
    # detecting useful-output drift without keeping the old implementation live.
    assert _sha(_canonical(stripped_crosswalk)) == (
        "6f1c3152064a9be7183745612e09f3d3fd32d3c035300850549a83e8e316b688"
    )
    assert _sha(text) == "7168f2b44e52cd2461bcee6a21964772684755726985db86b439c030df43bc25"
    assert len(json.loads((ROOT / "data/commentaries/expositors-bible/mark.json").read_bytes())["data"]) == 85


def test_mark_runtime_authority_excludes_derived_json_comparator() -> None:
    manifest = json.loads(SOURCE_MANIFEST.read_bytes())
    names = {item["name"] for item in manifest["authorities"]}
    profile = json.loads(
        (ROOT / "sources/commentaries/expositors-bible/mark.reconstruction-profile.json").read_bytes()
    )

    assert "mark-json-comparator" not in names
    assert "comparison_baseline" not in profile["candidate_model"]
    assert "data/commentaries/expositors-bible/mark.json" not in SOURCE_MANIFEST.read_text(
        encoding="utf-8"
    )


def test_candidate_destination_rejects_actual_raw_junction() -> None:
    source = SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)
    lexical = ROOT / "raw/ccel/expositors-bible/__strip03-candidate-must-not-exist__"
    resolved = (
        (ROOT / "raw").resolve()
        / "ccel/expositors-bible/__strip03-resolved-candidate-must-not-exist__"
    )
    assert not lexical.exists()
    assert not resolved.exists()

    for destination in (lexical, resolved):
        with pytest.raises(ValueError, match="safe candidate destination"):
            reconstruct(source, destination, _convert)
        assert not destination.exists()


def _resealed_copy(candidate: CandidatePackage, destination: Path) -> Path:
    shutil.copytree(candidate.path, destination)
    return destination


def _reseal_member(path: Path, name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (path / name).read_bytes()
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


@pytest.mark.parametrize(
    "mutation",
    ["omission", "duplication", "order", "misattachment", "invention", "metadata", "rights", "unresolved"],
)
def test_mark_oracle_rejects_candidate_mutations(mark_candidate, tmp_path: Path, mutation: str) -> None:
    source, candidate, _ = mark_candidate
    target = _resealed_copy(candidate, tmp_path / mutation)
    if mutation in {"omission", "duplication", "order", "misattachment"}:
        name = "source-accountability.json"
        record = json.loads((target / name).read_bytes())
        if mutation == "omission":
            record["crosswalk"].pop()
        elif mutation == "duplication":
            record["crosswalk"][-1] = record["crosswalk"][-2]
        elif mutation == "order":
            record["crosswalk"][10], record["crosswalk"][11] = record["crosswalk"][11], record["crosswalk"][10]
        else:
            record["crosswalk"][10]["tei_parent_id"] = "mark-whole-body"
        (target / name).write_bytes(_canonical(record))
    elif mutation == "invention":
        name = "content.tei.xml"
        tree = etree.fromstring((target / name).read_bytes())
        body = tree.find(".//{http://www.tei-c.org/ns/1.0}body")
        body.append(etree.Element("{http://www.tei-c.org/ns/1.0}p"))
        (target / name).write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=True))
    elif mutation in {"metadata", "rights"}:
        name = "provenance.json"
        record = json.loads((target / name).read_bytes())
        if mutation == "metadata":
            record["status"] = "accepted"
        else:
            record["rights"]["status"] = "free"
        (target / name).write_bytes(_canonical(record))
    else:
        name = "unresolved.jsonl"
        lines = (target / name).read_bytes().splitlines(keepends=True)
        (target / name).write_bytes(b"".join(lines[:1]))
    mutated = _reseal_member(target, name)
    with pytest.raises(ValueError):
        validate(source, mutated, _oracle)


def test_mark_oracle_rejects_weakened_candidate_authority(mark_candidate, tmp_path: Path) -> None:
    source, candidate, _ = mark_candidate
    target = _resealed_copy(candidate, tmp_path / "weakened")
    manifest = json.loads((target / "manifest.json").read_bytes())
    manifest["source_manifest"]["sha256"] = "0" * 64
    (target / "manifest.json").write_bytes(_canonical(manifest))
    mutated = CandidatePackage.load(target)
    with pytest.raises(ValueError, match="^candidate source manifest binding mismatch$"):
        validate(source, mutated, _oracle)


@pytest.mark.parametrize("field", ["title", "author", "availability", "source-pointer", "source-digest"])
def test_mark_oracle_rejects_complete_header_mutations(
    mark_candidate, tmp_path: Path, field: str
) -> None:
    source, candidate, _ = mark_candidate
    target = _resealed_copy(candidate, tmp_path / field)
    name = "content.tei.xml"
    tree = etree.fromstring((target / name).read_bytes())
    ns = "{http://www.tei-c.org/ns/1.0}"
    if field == "title":
        tree.find(f".//{ns}title").text = "Invented title"
    elif field == "author":
        tree.find(f".//{ns}author").text = "Invented author"
    elif field == "availability":
        tree.find(f".//{ns}availability/{ns}p").text = "Public domain."
    elif field == "source-pointer":
        tree.find(f".//{ns}sourceDesc//{ns}ptr").set("target", "https://example.invalid")
    else:
        tree.find(f".//{ns}sourceDesc//{ns}idno").text = "0" * 64
    (target / name).write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    )
    mutated = _reseal_member(target, name)
    with pytest.raises(ValueError, match="header"):
        validate(source, mutated, _oracle)


def test_mark_validate_rejects_fake_oracle_result(
    mark_candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, candidate, _ = mark_candidate
    monkeypatch.setattr(mark_oracle_module, "ORACLE_ID", "spoofed-oracle")
    with pytest.raises(ValueError, match="oracle identity"):
        validate(source, candidate, _oracle)


def test_mark_runtime_has_no_old_control_plane_or_forbidden_imports(mark_candidate) -> None:
    _, _, report = mark_candidate
    for path in (ROOT / "build/tei/mark_reconstruction.py", ROOT / "build/tei/mark_oracle.py"):
        source = path.read_text(encoding="utf-8")
        assert "build.reconstruction" not in source
        assert "build.lib.ccel_thml" not in source
        assert "case_declaration" not in source
        assert "reconstruction.wave" not in source
        assert "reports/adaptive-reconstruction-waves" not in source
    assert len(report.attestation["import_closure_sha256"]) == 64


def test_mark_candidate_is_byte_identical_across_fresh_processes(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    code = (
        "from pathlib import Path; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.mark_reconstruction import _convert; "
        f"r=Path({str(ROOT)!r}); "
        f"s=SourceManifest.load(r/{str(SOURCE_MANIFEST.relative_to(ROOT))!r},repository_root=r); "
        "reconstruct(s,Path(__import__('sys').argv[1]),_convert)"
    )
    for destination in (first, second):
        subprocess.run([sys.executable, "-c", code, str(destination)], cwd=ROOT, check=True)
    assert {
        path.name: path.read_bytes() for path in sorted(first.iterdir())
    } == {path.name: path.read_bytes() for path in sorted(second.iterdir())}
