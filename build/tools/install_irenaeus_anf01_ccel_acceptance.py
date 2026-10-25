"""Preflight and guardedly install only five Against Heresies books from ANF1.

Default is read-only. ``--apply`` swaps exactly one complete work
generation under a lock, with journaled rollback. It does not publish data.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import uuid

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable

ROOT = Path(__file__).resolve().parents[2]
STAGE = Path('D:/Library/Open Christian Data/candidate-reviews/irenaeus-anf01-ccel-acceptance-stage-20260928-v2')
RECEIPT = STAGE / 'irenaeus-against-heresies-ccel-acceptance-stage-receipt.json'
RECEIPT_SHA = '8d9390da04d47e97a6a4d84377ff292db0e30525a1d83bcb358e22656bfb84f0'
CONTRACT = 'ocd-irenaeus-against-heresies-ccel-electronic-stage-v1'
FIXTURE_MARKER = '.ocd-irenaeus-against-heresies-ccel-fixture'
WORK_ID = 'irenaeus-against-heresies'
SOURCE = 'raw/ccel/anf/anf01.xml'
EVIDENCE = 'integration/irenaeus-against-heresies-ccel-electronic-v1/'
SELECTED = ['ix.ii', 'ix.iii', 'ix.iv', 'ix.vi', 'ix.vii']
EXCLUDED = ['ix.i', 'ix.v', 'ix.viii']
ANTHOLOGY_SIBLINGS = ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii']


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _json(path: Path) -> dict:
    return json.loads(_io_path(path).read_bytes())


def _dependencies(stage: Path) -> None:
    record = _json(RECEIPT)
    deps = {relative: digest for relative, digest in _files(stage).items()
            if not relative.startswith('library/works/' + WORK_ID + '/') and relative != RECEIPT.name}
    if deps != record['dependencies']:
        raise PipelineError('Irenaeus staged dependencies differ from frozen receipt')
    for relative, checksum in deps.items():
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise PipelineError(f'unsafe Irenaeus dependency: {relative}')
        source = (resolve_repo_path(ROOT, relative)
                  if path.parts[0] in {'raw', 'reports', 'exports'} else ROOT / path)
        if not _io_path(source).is_file() or _sha(source) != checksum:
            raise PipelineError(f'Irenaeus source or evidence changed: {relative}')


def _scope(root: Path, stage: Path, row: dict) -> None:
    work_path = Path(row['work_path'])
    before, after = _files(root / work_path), _files(stage / work_path)
    if (work_path != Path('library/works') / WORK_ID or row['work_id'] != WORK_ID
            or before != row['before'] or after != row['after']
            or len(before) != 3 or len(after) != 21
            or row['source_path'] != SOURCE or row['native_rows'] != 5):
        raise PipelineError('Irenaeus accepted-generation receipt is stale')
    base = Path('forms/irenaeus-against-heresies-english/editions/irenaeus-against-heresies-retained-electronic-witness')
    acceptance_rel = (base / 'acceptance.json').as_posix()
    master_rel = (base / 'master.tei.xml').as_posix()
    acquisition_rel = (base / 'acquisitions/irenaeus-against-heresies-retained-source.json').as_posix()
    if set(before) != {'work.json', 'state.json', acquisition_rel}:
        raise PipelineError('Irenaeus prior acquisition generation differs')
    for relative in set(before) | set(after):
        if before.get(relative) == after.get(relative):
            continue
        if relative in {'work.json', 'state.json', acceptance_rel, master_rel}:
            continue
        if relative.startswith(EVIDENCE) and relative not in before and relative in after:
            continue
        raise PipelineError(f'Irenaeus unrelated accepted-work file changed: {relative}')
    if (after[master_rel] != row['new_master_sha256']
            or after[acceptance_rel] != row['new_acceptance_sha256']
            or after[EVIDENCE + 'candidate.tei.xml'] != row['new_master_sha256']):
        raise PipelineError('Irenaeus accepted master or record differs')
    prior_work = _json(root / work_path / 'work.json')
    staged_work = _json(stage / work_path / 'work.json')
    expected_work = json.loads(json.dumps(prior_work))
    edition = expected_work['textual_forms'][0]['editions'][0]
    if edition.get('category') is not None:
        raise PipelineError('Irenaeus edition already categorized')
    edition['category'] = 'prose'
    if staged_work != expected_work or before[acquisition_rel] != after[acquisition_rel]:
        raise PipelineError('Irenaeus identity or acquisition changed beyond prose category')
    prior_state = _json(root / work_path / 'state.json')
    staged_state = _json(stage / work_path / 'state.json')
    if len(prior_state['targets']) != len(staged_state['targets']):
        raise PipelineError('Irenaeus state target count changed')
    for old, new in zip(prior_state['targets'], staged_state['targets'], strict=True):
        if old['target_type'] == 'acquisition':
            if old != new:
                raise PipelineError('Irenaeus acquisition state changed')
        elif old['target_type'] == 'edition':
            expected = dict(old)
            expected['stage'] = 'accepted'
            expected['reason'] = 'Evidence-backed TEI is the master; human verification, rights, and publication remain separate.'
            expected['updated_at'] = new['updated_at']
            expected['evidence'] = old['evidence'] + [
                (work_path / master_rel).as_posix(), (work_path / acceptance_rel).as_posix()]
            if new != expected:
                raise PipelineError('Irenaeus edition state transition differs')
        else:
            raise PipelineError('Irenaeus unexpected state target')
    accepted = validate_acceptance(_io_path(stage / work_path / acceptance_rel), root=_io_path(stage))
    validate_state(_io_path(stage / work_path / 'state.json'), root=_io_path(stage))
    if (accepted['identity']['work_id'] != WORK_ID
            or accepted['promotion']['master']['sha256'] != row['new_master_sha256']
            or accepted['representation_revision']['id'] != 'irenaeus-anf01-five-book-v1'
            or accepted['scope']['kind'] != 'selection'
            or accepted['decision']['human_decision']['status'] != 'not-recorded'):
        raise PipelineError('Irenaeus staged acceptance differs')
    accounting = _json(stage / work_path / EVIDENCE / 'source-accounting.json')
    if (accounting['selected_book_ids'] != SELECTED
            or accounting['excluded_irenaeus_div2_ids'] != EXCLUDED
            or accounting['excluded_sibling_anf_div1_ids'] != ANTHOLOGY_SIBLINGS
            or accounting['source_feature_counts'] != {'selected_elements': 9159, 'selected_attributes': 28874}):
        raise PipelineError('Irenaeus selected-book or anthology exclusion accounting differs')
    from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
    from build.tei.irenaeus_against_heresies_oracle import _oracle
    manifest = SourceManifest.load(ROOT / 'sources/structured-text/irenaeus-against-heresies/irenaeus-against-heresies.source-manifest.json', repository_root=ROOT)
    candidate = CandidatePackage.load(Path('D:/Library/Open Christian Data/candidate-reviews/irenaeus-ccel-native-screen-20260928-v1'))
    report = validate(manifest, candidate, _oracle)
    if (manifest.sha256 != row['source_manifest_sha256']
            or candidate.sha256 != row['candidate_package_sha256'] or report.status != 'pass'):
        raise PipelineError('Irenaeus exact-source oracle differs')
    raw_candidate = candidate.member_bytes('content.tei.xml')
    staged_master = _io_path(stage / work_path / master_rel).read_bytes()
    if (raw_candidate.split(b'</teiHeader>', 1)[1] != staged_master.split(b'</teiHeader>', 1)[1]
            or b'sourced via CCEL.org' not in staged_master.split(b'</teiHeader>', 1)[0]):
        raise PipelineError('Irenaeus source text or visible CCEL credit differs')
    from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(stage / work_path / acceptance_rel))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(stage / work_path / acceptance_rel),
                                   rows=projected['rows'], receipt=projected['receipt'])
    if errors or len(projected['rows']) != 5:
        raise PipelineError(f'Irenaeus native prose projection differs: {errors[:2]}')


def preflight(*, root_override: Path | None = None) -> tuple[dict, Path, Path, bool]:
    if not _io_path(RECEIPT).is_file() or _sha(RECEIPT) != RECEIPT_SHA:
        raise PipelineError('Irenaeus frozen stage receipt differs')
    record = _json(RECEIPT)
    if (record.get('contract') != CONTRACT or record.get('status') != 'staged-only'
            or record.get('installation') != 'not-performed' or record.get('rights') != 'not-assessed'
            or Path(record.get('stage_root', '')).resolve(strict=True) != STAGE.resolve(strict=True)
            or Path(record.get('canonical_root', '')).resolve(strict=True) != ROOT.resolve(strict=True)):
        raise PipelineError('Irenaeus stage contract or roots differ')
    stage = STAGE.resolve(strict=True)
    fixture = root_override is not None
    root = root_override.resolve(strict=True) if fixture else ROOT.resolve(strict=True)
    if fixture:
        scratch = Path('D:/Library/Open Christian Data/candidate-reviews').resolve(strict=True)
        if scratch not in root.parents or not _io_path(root / FIXTURE_MARKER).is_file():
            raise PipelineError('Irenaeus override requires a marked review-area fixture')
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError('Irenaeus install roots overlap')
    _dependencies(stage)
    _scope(root, stage, record['work'])
    return record, root, stage, fixture


def _copy_generation(source: Path, target: Path, expected: dict[str, str]) -> None:
    if _io_path(target).exists():
        raise PipelineError('Irenaeus incoming generation already exists')
    _io_path(target).mkdir(parents=True)
    for relative, checksum in expected.items():
        original, destination = _io_path(source / relative), _io_path(target / relative)
        if not original.is_file() or _sha(original) != checksum:
            raise PipelineError(f'Irenaeus staged file changed: {relative}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
    if _files(target) != expected:
        raise PipelineError('Irenaeus incoming generation differs')


def install(*, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict:
    record, root, stage, fixture = preflight(root_override=root_override)
    row = record['work']
    work_path = Path(row['work_path'])
    target, source = root / work_path, stage / work_path
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != row['before'] or _files(source) != row['after']:
            raise PipelineError('Irenaeus work changed while acquiring lock')
        _dependencies(stage)
        operation = root / 'library/.sidecar-operations' / ('irenaeus-against-heresies-ccel-acceptance-' + uuid.uuid4().hex[:12])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ('incoming', 'previous', 'failed-new'))
        journal = dict(contract='ocd-irenaeus-against-heresies-ccel-work-swap-v1', work_id=row['work_id'], phase='created',
                       before=row['before'], after=row['after'], receipt=RECEIPT.as_posix(), updated_at=_now())
        _write_json_durable(operation / 'operation.json', journal)
        moved = live = False
        try:
            _copy_generation(source, incoming, row['after'])
            if _files(target) != row['before']:
                raise PipelineError('Irenaeus work changed during incoming copy')
            journal.update(phase='prepared', updated_at=_now())
            _write_json_durable(operation / 'operation.json', journal)
            if fail_at:
                fail_at('after-copy')
            _dependencies(stage)
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            journal.update(phase='previous-moved', updated_at=_now())
            _write_json_durable(operation / 'operation.json', journal)
            if fail_at:
                fail_at('after-old-rename')
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            journal.update(phase='new-live', updated_at=_now())
            _write_json_durable(operation / 'operation.json', journal)
            if fail_at:
                fail_at('after-new-rename')
            if _files(target) != row['after']:
                raise PipelineError('Irenaeus installed generation differs')
            if not fixture:
                acceptance_rel = next(x for x in row['after'] if x.endswith('/acceptance.json'))
                validate_acceptance(_io_path(root / work_path / acceptance_rel), root=_io_path(root))
                validate_state(_io_path(root / work_path / 'state.json'), root=_io_path(root))
            if fail_at:
                fail_at('after-validation')
            journal.update(phase='complete', updated_at=_now())
            _write_json_durable(operation / 'operation.json', journal)
            return dict(status='installed-and-validated', work_id=WORK_ID, operation=operation.as_posix(),
                        before_count=len(row['before']), after_count=len(row['after']),
                        master_sha256=row['new_master_sha256'])
        except BaseException:
            try:
                if live:
                    if _files(target) != row['after']:
                        raise PipelineError('Irenaeus live generation differs during rollback')
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != row['before']:
                        raise PipelineError('Irenaeus previous generation differs during rollback')
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != row['before']:
                        raise PipelineError('Irenaeus rollback restored wrong bytes')
                journal.update(phase='rolled-back' if moved else 'failed-before-swap', updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
            except BaseException as exc:
                journal.update(phase='recovery-required', rollback_error=str(exc), updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
                raise PipelineError(f'Irenaeus rollback requires recovery: {operation}') from exc
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        result = install()
    else:
        record, _, _, _ = preflight()
        result = dict(status='ready-for-review', receipt_sha256=RECEIPT_SHA,
                      work_id=WORK_ID, before_count=len(record['work']['before']),
                      after_count=len(record['work']['after']),
                      master_sha256=record['work']['new_master_sha256'])
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
