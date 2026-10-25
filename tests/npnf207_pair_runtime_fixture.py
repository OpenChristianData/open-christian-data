"""Actual current oracles and candidates for the two frozen NPNF207 bodies."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
from build.tei.se_candidate_oracle import _closure
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.runtime_candidate_baselines import current_runtime_baseline
from tests.vendored_schema_mirrors import copy_vendored_schema_imports

ROOT = Path(__file__).resolve().parents[1]


def npnf207_pair_context(route, destination):
    root, stages = destination / "root", destination / "stages"
    root.mkdir()
    pins, routes, replacements = {}, deepcopy(route.ROUTES), {}
    cases = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-henry.json").read_bytes())
    oracle = None
    for work_id, original_pin in route.RECEIPT_SHA.items():
        original_stage = route.STAGE_ROOT / work_id
        raw = _io_path(original_stage / "stage-receipt.json").read_bytes()
        assert sha256(raw).hexdigest() == original_pin
        original = json.loads(raw)
        case = next(row for row in cases if row["original"] == routes[work_id]["manifest"])
        retained = Path("D:/Library/Open Christian Data/candidate-reviews") / f"{work_id}-npnf207-native-screen-20260928-v1"
        manifest, candidate = current_runtime_baseline(
            root=ROOT, original_manifest=case["original"], runtime_manifest=case["manifest"],
            retained_package=retained, retained_sha256=original["work"]["candidate_package_sha256"],
            destination=destination / (work_id + "-current"))
        replacements[retained.resolve()] = (candidate, original["work"]["candidate_package_sha256"])
        routes[work_id]["manifest"] = case["manifest"]
        stage = stages / work_id
        shutil.copytree(_io_path(original_stage), _io_path(stage))
        work = Path(original["work"]["work_path"])
        assert _files(stage / work) == original["work"]["after"]
        for relative, digest in original["dependencies"].items():
            payload = _io_path(stage / relative).read_bytes()
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
                    raise AssertionError("Undocumented acquired transition")
                payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            assert sha256(payload).hexdigest() == expected
            target = _io_path(root / work / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        assert _files(root / work) == original["work"]["before"]
        logical_paths = {str(a["path"]) for a in manifest.record["authorities"]}
        logical_paths.add(case["manifest"])
        for role in ("converter", "validator"):
            _, members = _closure(ROOT, ROOT / manifest.record[role]["implementation_path"])
            logical_paths.update(row["path"] for row in members)
        for relative in logical_paths:
            payload = _io_path(ROOT / relative).read_bytes()
            target = _io_path(root / relative)
            if target.exists():
                assert target.read_bytes() == payload
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
        copy_vendored_schema_imports(ROOT, root)
        context = deepcopy(original)
        context["canonical_root"], context["stage_root"] = root.as_posix(), stage.as_posix()
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
        pins[work_id] = sha256(payload).hexdigest()
        if oracle is None:
            oracle_path = root / manifest.record["validator"]["implementation_path"]
            assert oracle_path.read_bytes() == _io_path(ROOT / manifest.record["validator"]["implementation_path"]).read_bytes()
            spec = importlib.util.spec_from_file_location("build.tei._npnf207_current_fixture_oracle", oracle_path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            oracle = module._oracle
    return root, stages, pins, routes, replacements, oracle
