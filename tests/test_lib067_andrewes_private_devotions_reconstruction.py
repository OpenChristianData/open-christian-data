"""Focused LIB-067 Andrewes retained-text reconstruction contract."""

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

from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-andrewes-private-devotions.source-manifest.json'
DURABLE_RAW = Path(
    r"D:/Library/Open Christian Data/raw/ccel/andrewes-private-devotions.txt"
)
SOURCE_SHA256 = "366ebbd4dc4ea9420099d7335beb73a47ff0f331803d8e3d7fb1c4ad81e6ea47"
MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}
TEI = {"t": "http://www.tei-c.org/ns/1.0"}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mirror(tmp_path_factory: pytest.TempPathFactory) -> Path:
    assert DURABLE_RAW.is_file()
    root = tmp_path_factory.mktemp("lib067-andrewes-mirror")
    shutil.copytree(
        ROOT / "sources/andrewes-private-devotions",
        root / "sources/andrewes-private-devotions",
    )
    raw = root / "raw/ccel/andrewes-private-devotions.txt"
    raw.parent.mkdir(parents=True)
    shutil.copyfile(DURABLE_RAW, raw)
    for relative in (
        "build/tei/lib067_andrewes_private_devotions.py",
        "build/tei/lib067_andrewes_private_devotions_oracle.py",
        "ocd_kernel/__init__.py",
        "ocd_kernel/lib/__init__.py",
        "ocd_kernel/lib/path_io.py",
        "ocd_kernel/lib/storage_topology.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    shutil.copytree(
        ROOT / "ocd_kernel/tei/vendor/xsd", root / "ocd_kernel/tei/vendor/xsd"
    )
    fixture = root / MANIFEST.relative_to(ROOT)
    fixture.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MANIFEST, fixture)
    return root


@pytest.fixture(scope="module")
def manifest(mirror: Path) -> SourceManifest:
    return SourceManifest.load(
        mirror / MANIFEST.relative_to(ROOT), repository_root=mirror
    )


@pytest.fixture(scope="module")
def route(mirror: Path) -> ModuleType:
    return _load(
        mirror / "build/tei/lib067_andrewes_private_devotions.py",
        "_lib067_andrewes_route",
    )


@pytest.fixture(scope="module")
def oracle(mirror: Path) -> ModuleType:
    return _load(
        mirror / "build/tei/lib067_andrewes_private_devotions_oracle.py",
        "_lib067_andrewes_oracle",
    )


@pytest.fixture(scope="module")
def candidate(
    tmp_path_factory: pytest.TempPathFactory,
    manifest: SourceManifest,
    route: ModuleType,
) -> CandidatePackage:
    return reconstruct(
        manifest,
        tmp_path_factory.mktemp("lib067-candidate") / "candidate",
        route._convert,
    )


def _copy(tmp_path: Path, candidate: CandidatePackage, label: str) -> Path:
    destination = tmp_path / label
    shutil.copytree(candidate.path, destination)
    return destination


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    record = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in record["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (path / "manifest.json").write_bytes(_canonical(record))
    return CandidatePackage.load(path)


def _mutate_tei(path: Path, mutate) -> CandidatePackage:
    root = etree.fromstring((path / "content.tei.xml").read_bytes())
    mutate(root)
    return _reseal(
        path,
        "content.tei.xml",
        etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
    )


def _resealed_policy_manifest(
    tmp_path: Path, mirror: Path, mutation: str
) -> SourceManifest:
    root = tmp_path / f"policy-{mutation}"
    shutil.copytree(mirror, root)
    policy_path = (
        root
        / "sources/andrewes-private-devotions/lib067-andrewes.validation-policy.json"
    )
    policy = json.loads(policy_path.read_bytes())
    if mutation == "empty-rules":
        policy["rules"] = []
    elif mutation == "changed-rule":
        policy["rules"][0] = "accept approximately matching source bytes"
    elif mutation == "reordered-rules":
        policy["rules"][0], policy["rules"][1] = (
            policy["rules"][1],
            policy["rules"][0],
        )
    elif mutation == "missing-schema":
        del policy["schema"]
    elif mutation == "extra-field":
        policy["self_asserted_valid"] = True
    elif mutation == "reordered-fields":
        policy = {"rules": policy["rules"]} | {
            key: value for key, value in policy.items() if key != "rules"
        }
    else:  # pragma: no cover - parametrization is closed below
        raise AssertionError(mutation)
    policy_content = (
        json.dumps(policy, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    policy_path.write_bytes(policy_content)
    manifest_path = root / MANIFEST.relative_to(ROOT)
    record = json.loads(manifest_path.read_bytes())
    authority = next(
        item for item in record["authorities"] if item["name"] == "validation-policy"
    )
    authority.update(bytes=len(policy_content), sha256=_sha(policy_content))
    manifest_path.write_bytes(_canonical(record))
    return SourceManifest.load(manifest_path, repository_root=root)


def _resealed_closure_manifest(
    tmp_path: Path,
    mirror: Path,
    route: ModuleType,
    oracle: ModuleType,
    target: str,
    mutation: str,
) -> SourceManifest:
    root = tmp_path / f"closure-{target}-{mutation}"
    shutil.copytree(mirror, root)
    route_path = root / "build/tei/lib067_andrewes_private_devotions.py"
    oracle_path = root / "build/tei/lib067_andrewes_private_devotions_oracle.py"
    closure = (
        route._closure(root, route_path)
        if target == "producer"
        else oracle._closure(root, oracle_path)
    )
    forged = _sha(_canonical(closure[:-1])) if mutation == "incomplete" else "0" * 64
    manifest_path = root / MANIFEST.relative_to(ROOT)
    record = json.loads(manifest_path.read_bytes())
    if target == "producer":
        record["producer_import_closure_sha256"] = forged
    else:
        record["validator"]["import_closure_sha256"] = forged
    manifest_path.write_bytes(_canonical(record))
    return SourceManifest.load(manifest_path, repository_root=root)


def test_manifest_binds_exact_single_retained_member(manifest: SourceManifest) -> None:
    manifest.verify()
    record = manifest.record
    assert (record["ticket_id"], record["work_id"]) == (
        "LIB-067",
        "andrewes-private-devotions",
    )
    retained = [
        item for item in record["authorities"] if item["role"] == "primary-source"
    ]
    assert [(item["path"], item["bytes"], item["sha256"]) for item in retained] == [
        ("raw/ccel/andrewes-private-devotions.txt", 168055, SOURCE_SHA256)
    ]


def test_candidate_passes_independent_oracle_and_direct_schemas(
    manifest: SourceManifest, candidate: CandidatePackage, oracle: ModuleType
) -> None:
    assert {item["name"] for item in candidate.manifest["members"]} | {
        "manifest.json"
    } == MEMBERS
    report = validate(manifest, candidate, oracle._oracle)
    assert report.status == "pass" and report.findings == ()
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["member_census"] == [
        {
            "bytes": 168055,
            "decision": "include",
            "path": "raw/ccel/andrewes-private-devotions.txt",
            "reason": "The sole frozen LIB-067 retained primary-source member.",
            "sha256": SOURCE_SHA256,
        }
    ]
    assert accountability["source_line_count"] == 4883
    assert (
        accountability["omitted_line_count"]
        == accountability["duplicate_line_count"]
        == 0
    )
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert compiled_tei_schema(manifest.authority_path("tei-p5-xsd")).validate(tei)
    assert (
        len(
            tei.xpath(
                "/t:TEI/t:text/t:body/t:div[@type='retained-source']/t:ab[@type='source-line']",
                namespaces=TEI,
            )
        )
        == 4883
    )


def test_candidate_is_byte_deterministic_in_process_fresh_process_and_different_cwd(
    tmp_path: Path,
    manifest: SourceManifest,
    route: ModuleType,
    candidate: CandidatePackage,
    mirror: Path,
) -> None:
    assert (
        reconstruct(manifest, tmp_path / "again", route._convert).sha256
        == candidate.sha256
    )
    fresh = tmp_path / "fresh"
    cwd = tmp_path / "different-cwd"
    cwd.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "build/tools/reconstruct_candidate.py"),
            "--manifest",
            MANIFEST.relative_to(ROOT).as_posix(),
            "--destination",
            str(fresh),
            "--repository-root",
            str(mirror),
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout)["candidate"]["sha256"] == candidate.sha256
    fresh_package = fresh / "package"
    assert sorted(
        path.relative_to(fresh_package).as_posix()
        for path in fresh_package.rglob("*")
        if path.is_file()
    ) == sorted(
        path.relative_to(candidate.path).as_posix()
        for path in candidate.path.rglob("*")
        if path.is_file()
    )
    for relative in (
        path.relative_to(candidate.path)
        for path in candidate.path.rglob("*")
        if path.is_file()
    ):
        assert (fresh_package / relative).read_bytes() == (
            candidate.path / relative
        ).read_bytes()


def test_oracle_is_independent_of_producer() -> None:
    text = (ROOT / "build/tei/lib067_andrewes_private_devotions_oracle.py").read_text(
        encoding="utf-8"
    )
    assert "lib067_andrewes_private_devotions import" not in text
    assert "_convert" not in text


def test_producer_and_oracle_closures_are_complete_and_pinned(
    mirror: Path,
    manifest: SourceManifest,
    route: ModuleType,
    oracle: ModuleType,
) -> None:
    expected_common = {
        "ocd_kernel/__init__.py",
        "ocd_kernel/lib/__init__.py",
        "ocd_kernel/lib/path_io.py",
        "ocd_kernel/lib/storage_topology.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
    }
    producer = route._closure(
        mirror, mirror / "build/tei/lib067_andrewes_private_devotions.py"
    )
    validator = oracle._closure(
        mirror, mirror / "build/tei/lib067_andrewes_private_devotions_oracle.py"
    )
    assert {item["path"] for item in producer} == expected_common | {
        "build/tei/lib067_andrewes_private_devotions.py"
    }
    assert {item["path"] for item in validator} == expected_common | {
        "build/tei/lib067_andrewes_private_devotions_oracle.py"
    }
    assert (
        _sha(_canonical(producer)) == manifest.record["producer_import_closure_sha256"]
    )
    assert (
        _sha(_canonical(validator))
        == manifest.record["validator"]["import_closure_sha256"]
    )
    assert route._verify_closure(manifest) == _sha(_canonical(producer))
    assert oracle._verify_closures(
        manifest,
        manifest.record["converter"],
        manifest.record["validator"],
    ) == (_sha(_canonical(producer)), _sha(_canonical(validator)))


@pytest.mark.parametrize(
    "mutation",
    [
        "empty-rules",
        "changed-rule",
        "reordered-rules",
        "missing-schema",
        "extra-field",
        "reordered-fields",
    ],
)
def test_fully_resealed_policy_envelope_mutations_are_rejected(
    tmp_path: Path,
    mirror: Path,
    route: ModuleType,
    oracle: ModuleType,
    mutation: str,
) -> None:
    source = _resealed_policy_manifest(tmp_path, mirror, mutation)
    source.verify()
    policy = route._strict(
        source.authority_path("validation-policy"), "Andrewes mutated policy"
    )
    with pytest.raises(ValueError, match="validation policy envelope drifted"):
        route._verify_policy(policy)
    with pytest.raises(ValueError, match="validation policy envelope drifted"):
        oracle._verify_policy(policy)
    with pytest.raises(ValueError, match="validation policy envelope drifted"):
        route._convert(source)


def test_fully_resealed_empty_policy_is_rejected_by_oracle(
    tmp_path: Path,
    mirror: Path,
    candidate: CandidatePackage,
    oracle: ModuleType,
) -> None:
    source = _resealed_policy_manifest(tmp_path, mirror, "empty-rules")
    candidate_path = _copy(tmp_path, candidate, "oracle-empty-policy")
    candidate_manifest = json.loads((candidate_path / "manifest.json").read_bytes())
    candidate_manifest["source_manifest"]["sha256"] = source.sha256
    (candidate_path / "manifest.json").write_bytes(_canonical(candidate_manifest))
    rebound = CandidatePackage.load(candidate_path)

    with pytest.raises(ValueError, match="validation policy envelope drifted"):
        oracle._oracle(source, rebound)


@pytest.mark.parametrize("target", ["producer", "oracle"])
@pytest.mark.parametrize("mutation", ["incomplete", "forged"])
def test_incomplete_and_forged_import_closures_are_rejected(
    tmp_path: Path,
    mirror: Path,
    route: ModuleType,
    oracle: ModuleType,
    target: str,
    mutation: str,
) -> None:
    source = _resealed_closure_manifest(
        tmp_path, mirror, route, oracle, target, mutation
    )
    source.verify()
    if target == "producer":
        with pytest.raises(ValueError, match="producer import closure drifted"):
            route._verify_closure(source)
    with pytest.raises(ValueError, match=f"{target} import closure drifted"):
        oracle._verify_closures(
            source,
            source.record["converter"],
            source.record["validator"],
        )


@pytest.mark.parametrize(
    "mutation", ["omit", "duplicate", "reorder", "invent", "text", "metadata"]
)
def test_oracle_rejects_tei_mutations(
    tmp_path: Path,
    manifest: SourceManifest,
    candidate: CandidatePackage,
    oracle: ModuleType,
    mutation: str,
) -> None:
    path = _copy(tmp_path, candidate, mutation)

    def mutate(root: etree._Element) -> None:
        lines = root.xpath("//t:ab[@type='source-line']", namespaces=TEI)
        if mutation == "omit":
            lines[20].getparent().remove(lines[20])
        elif mutation == "duplicate":
            lines[20].addnext(copy.deepcopy(lines[20]))
        elif mutation == "reorder":
            first, second, parent = lines[20], lines[21], lines[20].getparent()
            parent.remove(second)
            parent.insert(parent.index(first), second)
        elif mutation == "invent":
            invented = copy.deepcopy(lines[20])
            invented.set("n", "invented")
            invented.text = "INVENTED"
            lines[20].addnext(invented)
        elif mutation == "text":
            lines[20].text = "altered"
        else:
            root.xpath(
                "/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=TEI
            )[0].text = "Invented title"

    with pytest.raises(ValueError):
        validate(manifest, _mutate_tei(path, mutate), oracle._oracle)


@pytest.mark.parametrize(
    "name,change",
    [
        ("source-accountability.json", {"source_line_count": 1}),
        ("provenance.json", {"status": "accepted"}),
        ("unresolved.jsonl", None),
        ("README.source.md", None),
    ],
)
def test_oracle_rejects_evidence_provenance_and_scope_mutations(
    tmp_path: Path,
    manifest: SourceManifest,
    candidate: CandidatePackage,
    oracle: ModuleType,
    name: str,
    change: dict[str, object] | None,
) -> None:
    path = _copy(tmp_path, candidate, name.replace(".", "-"))
    if change is None:
        content = b"mutated\n"
    else:
        record = json.loads((path / name).read_bytes())
        record.update(change)
        content = _canonical(record)
    with pytest.raises(ValueError):
        validate(manifest, _reseal(path, name, content), oracle._oracle)
