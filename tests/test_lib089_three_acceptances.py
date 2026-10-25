"""Focused frozen-cohort and guarded-install checks for three LIB-089 works."""

from __future__ import annotations

from hashlib import sha256
import json
import importlib.util
import shutil
from pathlib import Path

import pytest

from build.tools import install_lib089_three_acceptances as installer
from tests.runtime_candidate_baselines import current_runtime_baseline
from build.tools.stage_lib089_three_acceptances import COHORT, ROOT, WORK_IDS, _paths
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


def _fixture(root: Path, work_id: str) -> Path:
    stage = installer.COHORT / work_id
    work_path, _, _, _, _ = _paths(work_id)
    _io_path(root).mkdir(parents=True, exist_ok=True)
    _io_path(root / installer.FIXTURE_MARKER).write_bytes(b"fixture-only\n")
    prefix = work_path.as_posix() + "/"
    for name in _files(stage):
        if name == "stage-receipt.json" or name.startswith(prefix):
            continue
        target = _io_path(root / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_io_path(stage / name).read_bytes())
    for name in _files(installer.ROOT / work_path):
        target = _io_path(root / work_path / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_io_path(installer.ROOT / work_path / name).read_bytes())
    return root


def test_three_exact_receipts_source_credits_and_read_only_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    assert sha256(_io_path(installer.INDEX).read_bytes()).hexdigest() == installer.INDEX_SHA
    before = {work_id: _files(ROOT / _paths(work_id)[0]) for work_id in WORK_IDS}
    rows = [installer.preflight(work_id) for work_id in WORK_IDS]
    assert [row["native_rows"] for row in rows] == [1, 5, 4]
    assert all(row["status"] == "ready-for-review" and row["after_files"] == 22 for row in rows)
    for work_id in WORK_IDS:
        assert _files(ROOT / _paths(work_id)[0]) == before[work_id]
        assert "SOURCE_CREDIT.md" in _files(COHORT / work_id / _paths(work_id)[0])
    monkeypatch.setattr(installer, "INDEX_SHA", "0" * 64)
    with pytest.raises(PipelineError, match="frozen cohort index differs"):
        installer.preflight(WORK_IDS[0])


def test_publick_long_path_fixture_rollback_then_installs(tmp_path: Path) -> None:
    work_id = "directory-for-publick-worship"
    fixture = _fixture(tmp_path / ("lib089-publick-fixture-" + "x" * 35), work_id)
    work_path, edition_path, _, _, _ = _paths(work_id)
    assert len(str(fixture / edition_path / "master.tei.xml")) > 260
    before = _files(fixture / work_path)

    def fail_after_new_live(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected LIB-089 swap failure")

    with pytest.raises(RuntimeError, match="injected LIB-089 swap failure"):
        installer.install(work_id, root_override=fixture, fail_at=fail_after_new_live)
    assert _files(fixture / work_path) == before
    result = installer.install(work_id, root_override=fixture)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 5


@pytest.fixture(scope="module", autouse=True)
def historical_cohort(tmp_path_factory: pytest.TempPathFactory):
    original_index_raw = _io_path(installer.INDEX).read_bytes()
    assert sha256(original_index_raw).hexdigest() == installer.INDEX_SHA
    original_index = json.loads(original_index_raw)
    home = tmp_path_factory.mktemp("lib089-historical")
    root, cohort = home / "root", home / "cohort"
    root.mkdir()
    cohort.mkdir()
    current_index = json.loads(original_index_raw)
    candidates = home / "current-candidates"
    candidates.mkdir()
    last_manifest = None
    for pin in current_index["works"]:
        work_id = pin["work_id"]
        original_stage = COHORT / work_id
        receipt_raw = _io_path(original_stage / "stage-receipt.json").read_bytes()
        assert sha256(receipt_raw).hexdigest() == pin["receipt_sha256"]
        original = json.loads(receipt_raw)
        work, _, _, manifest_logical, evidence = _paths(work_id)
        runtime = Path("tests/fixtures/reconstruction-runtime") / f"lib089-{work_id}.source-manifest.json"
        candidate_home = candidates / f"lib089-{work_id}-current-20260928-v1"
        assert _files(original_stage / work) == original["after"]
        stage = cohort / work_id
        shutil.copytree(_io_path(original_stage), _io_path(stage))
        for relative, expected in original["before"].items():
            payload = _io_path(original_stage / work / relative).read_bytes()
            assert sha256(payload).hexdigest() == original["after"][relative]
            if sha256(payload).hexdigest() != expected:
                value = json.loads(payload)
                if relative == "work.json":
                    form = value["textual_forms"][0]
                    assert form.pop("language") == "en"
                    edition = form["editions"][0]
                    assert edition.pop("language") == "en"
                    assert edition.pop("category") == "prose"
                elif relative == "state.json":
                    edition = next(t for t in value["targets"] if t["target_type"] == "edition")
                    acquisition = next(t for t in value["targets"] if t["target_type"] == "acquisition")
                    assert edition["stage"] == "accepted"
                    edition["stage"] = "acquired"
                    edition.pop("reason")
                    edition["updated_at"] = acquisition["updated_at"]
                    assert edition["evidence"][-2].endswith("/master.tei.xml")
                    assert edition["evidence"][-1].endswith("/acceptance.json")
                    edition["evidence"] = edition["evidence"][:-2]
                else:
                    raise AssertionError("Acquisition must retain its complete original bytes")
                payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            assert sha256(payload).hexdigest() == expected
            target = _io_path(root / work / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        assert _files(root / work) == original["before"]
        prefix = work.as_posix() + "/"
        for relative in _files(original_stage):
            if relative == "stage-receipt.json" or relative.startswith(prefix):
                continue
            payload = _io_path(original_stage / relative).read_bytes()
            target = _io_path(root / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                assert target.read_bytes() == payload
            else:
                target.write_bytes(payload)
        # The real contract binds the source manifest PATH as well as its SHA.
        # Generate at the historical logical route in this current-code mirror.
        runtime_raw = _io_path(ROOT / runtime).read_bytes()
        runtime_record = json.loads(runtime_raw)
        for authority in runtime_record["authorities"]:
            relative = Path(authority["path"])
            authority_raw = _io_path(ROOT / relative).read_bytes()
            assert len(authority_raw) == authority["bytes"]
            assert sha256(authority_raw).hexdigest() == authority["sha256"]
            for place in (root, stage):
                target = _io_path(place / relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    assert target.read_bytes() == authority_raw
                else:
                    target.write_bytes(authority_raw)
        for role in ("converter", "validator"):
            implementation = runtime_record[role]
            assert sha256(_io_path(ROOT / implementation["implementation_path"]).read_bytes()).hexdigest() == implementation["implementation_sha256"]
        for relative in {
            Path(runtime_record["converter"]["implementation_path"]),
            Path(runtime_record["validator"]["implementation_path"]),
            Path("build/__init__.py"),
            Path("build/tei/__init__.py"),
            Path("ocd_kernel/__init__.py"),
            Path("ocd_kernel/reconstruction/contract.py"),
            Path("ocd_kernel/reconstruction/verifier.py"),
            Path("ocd_kernel/reconstruction/__init__.py"),
        }:
            target = _io_path(root / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_io_path(ROOT / relative).read_bytes())
        historical_record = Path("historical-source-records") / work_id / "source-manifest.json"
        target = root / historical_record
        target.parent.mkdir(parents=True, exist_ok=True)
        original_manifest_raw = _io_path(ROOT / manifest_logical).read_bytes()
        assert sha256(original_manifest_raw).hexdigest() == original["source_manifest_sha256"]
        target.write_bytes(original_manifest_raw)
        _io_path(root / manifest_logical).write_bytes(runtime_raw)
        current_manifest, current_candidate = current_runtime_baseline(
            root=root, tool_root=ROOT, original_manifest=historical_record, runtime_manifest=manifest_logical,
            retained_package=installer.CANDIDATE_ROOT / f"lib089-{work_id}-current-20260928-v1/package",
            retained_sha256=original["candidate_package_sha256"], destination=candidate_home)
        assert current_candidate.manifest["source_manifest"]["path"] == manifest_logical.as_posix()
        current_validation = json.loads((candidate_home / "validation.json").read_bytes())
        last_manifest = current_manifest
        # Only runtime envelope identity changes; every retained candidate content byte,
        # acceptance, master, and historical evidence report remains unchanged.
        package_manifest = evidence / "inputs/package/manifest.json"
        package_root = stage / evidence / "inputs/package"
        assert set(_files(package_root)) == set(current_candidate.member_names)
        for name in current_candidate.member_names:
            _io_path(package_root / name).write_bytes(current_candidate.member_bytes(name))
        for destination in (root / manifest_logical, stage / manifest_logical):
            _io_path(destination).write_bytes(_io_path(ROOT / runtime).read_bytes())
        after = _files(stage / work)
        changed = {name for name in original["after"] if after[name] != original["after"][name]}
        assert changed == {
            package_manifest.relative_to(work).as_posix(),
            (package_manifest.parent / "provenance.json").relative_to(work).as_posix(),
        }
        derived = dict(original, canonical_root=root.as_posix(), stage_root=stage.as_posix(),
                       source_manifest_sha256=current_manifest.sha256,
                       candidate_package_sha256=current_candidate.sha256,
                       oracle_report_sha256=current_validation["report_sha256"], after=after)
        restored = dict(derived)
        for key in ("canonical_root", "stage_root", "source_manifest_sha256",
                    "candidate_package_sha256", "oracle_report_sha256", "after"):
            restored[key] = original[key]
        assert restored == original
        payload = (json.dumps(derived, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        (stage / "stage-receipt.json").write_bytes(payload)
        pin["receipt_sha256"] = sha256(payload).hexdigest()
    current_index.update(canonical_root=root.as_posix(), cohort_root=cohort.as_posix())
    restored = json.loads(json.dumps(current_index))
    restored.update(canonical_root=original_index["canonical_root"], cohort_root=original_index["cohort_root"])
    for pin, original_pin in zip(restored["works"], original_index["works"], strict=True):
        pin["receipt_sha256"] = original_pin["receipt_sha256"]
    assert restored == original_index
    payload = (json.dumps(current_index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    index = home / "freeze-index.json"
    index.write_bytes(payload)
    assert last_manifest is not None
    # Copy and execute byte-identical CURRENT code at its actual bound mirror path.
    code_paths = {
        Path(last_manifest.record["converter"]["implementation_path"]),
        Path(last_manifest.record["validator"]["implementation_path"]),
        Path("ocd_kernel/reconstruction/contract.py"),
        Path("ocd_kernel/reconstruction/verifier.py"),
        Path("ocd_kernel/reconstruction/__init__.py"),
    }
    for relative in code_paths:
        payload = _io_path(ROOT / relative).read_bytes()
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        assert target.read_bytes() == _io_path(ROOT / relative).read_bytes()
    oracle_path = root / last_manifest.record["validator"]["implementation_path"]
    spec = importlib.util.spec_from_file_location("build.tei._lib089_current_install_fixture_oracle", oracle_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.MonkeyPatch.context() as context:
        context.setattr(installer, "_oracle", module._oracle)
        context.setattr(installer, "CANDIDATE_ROOT", candidates)
        context.setattr(installer, "ROOT", root)
        context.setattr(installer, "COHORT", cohort)
        context.setattr(installer, "INDEX", index)
        context.setattr(installer, "INDEX_SHA", sha256(index.read_bytes()).hexdigest())
        yield root


def test_original_index_rejects_wrong_root(historical_cohort: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="frozen cohort identity differs"):
        installer._index()


@pytest.mark.parametrize("work_id", WORK_IDS)
def test_original_manifest_rejects_current_runtime(work_id: str) -> None:
    from build.tei.lib089_westminster_standards_oracle import _oracle
    from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
    original_stage = COHORT / work_id
    record = json.loads(_io_path(original_stage / "stage-receipt.json").read_bytes())
    manifest_logical = _paths(work_id)[3]
    original = SourceManifest.load(ROOT / manifest_logical, repository_root=ROOT)
    assert original.sha256 == record["source_manifest_sha256"]
    package = CandidatePackage.load(original_stage / _paths(work_id)[4] / "inputs/package")
    assert package.sha256 == record["candidate_package_sha256"]
    with pytest.raises(ValueError, match="closure"):
        validate(original, package, _oracle)
