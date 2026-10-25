"""Source-oracle and transactional guard checks for the staged PG34022 witness."""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import sys
from hashlib import sha256
import json
import shutil
from types import SimpleNamespace

from lxml import etree
import pytest

from build.tei.newman_grammar_pg34022_oracle import _oracle
from build.tools.install_newman_grammar_pg34022_acceptance import install, preflight
from build.tools.stage_newman_grammar_pg34022_acceptance import CANDIDATE, MANIFEST, ROOT, SOURCE, WORK
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _files, _io_path
from build.tools import install_newman_grammar_pg34022_acceptance as installer
from tests.runtime_candidate_baselines import current_runtime_baseline
from tests.current_frozen_install_context import current_frozen_stage


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/ng-s6")
RECEIPT_SHA = "a975e1e3b6993429ce5881b4a4c2b602946fd9a2d1a6f05bca1f8d6a6733a1d2"
PRIOR = Path(__file__).resolve().parent / "fixtures/newman_pg34022_prior_work"
NS = {"t": "http://www.tei-c.org/ns/1.0"}
HISTORICAL_STAGE = STAGE
HISTORICAL_RECEIPT_SHA = RECEIPT_SHA
ORIGINAL_MANIFEST = MANIFEST
RUNTIME_MANIFEST = Path("tests/fixtures/reconstruction-runtime/newman-pg34022-current-installer.source-manifest.json")
RUNTIME_SHA = "af39bbd5facc3d26b9ebb6ca9f6adbb3ca5046c4495a07a48203abd829e3a941"


def _fixture(root: Path) -> Path:
    (root / ".ocd-newman-grammar-install-fixture").write_text("fixture-only\n", encoding="utf-8")
    for name in ("raw", "sources", "build", "ocd_kernel", "plans", "tests"):
        if (STAGE / name).is_dir():
            shutil.copytree(STAGE / name, root / name)
    (root / WORK.parent).mkdir(parents=True, exist_ok=True)
    before = json.loads((STAGE / "stage-receipt.json").read_bytes())["before"]
    for relative, expected_sha in before.items():
        source = PRIOR / relative if relative in {"state.json", "work.json"} else STAGE / WORK / relative
        content = _io_path(source).read_bytes()
        assert sha256(content).hexdigest() == expected_sha
        target = root / WORK / relative
        _io_path(target.parent).mkdir(parents=True, exist_ok=True)
        _io_path(target).write_bytes(content)
    return root


def test_oracle_rejects_changed_head_and_note_attachment() -> None:
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(CANDIDATE)
    assert _oracle(manifest, package)["status"] == "pass"
    original = package.member_bytes("content.tei.xml")
    for change in ("head", "note"):
        document = etree.fromstring(original)
        if change == "head":
            node = document.xpath(".//t:head", namespaces=NS)[0]
            node.text = "Changed " + (node.text or "")
        else:
            document.xpath(".//t:ref[@type='note']", namespaces=NS)[0].set("target", "#wrong-note")
        changed = etree.tostring(document, encoding="UTF-8", xml_declaration=True)
        candidate = SimpleNamespace(
            sha256=package.sha256,
            member_bytes=lambda name, content=changed: content if name == "content.tei.xml" else package.member_bytes(name),
        )
        result = _oracle(manifest, candidate)
        assert result["status"] == "fail", change
        assert result["findings"], change


def test_read_only_preflight_and_exact_receipt_pin(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    ready = preflight(STAGE, RECEIPT_SHA, root=root)
    assert ready["status"] == "ready-for-review"
    assert ready["native_rows"] == 11
    with pytest.raises(PipelineError, match="receipt differs"):
        preflight(STAGE, "0" * 64, root=root)


def test_source_mutation_fails_and_failed_swap_rolls_back(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    source = root / SOURCE
    original = source.read_bytes()
    source.write_bytes(b"X" + original[1:])
    with pytest.raises((PipelineError, ValueError), match="source|authority|sha|digest|differs"):
        preflight(STAGE, RECEIPT_SHA, root=root)
    source.write_bytes(original)
    before = _files(root / WORK)

    def fail_after_swap(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected swap failure")

    with pytest.raises(RuntimeError, match="injected swap failure"):
        install(STAGE, RECEIPT_SHA, root=root, fail_at=fail_after_swap)
    assert _files(root / WORK) == before
    result = install(STAGE, RECEIPT_SHA, root=root)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 11


@pytest.fixture(scope="module")
def current_source_candidate(tmp_path_factory):
    assert sha256((ROOT / RUNTIME_MANIFEST).read_bytes()).hexdigest() == RUNTIME_SHA
    original = json.loads((HISTORICAL_STAGE / "stage-receipt.json").read_bytes())
    return current_runtime_baseline(
        root=ROOT, original_manifest=ORIGINAL_MANIFEST, runtime_manifest=RUNTIME_MANIFEST,
        retained_package=HISTORICAL_STAGE / installer.EVIDENCE / "inputs/package",
        retained_sha256=original["candidate_package_sha256"],
        destination=tmp_path_factory.mktemp("ng") / "current-candidate")


@pytest.fixture(autouse=True)
def current_runtime_stage(tmp_path, tmp_path_factory, monkeypatch, current_source_candidate):
    baseline, candidate = current_source_candidate
    original_source = (ROOT / ORIGINAL_MANIFEST).read_bytes()
    original_stage_files = _files(HISTORICAL_STAGE)
    destination = tmp_path_factory.mktemp("ngi")
    stage, pin = current_frozen_stage(installer, HISTORICAL_STAGE, HISTORICAL_RECEIPT_SHA,
                                      baseline, candidate, destination)
    monkeypatch.setattr(sys.modules[__name__], "STAGE", stage)
    monkeypatch.setattr(sys.modules[__name__], "RECEIPT_SHA", pin)
    monkeypatch.setattr(sys.modules[__name__], "MANIFEST", RUNTIME_MANIFEST)
    monkeypatch.setattr(sys.modules[__name__], "CANDIDATE", candidate.path)
    monkeypatch.setattr(installer, "LIBRARY", destination)
    monkeypatch.setattr(installer, "MANIFEST", RUNTIME_MANIFEST)
    monkeypatch.setattr(installer, "CANDIDATE", candidate.path)
    yield
    assert (ROOT / ORIGINAL_MANIFEST).read_bytes() == original_source
    assert _files(HISTORICAL_STAGE) == original_stage_files


def test_runtime_manifest_preserves_complete_original_newman_record():
    original = json.loads((ROOT / ORIGINAL_MANIFEST).read_bytes())
    raw = (ROOT / RUNTIME_MANIFEST).read_bytes()
    assert sha256(raw).hexdigest() == RUNTIME_SHA
    current = json.loads(raw)
    restored = deepcopy(current)
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    assert restored == original
    assert current["validator"]["import_closure_sha256"] != original["validator"]["import_closure_sha256"]
