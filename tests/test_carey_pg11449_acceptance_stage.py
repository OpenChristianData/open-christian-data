"""Exercise Carey PG11449's frozen source stage and guarded installer."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from build.tools.install_carey_pg11449_acceptance import install, preflight
from build.tools import install_carey_pg11449_acceptance as route
from build.tools.stage_carey_pg11449_acceptance import NATIVE_DEPENDENCIES, ROOT, SOURCE, WORK
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/ce-s1")
RECEIPT_SHA = "f58fa64ccb3518f5776e95cae65f8df77109a7248fa490b2f4549ce52e7f1607"
PRIOR = Path(__file__).resolve().parent / "fixtures/carey_pg11449_prior_work"


def _fixture(root: Path) -> Path:
    root.mkdir()
    (root / ".ocd-carey-install-fixture").write_text("fixture-only\n", encoding="utf-8")
    for name in ("raw", "sources", "build", "ocd_kernel", "plans"):
        if (STAGE / name).is_dir():
            shutil.copytree(STAGE / name, root / name)
    for relative in NATIVE_DEPENDENCIES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    before = json.loads((STAGE / "stage-receipt.json").read_bytes())["before"]
    for relative, expected_sha in before.items():
        source = PRIOR / relative if relative in {"state.json", "work.json"} else STAGE / WORK / relative
        content = _io_path(source).read_bytes()
        assert sha256(content).hexdigest() == expected_sha
        target = root / WORK / relative
        _io_path(target.parent).mkdir(parents=True, exist_ok=True)
        _io_path(target).write_bytes(content)
    return root


def test_read_only_preflight_and_receipt_pin(tmp_path_factory: pytest.TempPathFactory) -> None:
    root = _fixture(tmp_path_factory.mktemp("c") / "a")
    ready = preflight(STAGE, RECEIPT_SHA, root=root)
    assert ready["status"] == "ready-for-review"
    assert ready["native_rows"] == 1
    assert ready["before_files"] == 3 and ready["after_files"] == 21
    with pytest.raises(PipelineError, match="receipt differs"):
        preflight(STAGE, "0" * 64, root=root)


def test_source_drift_fails_and_injected_swap_restores_prior_work(tmp_path_factory: pytest.TempPathFactory) -> None:
    root = _fixture(tmp_path_factory.mktemp("c") / "b")
    source = root / SOURCE
    original = source.read_bytes()
    source.write_bytes(b"X" + original[1:])
    with pytest.raises((PipelineError, ValueError), match="source|authority|sha|digest|changed"):
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
    assert result["projection_rows"] == 1


INPUT_STAGE = STAGE
INPUT_RECEIPT_SHA = RECEIPT_SHA
INPUT_LIBRARY = route.LIBRARY
CURRENT_NATIVE_PINS = {'ocd_kernel/projection/categories/native_documents.py': '229f3f1e9be106c061c8f7a699820f263fc615798c61212ef8756a009261a59a', 'ocd_kernel/projection/native_content.py': '0cf26976895508516f84bff8c6436acf35b5d0593632971cf5eb5a788165ff77', 'ocd_kernel/projection/native_content_check.py': '15c06d8b03709e052aaa0356ee18372612ee79a5a8f41aa4888abb75c82bc16b', 'schemas/v2/native-content.schema.json': 'adee3a40da9f908948e5589b8816a022ee2a96458cb7c9e013bdbf606e0011ab'}


@pytest.fixture(scope="module", autouse=True)
def _current_native_test_context(tmp_path_factory):
    original_raw = (INPUT_STAGE / "stage-receipt.json").read_bytes()
    assert sha256(original_raw).hexdigest() == INPUT_RECEIPT_SHA
    original = json.loads(original_raw)
    before_stage = _files(INPUT_STAGE / WORK)
    assert before_stage == original["after"]
    library = tmp_path_factory.mktemp("carey-current") / "library"
    stage = library / "candidate-reviews/ce-s-current"
    stage.parent.mkdir(parents=True)
    shutil.copytree(INPUT_STAGE, stage)
    current = json.loads(original_raw)
    current["stage_root"] = stage.as_posix()
    for relative, expected in CURRENT_NATIVE_PINS.items():
        assert relative in current["dependencies"]
        assert relative in {p.as_posix() for p in NATIVE_DEPENDENCIES}
        assert sha256((ROOT / relative).read_bytes()).hexdigest() == expected
        current["dependencies"][relative] = expected
    # Only the interpreter identity changed; all source checks must still agree.
    original_validation = json.loads((INPUT_STAGE / route.EVIDENCE / "inputs/validation.json").read_bytes())
    assert original_validation["report_sha256"] == original["oracle_report_sha256"]
    manifest = route.SourceManifest.load(ROOT / route.MANIFEST, repository_root=ROOT)
    report = route.validate(manifest, route.CandidatePackage.load(route.CANDIDATE), route._oracle)
    observed = json.loads(json.dumps(dict(report.attestation)))
    restored_attestation = dict(observed, runtime=original_validation["attestation"]["runtime"],
                                result_sha256=original_validation["attestation"]["result_sha256"])
    assert restored_attestation == original_validation["attestation"]
    assert report.status == original_validation["status"] == "pass"
    assert list(report.findings) == original_validation["findings"]
    current["oracle_report_sha256"] = report.sha256
    restored = json.loads(json.dumps(current))
    restored["stage_root"] = original["stage_root"]
    restored["dependencies"] = original["dependencies"]
    restored["oracle_report_sha256"] = original["oracle_report_sha256"]
    assert restored == original
    assert {path for path in current["dependencies"] if current["dependencies"][path] != original["dependencies"][path]} == set(CURRENT_NATIVE_PINS)
    raw = (json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (stage / "stage-receipt.json").write_bytes(raw)
    assert _files(stage / WORK) == original["after"]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(route, "LIBRARY", library)
        patch.setitem(globals(), "STAGE", stage)
        patch.setitem(globals(), "RECEIPT_SHA", sha256(raw).hexdigest())
        yield
    assert (INPUT_STAGE / "stage-receipt.json").read_bytes() == original_raw
    assert _files(INPUT_STAGE / WORK) == before_stage


def test_original_native_dependency_receipt_still_rejects_current_code(tmp_path, monkeypatch):
    root = _fixture(tmp_path / "original-native-pins")
    monkeypatch.setattr(route, "LIBRARY", INPUT_LIBRARY)
    assert sha256((INPUT_STAGE / "stage-receipt.json").read_bytes()).hexdigest() == INPUT_RECEIPT_SHA
    with pytest.raises(PipelineError, match="Carey dependency changed"):
        preflight(INPUT_STAGE, INPUT_RECEIPT_SHA, root=root)
