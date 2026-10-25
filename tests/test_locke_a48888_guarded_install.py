"""Focused rollback proof for the frozen external Locke A48888 acceptance stage."""
from pathlib import Path
import shutil

import pytest

from build.tools import install_locke_a48888_acceptance as route
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.guarded_installer_historical_fixture import historical_guarded_install_context


INPUT_ROOT = route.ROOT


@pytest.fixture(autouse=True)
def historical_default_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    current_files = _files(INPUT_ROOT / route.WORK)
    root, receipt, digest = historical_guarded_install_context(route, tmp_path / "historical-root")
    monkeypatch.setattr(route, "ROOT", root)
    monkeypatch.setattr(route, "RECEIPT", receipt)
    monkeypatch.setattr(route, "RECEIPT_SHA", digest)
    yield
    assert _files(INPUT_ROOT / route.WORK) == current_files


@pytest.mark.skipif(not _io_path(route.RECEIPT).is_file(), reason='frozen Locke A48888 stage unavailable')
@pytest.mark.parametrize('failure', ['after-copy', 'after-old-rename', 'after-new-rename', 'after-validation'])
def test_locke_a48888_guarded_install_restores_complete_preimage_on_failure(tmp_path: Path, failure: str):
    fixture = route.ROOT
    before = route.preflight()[0]['before']
    assert _files(fixture / route.WORK) == before
    assert route.preflight()[0]['before'] == before

    def fail_at(phase: str) -> None:
        if phase == failure:
            raise RuntimeError('injected Locke A48888 fixture failure')

    with pytest.raises(RuntimeError, match='injected Locke A48888 fixture failure'):
        route.install(fail_at=fail_at)
    assert _files(fixture / route.WORK) == before
    journals = list((fixture / 'library/.sidecar-operations').glob('locke-a48888-*/operation.json'))
    assert len(journals) == 1
    import json
    journal = json.loads(journals[0].read_text(encoding='utf-8'))
    assert journal['phase'] == ('failed-before-swap' if failure == 'after-copy' else 'rolled-back')
    assert route.preflight()[0]['before'] == before


@pytest.mark.skipif(not _io_path(route.RECEIPT).is_file(), reason='frozen Locke A48888 stage unavailable')
def test_locke_a48888_guarded_install_accepts_only_staged_generation_in_fixture(tmp_path: Path):
    fixture = route.ROOT
    record = route.preflight()[0]
    outcome = route.install()
    assert outcome['status'] == 'installed-and-validated'
    assert outcome['master_sha256'] == record['accepted_master_sha256']
    assert _files(fixture / route.WORK) == record['after']
    assert _files(fixture / route.WORK) == record['after']


@pytest.mark.skipif(not _io_path(route.RECEIPT).is_file(), reason='frozen Locke A48888 stage unavailable')
def test_locke_a48888_changed_receipt_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    altered = tmp_path / 'altered-receipt.json'
    data = _io_path(route.RECEIPT).read_bytes()
    altered.write_bytes(data.replace(b'"staged-only"', b'"staged-drift"', 1))
    assert altered.read_bytes() != data
    monkeypatch.setattr(route, 'RECEIPT', altered)
    with pytest.raises(PipelineError, match='frozen stage receipt differs'):
        route.preflight()


def test_original_receipt_guard_rejects_wrong_context_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(route, "ROOT", wrong)
    with pytest.raises(PipelineError, match="stage receipt contract or roots differ"):
        route.preflight()
