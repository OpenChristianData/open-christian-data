"""Rebuild current test candidates while preserving frozen historical packages."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest



def historical_bound_bytes(path, expected_sha256):
    """Recover a frozen text's exact newline variant, selected by its original hash."""
    raw = path.read_bytes()
    if sha256(raw).hexdigest() == expected_sha256:
        return raw
    lf = raw.replace(b"\r\n", b"\n")
    for candidate in (lf, lf.replace(b"\n", b"\r\n")):
        if sha256(candidate).hexdigest() == expected_sha256:
            return candidate
    raise AssertionError(f"historical byte binding differs: {path}")


def _assert_runtime_member(name, current, retained, *, original_sha256, runtime_sha256):
    """Conserve bytes, or the full accounting record except its explicit source identity."""
    if current == retained:
        return
    assert name in {"provenance.json", "source-accountability.json"}, name
    before, after = json.loads(retained), json.loads(current)
    assert isinstance(before, dict) and isinstance(after, dict), name
    assert before["source_manifest_sha256"] == original_sha256, name
    assert after["source_manifest_sha256"] == runtime_sha256, name
    restored = dict(after, source_manifest_sha256=before["source_manifest_sha256"])
    assert restored == before, name


def current_runtime_baseline(*, root, original_manifest, runtime_manifest,
                             retained_package, retained_sha256, destination, tool_root=None):
    retained = CandidatePackage.load(retained_package)
    assert retained.sha256 == retained_sha256
    assert retained.manifest["source_manifest"]["sha256"] == sha256(
        (root / original_manifest).read_bytes()).hexdigest()
    result = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--repository-root", str(root),
         "--manifest", Path(runtime_manifest).as_posix(), "--destination", str(destination)],
        cwd=root if tool_root is None else tool_root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout)["status"] == "pass"
    current = CandidatePackage.load(destination / "package")
    runtime = SourceManifest.load(root / runtime_manifest, repository_root=root)
    assert current.manifest["source_manifest"]["sha256"] == runtime.sha256
    assert current.member_names == retained.member_names
    for name in current.member_names:
        if name != "manifest.json":
            _assert_runtime_member(
                name, current.member_bytes(name), retained.member_bytes(name),
                original_sha256=retained.manifest["source_manifest"]["sha256"],
                runtime_sha256=runtime.sha256)
    assert current.manifest["status"] == "nonaccepted"
    return runtime, current


def current_runtime_catalog(*, root, manifest, work_ids, reconstruction_evidence,
                            data_resource_allowlist=None):
    """Bind real retained claims to an explicit test successor of a historical route."""
    from build.tools import count_dataset_records

    selection = manifest.relative_to(root).as_posix()
    resources = (
        [f"data/structured-text/{work_id}.json" for work_id in work_ids]
        if data_resource_allowlist is None
        else list(data_resource_allowlist)
    )
    assert all((root / path).is_file() for path in resources)
    original_rglob = Path.rglob

    def selected_paths(sources_root, selections):
        assert sources_root == root / "sources"
        assert tuple(selections) == (selection,)
        return sources_root, None

    def selected_discovery(path, pattern):
        if path == root / "sources" and pattern in {"*.source-manifest.json", "source-manifest.json"}:
            return iter((manifest,))
        return original_rglob(path, pattern)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(count_dataset_records, "_resolve_source_manifest_allowlist", selected_paths)
        patch.setattr(Path, "rglob", selected_discovery)
        return count_dataset_records.collect_work_catalog(
            root / "data", source_manifest_allowlist=[selection],
            data_resource_allowlist=resources, reconstruction_evidence=reconstruction_evidence)
