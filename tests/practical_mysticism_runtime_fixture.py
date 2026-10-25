"""Real current-runtime source proof and exact acquired/staged Practical Mysticism fixtures."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

from build.tei.se_candidate_oracle import _closure
from build.tools.reconstruct_candidate import _bound_callable
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.install_accepted import _files, _io_path

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "tests/fixtures/practical-mysticism-acquired-before"
ORIGINAL_STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/practical-mysticism-stage-20260928-v1")
ORIGINAL_PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/practical-mysticism-current-20260928-v1/package")
MANIFEST = Path("sources/standard-ebooks/evelyn-underhill_practical-mysticism/practical-mysticism.source-manifest.json")
MANIFEST_SHA = "afff3494208de6fa63b38fda51dfb79afb66e056844fce0e2dff941c589523d0"
PACKAGE_SHA = "653961af8dd5a750584ade2fab622bc54c358bc5310d4fc4143c2ef451b09138"
WORK = Path("library/works/practical-mysticism")


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def runtime_context(tmp_path, monkeypatch, test_module):
    from build.tools import stage_practical_mysticism_current as producer
    from build.tools import install_practical_mysticism_current as installer

    inventory = json.loads((BEFORE / "stage-inventory.json").read_bytes())
    assert _files(ORIGINAL_STAGE) == inventory["files"]
    original_stage_raw = (ORIGINAL_STAGE / "stage-receipt.json").read_bytes()
    assert sha256(original_stage_raw).hexdigest() == inventory["receipt_sha256"]
    original_stage_record = json.loads(original_stage_raw)
    original_raw = (ROOT / MANIFEST).read_bytes()
    assert sha256(original_raw).hexdigest() == MANIFEST_SHA
    original_manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    retained = CandidatePackage.load(ORIGINAL_PACKAGE)
    assert retained.sha256 == PACKAGE_SHA
    assert retained.manifest["source_manifest"]["sha256"] == MANIFEST_SHA

    mirror = tmp_path / "source-root"
    mirror.mkdir()
    # Every declared source/config/profile/policy/schema/implementation is copied exactly.
    for row in original_manifest.record["authorities"]:
        raw = _io_path(original_manifest.authority_path(row["name"])).read_bytes()
        assert len(raw) == row["bytes"] and sha256(raw).hexdigest() == row["sha256"]
        target = mirror / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    # Mirror only actual CURRENT first-party imports. No historical kernel is restored.
    imports = {}
    for start in (ROOT / original_manifest.record[role]["implementation_path"] for role in ("converter", "validator")):
        _, rows = _closure(ROOT, start=start)
        for row in rows:
            raw = (ROOT / row["path"]).read_bytes()
            assert sha256(raw).hexdigest() == row["sha256"]
            target = mirror / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                assert target.read_bytes() == raw
            target.write_bytes(raw)
            imports[row["path"]] = raw
    for relative in (
        "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd",
        "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd",
        "metadata/source-evidence/catalog/practical-mysticism.json",
    ):
        target = mirror / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    for name in ("work.json", "state.json"):
        target = mirror / WORK / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((BEFORE / name).read_bytes())
    current = deepcopy(json.loads(original_raw))
    oracle = _bound_callable(mirror, current["validator"], role="validator")
    closure, closure_rows = oracle.__globals__["_closure"](mirror)
    assert closure != current["validator"]["import_closure_sha256"]
    current["validator"]["import_closure_sha256"] = closure
    reverse = deepcopy(current)
    reverse["validator"]["import_closure_sha256"] = json.loads(original_raw)["validator"]["import_closure_sha256"]
    assert reverse == json.loads(original_raw)
    manifest_path = mirror / MANIFEST
    manifest_path.write_bytes(_json(current))
    manifest = SourceManifest.load(manifest_path, repository_root=mirror)
    destination = tmp_path / "current-candidate"
    result = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--repository-root", str(mirror),
         "--manifest", MANIFEST.as_posix(), "--destination", str(destination)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "pass"
    package = CandidatePackage.load(destination / "package")
    assert package.member_names == retained.member_names
    for name in package.member_names:
        if name == "manifest.json":
            expected = json.loads(retained.member_bytes(name))
            expected["source_manifest"]["sha256"] = manifest.sha256
            provenance = package.member_bytes("provenance.json")
            member = next(row for row in expected["members"] if row["name"] == "provenance.json")
            member.update(sha256=sha256(provenance).hexdigest(), bytes=len(provenance))
            assert json.loads(package.member_bytes(name)) == expected
        elif name == "provenance.json":
            observed = json.loads(package.member_bytes(name))
            expected = json.loads(retained.member_bytes(name))
            assert expected["source_manifest_sha256"] == MANIFEST_SHA
            expected["source_manifest_sha256"] = manifest.sha256
            assert observed == expected
        else:
            assert package.member_bytes(name) == retained.member_bytes(name), name
    report = validate(manifest, package, oracle)
    assert report.status == "pass" and not report.findings
    monkeypatch.setattr(producer, "ROOT", mirror)
    monkeypatch.setattr(producer, "PACKAGE", package.path)
    monkeypatch.setattr(producer, "MANIFEST_SHA256", manifest.sha256)
    monkeypatch.setattr(producer, "PACKAGE_SHA256", package.sha256)
    monkeypatch.setattr(producer, "_oracle", oracle)
    direct, sidecars, actual_oracle = producer.source_check()
    assert direct == retained.member_bytes("content.tei.xml")

    stage = tmp_path / ORIGINAL_STAGE.name
    shutil.copytree(ORIGINAL_STAGE, stage)
    acquired = tmp_path / "acquired-root"
    shutil.copytree(ORIGINAL_STAGE, acquired)
    shutil.rmtree(acquired / WORK)
    for relative, digest in inventory["before"].items():
        source = BEFORE / relative if relative in {"work.json", "state.json"} else ORIGINAL_STAGE / WORK / relative
        raw = source.read_bytes()
        assert sha256(raw).hexdigest() == digest
        target = acquired / WORK / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    assert _files(acquired / WORK) == inventory["before"]
    record = deepcopy(original_stage_record)
    record["stage_root"] = stage.as_posix()
    record["dependencies"] = {relative: sha256((ROOT / relative).read_bytes()).hexdigest()
                              for relative in original_stage_record["dependencies"]}
    for relative in record["dependencies"]:
        target = acquired / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    record["source_manifest_sha256"] = manifest.sha256
    record["direct_package_sha256"] = package.sha256
    record["oracle"] = actual_oracle
    oracle_relative = "integration/practical-mysticism-current-v1/inputs/oracle.json"
    (stage / WORK / oracle_relative).write_bytes(_json(actual_oracle))
    record["after"][oracle_relative] = sha256(_json(actual_oracle)).hexdigest()
    (stage / "stage-receipt.json").write_bytes(_json(record))
    allowed = {"stage-receipt.json", (WORK / oracle_relative).as_posix()}
    current_stage_files = _files(stage)
    assert set(current_stage_files) == set(inventory["files"])
    assert all(current_stage_files[p] == h for p, h in inventory["files"].items() if p not in allowed)
    assert {k: v for k, v in record.items() if k not in {
        "stage_root", "dependencies", "source_manifest_sha256", "direct_package_sha256", "oracle", "after"
    }} == {k: v for k, v in original_stage_record.items() if k not in {
        "stage_root", "dependencies", "source_manifest_sha256", "direct_package_sha256", "oracle", "after"
    }}
    assert {k: v for k, v in record["after"].items() if k != oracle_relative} == {
        k: v for k, v in original_stage_record["after"].items() if k != oracle_relative
    }
    monkeypatch.setattr(installer, "ROOT", acquired)
    monkeypatch.setattr(installer, "STAGE_PARENT", tmp_path)
    monkeypatch.setattr(installer, "STAGE", stage)
    monkeypatch.setattr(installer, "RECEIPT_SHA256", sha256(_json(record)).hexdigest())
    monkeypatch.setattr(installer, "MANIFEST_SHA256", manifest.sha256)
    monkeypatch.setattr(installer, "PACKAGE_SHA256", package.sha256)
    monkeypatch.setattr(installer, "source_check", producer.source_check)
    monkeypatch.setattr(test_module, "ROOT", acquired)
    monkeypatch.setattr(test_module, "PACKAGE_SHA256", package.sha256)
    monkeypatch.setattr(test_module, "source_check", producer.source_check)
    assert _files(ORIGINAL_STAGE) == inventory["files"]
    assert (ROOT / MANIFEST).read_bytes() == original_raw
    assert all((ROOT / p).read_bytes() == b for p, b in imports.items())
    return {"manifest": manifest, "package": package, "oracle": oracle, "inventory": inventory,
            "stage": stage, "acquired": acquired, "original_root": ROOT,
            "original_stage": ORIGINAL_STAGE, "original_stage_record": original_stage_record}
