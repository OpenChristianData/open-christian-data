from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

import ocd_kernel.reconstruction as reconstruction
import ocd_kernel.reconstruction.contract as contract_module


PUBLIC = {
    "SourceManifest",
    "CandidatePackage",
    "ValidationReport",
    "ReviewView",
    "CandidateDecision",
    "reconstruct",
    "validate",
    "prepare_review",
}
MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}


def test_shared_checkout_agent_control_plane_is_absent() -> None:
    root = Path(__file__).resolve().parents[1]

    assert not (root / "ocd_kernel" / "reconstruction" / "shared_checkout.py").exists()
    assert not list(
        (root / "ocd_kernel" / "build").glob(
            "**/ocd_kernel/reconstruction/shared_checkout.py"
        )
    )
    assert not list(
        (root / "ocd_kernel").glob("**/__pycache__/shared_checkout.*.pyc")
    )
    assert importlib.util.find_spec("ocd_kernel.reconstruction.shared_checkout") is None
    assert "shared_checkout" not in reconstruction.__dict__


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _load_fixture_callable(path: Path, callable_name: str) -> object:
    module_name = f"_ocd_contract_fixture_{hashlib.sha256(str(path).encode()).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, callable_name)


def _fixture(
    tmp_path: Path,
    *,
    missing_role: str | None = None,
    source_contents: tuple[bytes, ...] = (b"source",),
) -> tuple[reconstruction.SourceManifest, object, object]:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    authorities = []
    for index, content in enumerate(source_contents):
        path = root / f"source-{index}.bin"
        path.write_bytes(content)
        authorities.append(
            {
                "name": f"source-part-{index}",
                "path": path.name,
                "role": "primary-source",
                "bytes": len(content),
                "sha256": _sha(content),
            }
        )
    governed = {
        "complete-source-feature-profile": ("profile.json", b"{}\n"),
        "candidate-package-schema": ("candidate.schema.json", b"{}\n"),
        "tei-validation-schema": ("tei.xsd", b"<schema/>\n"),
        "independent-validation-policy": ("policy.json", b"{}\n"),
    }
    for role, (name, content) in governed.items():
        path = root / name
        path.write_bytes(content)
        if role != missing_role:
            authorities.append(
                {
                    "name": role,
                    "path": name,
                    "role": role,
                    "bytes": len(content),
                    "sha256": _sha(content),
                }
            )
    implementation = root / "converter.py"
    implementation.write_text(
        '''from __future__ import annotations

def converter(_):
    return {
        "content.tei.xml": b"<TEI/>\\n",
        "source-accountability.json": b"{}\\n",
        "provenance.json": b"{}\\n",
        "unresolved.jsonl": b"",
        "README.source.md": b"# Source\\n",
    }

converter.converter_id = "fixture-converter"
converter.converter_version = "1"
''',
        encoding="utf-8",
        newline="\n",
    )
    oracle_path = root / "oracle.py"
    oracle_path.write_text(
        '''from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys

def _sha(content):
    return hashlib.sha256(content).hexdigest()

def _canonical(record):
    return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\\n").encode()

def oracle(source_manifest, candidate):
    oracle.calls += 1
    by_role = {}
    for item in source_manifest.record["authorities"]:
        by_role.setdefault(item["role"], []).append(item)
    sources = sorted(by_role["primary-source"], key=lambda item: item["path"])
    source_records = [
        {
            "name": item["name"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in sources
    ]
    source_binding = (
        sources[0]["sha256"]
        if len(sources) == 1
        else _sha(
            _canonical(
                {"contract": "ocd-source-member-set-v1", "members": source_records}
            )
        )
    )
    result = {
        "status": "pass",
        "oracle_id": "fixture-oracle",
        "oracle_version": "1",
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": "a" * 64,
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": by_role["complete-source-feature-profile"][0]["sha256"],
        "package_schema_sha256": by_role["candidate-package-schema"][0]["sha256"],
        "source_sha256": source_binding,
        "xsd_sha256": by_role["tei-validation-schema"][0]["sha256"],
        "policy_sha256": by_role["independent-validation-policy"][0]["sha256"],
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result

oracle.oracle_id = "fixture-oracle"
oracle.oracle_version = "1"
oracle.calls = 0
''',
        encoding="utf-8",
        newline="\n",
    )
    implementation_bytes = implementation.read_bytes()
    oracle_bytes = oracle_path.read_bytes()
    manifest_path = root / "source-manifest.json"
    record = {
        "contract": "ocd-source-manifest-v1",
        "source_id": "fixture",
        "authorities": authorities,
        "converter": {
            "id": "fixture-converter",
            "version": "1",
            "callable": "converter",
            "implementation_path": "converter.py",
            "implementation_sha256": _sha(implementation_bytes),
        },
        "validator": {
            "id": "fixture-oracle",
            "version": "1",
            "callable": "oracle",
            "implementation_path": "oracle.py",
            "implementation_sha256": _sha(oracle_bytes),
            "import_closure_sha256": "a" * 64,
        },
        "package_schema": {
            "path": "candidate.schema.json",
            "sha256": _sha(b"{}\n"),
        },
    }
    manifest_path.write_bytes(_canonical(record))
    source = reconstruction.SourceManifest.load(manifest_path, repository_root=root)
    converter = _load_fixture_callable(implementation, "converter")
    converter.implementation_path = implementation
    oracle = _load_fixture_callable(oracle_path, "oracle")
    oracle.implementation_path = oracle_path

    return source, converter, oracle


def test_source_manifest_loads_long_authority_paths_with_windows_io(tmp_path: Path) -> None:
    source, _, _ = _fixture(tmp_path)
    content = b"long-path authority"
    relative = (
        Path("deep")
        / ("w" * 48)
        / "forms"
        / ("f" * 48)
        / "editions"
        / ("e" * 48)
        / "acquisitions"
        / ("a" * 48 + ".json")
    )
    authority_path = source.repository_root / relative
    contract_module.io_path(authority_path).parent.mkdir(parents=True, exist_ok=True)
    contract_module.io_path(authority_path).write_bytes(content)

    record = json.loads(source.path.read_text(encoding="utf-8"))
    primary = next(
        item for item in record["authorities"] if item["role"] == "primary-source"
    )
    primary.update(
        path=relative.as_posix(), bytes=len(content), sha256=_sha(content)
    )
    source.path.write_bytes(_canonical(record))

    loaded = reconstruction.SourceManifest.load(
        source.path, repository_root=source.repository_root
    )

    assert loaded.authority_path(primary["name"]).read_bytes() == content


def test_fixture_creation_never_hardlinks_the_tracked_test_module(tmp_path: Path) -> None:
    tracked_test = Path(__file__)
    link_count = tracked_test.stat().st_nlink

    _fixture(tmp_path / "first")
    _fixture(tmp_path / "second")

    assert tracked_test.stat().st_nlink == link_count


def test_public_interface_is_exactly_eight_concepts() -> None:
    assert set(reconstruction.__all__) == PUBLIC


def test_reconstruct_seals_exact_six_member_candidate_and_detects_mutation(tmp_path: Path) -> None:
    source, converter, _ = _fixture(tmp_path)
    candidate = reconstruction.reconstruct(source, tmp_path / "candidate", converter)

    assert set(candidate.member_names) == MEMBERS
    assert candidate.verify_integrity() is None
    with pytest.raises(TypeError):
        candidate.manifest["contract"] = "changed"

    (candidate.path / "content.tei.xml").write_bytes(b"changed")
    with pytest.raises(ValueError, match="content.tei.xml"):
        candidate.verify_integrity()


def test_validate_review_and_decision_are_candidate_bound_and_separate(tmp_path: Path) -> None:
    source, converter, oracle = _fixture(tmp_path)
    candidate = reconstruction.reconstruct(source, tmp_path / "candidate", converter)
    report = reconstruction.validate(source, candidate, oracle)
    review = reconstruction.prepare_review(source, candidate, report)
    decision = reconstruction.CandidateDecision.create(
        review,
        disposition="needs-human-review",
        rationale="fixture",
        decided_by="test",
        decided_at="2026-08-24T00:00:00Z",
    )

    assert report.status == "pass"
    assert review.candidate_sha256 == candidate.sha256
    assert not hasattr(review, "source_path")
    assert review.source_manifest.authority_path("source-part-0") == (
        source.repository_root / "source-0.bin"
    )
    assert decision.candidate_sha256 == candidate.sha256
    assert decision.validation_sha256 == report.sha256
    assert not hasattr(review, "accept")
    assert not hasattr(decision, "apply")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("path", "other/source-manifest.json"),
        ("sha256", "0" * 64),
        ("source_id", "other-source"),
    ),
)
def test_validate_rejects_resealed_source_manifest_binding_drift(
    tmp_path: Path, field: str, value: str
) -> None:
    source, converter, oracle = _fixture(tmp_path)
    candidate = reconstruction.reconstruct(source, tmp_path / "candidate", converter)
    record = json.loads((candidate.path / "manifest.json").read_bytes())
    if field == "source_id":
        record[field] = value
    else:
        record["source_manifest"][field] = value
    (candidate.path / "manifest.json").write_bytes(_canonical(record))
    resealed = reconstruction.CandidatePackage.load(candidate.path)

    with pytest.raises(
        ValueError, match="^candidate source manifest binding mismatch$"
    ):
        reconstruction.validate(source, resealed, oracle)
    assert oracle.calls == 0


def test_prepare_review_rejects_resealed_source_binding_with_matching_report(
    tmp_path: Path,
) -> None:
    source, converter, oracle = _fixture(tmp_path)
    candidate = reconstruction.reconstruct(source, tmp_path / "candidate", converter)
    valid_report = reconstruction.validate(source, candidate, oracle)
    record = json.loads((candidate.path / "manifest.json").read_bytes())
    record["source_manifest"]["sha256"] = "0" * 64
    (candidate.path / "manifest.json").write_bytes(_canonical(record))
    resealed = reconstruction.CandidatePackage.load(candidate.path)
    matching_report = reconstruction.ValidationReport(
        "pass",
        resealed.sha256,
        source.sha256,
        valid_report.attestation,
        (),
        valid_report.sha256,
    )

    with pytest.raises(
        ValueError, match="^candidate source manifest binding mismatch$"
    ):
        reconstruction.prepare_review(source, resealed, matching_report)


def test_source_manifest_rejects_authority_drift(tmp_path: Path) -> None:
    source, _, _ = _fixture(tmp_path)
    source.authority_path("source-part-0").write_bytes(b"drift")
    with pytest.raises(ValueError, match="source"):
        source.verify()


def test_large_manifest_checks_every_source_with_bounded_workers(tmp_path, monkeypatch):
    from collections import Counter
    from threading import Lock, get_ident

    source, _, _ = _fixture(tmp_path, source_contents=(b"source",) * 512)
    contained = contract_module._contained
    threads = set()
    checked = Counter()
    lock = Lock()

    def observed(root, path, label):
        result = contained(root, path, label)
        if label.startswith("source-part-"):
            with lock:
                threads.add(get_ident())
                checked[label] += 1
        return result

    monkeypatch.setattr(contract_module, "_contained", observed)
    source.verify()
    assert checked == Counter({f"source-part-{index}": 1 for index in range(512)})
    assert 1 < len(threads) <= 4
    late_source = source.repository_root / "source-511.bin"
    late_source.write_bytes(b"SOURCE")
    with pytest.raises(ValueError, match="source-part-511 authority bytes drifted"):
        source.verify()
    late_source.unlink()
    with pytest.raises(OSError):
        source.verify()


def test_validate_rejects_missing_governed_authority_before_oracle(tmp_path: Path) -> None:
    source, converter, oracle = _fixture(
        tmp_path, missing_role="independent-validation-policy"
    )
    candidate = reconstruction.reconstruct(source, tmp_path / "candidate", converter)
    with pytest.raises(ValueError, match="independent-validation-policy"):
        reconstruction.validate(source, candidate, oracle)
    assert oracle.calls == 0


def test_validate_derives_complete_multi_member_source_binding(tmp_path: Path) -> None:
    source, converter, oracle = _fixture(
        tmp_path, source_contents=(b"first", b"second")
    )
    candidate = reconstruction.reconstruct(source, tmp_path / "candidate", converter)

    report = reconstruction.validate(source, candidate, oracle)

    members = sorted(
        (
            {
                "name": item["name"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in source.record["authorities"]
            if item["role"] == "primary-source"
        ),
        key=lambda item: (item["path"], item["name"]),
    )
    expected = _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": members})
    )
    assert report.attestation["source_sha256"] == expected


def test_callable_source_resolution_errors_are_value_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _, _ = _fixture(tmp_path)
    namespace: dict[str, object] = {}
    exec("def converter(_): return {}", namespace)
    converter = namespace["converter"]
    converter.converter_id = "fixture-converter"
    converter.converter_version = "1"

    with pytest.raises(ValueError, match="callable provenance"):
        reconstruction.reconstruct(source, tmp_path / "candidate", converter)

    monkeypatch.setattr(
        contract_module.inspect,
        "getsourcefile",
        lambda _: r"Z:\missing\strict-editable-shadow.py",
    )
    monkeypatch.setattr(contract_module.inspect, "getsource", lambda _: "def converter(): ...")
    with pytest.raises(ValueError, match="callable provenance"):
        reconstruction.reconstruct(source, tmp_path / "candidate-winerror", converter)


def test_reconstruct_rejects_callable_metadata_spoof(tmp_path: Path) -> None:
    source, converter, _ = _fixture(tmp_path)

    def fake(manifest):
        return converter(manifest)

    fake.converter_id = converter.converter_id
    fake.converter_version = converter.converter_version
    fake.implementation_path = converter.implementation_path
    with pytest.raises(ValueError, match="callable provenance"):
        reconstruction.reconstruct(source, tmp_path / "candidate", fake)


def test_validate_rejects_callable_and_returned_identity_spoofs(tmp_path: Path) -> None:
    source, converter, oracle = _fixture(tmp_path)
    candidate = reconstruction.reconstruct(source, tmp_path / "candidate", converter)

    def fake_callable(manifest, package):
        return oracle(manifest, package)

    fake_callable.oracle_id = oracle.oracle_id
    fake_callable.oracle_version = oracle.oracle_version
    fake_callable.implementation_path = oracle.implementation_path
    with pytest.raises(ValueError, match="callable provenance"):
        reconstruction.validate(source, candidate, fake_callable)

@pytest.mark.parametrize(
    "root_name",
    ["raw", "data", "ir", "reports", "exports", "acceptance", "publication"],
)
def test_reconstruct_rejects_governed_or_canonical_destinations(
    tmp_path: Path, root_name: str
) -> None:
    source, converter, _ = _fixture(tmp_path)
    destination = source.repository_root / root_name / "candidate"
    destination.parent.mkdir()
    with pytest.raises(ValueError, match="safe candidate destination"):
        reconstruction.reconstruct(source, destination, converter)


def test_clean_public_import_does_not_load_legacy_control_plane() -> None:
    code = (
        "import sys,ocd_kernel.reconstruction as r;"
        "bad=('case_declaration','persistence','verifier_process','wave');"
        "assert not any(any(n.endswith('.'+x) for x in bad) "
        "for n in sys.modules if n.startswith('ocd_kernel.reconstruction'));"
        "assert len(r.__all__)==8"
    )
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parents[1], check=True)


def test_contained_authority_uses_configured_durable_raw_without_junction(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    library = tmp_path / "durable-library"
    witness = library / "raw" / "sources" / "witness.txt"
    root.mkdir()
    witness.parent.mkdir(parents=True)
    witness.write_text("source", encoding="utf-8")
    (root / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library)}), encoding="utf-8"
    )

    assert contract_module._contained(root, "raw/sources/witness.txt", "witness") == witness.resolve()
    assert not (root / "raw").exists()
    with pytest.raises(ValueError):
        contract_module._contained(root, "../outside.txt", "witness")
    with pytest.raises(ValueError):
        contract_module._contained(root, str(witness), "witness")
    with pytest.raises((ValueError, FileNotFoundError)):
        contract_module._contained(root, "raw/sources/missing.txt", "witness")
