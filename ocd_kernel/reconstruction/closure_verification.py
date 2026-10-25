"""Live verification of source-manifest producer and validator closures.

This module is deliberately an auditor, not a second closure implementation.
Each reconstruction route remains responsible for defining its independent
oracle closure.  The auditor discovers every v1 source manifest and invokes
the closure function implemented by that route, then compares the live result
with the manifest/profile declaration.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib
import inspect
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping, Sequence


_POLICY_ROLES = frozenset(
    {
        "independent-validation-policy",
        "validation-policy",
        "source-validation-policy",
    }
)
_SELF_ONLY_VALIDATORS = frozenset(
    {
        "build/tei/aa_hodge_outlines_oracle.py",
        "build/tei/gutenberg_catechisms_oracle.py",
        "build/tei/lib015_gutenberg_theology_oracle.py",
        "build/tei/lib016_hastings_dictionary_oracle.py",
        "build/tei/hodge_systematic_theology_vol_3_oracle.py",
    }
)
_SELF_ONLY_CANONICAL_VALIDATORS = frozenset(
    {
        "build/tei/gutenberg_proofread_selected_oracle.py",
        "build/tei/strong_systematic_theology_vol_3_oracle.py",
    }
)


@dataclass(frozen=True)
class ClosureCheck:
    manifest_path: str
    work_id: str
    kind: str
    implementation_path: str
    declared_sha256: str
    live_sha256: str
    strategy: str

    @property
    def matches(self) -> bool:
        return self.declared_sha256 == self.live_sha256


class ClosureAuditError(ValueError):
    """Incomplete audit, retaining checked routes and every unsupported route."""

    def __init__(self, checks: Sequence[ClosureCheck], failures: Sequence[str]) -> None:
        self.checks = tuple(checks)
        self.failures = tuple(failures)
        super().__init__(
            f"Producer closure audit incomplete: {len(checks)} checked, "
            f"{len(failures)} unsupported; " + "; ".join(failures)
        )


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _resolve_within_root(root: Path, logical_path: str, *, context: str) -> Path:
    root = root.resolve(strict=True)
    relative = Path(logical_path)
    if relative.is_absolute():
        raise ValueError(f"{context} path must be repository-relative: {logical_path}")
    resolved = (root / relative).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{context} path escapes repository: {logical_path}") from exc
    return resolved


def discover_v1_source_manifests(root: Path) -> tuple[Path, ...]:
    root = root.resolve(strict=True)
    manifests = []
    for path in (root / "sources").rglob("*source-manifest.json"):
        record = _load_json(path)
        if record.get("contract") == "ocd-source-manifest-v1":
            manifests.append(path.resolve(strict=True))
    return tuple(sorted(manifests, key=lambda item: item.relative_to(root).as_posix()))


def _module(root: Path, implementation_path: str) -> ModuleType:
    path = (root / implementation_path).resolve(strict=True)
    path.relative_to(root)
    if path.suffix != ".py":
        raise ValueError(f"closure implementation is not Python: {implementation_path}")
    name = ".".join(path.relative_to(root).with_suffix("").parts)
    module = importlib.import_module(name)
    loaded = Path(inspect.getsourcefile(module) or "").resolve(strict=True)
    if not loaded.samefile(path):
        raise ValueError(f"runtime module shadow for {implementation_path}: {loaded}")
    return module


def _policy(root: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    authorities = record.get("authorities")
    if not isinstance(authorities, list):
        return {}
    matches = [
        item
        for item in authorities
        if isinstance(item, dict) and item.get("role") in _POLICY_ROLES
    ]
    if not matches:
        matches = [
            item
            for item in authorities
            if isinstance(item, dict)
            and isinstance(item.get("role"), str)
            and "policy" in item["role"]
        ]
    if len(matches) > 1:
        raise ValueError(f"ambiguous validation policy for {record.get('work_id')}")
    if not matches:
        return {}
    return _load_json(
        _resolve_within_root(
            root,
            str(matches[0]["path"]),
            context="validation policy authority",
        )
    )


def _forbidden(policy: Mapping[str, Any]) -> tuple[str, ...]:
    for key in (
        "forbidden_import_prefixes",
        "oracle_forbidden_import_prefixes",
        "forbidden_imports",
    ):
        value = policy.get(key)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return tuple(value)
    return ()


def _result_digest(result: object) -> str:
    if _is_digest(result):
        return str(result)
    if isinstance(result, tuple) and result and _is_digest(result[0]):
        return str(result[0])
    raise TypeError(f"closure function returned an unsupported result: {type(result).__name__}")


def _records_digest(module: ModuleType, records: object) -> str:
    digest_function = getattr(module, "_digest", None)
    if callable(digest_function):
        value = digest_function(records)
        if _is_digest(value):
            return str(value)
    sha_function = getattr(module, "_sha", None)
    canonical_function = getattr(module, "_canonical", None)
    if callable(sha_function) and callable(canonical_function):
        value = sha_function(canonical_function(records))
        if _is_digest(value):
            return str(value)
    raise TypeError(f"{module.__name__} exposes records without a digest convention")


def _call_validator_closure(
    root: Path,
    implementation_path: str,
    record: Mapping[str, Any],
    *,
    manifest_path: Path | None = None,
) -> tuple[str, str]:
    module = _module(root, implementation_path)
    policy = _policy(root, record)
    entry = (root / implementation_path).resolve(strict=True)

    if implementation_path == "build/tei/lib062_six_catechisms_oracle.py":
        records = module.family.repository_import_closure(root, entry)
        return _digest(_canonical(records)), "LIB-062 family repository closure"

    if implementation_path == "build/tei/web_eng_oracle.py":
        # L596 attests the oracle implementation bytes as its closure.
        return _digest(entry.read_bytes()), "L596 oracle implementation bytes"

    preparation_path = {
        "build/tei/npnf109_work_oracle.py": "build/tools/prepare_npnf109_work_candidates.py",
        "build/tei/npnf113_work_oracle.py": "build/tools/prepare_npnf113_work_candidates.py",
    }.get(implementation_path)
    if preparation_path is not None:
        # These closures are sealed by the preparer; the oracle returns its declaration.
        preparation = _module(root, preparation_path)
        if preparation.ORACLE.as_posix() != implementation_path:
            raise ValueError("NPNF work preparation oracle route differs")
        paths = (preparation.ORACLE, preparation.SOURCE_RULES,
                 Path("ocd_kernel/reconstruction/contract.py"))
        records = [{"path": path.as_posix(), "sha256": _digest(
            _resolve_within_root(root, path, context="NPNF work preparation closure").read_bytes()
        )} for path in paths]
        return _result_digest(preparation._sha(preparation._json(records))), "NPNF work preparation closure"

    if implementation_path in {
        "build/tei/npnf103_work_oracle.py",
        "build/tei/npnf104_work_oracle.py",
        "build/tei/npnf105_work_oracle.py",
        "build/tei/npnf205_work_oracle.py",
        "build/tei/npnf206_work_oracle.py",
    }:
        # These readers hash ordered policy rows inline with their own serializer.
        label = Path(implementation_path).stem.removesuffix("_work_oracle").upper()
        paths = policy.get("closure_inputs")
        if (not isinstance(paths, list) or not paths
                or any(not isinstance(path, str) for path in paths)
                or len(set(paths)) != len(paths)):
            raise ValueError(f"{label} validator closure inputs are invalid")
        records = []
        for logical in paths:
            relative = Path(logical)
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != logical:
                raise ValueError(f"{label} validator closure path must be repository-relative")
            path = _resolve_within_root(root, logical, context=f"{label} validator closure")
            records.append({"path": logical, "sha256": _digest(path.read_bytes())})
        return _result_digest(module._sha(module._json(records))), f"{label} policy closure rows"

    # New retained routes expose their own closure calculation in these forms.
    function = getattr(module, "_import_closure_sha256", None)
    if callable(function) and tuple(inspect.signature(function).parameters) in {("repository_root",), ("root",)}:
        return _result_digest(function(root)), "_import_closure_sha256(root)"
    if callable(function) and not inspect.signature(function).parameters:
        return _result_digest(function()), "_import_closure_sha256()"

    function = getattr(module, "_closure_sha", None)
    if callable(function) and not inspect.signature(function).parameters:
        return _result_digest(function()), "_closure_sha()"

    function = getattr(module, "_local_closure", None)
    if callable(function) and tuple(inspect.signature(function).parameters) == ("root", "policy"):
        return _result_digest(function(root, policy)), "_local_closure(root, policy)"

    function = getattr(module, "closure_digest", None)
    if callable(function) and tuple(inspect.signature(function).parameters) == ("root", "policy"):
        return _result_digest(function(root, policy)), "closure_digest(root, policy)"
    if callable(function) and tuple(inspect.signature(function).parameters) == ("root",):
        return _result_digest(function(root)), "closure_digest(root)"
    if callable(function) and not inspect.signature(function).parameters:
        return _result_digest(function()), "closure_digest()"

    function = getattr(module, "_closure_digest", None)
    if callable(function):
        parameters = tuple(inspect.signature(function).parameters.values())
        names = tuple(parameter.name for parameter in parameters)
        records = getattr(module, "_closure_records", None)
        if names == ("rows",) and callable(records) and not inspect.signature(records).parameters:
            return _result_digest(function(records())), "_closure_digest(_closure_records())"
        if not names:
            return _result_digest(function()), "_closure_digest()"
        if names == ("root",):
            return _result_digest(function(root)), "_closure_digest(root)"
        if names == ("policy", "repository_root"):
            return _result_digest(function(policy, root)), "_closure_digest(policy, root)"
        if len(names) >= 2 and names[:2] == ("root", "policy") and all(
            parameter.default is not inspect.Parameter.empty for parameter in parameters[2:]
        ):
            return _result_digest(function(root, policy)), "_closure_digest(root, policy)"
        if len(names) == 2 and names[1] in {"route", "entry"}:
            return _result_digest(function(root, entry)), "_closure_digest(root, entry)"
        if len(names) == 3 and names[1:] == ("entry", "forbidden"):
            return (
                _result_digest(function(root, entry, _forbidden(policy))),
                "_closure_digest(root, entry, forbidden)",
            )

    function = getattr(module, "_closure", None)
    if callable(function):
        parameters = tuple(inspect.signature(function).parameters.values())
        names = tuple(parameter.name for parameter in parameters)
        required = tuple(
            parameter.name
            for parameter in parameters
            if parameter.default is inspect.Parameter.empty
        )
        if required in {("root",), ("repository_root",), ("repo",)}:
            return _result_digest(function(root)), "_closure(root)"
        if required == ("repo", "forbidden"):
            return _result_digest(function(root, _forbidden(policy))), "_closure(root, forbidden)"
        if required == ("root", "entry", "forbidden"):
            result = function(root, entry, _forbidden(policy))
            if implementation_path in {"build/tei/luther_galatians_oracle.py",
                                       "build/tei/luther_galatians_native_v2_oracle.py"}:
                # This oracle hashes _stable(records): sorted compact UTF-8 JSON
                # with a final newline. Canonicalize independently of the producer.
                return _digest(_canonical(result)), "Luther canonical closure records"
            digest_function = getattr(module, "_digest", None) or getattr(module, "_sha", None)
            canonical = getattr(module, "_canonical", None)
            if not callable(digest_function) or not callable(canonical):
                raise TypeError(f"{implementation_path} has records-only closure without digest helpers")
            return str(digest_function(canonical(result))), "_closure(root, entry, forbidden)"

    for name in ("_import_closure", "_repository_closure", "_import_closure_digest", "_project_closure", "closure", "closure_sha", "import_closure_sha256"):
        function = getattr(module, name, None)
        if callable(function) and tuple(inspect.signature(function).parameters) == ("root",):
            return _result_digest(function(root)), f"{name}(root)"

    if implementation_path == "build/tei/law_serious_call_oracle.py":
        if manifest_path is None:
            raise ValueError("law-serious-call closure requires its source manifest")
        from ocd_kernel.reconstruction.contract import SourceManifest

        source_manifest = SourceManifest.load(manifest_path, repository_root=root)
        function = getattr(module, "_import_closure_digest")
        return _result_digest(function(source_manifest)), "law source-manifest closure"

    if implementation_path == "build/tei/drummond_greatest_thing_37c135_oracle.py":
        if manifest_path is None:
            raise ValueError("37c-135 closure requires its source manifest")
        from ocd_kernel.reconstruction.contract import SourceManifest

        source_manifest = SourceManifest.load(manifest_path, repository_root=root)
        base_oracle = module._load_base_oracle(source_manifest)
        return _result_digest(module._closure_digest(source_manifest, base_oracle)), "37c-135 local-plus-base closure"

    if implementation_path == "build/tei/npnf113_lib041_oracle.py":
        authorities = [item for item in record["authorities"] if item.get("name") == "oracle-import-closure"]
        if len(authorities) != 1:
            raise ValueError("LIB-041 oracle closure authority is missing or ambiguous")
        path = _resolve_within_root(root, authorities[0]["path"], context="LIB-041 oracle closure")
        content = path.read_bytes()
        closure = _load_json(path)
        module._verify_runtime_closure(root, closure)
        if closure.get("contract") != "ocd-lib041-oracle-import-closure-v1" or closure.get("oracle_sha256") != _digest(entry.read_bytes()):
            raise ValueError("LIB-041 oracle closure implementation drifted")
        return _digest(content), "LIB-041 verified runtime closure"

    function = getattr(module, "_import_closure", None)
    stable_json = getattr(module, "_stable_json", None)
    digest = getattr(module, "_digest", None)
    if callable(function) and callable(stable_json) and callable(digest) and tuple(inspect.signature(function).parameters) == ("root", "entry", "forbidden"):
        return _result_digest(digest(stable_json(function(root, entry, _forbidden(policy))))), "_import_closure(root, entry, forbidden)"

    implementation_sha = _digest(entry.read_bytes())
    if implementation_path in _SELF_ONLY_CANONICAL_VALIDATORS:
        return (
            _digest(_canonical([{"path": implementation_path, "sha256": implementation_sha}])),
            "self-only canonical implementation",
        )
    declared = record.get("validator", {}).get("import_closure_sha256")
    if (
        implementation_path in _SELF_ONLY_VALIDATORS
        and declared == record.get("validator", {}).get("implementation_sha256")
    ):
        return implementation_sha, "self-only implementation"
    raise NotImplementedError(f"no live validator closure adapter for {implementation_path}")


def check_validator_closures(
    root: Path,
    *,
    excluded_manifest_paths: Sequence[str] = (),
) -> tuple[ClosureCheck, ...]:
    root = root.resolve(strict=True)
    excluded = frozenset(Path(item).as_posix() for item in excluded_manifest_paths)
    checks = []
    for manifest in discover_v1_source_manifests(root):
        relative = manifest.relative_to(root).as_posix()
        if relative in excluded:
            continue
        checks.append(check_validator_manifest_closure(root, relative))
    return tuple(checks)


def check_validator_manifest_closure(root: Path, manifest_path: str | Path) -> ClosureCheck:
    """Check one explicitly selected source manifest without scanning its peers."""

    root = root.resolve(strict=True)
    logical_path = Path(manifest_path)
    if logical_path.is_absolute() or ".." in logical_path.parts:
        raise ValueError("source manifest path must be repository-relative")
    manifest = _resolve_within_root(root, logical_path, context="source manifest")
    relative = manifest.relative_to(root).as_posix()
    parts = manifest.relative_to(root).parts
    if not (parts[0] == "sources" or parts[:3] == ("tests", "fixtures", "reconstruction-runtime")):
        raise ValueError("source manifest path is outside sources/ and tests/fixtures/reconstruction-runtime/")
    if re.fullmatch(r".*source-manifest(?:\.v[1-9][0-9]*|\.canonical-v[1-9][0-9]*)?\.json", manifest.name) is None:
        raise ValueError(f"not a source-manifest.json file or numbered version: {relative}")
    record = _load_json(manifest)
    if record.get("contract") != "ocd-source-manifest-v1":
        raise ValueError(f"source manifest contract mismatch: {relative}")
    validator = record.get("validator")
    if not isinstance(validator, dict):
        raise ValueError(f"manifest validator is invalid: {relative}")
    implementation_path = str(validator["implementation_path"])
    declared = str(validator["import_closure_sha256"])
    live, strategy = _call_validator_closure(
        root,
        implementation_path,
        record,
        manifest_path=manifest,
    )
    return ClosureCheck(
        manifest_path=relative,
        work_id=str(record.get("work_id", record.get("source_id", manifest.stem))),
        kind="validator",
        implementation_path=implementation_path,
        declared_sha256=declared,
        live_sha256=live,
        strategy=strategy,
    )


def _profile_owner(
    root: Path,
    declaration: Path,
    manifests: Sequence[Path],
) -> tuple[Path, dict[str, Any]]:
    logical = declaration.relative_to(root).as_posix()
    owners = []
    for manifest in manifests:
        record = _load_json(manifest)
        authorities = record.get("authorities")
        if isinstance(authorities, list) and any(
            isinstance(item, dict) and item.get("path") == logical
            for item in authorities
        ):
            owners.append((manifest, record))
    if not owners:
        raise ValueError(f"producer closure profile has no source-manifest owner: {logical}")
    converter_paths = {str(record["converter"]["implementation_path"]) for _, record in owners}
    validator_paths = {str(record["validator"]["implementation_path"]) for _, record in owners}
    if len(converter_paths) != 1 or len(validator_paths) != 1:
        raise ValueError(f"producer closure profile has inconsistent owners: {logical}")
    return owners[0]


def _lib028_producer_closure(root: Path, record: Mapping[str, Any]) -> str:
    authorities = record.get("authorities")
    if not isinstance(authorities, list):
        raise ValueError("LIB-028 authorities are invalid")
    matches = [
        item
        for item in authorities
        if isinstance(item, dict) and item.get("name") == "tei-p5-xsd-closure"
    ]
    if len(matches) != 1:
        raise ValueError("LIB-028 producer closure authority is missing or ambiguous")
    closure = _load_json(
        _resolve_within_root(
            root,
            str(matches[0]["path"]),
            context="LIB-028 closure authority",
        )
    )
    producer = closure.get("producer_runtime")
    if not isinstance(producer, dict) or not isinstance(producer.get("members"), list):
        raise ValueError("LIB-028 producer runtime closure is invalid")
    live = []
    for member in producer["members"]:
        if not isinstance(member, dict) or set(member) != {"path", "bytes", "sha256"}:
            raise ValueError("LIB-028 producer runtime closure member is invalid")
        logical = str(member["path"])
        content = _resolve_within_root(
            root, logical, context="LIB-028 producer closure member"
        ).read_bytes()
        live.append({"path": logical, "bytes": len(content), "sha256": _digest(content)})
    return _digest(_canonical(live))


def _call_producer_closure(
    root: Path,
    implementation_path: str,
    validator_path: str,
    record: Mapping[str, Any],
) -> tuple[str, str]:
    module = _module(root, implementation_path)
    policy = _policy(root, record)
    entry = (root / implementation_path).resolve(strict=True)

    if implementation_path == "build/tei/lib028_reconstruction.py":
        return _lib028_producer_closure(root, record), "LIB-028 governed runtime closure"

    function = getattr(module, "_producer_import_closure_sha256", None)
    if callable(function) and not inspect.signature(function).parameters:
        return _result_digest(function()), "_producer_import_closure_sha256()"

    function = getattr(module, "_producer_closure", None)
    if callable(function):
        return _result_digest(function(root)), "_producer_closure(root)"

    function = getattr(module, "_producer_closure_digest", None)
    if callable(function):
        return _result_digest(function(root)), "_producer_closure_digest(root)"

    function = getattr(module, "_closure_digest", None)
    if callable(function):
        names = tuple(inspect.signature(function).parameters)
        if names == ("root", "policy"):
            return _result_digest(function(root, policy)), "_closure_digest(root, policy)"
        if names == ("root", "route"):
            return _result_digest(function(root, entry)), "_closure_digest(root, entry)"
        if names == ("root", "entry", "forbidden"):
            return (
                _result_digest(function(root, entry, _forbidden(policy))),
                "_closure_digest(root, entry, forbidden)",
            )

    function = getattr(module, "_closure", None)
    if callable(function):
        names = tuple(inspect.signature(function).parameters)
        if names in (("root",), ("repository_root",)):
            return _result_digest(function(root)), "_closure(root)"
        if names[:2] == ("root", "entry"):
            return _records_digest(module, function(root, entry)), "_closure(root, entry)"

    oracle = _module(root, validator_path)
    function = getattr(oracle, "_closure_digest", None)
    if callable(function) and tuple(inspect.signature(function).parameters) == ("root", "route"):
        return _result_digest(function(root, entry)), "oracle _closure_digest(root, route) for producer"
    function = getattr(oracle, "_import_closure", None)
    stable_json = getattr(oracle, "_stable_json", None)
    digest = getattr(oracle, "_digest", None)
    if callable(function) and callable(stable_json) and callable(digest) and tuple(inspect.signature(function).parameters) == ("root", "entry", "forbidden"):
        forbidden = policy.get("producer_forbidden_import_prefixes", [])
        if not isinstance(forbidden, list) or not all(isinstance(value, str) for value in forbidden):
            raise ValueError("producer forbidden import prefixes are invalid")
        return _result_digest(digest(stable_json(function(root, entry, tuple(forbidden))))), "oracle _import_closure for producer"
    function = getattr(oracle, "_repository_import_closure", None)
    if callable(function):
        records = function(root, entry, _forbidden(policy))
        return _records_digest(oracle, records), "oracle repository closure for producer"
    function = getattr(oracle, "_closure", None)
    if callable(function):
        parameters = tuple(inspect.signature(function).parameters.values())
        if len(parameters) == 1 and parameters[0].name in {"root", "repository_root"}:
            return _result_digest(function(root)), "oracle closure for producer"
        if len(parameters) >= 2 and parameters[1].default is not inspect.Parameter.empty:
            return _result_digest(function(root, entry)), "oracle closure for producer"
    raise NotImplementedError(f"no live producer closure adapter for {implementation_path}")


def check_producer_closures(
    root: Path,
    *,
    excluded_manifest_paths: Sequence[str] = (),
) -> tuple[ClosureCheck, ...]:
    root = root.resolve(strict=True)
    manifests = discover_v1_source_manifests(root)
    excluded = frozenset(Path(item).as_posix() for item in excluded_manifest_paths)
    declarations = []
    for path in (root / "sources").rglob("*.json"):
        record = json.loads(path.read_bytes())
        if isinstance(record, dict) and _is_digest(record.get("producer_import_closure_sha256")):
            declarations.append((path.resolve(strict=True), record))

    checks = []
    failures = []
    for declaration, declared_record in sorted(
        declarations, key=lambda item: item[0].relative_to(root).as_posix()
    ):
        logical = declaration.relative_to(root).as_posix()
        if declared_record.get("contract") == "ocd-source-manifest-v1":
            manifest, record = declaration, declared_record
        else:
            manifest, record = _profile_owner(root, declaration, manifests)
        manifest_logical = manifest.relative_to(root).as_posix()
        if manifest_logical in excluded:
            continue
        implementation_path = str(record["converter"]["implementation_path"])
        validator_path = str(record["validator"]["implementation_path"])
        try:
            live, strategy = _call_producer_closure(
                root, implementation_path, validator_path, record
            )
        except NotImplementedError as exc:
            failures.append(f"{logical}: {exc}")
            continue
        checks.append(
            ClosureCheck(
                manifest_path=logical,
                work_id=str(record.get("work_id", record.get("source_id", manifest.stem))),
                kind="producer",
                implementation_path=implementation_path,
                declared_sha256=str(declared_record["producer_import_closure_sha256"]),
                live_sha256=live,
                strategy=strategy,
            )
        )
    if failures:
        raise ClosureAuditError(checks, failures)
    return tuple(checks)


__all__ = (
    "ClosureAuditError",
    "ClosureCheck",
    "check_validator_manifest_closure",
    "check_producer_closures",
    "check_validator_closures",
    "discover_v1_source_manifests",
)
