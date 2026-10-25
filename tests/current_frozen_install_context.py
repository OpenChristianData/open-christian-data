"""Current source-proof envelopes around unchanged historical install generations."""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
import subprocess
import sys
from pathlib import Path
import shutil

from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


def current_frozen_stage(installer, original_stage, original_pin, baseline, candidate, destination):
    raw = _io_path(original_stage / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == original_pin
    original = json.loads(raw)
    assert _files(original_stage / installer.WORK) == original["after"]
    retained_manifest = _io_path(original_stage / installer.MANIFEST).read_bytes()
    assert sha256(retained_manifest).hexdigest() == original["source_manifest_sha256"]
    assert candidate.manifest["source_manifest"]["sha256"] == baseline.sha256
    validation_raw = _io_path(candidate.path.parent / "validation.json").read_bytes()
    validation = json.loads(validation_raw)
    assert validation["status"] == "pass" and validation["findings"] == []
    assert validation["source_manifest_sha256"] == baseline.sha256
    assert validation["candidate_sha256"] == candidate.sha256
    runtime_logical = baseline.path.relative_to(installer.ROOT)
    stage = destination / "candidate-reviews" / original_stage.name
    shutil.copytree(_io_path(original_stage), _io_path(stage))
    target = _io_path(stage / runtime_logical)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(baseline.path.read_bytes())
    native = (original["work_id"] in {"charnock-existence-attributes-vol-2", "luther-commentary-on-galatians"}
              and baseline.record["converter"]["version"] == "2")
    if native:
        for row in baseline.record["authorities"]:
            if Path(row["path"]).is_relative_to(Path("tests/fixtures/reconstruction-runtime")):
                payload = baseline.authority_path(row["name"]).read_bytes()
                support = _io_path(stage / row["path"])
                if support.exists():
                    assert support.read_bytes() == payload
                else:
                    support.parent.mkdir(parents=True, exist_ok=True)
                    support.write_bytes(payload)
    package = stage / installer.EVIDENCE / "inputs/package"
    for name in candidate.member_names:
        payload = candidate.member_bytes(name)
        if native and name == "provenance.json":
            _assert_native_provenance(_io_path(package / name).read_bytes(), payload,
                                      baseline, original["source_manifest_sha256"])
        elif name != "manifest.json":
            assert _io_path(package / name).read_bytes() == payload, name
        _io_path(package / name).write_bytes(payload)
    _io_path(stage / installer.EVIDENCE / "inputs/validation.json").write_bytes(validation_raw)
    current = deepcopy(original)
    current.update(stage_root=stage.as_posix(), source_manifest_sha256=baseline.sha256,
                   candidate_package_sha256=candidate.sha256,
                   oracle_report_sha256=validation["report_sha256"],
                   after=_files(stage / installer.WORK))
    assert set(current["after"]) == set(original["after"])
    allowed = {(installer.EVIDENCE / "inputs/package/manifest.json").relative_to(installer.WORK).as_posix(),
               (installer.EVIDENCE / "inputs/validation.json").relative_to(installer.WORK).as_posix()}
    if native:
        allowed.add((installer.EVIDENCE / "inputs/package/provenance.json").relative_to(installer.WORK).as_posix())
    assert {p for p in current["after"] if current["after"][p] != original["after"][p]} <= allowed
    restored = deepcopy(current)
    for key in ("stage_root", "source_manifest_sha256", "candidate_package_sha256", "oracle_report_sha256", "after"):
        restored[key] = original[key]
    assert restored == original
    _io_path(stage / "stage-receipt.json").write_bytes((json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    assert _io_path(original_stage / "stage-receipt.json").read_bytes() == raw
    assert _files(original_stage / installer.WORK) == original["after"]
    return stage, sha256(_io_path(stage / "stage-receipt.json").read_bytes()).hexdigest()


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _assert_native_provenance(original_raw, current_raw, baseline, original_source_sha):
    original, current = json.loads(original_raw), json.loads(current_raw)
    profile = json.loads(baseline.authority_path("reconstruction-profile").read_bytes())
    assert baseline.record["converter"]["version"] == baseline.record["validator"]["version"] == "2"
    assert original["work_id"] == current["work_id"] == profile["work_id"]
    assert current["work_id"] in {"charnock-existence-attributes-vol-2", "luther-commentary-on-galatians"}
    from ocd_kernel.reconstruction.contract import _runtime_binding
    assert current["runtime"] == _runtime_binding()
    assert original["source_manifest_sha256"] == original_source_sha
    assert current["source_manifest_sha256"] == baseline.sha256
    row = baseline.record["converter"]
    module = importlib.import_module(row["implementation_path"][:-3].replace("/", "."))
    assert Path(module.__file__).resolve() == (baseline.repository_root / row["implementation_path"]).resolve()
    closure = list(module._closure(baseline.repository_root, baseline.repository_root / row["implementation_path"]))
    assert current["producer_import_closure"] == closure
    assert current["producer_import_closure_sha256"] == sha256(_canonical(closure)).hexdigest() == profile["producer_import_closure_sha256"]
    restored = deepcopy(current)
    for key in ("source_manifest_sha256", "producer_import_closure", "producer_import_closure_sha256", "runtime"):
        restored[key] = original[key]
    assert restored == original


def current_native_source_baseline(root, case, retained_package, destination):
    original_raw = (root / case["original"]).read_bytes()
    assert sha256(original_raw).hexdigest() == case["original_sha256"]
    baseline = SourceManifest.load(root / case["manifest"], repository_root=root)
    assert baseline.sha256 == case["manifest_sha256"]
    assert baseline.record["converter"]["version"] == baseline.record["validator"]["version"] == "2"
    retained = CandidatePackage.load(retained_package)
    assert retained.manifest["source_manifest"]["sha256"] == case["original_sha256"]
    receipt_raw = (Path(case["original_stage"]) / "stage-receipt.json").read_bytes()
    assert sha256(receipt_raw).hexdigest() == case["original_receipt_sha256"]
    assert retained.sha256 == json.loads(receipt_raw)["candidate_package_sha256"]
    result = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--repository-root", str(root),
         "--manifest", case["manifest"], "--destination", str(destination)],
        cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "pass"
    candidate = CandidatePackage.load(destination / "package")
    assert candidate.member_names == retained.member_names
    for name in candidate.member_names:
        if name == "provenance.json":
            _assert_native_provenance(retained.member_bytes(name), candidate.member_bytes(name),
                                      baseline, case["original_sha256"])
        elif name != "manifest.json":
            assert candidate.member_bytes(name) == retained.member_bytes(name), name
    original = json.loads(retained.member_bytes("manifest.json"))
    current = json.loads(candidate.member_bytes("manifest.json"))
    assert current["source_manifest"] == {"path": case["manifest"], "sha256": baseline.sha256}
    restored = deepcopy(current)
    restored["source_manifest"] = original["source_manifest"]
    original_provenance = next(row for row in original["members"] if row["name"] == "provenance.json")
    index = next(i for i, row in enumerate(restored["members"]) if row["name"] == "provenance.json")
    restored["members"][index] = deepcopy(original_provenance)
    assert restored == original
    assert (root / case["original"]).read_bytes() == original_raw
    return baseline, candidate
