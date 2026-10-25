"""Stage existing candidate/validation bytes without rebuilding or validating anew."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    _verify_candidate_source_binding,
)
from ocd_kernel.reconstruction.destination_policy import preflight_destination
from cvw_app.review_contract import _is_reparse_point, _load_validation_report


def _ordinary(path: Path, *, directory: bool = False) -> None:
    if _is_reparse_point(path) or (
        not path.is_dir() if directory else not path.is_file()
    ):
        raise ValueError(
            f"staging input must be an ordinary {'directory' if directory else 'file'}: {path}"
        )


def stage_candidate(
    *, package: Path, validation: Path, destination: Path, repository_root: Path
) -> dict[str, str]:
    """Copy exact inputs, verify existing evidence, and atomically publish a wrapper.

    This establishes package integrity only; catalog/declared-library admission
    remains a separate read-only check. No converter or oracle is executed.
    """
    root = Path(repository_root).resolve(strict=True)
    package, validation = Path(package), Path(validation)
    _ordinary(package, directory=True)
    _ordinary(validation)
    package, validation = package.resolve(strict=True), validation.resolve(strict=True)
    plan = preflight_destination(repository_root, destination)
    if plan.destination_existed:
        raise ValueError("staging destination must be absent")
    if plan.destination.is_relative_to(package) or validation.is_relative_to(
        plan.destination
    ):
        raise ValueError("staging destination overlaps an input")
    for member in package.iterdir():
        _ordinary(member)
    original = CandidatePackage.load(package)
    if original.manifest.get("status") != "nonaccepted":
        raise ValueError("candidate must remain nonaccepted")
    binding = original.manifest.get("source_manifest")
    if not isinstance(binding, Mapping):
        raise ValueError("candidate source manifest binding is invalid")
    relative = binding.get("path")
    if (
        not isinstance(relative, str)
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
    ):
        raise ValueError("source manifest must be repository-relative")
    source = SourceManifest.load(root / relative, repository_root=root)
    _verify_candidate_source_binding(source, original)
    validation_bytes = validation.read_bytes()
    text_quality = validation.with_name("text-quality.json")
    text_quality_bytes = None
    if text_quality.exists() or text_quality.is_symlink():
        _ordinary(text_quality)
        text_quality_bytes = text_quality.read_bytes()
    with plan.stage() as staged:
        target = staged.path / "package"
        target.mkdir()
        for name in original.member_names:
            _ordinary(package / name)
            (target / name).write_bytes((package / name).read_bytes())
        (staged.path / "validation.json").write_bytes(validation_bytes)
        if text_quality_bytes is not None:
            (staged.path / "text-quality.json").write_bytes(text_quality_bytes)
        copied = CandidatePackage.load(target)
        if copied.sha256 != original.sha256:
            raise ValueError("candidate changed during staging")
        _verify_candidate_source_binding(source, copied)
        report = _load_validation_report(staged.path, source, copied)
        original.verify_integrity()
        for name in original.member_names:
            _ordinary(package / name)
            if (package / name).read_bytes() != (target / name).read_bytes():
                raise ValueError(f"candidate changed during staging: {name}")
        _ordinary(validation)
        if validation.read_bytes() != validation_bytes:
            raise ValueError("validation record changed during staging")
        if text_quality_bytes is not None:
            _ordinary(text_quality)
            if text_quality.read_bytes() != text_quality_bytes:
                raise ValueError("text-quality record changed during staging")
        source.verify()
        staged.promote()
    return {
        "destination": str(plan.destination),
        "candidate_sha256": original.sha256,
        "source_manifest_sha256": source.sha256,
        "validation_report_sha256": report.sha256,
        "validation_sidecar_sha256": hashlib.sha256(validation_bytes).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = stage_candidate(**vars(args))
    except (ValueError, OSError) as error:
        parser.exit(1, f"Candidate staging refused: {error}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
