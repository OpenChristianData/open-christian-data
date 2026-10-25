"""A current source oracle checks the unchanged Orthodoxy acceptance stage body."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
from build.tei.se_candidate_oracle import _closure
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.runtime_candidate_baselines import current_runtime_baseline

ROOT = Path(__file__).resolve().parents[1]


def orthodoxy_runtime_context(installer, destination):
    work_id = "orthodoxy"
    case = next(row for row in json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-se-four.json").read_bytes())
                if row["original"].endswith("/orthodoxy.source-manifest.json"))
    original_stage = installer.STAGES[work_id]
    raw = _io_path(original_stage / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == installer.RECEIPT_SHA[work_id]
    original = json.loads(raw)
    assert original["work"]["source_manifest_sha256"] == case["original_sha256"]
    baseline, candidate = current_runtime_baseline(
        root=ROOT, original_manifest=case["original"], runtime_manifest=case["manifest"],
        retained_package=installer.BASE / "orthodoxy-current-20260928-v1/package",
        retained_sha256=original["work"]["candidate_package_sha256"],
        destination=destination / "runtime-candidate")
    root, stage, base = destination / "root", destination / "stage", destination / "candidates"
    root.mkdir()
    shutil.copytree(_io_path(original_stage), _io_path(stage))
    work = Path(original["work"]["work_path"])
    assert _files(stage / work) == original["work"]["after"]
    for relative, digest in original["dependencies"].items():
        payload = _io_path(stage / relative).read_bytes()
        assert sha256(payload).hexdigest() == digest
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    for relative, expected in original["work"]["before"].items():
        payload = _io_path(stage / work / relative).read_bytes()
        if sha256(payload).hexdigest() != expected:
            value = json.loads(payload)
            if relative == "work.json":
                assert value["textual_forms"][0]["editions"][0].pop("category") == "prose"
            elif relative == "state.json":
                edition = next(x for x in value["targets"] if x["target_type"] == "edition")
                acquisition = next(x for x in value["targets"] if x["target_type"] == "acquisition")
                assert edition["stage"] == "accepted"
                edition["stage"] = "acquired"
                edition.pop("reason")
                edition["updated_at"] = acquisition["updated_at"]
                assert edition["evidence"][-2].endswith("/master.tei.xml")
                assert edition["evidence"][-1].endswith("/acceptance.json")
                edition["evidence"] = edition["evidence"][:-2]
            else:
                raise AssertionError("Unexplained Orthodoxy acquired metadata")
            payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        assert sha256(payload).hexdigest() == expected
        target = _io_path(root / work / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    assert _files(root / work) == original["work"]["before"]
    logical_paths = {str(a["path"]) for a in baseline.record["authorities"]}
    for role in ("converter", "validator"):
        _, members = _closure(ROOT, ROOT / baseline.record[role]["implementation_path"])
        logical_paths.update(row["path"] for row in members)
    current_dependency_updates = {}
    for relative in logical_paths:
        payload = _io_path(ROOT / relative).read_bytes()
        target = _io_path(root / relative)
        if target.exists() and target.read_bytes() != payload:
            assert relative == "ocd_kernel/reconstruction/contract.py"
            assert sha256(target.read_bytes()).hexdigest() == original["dependencies"][relative]
            current_dependency_updates[relative] = sha256(payload).hexdigest()
            target.write_bytes(payload)
            _io_path(stage / relative).write_bytes(payload)
        elif target.exists():
            assert target.read_bytes() == payload
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
    assert set(current_dependency_updates) == {"ocd_kernel/reconstruction/contract.py"}
    # Execute the exact current oracle from its mirrored path so __file__-based
    # closure discovery describes this temporary read root, with no guard bypass.
    oracle_path = root / baseline.record["validator"]["implementation_path"]
    assert oracle_path.read_bytes() == _io_path(ROOT / baseline.record["validator"]["implementation_path"]).read_bytes()
    spec = importlib.util.spec_from_file_location("build.tei._orthodoxy_current_fixture_oracle", oracle_path)
    assert spec is not None and spec.loader is not None
    oracle_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle_module)
    manifest_payload = _io_path(ROOT / case["manifest"]).read_bytes()
    manifest_path = root / case["original"]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_payload)
    manifest = SourceManifest.load(manifest_path, repository_root=root)
    original_candidate_manifest = json.loads(candidate.member_bytes("manifest.json"))
    rebound_package = destination / "historical-path-package"
    shutil.copytree(_io_path(candidate.path), _io_path(rebound_package))
    rebound_manifest = deepcopy(original_candidate_manifest)
    assert rebound_manifest["source_manifest"]["path"] == case["manifest"]
    rebound_manifest["source_manifest"]["path"] = case["original"]
    restored_manifest = deepcopy(rebound_manifest)
    restored_manifest["source_manifest"]["path"] = original_candidate_manifest["source_manifest"]["path"]
    assert restored_manifest == original_candidate_manifest
    (rebound_package / "manifest.json").write_bytes(
        (json.dumps(rebound_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    rebound = CandidatePackage.load(rebound_package)
    for name in candidate.member_names:
        if name != "manifest.json":
            assert rebound.member_bytes(name) == candidate.member_bytes(name)
    assert json.loads(candidate.member_bytes("manifest.json")) == original_candidate_manifest
    candidate = rebound
    report = validate(manifest, candidate, oracle_module._oracle)
    assert report.status == "pass"
    cloned_package = base / "orthodoxy-current-20260928-v1/package"
    shutil.copytree(_io_path(candidate.path), _io_path(cloned_package))
    context = deepcopy(original)
    context["canonical_root"], context["stage_root"] = root.as_posix(), stage.as_posix()
    context["dependencies"].update(current_dependency_updates)
    for key, value in {"source_manifest_sha256": manifest.sha256, "candidate_package_sha256": candidate.sha256,
                       "oracle_report_sha256": report.sha256}.items():
        context["work"][key] = value
    if case["original"] in context["dependencies"]:
        _io_path(stage / case["original"]).write_bytes(manifest_payload)
        context["dependencies"][case["original"]] = manifest.sha256
    restored = deepcopy(context)
    for key in ("canonical_root", "stage_root"):
        restored[key] = original[key]
    for key in ("source_manifest_sha256", "candidate_package_sha256", "oracle_report_sha256"):
        restored["work"][key] = original["work"][key]
    restored["dependencies"] = original["dependencies"]
    assert restored == original
    expected_dependencies = dict(original["dependencies"])
    expected_dependencies.update(current_dependency_updates)
    if case["original"] in expected_dependencies:
        expected_dependencies[case["original"]] = manifest.sha256
    assert context["dependencies"] == expected_dependencies
    payload = (json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _io_path(stage / "stage-receipt.json").write_bytes(payload)
    assert _files(stage / work) == original["work"]["after"]
    return root, stage, base, sha256(payload).hexdigest(), oracle_module._oracle
