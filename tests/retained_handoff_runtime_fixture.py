"""Replay current handoffs with unchanged retained source, TEI, and old visual evidence.

Only temporary source-manifest/package/validation identities become current. The
original visual receipts are checked by their original production verifier with
their original identities; byte equality makes their bounded reuse explicit.
Nothing here writes to the input repository or retained review directories.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import pytest

from build.tools.reconstruct_candidate import _bound_callable
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate

CASES = {
    "law-serious-call": {
        "runtime": "tests/fixtures/reconstruction-runtime/law-serious-call.source-manifest.json",
        "original_sha256": "9871fd284891960a8b8771c24fc4a4690d75a25613615adea89605c602142285",
        "runtime_sha256": "898fc74ab9ab911fb0f404aeca05efab238434983e81afc65a868eacf33eed97",
    },
    "john-owen-conscience": {
        "runtime": "tests/fixtures/reconstruction-runtime/john-owen-conscience.source-manifest.json",
        "original_sha256": "d212bcd407d1c119a00d8ef23e30d6bc2fd1f355ce1150b8fb166ce536fdb885",
        "runtime_sha256": "620abe276058e3921da06bff50f21404bccd40c13e902e7a31a768b701134482",
    },
    "augustine-on-christian-doctrine": {
        "runtime": "tests/fixtures/reconstruction-runtime/augustine-on-christian-doctrine.source-manifest.json",
        "original_sha256": "263970f14d1eee1fdf1a746acd4da7dced012355a0773f27fa24d3e8b23116cd",
        "runtime_sha256": "87e2a0a965fa32d54542bca7dd2243e3d801d9d8c1d4f42b70b268fb4f2df994",
    },
}


def _sha(content):
    return sha256(content).hexdigest()


def _copy(root, relative, content):
    relative = Path(relative)
    assert not relative.is_absolute() and ".." not in relative.parts
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _references(value):
    if isinstance(value, dict):
        for key, member in value.items():
            if key in {"path", "implementation_path"} and isinstance(member, str):
                yield member
            yield from _references(member)
    elif isinstance(value, list):
        for member in value:
            yield from _references(member)


def _mirror(input_root, root, record):
    pending = list(_references(record))
    # These are current bytes. The implementation's own digest checks still run.
    pending += ["ocd_kernel/__init__.py", "ocd_kernel/reconstruction/__init__.py",
                "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/verifier.py"]
    seen = set()
    while pending:
        relative = pending.pop()
        if relative in seen:
            continue
        seen.add(relative)
        path = Path(relative)
        assert not path.is_absolute() and ".." not in path.parts
        source = input_root / path
        assert source.is_file(), relative
        raw = source.read_bytes()
        _copy(root, path, raw)
    for directory in ("schemas/v2", "ocd_kernel/reconstruction/schemas", "ocd_kernel/tei/vendor/xsd"):
        for source in (input_root / directory).rglob("*"):
            if source.is_file():
                _copy(root, source.relative_to(input_root), source.read_bytes())


def _handoff_work_bytes(input_root, relative, record):
    bindings = [item for item in record["authorities"] if item.get("name") == "work"]
    if not bindings:
        return (input_root / relative).read_bytes()
    assert len(bindings) == 1, "handoff work authority is ambiguous"
    binding = bindings[0]
    held = Path(binding["path"])
    assert not held.is_absolute() and ".." not in held.parts
    raw = (input_root / held).read_bytes()
    assert len(raw) == binding["bytes"] and _sha(raw) == binding["sha256"], "handoff work authority drifted"
    return raw


def assert_original_handoff_is_currently_rejected(helper, work_id, destination):
    case = CASES[work_id]
    assert _sha((helper.ROOT / helper.MANIFEST).read_bytes()) == case["original_sha256"]
    original = (helper.ROOT / helper.MANIFEST).read_bytes()
    from ocd_kernel.library._common import PipelineError
    with pytest.raises((PipelineError, ValueError)):
        helper.prepare(helper.ROOT, destination)
    assert not destination.exists()
    assert (helper.ROOT / helper.MANIFEST).read_bytes() == original


@contextmanager
def current_handoff_context(helper, work_id, destination, monkeypatch):
    """Use explicit maintained runtime records while retaining the historical pair."""
    input_root = helper.ROOT
    case = CASES[work_id]
    original_manifest = (input_root / helper.MANIFEST).read_bytes()
    assert _sha(original_manifest) == case["original_sha256"]
    runtime_path = Path(case["runtime"])
    runtime_bytes = (input_root / runtime_path).read_bytes()
    assert _sha(runtime_bytes) == case["runtime_sha256"]
    record = json.loads(runtime_bytes)
    assert record["work_id"] == work_id
    root = destination / "r"
    root.mkdir(parents=True)
    _mirror(input_root, root, record)
    for relative in (helper.WORK / "work.json", helper.WORK / "state.json", helper.ACQUISITION,
                     helper.TICKET, helper.REPORT):
        content = (_handoff_work_bytes(input_root, relative, record)
                   if relative == helper.WORK / "work.json" else (input_root / relative).read_bytes())
        _copy(root, relative, content)
    _copy(root, helper.MANIFEST, runtime_bytes)
    protected = [input_root / helper.MANIFEST, input_root / runtime_path,
                 input_root / helper.WORK / "work.json", input_root / helper.WORK / "state.json",
                 input_root / helper.ACQUISITION, input_root / helper.TICKET, input_root / helper.REPORT]
    old_pins = dict(helper.PINS) if work_id == "augustine-on-christian-doctrine" else None
    if work_id == "law-serious-call":
        retained_root = helper.OLD
        retained_sha = helper.OLD_PACKAGE_SHA
        frame_bytes = (input_root / helper.FRAMES).read_bytes()
        assert _sha(frame_bytes) == helper.FRAMES_SHA
        _copy(root, helper.FRAMES, frame_bytes)
        protected.append(input_root / helper.FRAMES)
        for frame in json.loads(frame_bytes)["frames"]:
            path = helper.FRAMES.parent / frame["file"]
            content = (input_root / path).read_bytes()
            assert _sha(content) == frame["sha256"] and len(content) == frame["bytes"]
            _copy(root, path, content)
            protected.append(input_root / path)
    else:
        retained_root = helper.CANDIDATE
        retained_sha = old_pins["package"] if old_pins else helper.PACKAGE_SHA
    retained = CandidatePackage.load(retained_root / "package")
    assert retained.sha256 == retained_sha
    protected.extend(retained_root / "package" / name for name in retained.member_names)
    protected.append(retained_root / "validation.json")
    if work_id == "john-owen-conscience":
        coverage_path = helper.CVW / "coverage-receipt.json"
        coverage = json.loads(coverage_path.read_bytes())
        assert _sha(coverage_path.read_bytes()) == helper.COVERAGE_SHA
        protected.append(coverage_path)
        for point in coverage["coverage"]["points"]:
            protected.extend(helper.CVW / point[key] for key in ("screenshot_file", "record_file"))
        protected.extend(helper.CVW / item["path"] for item in coverage.get("session_files", {}).values())
    if old_pins:
        assert retained.manifest["source_manifest"]["sha256"] == old_pins["manifest"]
        for relative, key in ((helper.METADATA, "metadata"), (helper.RECEIPT, "receipt"),
                              (helper.MASTER, "master")):
            source = input_root / relative
            if key == "metadata":
                source = input_root / "tests/fixtures/reconstruction-runtime/authorities/augustine-christian-doctrine-original-catalog.json"
            raw = source.read_bytes()
            assert _sha(raw) == old_pins[key], relative
            _copy(root, relative, raw)
            protected.append(input_root / relative)
        review_receipt = json.loads((input_root / helper.RECEIPT).read_bytes())
        protected.extend(Path(item["frame"]) for item in review_receipt["v2_visual_review"]["captures"])
        # This retained source record is evidence, never substituted for live code.
        historical = input_root / helper.WORK / "integration/selected-thml-agent-handoff/inputs/source-manifest.json"
        assert _sha(historical.read_bytes()) == old_pins["manifest"]
        protected.append(historical)
    snapshots = {path: _sha(path.read_bytes()) for path in protected}
    try:
        current = destination / "c"
        result = subprocess.run(
            [sys.executable, "-m", "build.tools.reconstruct_candidate", "--repository-root", str(root),
             "--manifest", helper.MANIFEST.as_posix(), "--destination", str(current)],
            cwd=input_root, check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr or result.stdout
        assert json.loads(result.stdout)["status"] == "pass"
        package = CandidatePackage.load(current / "package")
        assert package.member_names == retained.member_names
        if work_id == "law-serious-call":
            # The production handoff deliberately allows old package metadata to
            # differ; it requires these exact reviewed source-derived members.
            names = ("content.tei.xml", "source-accountability.json")
        else:
            names = tuple(name for name in package.member_names if name != "manifest.json")
            assert len(names) == 5
        for name in names:
            assert package.member_bytes(name) == retained.member_bytes(name), name
        report_bytes = (current / "validation.json").read_bytes()
        report = json.loads(report_bytes)
        manifest = SourceManifest.load(root / helper.MANIFEST, repository_root=root)
        oracle = _bound_callable(root, record["validator"], role="validator")
        replay = validate(manifest, package, oracle)
        assert replay.status == "pass" and replay.sha256 == report["report_sha256"]
        with pytest.raises(ValueError, match="candidate source manifest binding mismatch"):
            validate(manifest, retained, oracle)
        with monkeypatch.context() as patch:
            patch.setattr(helper, "ROOT", root)
            if work_id == "law-serious-call":
                patch.setattr(helper, "MANIFEST_SHA", manifest.sha256)
                original_run = helper.subprocess.run
                def current_cli(command, **kwargs):
                    assert command[:3] == [sys.executable, "-m", "build.tools.reconstruct_candidate"]
                    assert kwargs["cwd"] == root and kwargs["check"] is True
                    assert command[command.index("--repository-root") + 1] == str(root)
                    return original_run(command, **(kwargs | {"cwd": input_root}))
                patch.setattr(helper, "subprocess", SimpleNamespace(run=current_cli))
            elif work_id == "john-owen-conscience":
                old_manifest_sha, old_package_sha = helper.MANIFEST_SHA, helper.PACKAGE_SHA
                old_visual = helper._visual_inputs
                def historical_visual():
                    # The production checker sees ORIGINAL route/package pins.
                    # Do not rewrite the pixels, coverage receipt, routes, or times.
                    with pytest.MonkeyPatch.context() as historical_patch:
                        historical_patch.setattr(helper, "MANIFEST_SHA", old_manifest_sha)
                        historical_patch.setattr(helper, "PACKAGE_SHA", old_package_sha)
                        return old_visual()
                patch.setattr(helper, "_visual_inputs", historical_visual)
                patch.setattr(helper, "CANDIDATE", current)
                patch.setattr(helper, "MANIFEST_SHA", manifest.sha256)
                patch.setattr(helper, "PACKAGE_SHA", package.sha256)
                patch.setattr(helper, "VALIDATION_SHA", _sha(report_bytes))
                patch.setattr(helper, "VALIDATION_REPORT_SHA", report["report_sha256"])
                patch.setattr(helper, "_oracle", oracle)
                # Keep old report bytes, adding a clearly identified test-only
                # current technical-binding appendix in the disposable mirror.
                appendix = ("\n\nTEST ONLY current runtime binding; historical visual routes remain unchanged.\n"
                            + manifest.sha256 + "\n" + package.sha256 + "\n").encode()
                for relative in (helper.TICKET, helper.REPORT):
                    old = (input_root / relative).read_bytes()
                    _copy(root, relative, old + appendix)
                    assert (root / relative).read_bytes()[:-len(appendix)] == old
            else:
                pins = dict(old_pins)
                pins.update(manifest=manifest.sha256, package=package.sha256,
                            validation=_sha(report_bytes), validation_report=report["report_sha256"],
                            oracle=record["validator"]["implementation_sha256"])
                restored = dict(pins)
                for key in ("manifest", "package", "validation", "validation_report", "oracle"):
                    restored[key] = old_pins[key]
                assert restored == old_pins
                patch.setattr(helper, "PINS", pins)
                patch.setattr(helper, "CANDIDATE", current)
                patch.setattr(helper, "_oracle", oracle)
            yield root
    finally:
        for path, digest in snapshots.items():
            assert _sha(path.read_bytes()) == digest, str(path)
