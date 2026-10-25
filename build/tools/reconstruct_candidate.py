"""Generate and validate one nonaccepted reconstruction candidate.

This is a family-neutral handoff surface.  The source manifest owns the exact
converter and validator implementations; this tool owns no source-family
selection, acceptance, canonical storage, or publication behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable
import sys
from types import ModuleType
from typing import Mapping


_TOOL_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validation_sidecar_bytes(report: object, *, text_quality_sha256: str | None = None) -> bytes:
    report_record = {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": dict(report.attestation),
        "findings": list(report.findings),
    }
    report_bytes = _canonical(report_record).encode("utf-8")
    if _sha(report_bytes) != report.sha256:
        raise ValueError("validation report digest does not match its record")
    if text_quality_sha256 is not None:
        report_record["text_quality_sha256"] = text_quality_sha256
    return _canonical({**report_record, "report_sha256": report.sha256}).encode(
        "utf-8"
    )


def _repository_relative(root: Path, value: str, label: str) -> Path:
    lexical = Path(value)
    if lexical.is_absolute() or not lexical.parts or ".." in lexical.parts:
        raise ValueError(f"{label} must be a repository-relative path")
    resolved = (root / lexical).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} resolves outside the repository") from exc
    return resolved


def _load_bound_module(path: Path, *, role: str, digest: str) -> ModuleType:
    if path.suffix.casefold() != ".py" or _sha(path.read_bytes()) != digest:
        raise ValueError(f"{role} implementation path or digest drifted")
    module_name = f"_ocd_bound_{role}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"{role} implementation cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    loaded = Path(getattr(module, "__file__", "")).resolve(strict=True)
    if not loaded.samefile(path):
        raise ValueError(f"{role} implementation loaded from a shadow path")
    return module


def _bound_callable(
    root: Path,
    binding: Mapping[str, object],
    *,
    role: str,
):
    implementation_path = binding.get("implementation_path")
    implementation_sha256 = binding.get("implementation_sha256")
    callable_name = binding.get("callable")
    if (
        not isinstance(implementation_path, str)
        or not isinstance(implementation_sha256, str)
        or not isinstance(callable_name, str)
        or not callable_name.isidentifier()
    ):
        raise ValueError(f"{role} manifest binding is invalid")
    path = _repository_relative(root, implementation_path, f"{role} implementation")
    module = _load_bound_module(path, role=role, digest=implementation_sha256)
    value = getattr(module, callable_name, None)
    if not callable(value):
        raise ValueError(f"{role} bound callable is absent")
    source = inspect.getsourcefile(value)
    if source is None or not Path(source).resolve(strict=True).samefile(path):
        raise ValueError(f"{role} callable is imported or shadowed")
    if getattr(value, "__module__", None) != module.__name__:
        raise ValueError(f"{role} callable does not belong to its bound module")
    return value


def _prioritize_import_root(path: Path, *, index: int) -> None:
    """Put one reviewed root ahead of untrusted ambient import paths."""

    resolved = path.resolve(strict=True)

    def is_same_root(entry: str) -> bool:
        try:
            return Path(entry or ".").resolve(strict=True).samefile(resolved)
        except OSError:
            return False

    sys.path[:] = [entry for entry in sys.path if not is_same_root(entry)]
    sys.path.insert(min(index, len(sys.path)), str(resolved))


def _contract_types():
    expected = _TOOL_REPOSITORY_ROOT / "ocd_kernel/reconstruction/contract.py"
    _prioritize_import_root(_TOOL_REPOSITORY_ROOT, index=0)
    from ocd_kernel.reconstruction import contract

    loaded = Path(contract.__file__).resolve(strict=True)
    if not loaded.samefile(expected):
        raise ValueError("minimal reconstruction contract loaded from a shadow path")
    return contract


def _destination_policy():
    expected = _TOOL_REPOSITORY_ROOT / "ocd_kernel/reconstruction/destination_policy.py"
    _prioritize_import_root(_TOOL_REPOSITORY_ROOT, index=0)
    from ocd_kernel.reconstruction import destination_policy

    loaded = Path(destination_policy.__file__).resolve(strict=True)
    if not loaded.samefile(expected):
        raise ValueError("reconstruction destination policy loaded from a shadow path")
    return destination_policy


def run(*, manifest: str, destination: str, repository_root: str | None, progress: Callable[[str], None] | None = None) -> dict[str, object]:
    root = Path(repository_root).resolve(strict=True) if repository_root else _TOOL_REPOSITORY_ROOT
    manifest_path = _repository_relative(root, manifest, "source manifest")
    destination_plan = _destination_policy().preflight_destination(
        root,
        destination,
        appeared_empty="replace",
        repository_lexical="allow_resolved_escape",
    )
    emit = progress or (lambda stage: None)
    emit("preflight")
    contract = _contract_types()
    from build.lib.reconstruction_text_screen import screen_reconstruction
    source_manifest = contract.SourceManifest.load(manifest_path, repository_root=root)

    root_index = 0 if root.samefile(_TOOL_REPOSITORY_ROOT) else 1
    _prioritize_import_root(root, index=root_index)
    converter_binding = source_manifest.record.get("converter")
    validator_binding = source_manifest.record.get("validator")
    if not isinstance(converter_binding, Mapping) or not isinstance(validator_binding, Mapping):
        raise ValueError("source manifest callable bindings are invalid")
    converter = _bound_callable(root, converter_binding, role="converter")
    validator = _bound_callable(root, validator_binding, role="validator")

    with destination_plan.stage() as staged:
        emit("reconstruct")
        candidate = contract.reconstruct(
            source_manifest,
            staged.path / "package",
            converter,
        )
        emit("validate")
        report = contract.validate(source_manifest, candidate, validator)
        if candidate.manifest.get("status") != "nonaccepted" or report.status != "pass":
            raise ValueError("candidate handoff must remain validated and nonaccepted")
        emit("screen-text")
        text_screen = screen_reconstruction(source_manifest, candidate)
        text_sidecar = staged.path / "text-quality.json"
        text_sidecar.write_bytes(_canonical(text_screen).encode("utf-8"))
        text_sidecar_sha256 = _sha(text_sidecar.read_bytes())
        validation_sidecar = staged.path / "validation.json"
        validation_sidecar.write_bytes(_validation_sidecar_bytes(report, text_quality_sha256=text_sidecar_sha256))
        validation_sidecar_sha256 = _sha(validation_sidecar.read_bytes())
        staged.promote()
    emit("complete")
    attestation = report.attestation
    return {
        "acceptance_status": "nonaccepted",
        "candidate": {
            "member_names": list(candidate.member_names),
            "sha256": candidate.sha256,
        },
        "contract": "ocd-reconstruction-candidate-handoff-v1",
        "digests": {
            "candidate": candidate.sha256,
            "converter_implementation": converter_binding["implementation_sha256"],
            "oracle_implementation": validator_binding["implementation_sha256"],
            "oracle_import_closure": attestation["import_closure_sha256"],
            "oracle_result": attestation["result_sha256"],
            "source_manifest": source_manifest.sha256,
            "validation_report": report.sha256,
            "validation_sidecar": validation_sidecar_sha256,
            "text_quality_sidecar": text_sidecar_sha256,
        },
        "human_review_required": True,
        "publication_status": "not-authorized",
        "status": "pass",
        "text_quality": {"path": "text-quality.json", "sha256": text_sidecar_sha256,
                         "coverage": text_screen["coverage"], "review_status": text_screen["review_status"],
                         "observation_counts": text_screen["observation_counts"], "text_correctness": "not_assessed"},
        "validation_report": {
            "findings": list(report.findings),
            "path": "validation.json",
            "sha256": report.sha256,
            "sidecar_sha256": validation_sidecar_sha256,
            "status": report.status,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate one validated, nonaccepted reconstruction candidate."
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--repository-root")
    parser.add_argument("--progress", action="store_true", help="Write timestamped stage events to stderr; stdout remains the deterministic summary.")
    return parser


def main() -> None:
    args = _parser().parse_args()
    def report_progress(stage):
        sys.stderr.write(_canonical({"event":"candidate-stage", "stage":stage, "at":datetime.now(timezone.utc).isoformat()}))
        sys.stderr.flush()
    summary = run(
        manifest=args.manifest,
        destination=args.destination,
        repository_root=args.repository_root,
        progress=report_progress if args.progress else None,
    )
    sys.stdout.write(_canonical(summary))


if __name__ == "__main__":
    main()
