"""Historical audit collection must not change other suites' import roots."""
import importlib.util
import inspect
import json
from pathlib import Path
import sys


def test_historical_candidate_collection_keeps_its_import_root_local(tmp_path):
    root = Path(__file__).resolve().parents[1]
    copied = tmp_path / "workspace" / "tests" / "test_manifest_apologetics_seven_candidate_challenge.py"
    copied.parent.mkdir(parents=True)
    copied.write_bytes((root / "tests" / copied.name).read_bytes())
    retained = tmp_path / "retained-execution"
    (retained / "cvw_app").mkdir(parents=True)
    audit = copied.parents[1] / "plans/2026-09-23-acquisition-manifest-source-to-tei/APOLOGETICS_SEVEN_TECHNICAL_20260927.json"
    audit.parent.mkdir(parents=True)
    audit.write_text(json.dumps({"execution_root": str(retained), "works": []}), encoding="utf-8")
    before = sys.path[:]
    try:
        spec = importlib.util.spec_from_file_location("_historical_collection_probe", copied)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        observed = sys.path[:]
    finally:
        sys.path[:] = before
    assert observed == before
    assert module.EXECUTION_ROOT == retained

    import cvw_app
    importlib.invalidate_caches()
    namespaces = list(cvw_app.__path__)
    context = inspect.unwrap(module.bound_execution_imports)()
    next(context)
    try:
        assert str(retained / "cvw_app") in list(cvw_app.__path__)
    finally:
        context.close()
    assert sys.path == before
    assert list(cvw_app.__path__) == namespaces
