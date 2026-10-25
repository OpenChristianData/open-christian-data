from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Callable, Mapping, cast

import pytest

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.reconstruction.verifier import (
    MechanicalFacts,
    MechanicalVerificationResult,
    __all__ as verifier_exports,
    verify_mechanical_facts,
)


_DIGEST = "a" * 64
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _fixture(
    tmp_path: Path, *, validator_import_closure_sha256: str = "b" * 64
) -> tuple[SourceManifest, CandidatePackage, MechanicalFacts]:
    root = tmp_path / "repository"
    root.mkdir()
    authority_contents = {
        "source.txt": b"retained source\n",
        "profile.json": b"{}\n",
        "candidate-package.schema.json": b"{}\n",
        "tei.xsd": b"<schema/>\n",
        "policy.json": b"{}\n",
        "converter.py": b"def convert(source_manifest):\n    return {}\n",
    }
    oracle_source = f'''from pathlib import Path
import hashlib

from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


def oracle(source_manifest, candidate):
    facts = MechanicalFacts(
        validator_implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        validator_import_closure_sha256={"b" * 64!r},
        source_sha256={_sha(authority_contents["source.txt"])!r},
        profile_sha256={_sha(authority_contents["profile.json"])!r},
        package_schema_sha256={_sha(authority_contents["candidate-package.schema.json"])!r},
        xsd_sha256={_sha(authority_contents["tei.xsd"])!r},
        policy_sha256={_sha(authority_contents["policy.json"])!r},
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


oracle.oracle_id = "fixture-oracle"
oracle.oracle_version = "1"
oracle.implementation_path = Path(__file__).resolve()
'''.encode("utf-8")
    authority_contents["oracle.py"] = oracle_source
    for name, content in authority_contents.items():
        (root / name).write_bytes(content)

    role_by_name = {
        "source.txt": "primary-source",
        "profile.json": "complete-source-feature-profile",
        "candidate-package.schema.json": "candidate-package-schema",
        "tei.xsd": "tei-validation-schema",
        "policy.json": "independent-validation-policy",
    }
    manifest = {
        "contract": "ocd-source-manifest-v1",
        "source_id": "fixture-source",
        "authorities": [
            {
                "name": name,
                "path": name,
                "role": role,
                "bytes": len(authority_contents[name]),
                "sha256": _sha(authority_contents[name]),
            }
            for name, role in role_by_name.items()
        ],
        "converter": {
            "id": "fixture-converter",
            "version": "1",
            "callable": "convert",
            "implementation_path": "converter.py",
            "implementation_sha256": _sha(authority_contents["converter.py"]),
        },
        "validator": {
            "id": "fixture-oracle",
            "version": "1",
            "callable": "oracle",
            "implementation_path": "oracle.py",
            "implementation_sha256": _sha(authority_contents["oracle.py"]),
            "import_closure_sha256": validator_import_closure_sha256,
        },
        "package_schema": {
            "path": "candidate-package.schema.json",
            "sha256": _sha(authority_contents["candidate-package.schema.json"]),
        },
    }
    manifest_path = root / "source-manifest.json"
    manifest_path.write_bytes(_canonical(manifest))
    source_manifest = SourceManifest.load(manifest_path, repository_root=root)

    candidate_path = tmp_path / "candidate"
    candidate_path.mkdir()
    candidate_members = {
        "content.tei.xml": b"<TEI xmlns='http://www.tei-c.org/ns/1.0'/>\n",
        "source-accountability.json": b"{}\n",
        "provenance.json": b"{}\n",
        "unresolved.jsonl": b"",
        "README.source.md": b"fixture\n",
    }
    for name, content in candidate_members.items():
        (candidate_path / name).write_bytes(content)
    candidate_manifest = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": "fixture-source",
        "source_manifest": {
            "path": "source-manifest.json",
            "sha256": source_manifest.sha256,
        },
        "converter": manifest["converter"],
        "package_schema": manifest["package_schema"],
        "members": [
            {"name": name, "bytes": len(content), "sha256": _sha(content)}
            for name, content in sorted(candidate_members.items())
        ],
    }
    (candidate_path / "manifest.json").write_bytes(_canonical(candidate_manifest))
    candidate = CandidatePackage.load(candidate_path)
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(authority_contents["oracle.py"]),
        validator_import_closure_sha256="b" * 64,
        source_sha256=_sha(authority_contents["source.txt"]),
        profile_sha256=_sha(authority_contents["profile.json"]),
        package_schema_sha256=_sha(
            authority_contents["candidate-package.schema.json"]
        ),
        xsd_sha256=_sha(authority_contents["tei.xsd"]),
        policy_sha256=_sha(authority_contents["policy.json"]),
        findings=(),
    )
    return source_manifest, candidate, facts


def _load_oracle(path: Path) -> Callable[
    [SourceManifest, CandidatePackage], Mapping[str, object]
]:
    name = f"_mechanical_verifier_fixture_{path.parent.name}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("fixture oracle module is not loadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.oracle


def _first_party_paths_loaded_by_import(module_name: str) -> tuple[str, ...]:
    script = """
import importlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve(strict=True)
sys.path.insert(0, str(root))
before = set(sys.modules)
importlib.import_module(sys.argv[2])
paths = set()
for name in set(sys.modules) - before:
    module_path = getattr(sys.modules[name], "__file__", None)
    if module_path is None:
        continue
    path = Path(module_path).resolve(strict=True)
    try:
        paths.add(path.relative_to(root).as_posix())
    except ValueError:
        pass
print(json.dumps(sorted(paths)))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            script,
            str(_REPOSITORY_ROOT),
            module_name,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(json.loads(result.stdout))


def test_mechanical_facts_is_closed_family_neutral_and_immutable() -> None:
    facts = MechanicalFacts(
        validator_implementation_sha256=_DIGEST,
        validator_import_closure_sha256=_DIGEST,
        source_sha256=_DIGEST,
        profile_sha256=_DIGEST,
        package_schema_sha256=_DIGEST,
        xsd_sha256=_DIGEST,
        policy_sha256=_DIGEST,
        findings=(),
    )

    assert tuple(field.name for field in fields(facts)) == (
        "validator_implementation_sha256",
        "validator_import_closure_sha256",
        "source_sha256",
        "profile_sha256",
        "package_schema_sha256",
        "xsd_sha256",
        "policy_sha256",
        "findings",
    )
    assert not hasattr(facts, "__dict__")
    with pytest.raises(FrozenInstanceError):
        facts.source_sha256 = "b" * 64  # type: ignore[misc]


def test_verifier_module_exports_only_the_frozen_interface() -> None:
    assert verifier_exports == (
        "MechanicalFacts",
        "MechanicalVerificationResult",
        "verify_mechanical_facts",
    )


def test_reconstruction_package_import_does_not_load_or_export_verifier() -> None:
    assert _first_party_paths_loaded_by_import("ocd_kernel.reconstruction") == (
        "ocd_kernel/__init__.py",
        "ocd_kernel/lib/__init__.py",
        "ocd_kernel/lib/path_io.py",
        "ocd_kernel/lib/storage_topology.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
    )


def test_verifier_builds_the_exact_immutable_attestation_record(tmp_path: Path) -> None:
    source_manifest, candidate, facts = _fixture(tmp_path)

    result = verify_mechanical_facts(source_manifest, candidate, facts)

    assert isinstance(result, MechanicalVerificationResult)
    assert not hasattr(result, "__dict__")
    expected_without_digest = {
        "status": "pass",
        "oracle_id": "fixture-oracle",
        "oracle_version": "1",
        "implementation_sha256": facts.validator_implementation_sha256,
        "import_closure_sha256": facts.validator_import_closure_sha256,
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": facts.profile_sha256,
        "package_schema_sha256": facts.package_schema_sha256,
        "source_sha256": facts.source_sha256,
        "xsd_sha256": facts.xsd_sha256,
        "policy_sha256": facts.policy_sha256,
        "findings": [],
    }
    expected = {
        **expected_without_digest,
        "result_sha256": _sha(_canonical(expected_without_digest)),
    }
    assert result.as_record() == expected
    with pytest.raises(FrozenInstanceError):
        result.status = "fail"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field_name",
    (
        "validator_implementation_sha256",
        "validator_import_closure_sha256",
        "source_sha256",
        "profile_sha256",
        "package_schema_sha256",
        "xsd_sha256",
        "policy_sha256",
    ),
)
def test_verifier_rejects_an_invalid_digest_fact(
    tmp_path: Path, field_name: str
) -> None:
    source_manifest, candidate, facts = _fixture(tmp_path)
    invalid = replace(facts, **{field_name: "A" * 64})

    with pytest.raises(
        ValueError, match=rf"^{field_name} must be a lowercase SHA-256$"
    ):
        verify_mechanical_facts(source_manifest, candidate, invalid)


def test_verifier_refuses_a_passing_result_with_findings(tmp_path: Path) -> None:
    source_manifest, candidate, facts = _fixture(tmp_path)

    with pytest.raises(
        ValueError, match="^mechanical verification requires zero findings$"
    ):
        verify_mechanical_facts(
            source_manifest,
            candidate,
            replace(facts, findings=("unresolved mechanical finding",)),
        )


@pytest.mark.parametrize("invalid_findings", ([], (1,)))
def test_verifier_rejects_an_invalid_findings_shape(
    tmp_path: Path, invalid_findings: object
) -> None:
    source_manifest, candidate, facts = _fixture(tmp_path)
    invalid = replace(
        facts,
        findings=cast(tuple[str, ...], invalid_findings),
    )

    with pytest.raises(ValueError, match="^findings must be a tuple of strings$"):
        verify_mechanical_facts(source_manifest, candidate, invalid)


def test_shared_result_flows_through_the_unchanged_contract(tmp_path: Path) -> None:
    source_manifest, candidate, _ = _fixture(tmp_path)
    oracle = _load_oracle(source_manifest.repository_root / "oracle.py")

    validation = validate(source_manifest, candidate, oracle)

    assert validation.status == "pass"
    assert validation.candidate_sha256 == candidate.sha256
    assert validation.source_manifest_sha256 == source_manifest.sha256


def test_verifier_reuses_candidate_package_integrity_stage(tmp_path: Path) -> None:
    source_manifest, candidate, facts = _fixture(tmp_path)
    (candidate.path / "content.tei.xml").write_bytes(b"<mutated/>\n")

    with pytest.raises(ValueError, match="^content.tei.xml bytes drifted$"):
        verify_mechanical_facts(source_manifest, candidate, facts)


def test_unchanged_contract_rejects_a_wrong_closure_fact_at_its_existing_stage(
    tmp_path: Path,
) -> None:
    source_manifest, candidate, _ = _fixture(
        tmp_path,
        validator_import_closure_sha256="c" * 64,
    )
    oracle = _load_oracle(source_manifest.repository_root / "oracle.py")

    with pytest.raises(
        ValueError, match="^oracle import-closure binding mismatch$"
    ):
        validate(source_manifest, candidate, oracle)
