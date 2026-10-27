"""Current shared-code proof for the retained Watson Contentment closure recipe."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.watson_divine_contentment_oracle import CLOSURE, closure_digest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = "tests/fixtures/reconstruction-runtime/watson-divine-contentment.source-manifest.json"
RUNTIME_SHA = "05ed01b85896a563ca0aaadc740f600d74486e0d21ecb7cb0b836fde22225132"


def current_contentment_closure_context(route, destination, monkeypatch):
    historical_raw = (ROOT / route.HISTORICAL_MANIFEST).read_bytes()
    assert sha256(historical_raw).hexdigest() == route.HISTORICAL_MANIFEST_SHA
    runtime_raw = (ROOT / RUNTIME).read_bytes()
    assert sha256(runtime_raw).hexdigest() == RUNTIME_SHA
    historical, runtime = json.loads(historical_raw), json.loads(runtime_raw)
    restored = deepcopy(runtime)
    changed = {}
    for old, new, undo in zip(historical["authorities"], runtime["authorities"], restored["authorities"], strict=True):
        assert old["name"] == new["name"]
        if new["name"] == "work":
            assert old["path"] == "library/works/watson-divine-contentment/work.json"
            assert new["path"] == "tests/fixtures/reconstruction-runtime/authorities/watson-divine-contentment-original-bound-work.json"
            undo["path"] = old["path"]
        else:
            assert old["path"] == new["path"]
        if old != undo:
            changed[new["name"]] = (new["bytes"], new["sha256"])
            undo["bytes"], undo["sha256"] = old["bytes"], old["sha256"]
    restored["validator"]["import_closure_sha256"] = historical["validator"]["import_closure_sha256"]
    assert restored == historical
    assert set(changed) == {"closure-identities", "closure-common", "closure-storage-topology", "closure-contract", "closure-work-schema"}
    destination.mkdir()
    work = Path(*route.EDITION.parts[:3])
    shutil.copytree(ROOT / work, destination / work)
    work_raw = (ROOT / work / "work.json").read_bytes()
    work_binding = next(row for row in runtime["authorities"] if row["name"] == "work")
    held_work = (ROOT / work_binding["path"]).read_bytes()
    assert len(held_work) == work_binding["bytes"] and sha256(held_work).hexdigest() == work_binding["sha256"]
    (destination / work / "work.json").write_bytes(held_work)
    shutil.copy2(ROOT / ".ocd-storage.json", destination / ".ocd-storage.json")
    paths = {row["path"] for row in runtime["authorities"] if row["path"].split("/", 1)[0] not in {"raw", "reports", "exports"}}
    paths.update(CLOSURE)
    paths.update(runtime[role]["implementation_path"] for role in ("converter", "validator"))
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = (ROOT / relative).read_bytes()
        if target.exists():
            assert target.read_bytes() == content
        else:
            target.write_bytes(content)
    original = destination / route.HISTORICAL_MANIFEST
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(historical_raw)
    assert not (destination / route.CURRENT_MANIFEST).exists()
    expected_closure = runtime["validator"]["import_closure_sha256"]
    assert closure_digest(destination) == expected_closure
    monkeypatch.setattr(route, "ROOT", destination)
    monkeypatch.setattr(route, "CURRENT_CLOSURE_SHA", expected_closure)
    monkeypatch.setattr(route, "CHANGED_AUTHORITIES", changed)
    assert (ROOT / route.HISTORICAL_MANIFEST).read_bytes() == historical_raw
    assert (ROOT / work / "work.json").read_bytes() == work_raw
    return destination
