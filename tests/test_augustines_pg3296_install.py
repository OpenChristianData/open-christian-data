"""Focused source-pin, native projection, and rollback checks for PG3296."""

from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import shutil
from tempfile import TemporaryDirectory

import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime  # noqa: F401

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")

from build.tools.install_augustines_pg3296_acceptance import install, preflight
from build.tools.stage_augustines_pg3296_acceptance import ROOT, SOURCE, WORK
from tests.frozen_install_preimages import copy_recorded_preimage
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/augustines-pg3296-s1")
RECEIPT_SHA = "c3cf2a5d65a4222fb9e99dbaf2e71470df9e9fcd6adcd1c6caca2b9a70823082"


def _fixture(root: Path) -> Path:
    (root / ".ocd-augustines-pg3296-install-fixture").write_text("fixture-only\n", encoding="utf-8")
    for name in ("raw", "sources", "metadata", "build", "ocd_kernel"):
        if (STAGE / name).is_dir():
            shutil.copytree(STAGE / name, root / name)
    (root / WORK.parent).mkdir(parents=True, exist_ok=True)
    copy_recorded_preimage(STAGE, WORK, RECEIPT_SHA, root)
    from tests.vendored_schema_mirrors import copy_vendored_schema_imports
    copy_vendored_schema_imports(ROOT, root)
    # The original receipt binds this historical closure, retained exactly from Git.
    historical = (ROOT / "tests/fixtures/reconstruction-runtime/authorities/augustines-confessions-historical-contract.py.bin").read_bytes()
    assert sha256(historical).hexdigest() == "a3cdf8daa9d67725a22995584a2a99ba796fc4c7578058496f1f9d6bad401ac5"
    init = (ROOT / "ocd_kernel/reconstruction/__init__.py").read_bytes()
    assert sha256(init).hexdigest() == "e6ed13f040ada1d57354a3b8bfe7ce384be867031e017a72f027fe2d145848ca"
    for relative, payload in (("contract.py", historical), ("__init__.py", init)):
        target = root / "ocd_kernel/reconstruction" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return root


@pytest.fixture
def short_root():
    with TemporaryDirectory(prefix="ta-", dir="C:/tmp") as folder:
        try:
            yield _fixture(Path(folder))
        finally:
            shutil.rmtree(_io_path(Path(folder)))


def test_read_only_exact_receipt_and_native_units(short_root: Path) -> None:
    result = preflight(STAGE, RECEIPT_SHA, root=short_root)
    assert result["status"] == "ready-for-review"
    assert result["native_rows"] == 18
    assert result["source_lines"] == 9724
    with pytest.raises(PipelineError, match="receipt differs"):
        preflight(STAGE, "0" * 64, root=short_root)


def test_exact_retained_text_mutation_fails_closed(short_root: Path) -> None:
    source = short_root / SOURCE
    original = _io_path(source).read_bytes()
    _io_path(source).write_bytes(b"X" + original[1:])
    with pytest.raises((PipelineError, ValueError), match="source|authority|sha|digest|differs"):
        preflight(STAGE, RECEIPT_SHA, root=short_root)


def test_failed_swap_rolls_back_then_fixture_install_succeeds(short_root: Path) -> None:
    before = _files(short_root / WORK)

    def fail_after_swap(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected swap failure")

    with pytest.raises(RuntimeError, match="injected swap failure"):
        install(STAGE, RECEIPT_SHA, root=short_root, fail_at=fail_after_swap)
    assert _files(short_root / WORK) == before
    result = install(STAGE, RECEIPT_SHA, root=short_root)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 18


def test_current_accepted_generation_rejects_frozen_preimage() -> None:
    import json
    record = json.loads((STAGE / "stage-receipt.json").read_bytes())
    before = _files(ROOT / WORK)
    assert before != record["before"]
    with pytest.raises(PipelineError, match="complete work preimage or stage generation differs"):
        preflight(STAGE, RECEIPT_SHA)
    assert _files(ROOT / WORK) == before


def test_supplied_fixture_root_owns_the_validator(short_root: Path, monkeypatch) -> None:
    from build.tools import install_augustines_pg3296_acceptance as installer

    def unrelated_process_oracle(*args):
        raise AssertionError("process-global oracle must not validate a different root")

    monkeypatch.setattr(installer, "_oracle", unrelated_process_oracle)
    assert preflight(STAGE, RECEIPT_SHA, root=short_root)["native_rows"] == 18
