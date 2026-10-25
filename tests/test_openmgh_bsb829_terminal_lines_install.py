"""Focused pin, stale-input, rollback, and fixture-install checks for two letters."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")

from build.tools import install_openmgh_bsb830_next as transaction
from build.tools import prepare_openmgh_bsb829_terminal_lines as route
from build.tools.install_openmgh_bsb829_terminal_lines import (
    JOURNAL_CONTRACT, RECEIPTS, STAGE_HOME, pinned_receipt, preflight_receipt,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.openmgh_journal_historical_fixture import restore_mgh_journal_before


WORK_ID = "bruno-of-segni-letter-to-st-george-brothers"


def _bytes(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _fixture(tmp_path: Path, work_id: str = WORK_ID) -> tuple[Path, Path, dict]:
    pinned, _digest = pinned_receipt(work_id)
    original = json.loads(_bytes(pinned))
    root = tmp_path / "root"
    shutil.copytree(_io_path(STAGE_HOME / RECEIPTS[work_id][1]), _io_path(root))
    work = Path("library/works") / work_id
    shutil.rmtree(_io_path(root / work))
    restore_mgh_journal_before(root, original)
    prior = root / route.PRIOR_PLAN
    prior.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(route.ROOT / route.PRIOR_PLAN), _io_path(prior))
    fixture = dict(original, canonical_root=root.as_posix())
    receipt = tmp_path / "fixture-receipt.json"
    receipt.write_text(json.dumps(fixture, sort_keys=True, separators=(",", ":")) + "\n",
                       encoding="utf-8")
    return root, receipt, fixture


def test_both_exact_receipts_preflight(tmp_path: Path) -> None:
    for work_id in RECEIPTS:
        receipt, digest = pinned_receipt(work_id)
        assert sha256(_bytes(receipt)).hexdigest() == digest
        _, historical, _ = _fixture(tmp_path / work_id, work_id)
        assert preflight_receipt(historical)["projection_rows"] == 1


def test_stale_input_rollback_and_clean_fixture_install(tmp_path: Path, monkeypatch) -> None:
    root, receipt, record = _fixture(tmp_path)
    work = root / "library/works" / WORK_ID
    manifest = root / record["manifest_path"]
    profile = root / record["profile_path"]
    before_work = _files(work)
    before_manifest, before_profile = _bytes(manifest), _bytes(profile)
    assert preflight_receipt(receipt)["status"] == "ready-for-review"

    state = work / "state.json"
    old_state = _bytes(state)
    Path(_io_path(state)).write_bytes(old_state + b" ")
    with pytest.raises(Exception, match="generation changed"):
        preflight_receipt(receipt)
    Path(_io_path(state)).write_bytes(old_state)

    source = root / route.SOURCE
    old_source = _bytes(source)
    Path(_io_path(source)).write_bytes(old_source + b" ")
    with pytest.raises(Exception, match="frozen source"):
        preflight_receipt(receipt)
    Path(_io_path(source)).write_bytes(old_source)

    monkeypatch.setattr(transaction, "receipt_preflight", preflight_receipt)
    exact = sha256(_bytes(receipt)).hexdigest()

    def inject(phase: str) -> None:
        if phase == "after-source-manifest.json-swap":
            raise RuntimeError("injected terminal-line rollback")

    with pytest.raises(RuntimeError, match="injected terminal-line rollback"):
        transaction.install(receipt, allowed_ids=frozenset({WORK_ID}),
                            journal_contract=JOURNAL_CONTRACT,
                            operation_prefix="terminal-line-fixture",
                            expected_receipt_sha256=exact, fail_at=inject)
    assert _files(work) == before_work
    assert _bytes(manifest) == before_manifest
    assert _bytes(profile) == before_profile
    journals = list((root / "library/.sidecar-operations").glob("terminal-line-fixture-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(_bytes(journals[0]))["phase"] == "rolled-back"

    result = transaction.install(receipt, allowed_ids=frozenset({WORK_ID}),
                                 journal_contract=JOURNAL_CONTRACT,
                                 operation_prefix="terminal-line-fixture",
                                 expected_receipt_sha256=exact)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(work) == record["after"]
    assert json.loads(_bytes(Path(result["operation"]) / "operation.json"))["phase"] == "complete"



def test_current_generation_is_not_the_original_acquired_before(tmp_path: Path) -> None:
    receipt, expected = pinned_receipt(WORK_ID)
    raw = _bytes(receipt)
    assert sha256(raw).hexdigest() == expected
    original = json.loads(raw)
    current = dict(original, canonical_root=route.ROOT.as_posix())
    assert dict(current, canonical_root=original["canonical_root"]) == original
    path = tmp_path / "current-generation.json"
    path.write_text(json.dumps(current), encoding="utf-8")
    with pytest.raises(Exception, match="generation changed"):
        preflight_receipt(path)
