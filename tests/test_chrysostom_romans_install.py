"""Source-bound Romans scope and exact prerequisite/guarded rollback behavior."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
import shutil
import pytest

from build.tools import prepare_chrysostom_romans as parts
from build.tools import install_chrysostom_romans as installer
from ocd_kernel.library._common import io_path, PipelineError
from tests.frozen_install_runtime import runtime_promoted_stage
from ocd_kernel.tei.install_accepted import _files

PROMOTED = Path("D:/Library/Open Christian Data/candidate-reviews/chrysostom-romans-promoted-20261001-v1")
PREIMAGE = parts.ROOT / "reports/_logs/chrysostom-romans-reconciliation-20261001-v1/work-preimage-tree"


def test_exact_category_prerequisite_preserves_identity_and_language():
    original = json.loads((PREIMAGE / "work.json").read_bytes())
    revised = json.loads(parts.canonical(original))
    revised["textual_forms"][0]["editions"][0]["category"] = "prose"
    installer.metadata_change(original, revised)
    for key, value in (("title", "Homily I only"), ("work_id", "chrysostom-homilies-on-acts")):
        altered = json.loads(parts.canonical(revised))
        altered[key] = value
        with pytest.raises(PipelineError, match="one-field"):
            installer.metadata_change(original, altered)
    altered = json.loads(parts.canonical(revised))
    altered["textual_forms"][0]["language"] = "la"
    with pytest.raises(PipelineError, match="one-field"):
        installer.metadata_change(original, altered)


def test_bad_frozen_receipt_fails_before_mutation(tmp_path):
    before = _files(parts.ROOT / parts.WORK)
    with pytest.raises(PipelineError, match="receipt differs"):
        installer.install(parts.ROOT, PROMOTED, "0" * 64, tmp_path / "rejected")
    assert _files(parts.ROOT / parts.WORK) == before
    assert not (tmp_path / "rejected").exists()


def test_guarded_install_failure_restores_exact_preimage(tmp_path):
    promoted, receipt_sha = runtime_promoted_stage(
        PROMOTED, tmp_path / "runtime-promoted", "tests/test_chrysostom_romans_install.py"
    )
    receipt_raw = (promoted / "stage-receipt.json").read_bytes()
    receipt = json.loads(receipt_raw)
    stage = Path(receipt["stage_root"])
    fixture = tmp_path / "root"
    shutil.copytree(io_path(stage), io_path(fixture))
    target = fixture / parts.WORK
    resolved = target.resolve(strict=True)
    assert resolved.is_relative_to(fixture.resolve(strict=True)) and not target.is_symlink() and not target.is_junction()
    shutil.rmtree(io_path(target))
    shutil.copytree(io_path(PREIMAGE), io_path(target))
    assert _files(target) == receipt["before"]
    def fail_at(point):
        if point == "after-new-live":
            raise PipelineError("injected failure at after-new-live")
    with pytest.raises(PipelineError, match="injected.*after-new-live"):
        installer.install(fixture, promoted, receipt_sha, tmp_path / "rollback", fail_at=fail_at)
    assert _files(target) == receipt["before"]
    assert not io_path(fixture / parts.EDITION / "master.tei.xml").exists()
    assert json.loads((tmp_path / "rollback/metadata-rollback.json").read_bytes())["exact_original_generation"]
    journals = list((fixture / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_bytes())["phase"] == "rolled-back"


def test_original_frozen_runtime_receipt_rejects_current_runtime(tmp_path):
    raw = (PROMOTED / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "4940aa9e9efdc64cbb80b1edd7c9d1dd6db04bd8b20a9b99052a1c4381111808"
    pins = json.loads(raw)["schema_pins"]
    assert {relative: sha256((parts.ROOT / relative).read_bytes()).hexdigest() for relative in pins} != pins
    before = _files(parts.ROOT / parts.WORK)
    with pytest.raises(PipelineError, match="frozen stage schema differs"):
        installer.install(parts.ROOT, PROMOTED, sha256(raw).hexdigest(), tmp_path / "rejected-runtime")
    assert _files(parts.ROOT / parts.WORK) == before
    assert not (tmp_path / "rejected-runtime").exists()
