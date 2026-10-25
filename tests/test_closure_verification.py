"""Explicit closure audit routes stay contained and track actual dependency bytes."""
from hashlib import sha256
from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from ocd_kernel.reconstruction import closure_verification as owner


def _record():
    return {"contract": "ocd-source-manifest-v1", "work_id": "fixture", "authorities": [],
            "validator": {"implementation_path": "unknown.py", "import_closure_sha256": "a" * 64}}


@pytest.mark.parametrize("logical", (
    "sources/book/source-manifest.json", "sources/book/book.source-manifest.v2.json",
    "sources/book/source-manifest.canonical-v1.json",
    "tests/fixtures/reconstruction-runtime/book.source-manifest.json",
))
def test_explicit_source_or_runtime_manifest_routes_remain_contained(tmp_path, monkeypatch, logical):
    path = tmp_path / logical
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_record()), encoding="utf-8")
    calls = []
    def live(root, implementation, record, *, manifest_path):
        calls.append((root, implementation, manifest_path))
        return "a" * 64, "fixture live route"
    monkeypatch.setattr(owner, "_call_validator_closure", live)
    result = owner.check_validator_manifest_closure(tmp_path, logical)
    assert result.matches and result.manifest_path == logical
    assert calls == [(tmp_path, "unknown.py", path)]


@pytest.mark.parametrize("logical", (
    "docs/book.source-manifest.json", "tests/fixtures/other/book.source-manifest.json",
    "sources/book/book.source-manifest.v0.json", "sources/book/manifest.json",
    "sources/book/source-manifest.canonical-v0.json",
    "sources/book/source-manifest.arbitrary-v1.json",
))
def test_arbitrary_location_or_nonmanifest_filename_is_rejected(tmp_path, monkeypatch, logical):
    path = tmp_path / logical
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_record()), encoding="utf-8")
    monkeypatch.setattr(owner, "_call_validator_closure", lambda *a, **k: pytest.fail("invalid path reached route"))
    with pytest.raises(ValueError, match="outside sources|not a source-manifest"):
        owner.check_validator_manifest_closure(tmp_path, logical)


@pytest.mark.parametrize("logical", ("../outside.source-manifest.json", "sources/../source-manifest.json"))
def test_explicit_manifest_traversal_is_rejected_before_loading(tmp_path, logical):
    with pytest.raises(ValueError, match="must be repository-relative"):
        owner.check_validator_manifest_closure(tmp_path, logical)


@pytest.mark.parametrize("route_name,extra", (
    ("lib054_work_local_oracle", ()),
    ("lib054_edwards_fragments_oracle", ("build/tei/lib054_work_local_oracle.py",)),
))
def test_root_import_closure_adapter_tracks_live_lib054_route(tmp_path, monkeypatch, route_name, extra):
    import importlib
    route = importlib.import_module("build.tei." + route_name)
    logical = "build/tei/" + route_name + ".py"
    paths = (logical,) + extra + ("ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/verifier.py", "ocd_kernel/tei/validate.py")
    for number, path in enumerate(paths):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# dependency {number}\n", encoding="utf-8")
    monkeypatch.setattr(owner, "_module", lambda root, path: route)
    digest, strategy = owner._call_validator_closure(tmp_path, logical, {"authorities": []})
    assert (digest, strategy) == (route._import_closure_sha256(tmp_path), "_import_closure_sha256(root)")
    (tmp_path / "ocd_kernel/reconstruction/contract.py").write_bytes(b"# current dependency changed\n")
    changed, _ = owner._call_validator_closure(tmp_path, logical, {"authorities": []})
    assert changed != digest and changed == route._import_closure_sha256(tmp_path)


@pytest.mark.parametrize("volume", ("103", "104", "105", "205", "206"))
def test_inline_npnf_work_adapters_keep_order_and_read_declared_members(tmp_path, monkeypatch, volume):
    import importlib
    route = importlib.import_module(f"build.tei.npnf{volume}_work_oracle")
    logical = f"build/tei/npnf{volume}_work_oracle.py"
    paths = [logical, f"build/tei/npnf{volume}_oracle.py", "ocd_kernel/reconstruction/contract.py"]
    for number, path in enumerate(paths):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# dependency {number}\n", encoding="utf-8")
    monkeypatch.setattr(owner, "_module", lambda root, path: route)
    monkeypatch.setattr(owner, "_policy", lambda root, record: {"closure_inputs": paths})
    rows = [{"path": p, "sha256": sha256((tmp_path / p).read_bytes()).hexdigest()} for p in paths]
    digest, strategy = owner._call_validator_closure(tmp_path, logical, {})
    assert (digest, strategy) == (route._sha(route._json(rows)), f"NPNF{volume} policy closure rows")
    paths.reverse()
    reordered, _ = owner._call_validator_closure(tmp_path, logical, {})
    assert reordered == route._sha(route._json(list(reversed(rows)))) and reordered != digest
    paths.reverse()
    (tmp_path / paths[-1]).write_bytes(b"# actual dependency changed\n")
    changed, _ = owner._call_validator_closure(tmp_path, logical, {})
    assert changed != digest
    paths[-1] = "../escaped.py"
    with pytest.raises(ValueError, match="must be repository-relative"):
        owner._call_validator_closure(tmp_path, logical, {})


def test_policy_rows_do_not_enable_unknown_implementations(tmp_path, monkeypatch):
    (tmp_path / "unknown.py").write_bytes(b"# no supported closure API\n")
    monkeypatch.setattr(owner, "_module", lambda root, path: SimpleNamespace())
    monkeypatch.setattr(owner, "_policy", lambda root, record: {"closure_inputs": ["unknown.py"]})
    with pytest.raises(NotImplementedError, match="no live validator closure adapter"):
        owner._call_validator_closure(tmp_path, "unknown.py", {})


def test_manifest_location_does_not_bypass_its_contract(tmp_path, monkeypatch):
    path = tmp_path / "tests/fixtures/reconstruction-runtime/book.source-manifest.json"
    path.parent.mkdir(parents=True)
    record = _record() | {"contract": "unexpected"}
    path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(owner, "_call_validator_closure", lambda *a, **k: pytest.fail("bad contract reached route"))
    with pytest.raises(ValueError, match="contract mismatch"):
        owner.check_validator_manifest_closure(tmp_path, path.relative_to(tmp_path))


@pytest.mark.parametrize("inside", (False, True))
def test_absolute_manifest_path_stays_rejected_before_io(tmp_path, monkeypatch, inside):
    path = (tmp_path / "sources/book/source-manifest.json" if inside else
            tmp_path.parent / "outside.source-manifest.json")
    monkeypatch.setattr(owner, "_call_validator_closure", lambda *a, **k: pytest.fail("absolute path reached route"))
    with pytest.raises(ValueError, match="must be repository-relative"):
        owner.check_validator_manifest_closure(tmp_path, path)


def test_lutheran_public_closure_adapter_reads_actual_dependencies(tmp_path, monkeypatch):
    from build.tei import lutheran_hymnbook_pg76498_oracle as route
    logical = "build/tei/lutheran_hymnbook_pg76498_oracle.py"
    for number, path in enumerate(route.CLOSURE):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# dependency {number}\n", encoding="utf-8")
    monkeypatch.setattr(owner, "_module", lambda root, path: route)
    digest, strategy = owner._call_validator_closure(tmp_path, logical, {"authorities": []})
    assert (digest, strategy) == (route.import_closure_sha256(tmp_path), "import_closure_sha256(root)")
    (tmp_path / route.CLOSURE[-1]).write_bytes(b"# current dependency changed\n")
    changed, _ = owner._call_validator_closure(tmp_path, logical, {"authorities": []})
    assert changed == route.import_closure_sha256(tmp_path) and changed != digest


@pytest.mark.parametrize("volume", ("109", "113"))
def test_npnf_work_preparation_closures_read_live_ordered_members(tmp_path, monkeypatch, volume):
    import importlib
    route = importlib.import_module(f"build.tei.npnf{volume}_work_oracle")
    preparation = importlib.import_module(f"build.tools.prepare_npnf{volume}_work_candidates")
    logical = f"build/tei/npnf{volume}_work_oracle.py"
    preparation_path = f"build/tools/prepare_npnf{volume}_work_candidates.py"
    assert preparation.ORACLE.as_posix() == logical
    paths = (preparation.ORACLE, preparation.SOURCE_RULES, Path("ocd_kernel/reconstruction/contract.py"))
    for number, path in enumerate(paths):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# dependency {number}\n", encoding="utf-8")
    modules = {logical: route, preparation_path: preparation}
    monkeypatch.setattr(owner, "_module", lambda root, path: modules[path])
    record = {"authorities": [], "validator": {"import_closure_sha256": "a" * 64}}
    expected = [{"path": p.as_posix(), "sha256": sha256((tmp_path / p).read_bytes()).hexdigest()} for p in paths]
    digest, strategy = owner._call_validator_closure(tmp_path, logical, record)
    assert (digest, strategy) == (preparation._sha(preparation._json(expected)), "NPNF work preparation closure")
    assert digest != record["validator"]["import_closure_sha256"]
    assert digest != preparation._sha(preparation._json(list(reversed(expected))))
    (tmp_path / paths[-1]).write_bytes(b"# actual contract dependency changed\n")
    changed, _ = owner._call_validator_closure(tmp_path, logical, record)
    assert changed != digest
    monkeypatch.setattr(preparation, "ORACLE", Path("different-oracle.py"))
    with pytest.raises(ValueError, match="preparation oracle route differs"):
        owner._call_validator_closure(tmp_path, logical, record)


def test_l596_oracle_closure_reads_actual_implementation_bytes(tmp_path, monkeypatch):
    logical = "build/tei/web_eng_oracle.py"
    path = tmp_path / logical
    path.parent.mkdir(parents=True)
    path.write_bytes(b"# original oracle\n")
    monkeypatch.setattr(owner, "_module", lambda root, implementation: SimpleNamespace())
    record = {"authorities": [], "validator": {"import_closure_sha256": "a" * 64}}
    digest, strategy = owner._call_validator_closure(tmp_path, logical, record)
    assert (digest, strategy) == (sha256(path.read_bytes()).hexdigest(), "L596 oracle implementation bytes")
    assert digest != record["validator"]["import_closure_sha256"]
    path.write_bytes(b"# changed actual oracle\n")
    changed, _ = owner._call_validator_closure(tmp_path, logical, record)
    assert changed == sha256(path.read_bytes()).hexdigest() and changed != digest


@pytest.mark.parametrize("name", ("before_most_holy_pg76888", "eliza_southall_pg11959", "evening_incense_pg50916"))
def test_noarg_oracle_closure_uses_actual_owner_and_contract_bytes(tmp_path, monkeypatch, name):
    import importlib
    route = importlib.import_module(f"build.tei.{name}_oracle")
    logical = f"build/tei/{name}_oracle.py"
    entry = tmp_path / logical
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b"# oracle input\n")
    contract = tmp_path / "contract.py"
    contract.write_bytes(b"# contract input\n")
    original_getsourcefile = route.inspect.getsourcefile
    monkeypatch.setattr(route, "__file__", str(entry))
    monkeypatch.setattr(route.inspect, "getsourcefile", lambda value: str(contract) if value is route.SourceManifest else original_getsourcefile(value))
    monkeypatch.setattr(owner, "_module", lambda root, path: route)
    record = {"authorities": [], "validator": {"import_closure_sha256": "a" * 64}}
    digest, strategy = owner._call_validator_closure(tmp_path, logical, record)
    expected = {"oracle": sha256(entry.read_bytes()).hexdigest(), "reconstruction-contract": sha256(contract.read_bytes()).hexdigest()}
    assert (digest, strategy) == (route._sha(route._canonical(expected)), "_closure_sha()")
    assert digest != record["validator"]["import_closure_sha256"]
    contract.write_bytes(b"# changed live contract\n")
    changed, _ = owner._call_validator_closure(tmp_path, logical, record)
    assert changed == route._closure_sha() and changed != digest
