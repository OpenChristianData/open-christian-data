"""Focused frozen-source and guarded-install checks for Schleitheim."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from build.tools import install_schleitheim_confession_acceptance as route
from tests.two_guarded_current_fixture import current_guarded_context
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate

from build.tools.install_schleitheim_confession_acceptance import (
    FIXTURE_MARKER, RECEIPT, RECEIPT_SHA, STAGE, install, preflight,
)
from build.tools.stage_schleitheim_confession_acceptance import (
    EDITION, ROOT, SOURCE, SOURCE_SHA, WORK,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


def _fixture(root: Path) -> Path:
    _io_path(root).mkdir(parents=True, exist_ok=True)
    _io_path(root / FIXTURE_MARKER).write_bytes(b"fixture-only\n")
    prefix = WORK.as_posix() + "/"
    for name in _files(STAGE):
        if name == RECEIPT.name or name.startswith(prefix):
            continue
        destination = _io_path(root / name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_io_path(STAGE / name).read_bytes())
    for name in _files(ROOT / WORK):
        destination = _io_path(root / WORK / name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_io_path(ROOT / WORK / name).read_bytes())
    return root


def test_exact_receipt_source_credit_and_read_only_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    before = _files(ROOT / WORK)
    assert sha256(_io_path(RECEIPT).read_bytes()).hexdigest() == RECEIPT_SHA
    assert sha256(_io_path(ROOT / SOURCE).read_bytes()).hexdigest() == SOURCE_SHA
    result = preflight()
    assert result["status"] == "ready-for-review"
    assert result["native_rows"] == 9
    assert result["rights"] == "unresolved-translation-rights"
    assert _files(ROOT / WORK) == before
    monkeypatch.setattr("build.tools.install_schleitheim_confession_acceptance.RECEIPT_SHA", "0" * 64)
    with pytest.raises(PipelineError, match="frozen receipt differs"):
        preflight()


def test_long_path_fixture_rollback_then_installs(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / ("schleitheim-fixture-" + "x" * 35))
    assert len(str(fixture / EDITION / "master.tei.xml")) > 260
    before = _files(fixture / WORK)

    def fail_after_new_live(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected Schleitheim swap failure")

    with pytest.raises(RuntimeError, match="injected Schleitheim swap failure"):
        install(root_override=fixture, fail_at=fail_after_new_live)
    assert _files(fixture / WORK) == before
    result = install(root_override=fixture)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 9


INPUT_ROOT = ROOT
INPUT_STAGE = STAGE
INPUT_RECEIPT = RECEIPT
INPUT_RECEIPT_SHA = RECEIPT_SHA


@pytest.fixture(scope="module", autouse=True)
def _historical_current_runtime_context(tmp_path_factory):
    original_work = _files(INPUT_ROOT / WORK)
    original_stage = _files(INPUT_STAGE / WORK)
    root, stage, receipt, digest, candidate, oracle = current_guarded_context(
        INPUT_ROOT, route, tmp_path_factory.mktemp("guarded-current"),
        runtime_manifest=Path("tests/fixtures/reconstruction-runtime/schleitheim-confession-1527.source-manifest.json"))
    with pytest.MonkeyPatch.context() as patch:
        for name, value in {"ROOT": root, "STAGE": stage, "RECEIPT": receipt, "RECEIPT_SHA": digest,
                            "CANDIDATE": candidate, "PACKAGE_SHA": CandidatePackage.load(candidate).sha256,
                            "_oracle": oracle}.items():
            patch.setattr(route, name, value)
        for name, value in {"ROOT": root, "STAGE": stage, "RECEIPT": receipt, "RECEIPT_SHA": digest}.items():
            patch.setitem(globals(), name, value)
        yield
    assert _files(INPUT_ROOT / WORK) == original_work
    assert _files(INPUT_STAGE / WORK) == original_stage
    assert sha256(_io_path(INPUT_RECEIPT).read_bytes()).hexdigest() == INPUT_RECEIPT_SHA


def test_original_wrong_root_remains_rejected(tmp_path, monkeypatch):
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(route, "ROOT", wrong)
    with pytest.raises(PipelineError, match="frozen receipt claim or identity differs"):
        route.preflight()



def test_original_manifest_rejects_current_runtime():
    import importlib
    original = SourceManifest.load(INPUT_ROOT / route.MANIFEST, repository_root=INPUT_ROOT)
    oracle_name = original.record["validator"]["implementation_path"].removesuffix(".py").replace("/", ".")
    original_oracle = importlib.import_module(oracle_name)._oracle
    package = CandidatePackage.load(INPUT_STAGE / route.EVIDENCE / "inputs/package")
    with pytest.raises(ValueError, match="closure"):
        validate(original, package, original_oracle)


def test_current_oracle_rejects_actual_kernel_dependency_tamper():
    kernel = route.ROOT / "ocd_kernel/reconstruction/contract.py"
    before = kernel.read_bytes()
    try:
        kernel.write_bytes(before + b"\n# injected dependency tamper\n")
        with pytest.raises(ValueError, match="closure|authority"):
            source = SourceManifest.load(route.ROOT / route.MANIFEST, repository_root=route.ROOT)
            package = CandidatePackage.load(route.CANDIDATE)
            route._oracle(source, package)
    finally:
        kernel.write_bytes(before)
    assert kernel.read_bytes() == before



def test_current_accepted_generation_cannot_replace_historical_before(tmp_path, monkeypatch):
    original = __import__("json").loads(route.RECEIPT.read_bytes())
    current = dict(original, canonical_root=INPUT_ROOT.as_posix())
    assert dict(current, canonical_root=original["canonical_root"]) == original
    raw = (__import__("json").dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    receipt = tmp_path / "current-generation.json"
    receipt.write_bytes(raw)
    monkeypatch.setattr(route, "ROOT", INPUT_ROOT)
    monkeypatch.setattr(route, "RECEIPT", receipt)
    monkeypatch.setattr(route, "RECEIPT_SHA", sha256(raw).hexdigest())
    with pytest.raises(PipelineError, match="work preimage or staged generation differs"):
        route.preflight()
