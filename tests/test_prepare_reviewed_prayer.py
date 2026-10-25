import json
from pathlib import Path

import pytest

from build.tools import prepare_reviewed_prayer as prayer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import promote_accepted_master, validate_acceptance


@pytest.fixture
def acquired_root(tmp_path: Path, short: str) -> Path:
    # Synthetic acquired baseline; the canonical works already have promoted masters.
    root = tmp_path / "acquired-input"
    root.mkdir()
    (root / ".ocd-storage.json").write_bytes((prayer.ROOT / ".ocd-storage.json").read_bytes())
    work_id, pg = prayer.CASES[short][:2]
    relative = Path("library/works") / work_id
    work = root / relative
    work.mkdir(parents=True)
    (work / "work.json").write_bytes((prayer.ROOT / relative / "work.json").read_bytes())
    state = json.loads((prayer.ROOT / relative / "state.json").read_bytes())
    target = next(row for row in state["targets"] if row["target_id"] == f"pg{pg}")
    assert target["target_type"] == "edition" and target["stage"] == "accepted"
    target["stage"] = "acquired"
    target["reason"] = "Synthetic acquired baseline for pending-acceptance preparation."
    target["evidence"] = [
        f"forms/english/editions/pg{pg}/acquisitions/pg{pg}-html-20260922.json",
        prayer.STATE_TICKET.as_posix(),
    ]
    (work / "state.json").write_text(json.dumps(state), encoding="utf-8")
    for name in (f"pg{pg}-html-20260922.json", f"pg{pg}-extracted-html-20260922.json"):
        source = relative / f"forms/english/editions/pg{pg}/acquisitions" / name
        destination = root / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((prayer.ROOT / source).read_bytes())
    ticket = root / prayer.STATE_TICKET
    ticket.parent.mkdir(parents=True, exist_ok=True)
    ticket.write_bytes((prayer.ROOT / prayer.STATE_TICKET).read_bytes())
    validate_state(work / "state.json", root=root)
    return root


@pytest.mark.parametrize('short', sorted(prayer.CASES))
def test_exact_prayer_candidate_stages_pending_promotion(tmp_path: Path, short: str, acquired_root: Path) -> None:
    stage = tmp_path / short
    canonical_state = prayer.ROOT / "library/works" / prayer.CASES[short][0] / "state.json"
    before = canonical_state.read_bytes()
    acceptance = prayer.prepare(acquired_root, stage, short)
    record = validate_acceptance(acceptance, root=stage)
    assert record['decision']['agent_assessment']['status'] == 'accepted'
    assert record['decision']['human_decision']['status'] == 'not-recorded'
    assert record['promotion']['status'] == 'pending'
    assert record['review']['coverage']['status'] == 'partial'
    work_id, pg = prayer.CASES[short][:2]
    work = stage / 'library/works' / work_id
    validate_state(work / 'state.json', root=stage)
    acquisition_dir = work / f'forms/english/editions/pg{pg}/acquisitions'
    retained_paths: set[str] = set()
    for sidecar in sorted(acquisition_dir.glob('*.json')):
        acquisition = json.loads(sidecar.read_bytes())
        for member in acquisition['retained_files']:
            retained_paths.add(member['path'])
            copied = stage / member['path']
            assert copied.stat().st_size == member['bytes']
            assert prayer.sha(copied.read_bytes()) == member['sha256']
    assert len(retained_paths) >= 3
    promoted = promote_accepted_master(stage, acceptance_path=acceptance, destination=tmp_path / f'{short}-promoted')
    promoted_record = validate_acceptance(promoted.acceptance_path, root=promoted.destination_root)
    validate_state(promoted.state_path, root=promoted.destination_root)
    assert promoted_record['promotion']['status'] == 'promoted'
    assert promoted_record['decision']['human_decision']['status'] == 'not-recorded'
    assert promoted.master_path.read_bytes() == (stage / record['technical']['candidate']['path']).read_bytes()
    if short == 'little':
        assert any('horizontally clipped' in item for item in record['review']['unreviewed_residuals'])
    if short == 'murray':
        assert any('79 image carriers' in item for item in record['review']['unreviewed_residuals'])
    assert canonical_state.read_bytes() == before
    assert next(row for row in json.loads(before)['targets'] if row['target_id'] == f'pg{pg}')['stage'] == 'accepted'
    candidate = stage / record['technical']['candidate']['path']
    candidate.write_bytes(candidate.read_bytes() + b' ')
    with pytest.raises(PipelineError, match='byte mismatch|sha256 mismatch'):
        validate_acceptance(acceptance, root=stage)


def test_preparation_requires_a_fresh_stage(tmp_path: Path) -> None:
    stage = tmp_path / 'existing'
    stage.mkdir()
    with pytest.raises(PipelineError, match='fresh'):
        prayer.prepare(prayer.ROOT, stage, 'little')


def test_preparation_rejects_a_durable_library_destination() -> None:
    with pytest.raises(PipelineError, match='durable library'):
        prayer.prepare(prayer.ROOT, prayer.LIBRARY_ROOT / 'raw' / 'unwanted-stage', 'little')
