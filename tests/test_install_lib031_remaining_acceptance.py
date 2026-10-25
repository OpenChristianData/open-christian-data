"""Exact LIB-031 stage pin and one-work rollback on an isolated fixture."""

import json
from pathlib import Path
import shutil

import pytest

from build.tools.install_lib031_remaining_acceptance import (
    FIXTURE_MARKER, _checked_generation, install, preflight,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path

WORK_ID = "bounds-essentials-of-prayer"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms/bounds-essentials-of-prayer-english/editions/bounds-essentials-of-prayer-ccel-thml-electronic"
STAGE = Path(r"D:\Library\Open Christian Data\l31-ess3")
RECEIPT_SHA256 = "22f564685c10c5a7ed90c99db74f3f7a7f04b415a792313cfb3f7fbbc98dee2f"


@pytest.fixture
def isolated_root(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    root.mkdir()
    (root / FIXTURE_MARKER).write_text("isolated LIB-031 fixture\n", encoding="utf-8")
    prefix = WORK.as_posix() + "/"
    for relative in _files(STAGE):
        if relative == "stage-receipt.json" or relative.startswith(prefix):
            continue
        destination = _io_path(root / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(STAGE / relative), destination)
    # Build an acquired baseline from the immutable stage, so this fixture
    # remains valid after the canonical Essentials acceptance is installed.
    acquisition = next(path for path in _files(STAGE / WORK) if path.endswith(".json") and "/acquisitions/" in path)
    destination = _io_path(root / WORK / acquisition)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(STAGE / WORK / acquisition), destination)
    work = json.loads((STAGE / WORK / "work.json").read_bytes())
    work.pop("creators")
    work["textual_forms"][0]["editions"][0].pop("category")
    state = json.loads((STAGE / WORK / "state.json").read_bytes())
    target = next(item for item in state["targets"] if item["target_id"] == "bounds-essentials-of-prayer-ccel-thml-electronic")
    target["stage"] = "acquired"
    target.pop("reason")
    target["evidence"] = target["evidence"][:-2]
    for name, record in (("work.json", work), ("state.json", state)):
        (root / WORK / name).write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    return root


def test_preflight_pins_exact_stage_and_rejects_stale_receipt(isolated_root: Path) -> None:
    result = preflight(WORK_ID, STAGE, RECEIPT_SHA256, root_override=isolated_root)
    assert result["status"] == "pass-read-only"
    assert result["current_work_files"] == 3
    assert result["staged_work_files"] == 23
    assert result["projection_independent_verifier_errors"] == []
    with pytest.raises(PipelineError, match="receipt differs"):
        preflight(WORK_ID, STAGE, "0" * 64, root_override=isolated_root)


def test_guarded_fixture_install_checks_live_master_and_keeps_previous(isolated_root: Path) -> None:
    before = _files(isolated_root / WORK)
    result = install(WORK_ID, STAGE, RECEIPT_SHA256, root_override=isolated_root)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(isolated_root / WORK) == _files(STAGE / WORK)
    operations = list((isolated_root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    journal = json.loads((operations[0] / "operation.json").read_bytes())
    assert journal["phase"] == "complete"
    assert _files(operations[0] / "previous") == before


@pytest.mark.parametrize("sibling", ["duplicate-edition", "malformed-identity"])
def test_post_swap_cache_rechecks_sibling_in_fresh_phase(
    isolated_root: Path, monkeypatch: pytest.MonkeyPatch, sibling: str,
) -> None:
    import ocd_kernel.library.identities as identities

    install(WORK_ID, STAGE, RECEIPT_SHA256, root_override=isolated_root)
    after = _files(STAGE / WORK)
    discover = identities.discover_library
    calls = 0

    def counted_discover(root: Path):
        nonlocal calls
        calls += 1
        return discover(root)

    monkeypatch.setattr(identities, "discover_library", counted_discover)
    _checked_generation(isolated_root, WORK, EDITION, after)
    assert calls == 1

    record = {"schema_version": "2.0", "work_id": "sibling", "title": "Sibling",
              "evidence": ["research/acquisition-leads.jsonl#1"], "textual_forms": []}
    if sibling == "duplicate-edition":
        record["textual_forms"] = [{"textual_form_id": "sibling-form", "editions": [
            {"edition_id": "bounds-essentials-of-prayer-ccel-thml-electronic", "title": "Conflicting edition"}]}]
        expected = "edition_id is ambiguous"
    else:
        record["work_id"] = "wrong-directory"
        expected = "work sidecar identity does not match directory"
    sibling_path = isolated_root / "library/works/sibling/work.json"
    sibling_path.parent.mkdir(parents=True)
    sibling_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(PipelineError, match=expected):
        _checked_generation(isolated_root, WORK, EDITION, after)
    assert calls == 2


def test_post_swap_check_accepts_windows_extended_root_spelling(isolated_root: Path) -> None:
    extended = _io_path(isolated_root)
    if extended == isolated_root:
        pytest.skip("Windows extended paths are unavailable")
    install(WORK_ID, STAGE, RECEIPT_SHA256, root_override=isolated_root)
    _checked_generation(extended, WORK, EDITION, _files(STAGE / WORK))


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename"])
def test_guarded_swap_restores_exact_prior_generation(isolated_root: Path, phase: str) -> None:
    before = _files(isolated_root / WORK)

    def fail_at(reached: str) -> None:
        if reached == phase:
            raise RuntimeError("injected " + phase)

    with pytest.raises(RuntimeError, match="injected " + phase):
        install(WORK_ID, STAGE, RECEIPT_SHA256, root_override=isolated_root, fail_at=fail_at)
    assert _files(isolated_root / WORK) == before
    operations = list((isolated_root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    journal = json.loads((operations[0] / "operation.json").read_bytes())
    assert journal["phase"] == "rolled-back"
    assert journal["before"] == before
    assert preflight(WORK_ID, STAGE, RECEIPT_SHA256, root_override=isolated_root)["status"] == "pass-read-only"
