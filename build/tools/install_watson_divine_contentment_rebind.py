"""Guarded installation of the reviewed Watson Divine Contentment evidence rebind.

Without --apply this tool only validates the immutable stage and current
canonical before-state. --apply installs one new evidence directory and replaces
one acceptance record; master, work, acquisition, and state are never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import uuid
from pathlib import Path

from build.tools import prepare_watson_divine_contentment_rebind as route
from ocd_kernel.library._common import PipelineError, io_glob, io_path
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance


DEFAULT_MANIFEST = Path(
    "plans/2026-09-22-source-preflight/"
    "watson-divine-contentment-closure-rebind-stage-20260926.json"
)
CONTROL_PATHS = {
    "acceptance_sha256": route.EDITION / "acceptance.json",
    "master_sha256": route.EDITION / "master.tei.xml",
    "state_sha256": route.WORK / "state.json",
    "work_sha256": route.WORK / "work.json",
    "acquisition_sha256": route.ACQUISITION,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def _plain(path: Path) -> None:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    while True:
        info = current.lstat()
        if current.is_symlink() or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise PipelineError(f"reparse-point path is not allowed: {current}")
        if current.parent == current:
            return
        current = current.parent


def _evidence_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha(path)
        for path in io_glob(root / route.EVIDENCE, "**/*")
        if io_path(path).is_file()
    }


def preflight(manifest_path: Path) -> tuple[dict, Path]:
    root = route.ROOT.resolve(strict=True)
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    if record.get("contract") != "ocd-watson-divine-contentment-closure-rebind-install-manifest-v1":
        raise PipelineError("Watson install manifest contract differs")
    stage = Path(record["stage_root"]).resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Watson stage overlaps canonical checkout")
    _plain(stage)
    if record.get("canonical_root") != root.as_posix():
        raise PipelineError("Watson canonical root differs from install manifest")
    if io_path(root / route.EVIDENCE).exists():
        raise PipelineError("Watson v2 evidence directory already exists")
    before = record["canonical_before"]
    if before.get("v2_evidence_absent") is not True:
        raise PipelineError("Watson before-state does not require a fresh evidence directory")
    for name, relative in CONTROL_PATHS.items():
        if _sha(root / relative) != before.get(name):
            raise PipelineError(f"Watson canonical before-hash differs: {name}")
    staged = record["stage"]
    acceptance = stage / route.EDITION / "acceptance.json"
    if (
        staged.get("acceptance_path") != (route.EDITION / "acceptance.json").as_posix()
        or _sha(acceptance) != staged.get("acceptance_sha256")
        or _sha(stage / route.CURRENT_MANIFEST) != staged.get("source_manifest_sha256")
        or _sha(stage / route.EVIDENCE / "current-candidate/package/manifest.json")
        != staged.get("current_package_sha256")
        or _sha(stage / route.EVIDENCE / "current-candidate/validation.json")
        != staged.get("current_validation_sha256")
    ):
        raise PipelineError("Watson stage bindings differ")
    for name, relative in CONTROL_PATHS.items():
        if name != "acceptance_sha256" and _sha(stage / relative) != before[name]:
            raise PipelineError(f"Watson staged protected file differs: {name}")
    for path in io_glob(stage / route.EVIDENCE, "**/*"):
        if path.is_symlink() or (
            getattr(io_path(path).lstat(), "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise PipelineError(f"Watson staged evidence contains a reparse point: {path}")
    if _evidence_hashes(stage) != staged.get("evidence_files"):
        raise PipelineError("Watson staged evidence set or hashes differ")
    prior = json.loads(io_path(root / route.EDITION / "acceptance.json").read_text(encoding="utf-8"))
    proposed = validate_acceptance(acceptance, root=stage)
    if (
        proposed["promotion"] != prior["promotion"]
        or proposed["decision"] != prior["decision"]
        or proposed["promotion"]["status"] != "promoted"
        or proposed["promotion"]["master"]["sha256"] != before["master_sha256"]
    ):
        raise PipelineError("Watson decision or promotion history differs")
    validate_state(stage / route.WORK / "state.json", root=stage)
    return record, stage


def _remove_owned(
    path: Path, *, parent: Path, expected: dict[str, str], allow_subset: bool = False
) -> None:
    parent = parent.resolve(strict=True)
    target = path.resolve(strict=True)
    if target.parent != parent or path.is_symlink():
        raise PipelineError(f"refusing cleanup outside Watson integration directory: {path}")
    _plain(target)
    relative_hashes = {
        child.relative_to(target).as_posix(): _sha(child)
        for child in io_glob(target, "**/*") if io_path(child).is_file()
    }
    expected_relative = {
        Path(key).relative_to(route.EVIDENCE).as_posix(): value
        for key, value in expected.items()
    }
    if (
        any(expected_relative.get(name) != digest for name, digest in relative_hashes.items())
        or (not allow_subset and relative_hashes != expected_relative)
    ):
        raise PipelineError(f"refusing cleanup of changed Watson evidence: {path}")
    shutil.rmtree(target)


def install(manifest_path: Path) -> dict:
    record, stage = preflight(manifest_path)
    root = route.ROOT.resolve(strict=True)
    old_acceptance = root / route.EDITION / "acceptance.json"
    new_acceptance = stage / route.EDITION / "acceptance.json"
    integration = root / route.WORK / "integration"
    final_evidence = root / route.EVIDENCE
    token = uuid.uuid4().hex[:12]
    copied = integration / f".ccel-thml-closure-rebind-v2-{token}"
    replacement = old_acceptance.with_name(f".acceptance-watson-new-{token}.json")
    backup = old_acceptance.with_name(f".acceptance-watson-old-{token}.json")
    evidence_published = False
    acceptance_replaced = False
    expected = record["stage"]["evidence_files"]
    try:
        _plain(integration)
        shutil.copytree(stage / route.EVIDENCE, copied)
        if {
            (route.EVIDENCE / p.relative_to(copied)).as_posix(): _sha(p)
            for p in io_glob(copied, "**/*") if io_path(p).is_file()
        } != expected:
            raise PipelineError("copied Watson evidence differs from reviewed stage")
        if final_evidence.exists():
            raise PipelineError("Watson v2 evidence appeared during copy")
        copied.rename(final_evidence)
        evidence_published = True
        with backup.open("xb") as handle:
            handle.write(old_acceptance.read_bytes())
        with replacement.open("xb") as handle:
            handle.write(new_acceptance.read_bytes())
        if _sha(old_acceptance) != record["canonical_before"]["acceptance_sha256"]:
            raise PipelineError("Watson acceptance changed during installation")
        os.replace(replacement, old_acceptance)
        acceptance_replaced = True
        validate_acceptance(old_acceptance, root=root)
        validate_state(root / route.WORK / "state.json", root=root)
        for name, relative in CONTROL_PATHS.items():
            expected_digest = (
                record["stage"]["acceptance_sha256"] if name == "acceptance_sha256"
                else record["canonical_before"][name]
            )
            if _sha(root / relative) != expected_digest:
                raise PipelineError(f"Watson installed control file differs: {name}")
        if _evidence_hashes(root) != expected:
            raise PipelineError("Watson installed evidence differs")
        backup.unlink()
        return {
            "status": "applied",
            "acceptance_before_sha256": record["canonical_before"]["acceptance_sha256"],
            "acceptance_after_sha256": record["stage"]["acceptance_sha256"],
            "evidence_file_count": len(expected),
            "protected_files_unchanged": True,
        }
    except Exception:
        if acceptance_replaced and backup.is_file():
            if _sha(old_acceptance) == record["stage"]["acceptance_sha256"]:
                os.replace(backup, old_acceptance)
            else:
                raise PipelineError(
                    "Watson acceptance changed after installation; backup retained for manual recovery"
                )
        if evidence_published and final_evidence.is_dir():
            _remove_owned(final_evidence, parent=integration, expected=expected)
        if copied.is_dir():
            _remove_owned(copied, parent=integration, expected=expected, allow_subset=True)
        if replacement.is_file():
            replacement.unlink()
        if backup.is_file():
            backup.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.manifest) if args.apply else {
        "status": "ready",
        "acceptance_after_sha256": preflight(args.manifest)[0]["stage"]["acceptance_sha256"],
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
