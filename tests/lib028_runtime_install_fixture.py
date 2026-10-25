"""Current LIB028 validation of frozen stage bodies in exact acquired test roots."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
from build.tei.lib028_oracle import _closure_paths, _producer_closure_paths
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.runtime_candidate_baselines import current_runtime_baseline

ROOT = Path(__file__).resolve().parents[1]


def lib028_current_context(route, destination):
    case = next(row for row in json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-puritan.json").read_bytes())
                if row["original"] == "sources/structured-text/eusebius-ecclesiastical-history/lib028.source-manifest.json")
    assert route.MANIFEST.as_posix() == case["original"]
    assert route.MANIFEST_SHA == case["original_sha256"]
    manifest, candidate = current_runtime_baseline(
        root=ROOT, original_manifest=case["original"], runtime_manifest=case["manifest"],
        retained_package=route.PACKAGE, retained_sha256=route.PACKAGE_SHA,
        destination=destination / "current-candidate")
    root, stages = destination / "historical-root", destination / "stages"
    root.mkdir()
    stage_pins = {}
    for work_id, original_pin in route.RECEIPT_SHA.items():
        original_stage = route.STAGE_ROOT / work_id
        raw = _io_path(original_stage / "stage-receipt.json").read_bytes()
        assert sha256(raw).hexdigest() == original_pin
        original = json.loads(raw)
        work = Path("library/works") / work_id
        assert _files(original_stage / work) == original["work"]["after"]
        stage = stages / work_id
        shutil.copytree(_io_path(original_stage), _io_path(stage))
        for relative, digest in original["dependencies"].items():
            payload = _io_path(original_stage / relative).read_bytes()
            assert sha256(payload).hexdigest() == digest
            target = _io_path(root / relative)
            if target.exists():
                assert target.read_bytes() == payload
            else:
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
                    acquired = next(x for x in value["targets"] if x["target_type"] == "acquisition")
                    assert edition["stage"] == "accepted"
                    edition["stage"] = "acquired"
                    edition.pop("reason")
                    edition["updated_at"] = acquired["updated_at"]
                    assert edition["evidence"][-2].endswith("/master.tei.xml")
                    assert edition["evidence"][-1].endswith("/acceptance.json")
                    edition["evidence"] = edition["evidence"][:-2]
                else:
                    raise AssertionError("Unexplained historical acquired bytes")
                payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            assert sha256(payload).hexdigest() == expected
            target = _io_path(root / work / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        assert _files(root / work) == original["work"]["before"]
        context = deepcopy(original)
        context["canonical_root"] = root.as_posix()
        context["stage_root"] = stage.as_posix()
        context["work"]["source_manifest_sha256"] = manifest.sha256
        context["work"]["candidate_package_sha256"] = candidate.sha256
        restored = deepcopy(context)
        for key in ("canonical_root", "stage_root"):
            restored[key] = original[key]
        for key in ("source_manifest_sha256", "candidate_package_sha256"):
            restored["work"][key] = original["work"][key]
        assert restored == original
        payload = (json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        _io_path(stage / "stage-receipt.json").write_bytes(payload)
        stage_pins[work_id] = sha256(payload).hexdigest()
        assert _files(stage / work) == original["work"]["after"]
    policy = json.loads(manifest.authority_path("validation-policy").read_bytes())
    paths = set(_closure_paths(ROOT, policy)) | set(_producer_closure_paths(ROOT))
    logical_paths = {path.relative_to(ROOT) for path in paths}
    logical_paths.update(Path(str(a["path"])) for a in manifest.record["authorities"])
    logical_paths.add(Path(case["manifest"]))
    xsd_closure = json.loads(manifest.authority_path("tei-p5-xsd-closure").read_bytes())
    assert xsd_closure["contract"] == "ocd-lib028-tei-xsd-closure-v1"
    for member in xsd_closure["members"]:
        relative = Path(member["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        payload = _io_path(ROOT / relative).read_bytes()
        assert len(payload) == member["bytes"] and sha256(payload).hexdigest() == member["sha256"]
        logical_paths.add(relative)
    for relative in logical_paths:
        payload = _io_path(ROOT / relative).read_bytes()
        target = _io_path(root / relative)
        if target.exists():
            assert target.read_bytes() == payload
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
    oracle_path = root / manifest.record["validator"]["implementation_path"]
    assert oracle_path.read_bytes() == _io_path(ROOT / manifest.record["validator"]["implementation_path"]).read_bytes()
    spec = importlib.util.spec_from_file_location("build.tei._lib028_current_install_fixture_oracle", oracle_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return root, stages, stage_pins, manifest, candidate, module._oracle
