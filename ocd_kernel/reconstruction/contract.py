"""Small authority-bound reconstruction seam.

The seam constructs immutable, nonaccepted candidate packages.  Acceptance,
publication, and canonical storage deliberately live elsewhere.
"""

from __future__ import annotations

from ocd_kernel.lib.path_io import io_path, resolve_path, io_iterdir

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
import hashlib
import inspect
from itertools import repeat
import json
import os
from pathlib import Path
import platform
import sys
from types import MappingProxyType
from typing import Callable, Mapping

from jsonschema import Draft202012Validator

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path, storage_read_phase


_CANDIDATE_MEMBERS = frozenset(
    {
        "content.tei.xml",
        "source-accountability.json",
        "provenance.json",
        "unresolved.jsonl",
        "README.source.md",
    }
)
_COMPLETE_MEMBERS = _CANDIDATE_MEMBERS | {"manifest.json"}
_HEX = frozenset("0123456789abcdef")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _contained(root: Path, logical_path: object, label: str) -> Path:
    if not isinstance(logical_path, str) or not logical_path:
        raise ValueError(f"{label} path is missing")
    lexical = Path(logical_path)
    if lexical.is_absolute() or ".." in lexical.parts:
        raise ValueError(f"{label} path must be repository-relative")
    # Validate the lexical repository path before resolving. Configured storage
    # roots (notably raw/) may intentionally resolve outside the code checkout.
    try:
        resolved = resolve_repo_path(root, logical_path, strict=True)
    except StorageTopologyError as error:
        raise ValueError(f"{label} path is invalid: {error}") from error
    # Preserve the legacy authority accessor's I/O-ready deep Windows path.
    # Manifest and package identities continue to use ordinary logical paths.
    if os.name == "nt" and len(str(resolved)) >= 248:
        return io_path(resolved)
    return resolved


@storage_read_phase()
def _verify_authority_bytes(root: Path, authorities: tuple) -> None:
    for authority in authorities:
        name = authority["name"]
        path = _contained(root, authority.get("path"), name)
        content = io_path(path).read_bytes()
        if authority.get("bytes") != len(content) or authority.get("sha256") != _sha(content):
            raise ValueError(f"{name} authority bytes drifted")


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _callable_source_path(value: object, label: str) -> Path:
    try:
        source_path = inspect.getsourcefile(value)
        inspect.getsource(value)
        if source_path is None:
            raise ValueError(f"{label} callable provenance has no source file")
        return resolve_path(Path(source_path), strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} callable provenance is not inspectable") from exc


def _validation_authority_bindings(source_manifest: "SourceManifest") -> dict[str, str]:
    """Derive every oracle digest from explicit, family-neutral authority roles."""

    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authorities are invalid")
    by_role: dict[str, list[Mapping[str, object]]] = {}
    for item in authorities:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise ValueError("source manifest authority role is invalid")
        by_role.setdefault(item["role"], []).append(item)

    source_members = by_role.get("primary-source", [])
    if not source_members:
        raise ValueError("source manifest requires primary-source authority members")
    member_records = sorted(
        (
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "bytes": item.get("bytes"),
                "sha256": item.get("sha256"),
            }
            for item in source_members
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    if len({item["path"] for item in member_records}) != len(member_records):
        raise ValueError("primary-source authority member paths must be unique")
    if len(member_records) == 1:
        source_sha256 = member_records[0]["sha256"]
        if not _is_digest(source_sha256):
            raise ValueError("primary-source authority digest is invalid")
    else:
        source_sha256 = _sha(
            _canonical(
                {"contract": "ocd-source-member-set-v1", "members": member_records}
            )
        )

    singleton_roles = {
        "profile_sha256": "complete-source-feature-profile",
        "package_schema_sha256": "candidate-package-schema",
        "xsd_sha256": "tei-validation-schema",
        "policy_sha256": "independent-validation-policy",
    }
    bindings = {"source_sha256": source_sha256}
    for field, role in singleton_roles.items():
        matches = by_role.get(role, [])
        if len(matches) != 1 or not _is_digest(matches[0].get("sha256")):
            raise ValueError(f"source manifest requires exactly one {role} authority")
        bindings[field] = str(matches[0]["sha256"])

    package_schema = source_manifest.record.get("package_schema")
    package_authority = by_role["candidate-package-schema"][0]
    if not isinstance(package_schema, Mapping) or (
        package_authority.get("path") != package_schema.get("path")
        or package_authority.get("sha256") != package_schema.get("sha256")
    ):
        raise ValueError("candidate-package-schema authority binding mismatch")
    return bindings


def _runtime_binding() -> str:
    return (
        f"{platform.python_implementation()} {platform.python_version()} "
        f"({resolve_path(Path(sys.executable), strict=True)})"
    )


def _safe_candidate_destination(source_manifest: "SourceManifest", destination: str | Path) -> Path:
    requested = Path(destination)
    lexical = Path(os.path.abspath(os.fspath(requested)))
    try:
        lexical.relative_to(source_manifest.repository_root)
    except ValueError:
        pass
    else:
        raise ValueError("safe candidate destination must be outside the repository")

    output = resolve_path(lexical, strict=False)
    protected_roots = {
        resolve_path(source_manifest.repository_root / name, strict=False)
        for name in (
            "raw",
            "data",
            "ir",
            "reports",
            "exports",
            "acceptance",
            "publication",
        )
    }
    for protected_root in protected_roots:
        try:
            output.relative_to(protected_root)
        except ValueError:
            continue
        raise ValueError("safe candidate destination resolves inside governed storage")
    if not io_path(output.parent).is_dir():
        raise ValueError("safe candidate destination parent must already exist")
    if io_path(output).exists() and (not io_path(output).is_dir() or any(io_iterdir(output))):
        raise ValueError("safe candidate destination must be an empty directory")
    return output


@dataclass(frozen=True, slots=True)
class SourceManifest:
    """Exact source-local authority manifest loaded from one repository root."""

    path: Path
    repository_root: Path
    sha256: str
    _record: Mapping[str, object]
    _authority_index: tuple[object, Mapping[str, Mapping[str, object]]] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    @classmethod
    def load(cls, path: str | Path, *, repository_root: str | Path) -> "SourceManifest":
        root = resolve_path(Path(repository_root), strict=True)
        manifest_path = resolve_path(Path(path), strict=True)
        try:
            manifest_path.relative_to(root)
        except ValueError as exc:
            raise ValueError("source manifest is outside repository root") from exc
        content = io_path(manifest_path).read_bytes()
        record = _strict_json(content, "source manifest")
        if record.get("contract") != "ocd-source-manifest-v1":
            raise ValueError("source manifest contract mismatch")
        instance = cls(manifest_path, root, _sha(content), _freeze(record))
        instance.verify()
        # Index verified immutable metadata; physical paths remain fresh on every use.
        object.__setattr__(instance, "_authority_index", (
            instance._record,
            MappingProxyType({item["name"]: item for item in instance._record["authorities"]}),
        ))
        return instance

    @property
    def record(self) -> Mapping[str, object]:
        return self._record

    def authority_path(self, name: str) -> Path:
        authorities = self._record.get("authorities")
        if not isinstance(authorities, tuple):
            raise ValueError("source manifest authorities are invalid")
        index = getattr(self, "_authority_index", None)
        if index is not None and index[0] is self._record and type(name) is str:
            authority = index[1].get(name)
            if authority is None:
                raise ValueError(f"source manifest has no {name!r} authority")
            return _contained(self.repository_root, authority.get("path"), name)
        for authority in authorities:
            if isinstance(authority, Mapping) and authority.get("name") == name:
                return _contained(self.repository_root, authority.get("path"), name)
        raise ValueError(f"source manifest has no {name!r} authority")

    def verify(self) -> None:
        if _sha(io_path(self.path).read_bytes()) != self.sha256:
            raise ValueError("source manifest bytes drifted")
        authorities = self._record.get("authorities")
        if not isinstance(authorities, tuple) or not authorities:
            raise ValueError("source manifest authorities must be nonempty")
        names: set[str] = set()
        for authority in authorities:
            if not isinstance(authority, Mapping):
                raise ValueError("source manifest authority is not an object")
            name = authority.get("name")
            if not isinstance(name, str) or not name or name in names:
                raise ValueError("source manifest authority names are invalid")
            names.add(name)
        if len(authorities) > 128:
            # Group small files to limit scheduling overhead; verify every member fresh.
            chunks = (authorities[start:start + 128] for start in range(0, len(authorities), 128))
            with ThreadPoolExecutor(max_workers=4) as executor:
                for _ in executor.map(_verify_authority_bytes, repeat(self.repository_root), chunks):
                    pass
        else:
            _verify_authority_bytes(self.repository_root, authorities)
        converter = self._record.get("converter")
        if not isinstance(converter, Mapping):
            raise ValueError("source manifest converter binding is invalid")
        if not isinstance(converter.get("callable"), str) or not converter["callable"]:
            raise ValueError("source manifest converter callable binding is invalid")
        implementation = _contained(
            self.repository_root,
            converter.get("implementation_path"),
            "converter implementation",
        )
        if not _is_digest(converter.get("implementation_sha256")) or converter.get(
            "implementation_sha256"
        ) != _sha(io_path(implementation).read_bytes()):
            raise ValueError("converter implementation authority drifted")
        validator = self._record.get("validator")
        if not isinstance(validator, Mapping):
            raise ValueError("source manifest validator binding is invalid")
        if (
            not isinstance(validator.get("callable"), str)
            or not validator["callable"]
            or not _is_digest(validator.get("import_closure_sha256"))
        ):
            raise ValueError("source manifest validator callable or closure binding is invalid")
        validator_path = _contained(
            self.repository_root,
            validator.get("implementation_path"),
            "validator implementation",
        )
        if not _is_digest(validator.get("implementation_sha256")) or validator.get(
            "implementation_sha256"
        ) != _sha(io_path(validator_path).read_bytes()):
            raise ValueError("validator implementation authority drifted")
        schema = self._record.get("package_schema")
        if not isinstance(schema, Mapping):
            raise ValueError("source manifest package schema binding is invalid")
        schema_path = _contained(
            self.repository_root, schema.get("path"), "candidate package schema"
        )
        if not _is_digest(schema.get("sha256")) or schema.get("sha256") != _sha(
            io_path(schema_path).read_bytes()
        ):
            raise ValueError("candidate package schema authority drifted")


@dataclass(frozen=True, slots=True)
class CandidatePackage:
    """Read-only handle to a sealed six-member candidate directory."""

    path: Path
    sha256: str
    _manifest: Mapping[str, object]

    @classmethod
    def load(cls, path: str | Path) -> "CandidatePackage":
        root = resolve_path(Path(path), strict=True)
        if not io_path(root).is_dir():
            raise ValueError("candidate path is not a directory")
        observed = {item.name for item in io_iterdir(root) if io_path(item).is_file()}
        if observed != _COMPLETE_MEMBERS or any(io_path(item).is_dir() for item in io_iterdir(root)):
            raise ValueError("candidate must contain exactly six flat members")
        content = (io_path(root / "manifest.json")).read_bytes()
        manifest = _strict_json(content, "candidate manifest")
        package = cls(root, _sha(content), _freeze(manifest))
        package.verify_integrity()
        return package

    @property
    def manifest(self) -> Mapping[str, object]:
        return self._manifest

    @property
    def member_names(self) -> tuple[str, ...]:
        return tuple(sorted(_COMPLETE_MEMBERS))

    def member_bytes(self, name: str) -> bytes:
        if name not in _COMPLETE_MEMBERS:
            raise ValueError(f"unknown candidate member {name!r}")
        self.verify_integrity()
        return (io_path(self.path / name)).read_bytes()

    def verify_integrity(self) -> None:
        observed = {item.name for item in io_iterdir(self.path) if io_path(item).is_file()}
        if observed != _COMPLETE_MEMBERS or any(io_path(item).is_dir() for item in io_iterdir(self.path)):
            raise ValueError("candidate member set drifted")
        manifest_content = (io_path(self.path / "manifest.json")).read_bytes()
        if _sha(manifest_content) != self.sha256:
            raise ValueError("manifest.json bytes drifted")
        manifest = _strict_json(manifest_content, "candidate manifest")
        if manifest.get("contract") != "ocd-candidate-package-v1":
            raise ValueError("candidate manifest contract mismatch")
        members = manifest.get("members")
        if not isinstance(members, list) or len(members) != len(_CANDIDATE_MEMBERS):
            raise ValueError("candidate manifest member inventory is incomplete")
        names: set[str] = set()
        for member in members:
            if not isinstance(member, dict):
                raise ValueError("candidate manifest member record is invalid")
            name = member.get("name")
            if not isinstance(name, str) or name not in _CANDIDATE_MEMBERS or name in names:
                raise ValueError("candidate manifest member names are invalid")
            names.add(name)
            content = (io_path(self.path / name)).read_bytes()
            if member.get("bytes") != len(content) or member.get("sha256") != _sha(content):
                raise ValueError(f"{name} bytes drifted")
        if names != _CANDIDATE_MEMBERS:
            raise ValueError("candidate manifest member inventory mismatch")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    status: str
    candidate_sha256: str
    source_manifest_sha256: str
    attestation: Mapping[str, object]
    findings: tuple[str, ...]
    sha256: str


@dataclass(frozen=True, slots=True)
class ReviewView:
    source_manifest: SourceManifest
    candidate: CandidatePackage
    validation: ValidationReport
    candidate_sha256: str
    member_names: tuple[str, ...]

    def member_bytes(self, name: str) -> bytes:
        return self.candidate.member_bytes(name)


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate_sha256: str
    validation_sha256: str
    disposition: str
    rationale: str
    decided_by: str
    decided_at: str

    @classmethod
    def create(
        cls,
        review: ReviewView,
        *,
        disposition: str,
        rationale: str,
        decided_by: str,
        decided_at: str,
    ) -> "CandidateDecision":
        values = (disposition, rationale, decided_by, decided_at)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("candidate decision fields must be nonempty strings")
        return cls(
            review.candidate_sha256,
            review.validation.sha256,
            disposition,
            rationale,
            decided_by,
            decided_at,
        )


def reconstruct(
    source_manifest: SourceManifest,
    destination: str | Path,
    implementation: Callable[[SourceManifest], Mapping[str, bytes]],
) -> CandidatePackage:
    """Construct and seal a candidate without canonical or acceptance writes."""

    source_manifest.verify()
    converter = source_manifest.record["converter"]
    assert isinstance(converter, Mapping)
    implementation_path = _callable_source_path(implementation, "converter")
    expected_path = _contained(
        source_manifest.repository_root,
        converter.get("implementation_path"),
        "converter implementation",
    )
    if (
        getattr(implementation, "converter_id", None) != converter.get("id")
        or getattr(implementation, "converter_version", None) != converter.get("version")
        or getattr(implementation, "__name__", None) != converter.get("callable")
        or not io_path(implementation_path).samefile(io_path(expected_path))
        or _sha(io_path(implementation_path).read_bytes()) != converter.get("implementation_sha256")
    ):
        raise ValueError("converter callable provenance mismatch")
    produced = implementation(source_manifest)
    if set(produced) != _CANDIDATE_MEMBERS or any(
        not isinstance(content, bytes) for content in produced.values()
    ):
        raise ValueError("converter must produce exactly five non-manifest members")
    member_records = [
        {"name": name, "bytes": len(produced[name]), "sha256": _sha(produced[name])}
        for name in sorted(produced)
    ]
    source_logical = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    manifest = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source_manifest": {"path": source_logical, "sha256": source_manifest.sha256},
        "converter": dict(converter),
        "package_schema": dict(source_manifest.record["package_schema"]),
        "members": member_records,
    }
    schema_binding = source_manifest.record["package_schema"]
    assert isinstance(schema_binding, Mapping)
    schema_path = _contained(
        source_manifest.repository_root,
        schema_binding["path"],
        "candidate package schema",
    )
    schema = _strict_json(io_path(schema_path).read_bytes(), "candidate package schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=str)
    if errors:
        raise ValueError(f"candidate manifest schema failure: {errors[0].message}")
    output = _safe_candidate_destination(source_manifest, destination)
    io_path(output).mkdir(exist_ok=True)
    for name in sorted(produced):
        (io_path(output / name)).write_bytes(produced[name])
    (io_path(output / "manifest.json")).write_bytes(_canonical(manifest))
    return CandidatePackage.load(output)


def validate(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    oracle: Callable[[SourceManifest, CandidatePackage], Mapping[str, object]],
) -> ValidationReport:
    """Run a producer-independent oracle and bind its attestation."""

    with storage_read_phase():
        source_manifest.verify()
        candidate.verify_integrity()
        _verify_candidate_source_binding(source_manifest, candidate)
        expected_bindings = _validation_authority_bindings(source_manifest)
        validator = source_manifest.record["validator"]
        assert isinstance(validator, Mapping)
        oracle_path = _callable_source_path(oracle, "validator")
        expected_path = _contained(
            source_manifest.repository_root,
            validator.get("implementation_path"),
            "validator implementation",
        )
        if (
            getattr(oracle, "oracle_id", None) != validator.get("id")
            or getattr(oracle, "oracle_version", None) != validator.get("version")
            or getattr(oracle, "__name__", None) != validator.get("callable")
            or not io_path(oracle_path).samefile(io_path(expected_path))
            or _sha(io_path(oracle_path).read_bytes()) != validator.get("implementation_sha256")
        ):
            raise ValueError("validator callable provenance mismatch")
        result = dict(oracle(source_manifest, candidate))
        required = {
            "status",
            "oracle_id",
            "oracle_version",
            "implementation_sha256",
            "import_closure_sha256",
            "runtime",
            "source_manifest_sha256",
            "candidate_sha256",
            "profile_sha256",
            "package_schema_sha256",
            "source_sha256",
            "xsd_sha256",
            "policy_sha256",
            "result_sha256",
            "findings",
        }
        if set(result) != required:
            raise ValueError("oracle attestation shape mismatch")
        if result["status"] != "pass":
            raise ValueError("candidate validation failed")
        if result["source_manifest_sha256"] != source_manifest.sha256:
            raise ValueError("oracle source-manifest binding mismatch")
        if result["candidate_sha256"] != candidate.sha256:
            raise ValueError("oracle candidate binding mismatch")
        if (
            result["oracle_id"] != validator.get("id")
            or result["oracle_version"] != validator.get("version")
        ):
            raise ValueError("oracle identity or version binding mismatch")
        if result["implementation_sha256"] != validator.get("implementation_sha256"):
            raise ValueError("oracle implementation binding mismatch")
        if result["import_closure_sha256"] != validator.get("import_closure_sha256"):
            raise ValueError("oracle import-closure binding mismatch")
        if result["runtime"] != _runtime_binding():
            raise ValueError("oracle runtime binding mismatch")
        for name, expected in expected_bindings.items():
            if result[name] != expected:
                raise ValueError(f"oracle {name} authority binding mismatch")
        result_digest_record = {key: value for key, value in result.items() if key != "result_sha256"}
        if result["result_sha256"] != _sha(_canonical(result_digest_record)):
            raise ValueError("oracle result binding mismatch")
        findings = result["findings"]
        if not isinstance(findings, list) or any(not isinstance(item, str) for item in findings):
            raise ValueError("oracle findings are invalid")
        for name in (
            "implementation_sha256",
            "import_closure_sha256",
            "profile_sha256",
            "package_schema_sha256",
            "source_sha256",
            "xsd_sha256",
            "policy_sha256",
            "result_sha256",
        ):
            if not _is_digest(result[name]):
                raise ValueError(f"oracle {name} is invalid")
        report_record = {
            "contract": "ocd-validation-report-v1",
            "status": "pass",
            "candidate_sha256": candidate.sha256,
            "source_manifest_sha256": source_manifest.sha256,
            "attestation": result,
            "findings": findings,
        }
        return ValidationReport(
            "pass",
            candidate.sha256,
            source_manifest.sha256,
            _freeze(result),
            tuple(findings),
            _sha(_canonical(report_record)),
        )


def prepare_review(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    validation: ValidationReport,
) -> ReviewView:
    """Prepare an immutable, read-only source/candidate review shape.

    Source selection remains an explicit caller decision through the verified
    source manifest rather than an inferred property of the review.
    """

    source_manifest.verify()
    candidate.verify_integrity()
    _verify_candidate_source_binding(source_manifest, candidate)
    if (
        validation.status != "pass"
        or validation.candidate_sha256 != candidate.sha256
        or validation.source_manifest_sha256 != source_manifest.sha256
    ):
        raise ValueError("validation report does not bind this review")
    return ReviewView(
        source_manifest,
        candidate,
        validation,
        candidate.sha256,
        candidate.member_names,
    )


def _verify_candidate_source_binding(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> None:
    """Require the sealed package to name this exact source manifest."""

    source_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    binding = candidate.manifest.get("source_manifest")
    if (
        not isinstance(binding, Mapping)
        or binding.get("path") != source_path
        or binding.get("sha256") != source_manifest.sha256
        or candidate.manifest.get("source_id")
        != source_manifest.record.get("source_id")
    ):
        raise ValueError("candidate source manifest binding mismatch")
