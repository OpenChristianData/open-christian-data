"""Source-bound reconstruction contract for the four LIB-068 works."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType

from lxml import etree
import pytest

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
LIB068_ROUTES = (
    (
        "donne-devotions-upon-emergent-occasions",
        Path(r"D:/Library/Open Christian Data/raw/gutenberg/pg23772.txt"),
    ),
    (
        "newman-apologia-pro-vita-sua",
        Path(r"D:/Library/Open Christian Data/raw/gutenberg/pg22088.txt"),
    ),
    (
        "taylor-holy-dying",
        Path(r"D:/Library/Open Christian Data/raw/ccel/taylor-holy-dying.txt"),
    ),
    (
        "taylor-holy-living",
        Path(r"D:/Library/Open Christian Data/raw/ccel/taylor-holy-living.txt"),
    ),
)
RECONSTRUCTION_ROUTES = LIB068_ROUTES
RUNTIME_MANIFESTS = {
    'donne-devotions-upon-emergent-occasions': (
        '99dded2c8e17b37b2c8ce0f0eb19ca4bc87fe1a152deda4605030f3e32b0bbce',
        'tests/fixtures/reconstruction-runtime/donne-lib068.source-manifest.json',
    ),
    'newman-apologia-pro-vita-sua': (
        '96f40195fb09c8767a445ed862e670c6658819f69683f40e5f46c45f022d75ae',
        'tests/fixtures/reconstruction-runtime/newman-lib068.source-manifest.json',
    ),
    'taylor-holy-dying': (
        'b364633b740c7d5092c3d552bec2ad44b881e8798eb17412603ed4d952776f47',
        'tests/fixtures/reconstruction-runtime/taylor-holy-dying-lib068.source-manifest.json',
    ),
    'taylor-holy-living': (
        '75be967e53be8af88c9b5088bbf172431e2f471d40fc48dc94977662613f57dd',
        'tests/fixtures/reconstruction-runtime/taylor-holy-living-lib068.source-manifest.json',
    ),
}


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _manifest(work_id: str) -> Path:
    return ROOT / RUNTIME_MANIFESTS[work_id][1]


@pytest.mark.parametrize("work_id", RUNTIME_MANIFESTS)
def test_runtime_fixture_preserves_complete_original_record_except_closure(work_id: str) -> None:
    original = ROOT / "sources/structured-text" / work_id / "LIB-068.source-manifest.json"
    raw = original.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RUNTIME_MANIFESTS[work_id][0]
    expected = json.loads(raw)
    oracle = _load(ROOT / "build/tei/lib068_source_local_oracle.py", "_lib068_preservation_oracle")
    live = oracle._closure(ROOT)
    assert live != expected["validator"]["import_closure_sha256"]
    expected["validator"]["import_closure_sha256"] = live
    assert json.loads(_manifest(work_id).read_bytes()) == expected


def _route_mirror(tmp_path: Path, work_id: str, durable_source: Path) -> Path:
    mirror = tmp_path / "mirror"
    manifest_path = _manifest(work_id)
    source_dir = Path("sources/structured-text") / work_id
    shutil.copytree(ROOT / source_dir, mirror / source_dir)
    runtime = mirror / manifest_path.relative_to(ROOT)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest_path, runtime)
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    retained = next(
        item for item in record["authorities"] if item["name"] == "retained-text"
    )
    raw = mirror / retained["path"]
    raw.parent.mkdir(parents=True)
    shutil.copyfile(durable_source, raw)
    for relative in (
        "build/tei/lib068_source_local.py",
        "build/tei/lib068_source_local_oracle.py",
        record["converter"]["implementation_path"],
        record["validator"]["implementation_path"],
        "ocd_kernel/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    ):
        destination = mirror / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    shutil.copytree(ROOT / "ocd_kernel/tei/vendor/xsd", mirror / "ocd_kernel/tei/vendor/xsd")
    for authority in record["authorities"]:
        relative = Path(authority["path"])
        if relative.parts[:2] == ("build", "tei"):
            destination = mirror / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
    return mirror


@pytest.mark.parametrize(("work_id", "durable_source"), LIB068_ROUTES)
def test_all_lib068_source_manifests_load_with_current_shared_closure(
    tmp_path: Path, work_id: str, durable_source: Path
) -> None:
    mirror = _route_mirror(tmp_path, work_id, durable_source)

    manifest = SourceManifest.load(
        mirror / _manifest(work_id).relative_to(ROOT), repository_root=mirror
    )

    assert manifest.record["work_id"] == work_id


@pytest.mark.parametrize(("work_id", "durable_source"), RECONSTRUCTION_ROUTES)
def test_lib068_source_manifest_reconstructs_and_passes_independent_oracle(
    tmp_path: Path, work_id: str, durable_source: Path
) -> None:
    mirror = _route_mirror(tmp_path, work_id, durable_source)
    module_suffix = work_id.replace("-", "_")
    producer = _load(
        mirror / "build/tei/lib068_source_local.py",
        f"_lib068_{module_suffix}_producer",
    )
    oracle = _load(
        mirror / "build/tei/lib068_source_local_oracle.py",
        f"_lib068_{module_suffix}_oracle",
    )
    manifest = SourceManifest.load(
        mirror / _manifest(work_id).relative_to(ROOT), repository_root=mirror
    )
    candidate = reconstruct(manifest, tmp_path / f"{work_id}-candidate", producer._convert)

    report = validate(manifest, candidate, oracle._oracle)

    assert report.status == "pass"
    assert report.findings == ()


@pytest.fixture(scope="module")
def donne_mutation_bundle(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[SourceManifest, CandidatePackage, object]:
    """Provide one Donne package for bounded source-fidelity mutation checks."""

    work_id, durable_source = LIB068_ROUTES[0]
    root = tmp_path_factory.mktemp("lib068-donne-mutations")
    mirror = _route_mirror(root, work_id, durable_source)
    producer = _load(
        mirror / "build/tei/lib068_source_local.py",
        "_lib068_donne_mutation_producer",
    )
    oracle = _load(
        mirror / "build/tei/lib068_source_local_oracle.py",
        "_lib068_donne_mutation_oracle",
    )
    manifest = SourceManifest.load(
        mirror / _manifest(work_id).relative_to(ROOT), repository_root=mirror
    )
    candidate = reconstruct(manifest, root / "candidate", producer._convert)
    return manifest, candidate, oracle._oracle


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal_member(
    source: CandidatePackage, destination: Path, name: str, content: bytes
) -> CandidatePackage:
    shutil.copytree(source.path, destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    (destination / name).write_bytes(content)
    manifest_path.write_bytes(_canonical_json(manifest))
    return CandidatePackage.load(destination)


@pytest.mark.parametrize("mutation", ["omission", "reordering", "bom", "blank-line"])
def test_donne_oracle_rejects_resealed_tei_source_risk_mutations(
    tmp_path: Path,
    donne_mutation_bundle: tuple[SourceManifest, CandidatePackage, object],
    mutation: str,
) -> None:
    """A validly resealed package cannot hide physical-line fidelity attacks."""

    manifest, candidate, oracle = donne_mutation_bundle
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    namespace = {"tei": "http://www.tei-c.org/ns/1.0"}
    lines = root.xpath("./tei:text/tei:body//tei:seg[@type='source-line']", namespaces=namespace)
    assert len(lines) == 7_647

    if mutation == "omission":
        lines[1_616].getparent().remove(lines[1_616])
    elif mutation == "reordering":
        first, second = lines[4_836:4_838]
        parent = first.getparent()
        index = list(parent).index(first)
        parent.remove(first)
        parent.insert(index + 1, first)
        assert parent[index] is second
    elif mutation == "bom":
        assert (lines[0].text or "").startswith("\ufeff")
        lines[0].text = (lines[0].text or "").lstrip("\ufeff")
    elif mutation == "blank-line":
        assert (lines[1_615].text or "") == ""
        lines[1_615].text = " "
    else:
        raise AssertionError(f"unknown mutation {mutation}")

    content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    mutated = _reseal_member(
        candidate, tmp_path / f"donne-{mutation}", "content.tei.xml", content
    )
    expected_reason = {
        "omission": "LIB-068 source carrier census is incomplete",
        "reordering": "LIB-068 normalized source-line 4837 drifted",
        "bom": "LIB-068 source-line 1 text drifted",
        "blank-line": "LIB-068 source-line 1616 text drifted",
    }
    with pytest.raises(ValueError, match=expected_reason[mutation]):
        validate(manifest, mutated, oracle)
