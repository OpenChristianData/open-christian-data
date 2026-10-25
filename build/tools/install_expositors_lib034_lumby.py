"""Preflight and guardedly install Lumby's one electronic edition as one work generation.

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
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.commentary import project_accepted_commentary, verify_accepted_commentary
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
from build.tools.expositors_review import preflight as _shared_preflight

ROOT = Path(__file__).resolve().parents[2]
STAGE = Path('D:/Library/Open Christian Data/candidate-reviews/expositors-lib034-lumby-stage-20260927-v4')
RECEIPT = STAGE / 'expositors-lumby-stage-receipt.json'
RECEIPT_SHA = 'dfa8b6a3659c0750d54c2c94786eb60b89abcf7092ccea873b0b3d62ee56108a'
CONTRACT = 'ocd-expositors-lib034-lumby-stage-v1'
FIXTURE_MARKER = '.ocd-expositors-lumby-install-fixture'
WORK_ID = 'expositors-bible--j-rawson-lumby'
MEMBERS = {'lumby-expositorpeter': (5, 'raw/ccel/expositors-bible/lumby_expositorpeter.xml')}


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _json(path: Path) -> dict:
    return json.loads(_io_path(path).read_bytes())


def _dependencies(stage: Path) -> None:
    work_prefix = 'library/works/' + WORK_ID + '/'
    for relative, checksum in _files(stage).items():
        if relative.startswith(work_prefix) or relative == RECEIPT.name:
            continue
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise PipelineError(f'unsafe Expositors staged dependency: {relative}')
        source = (resolve_repo_path(ROOT, relative)
                  if path.parts[0] in {'raw', 'reports', 'exports'} else ROOT / path)
        if not _io_path(source).is_file() or _sha(source) != checksum:
            raise PipelineError(f'Expositors external source or evidence changed: {relative}')


def _scope(root: Path, stage: Path, work_row: dict) -> None:
    work_path = Path(work_row['work_path'])
    before, after = _files(root / work_path), _files(stage / work_path)
    if (work_path != Path('library/works') / WORK_ID or work_row['work_id'] != WORK_ID
            or before != work_row['before'] or after != work_row['after']
            or len(before) != 4 or len(after) != 23):
        raise PipelineError('Lumby complete-generation receipt is stale')
    members = {row['member_id']: row for row in work_row['members']}
    if set(members) != set(MEMBERS) or len(work_row['members']) != 1:
        raise PipelineError('Lumby member identities differ')
    acquisitions = {Path(row['acquisition_path']).relative_to(work_path).as_posix() for row in members.values()}
    if set(before) != {'SOURCE_CREDIT.md', 'state.json', 'work.json'} | acquisitions:
        raise PipelineError('Lumby canonical preimage differs')
    if any(after.get(path) != before[path] for path in acquisitions | {'SOURCE_CREDIT.md'}):
        raise PipelineError('Lumby source credit or acquisition changed')
    allowed = {'work.json', 'state.json'}
    for member_id, row in members.items():
        if (row['work_id'] != WORK_ID or row['source_path'] != MEMBERS[member_id][1]
                or row['projection_rows'] != MEMBERS[member_id][0]):
            raise PipelineError(f'{member_id} source or native identity differs')
        edition = Path(row['edition_path']).relative_to(work_path)
        allowed.update((edition / name).as_posix() for name in
                       ('master.tei.xml', 'acceptance.json', 'README.source.md'))
    prefixes = tuple('integration/' + member_id + '-readable-electronic-v1/' for member_id in members)
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        if path in allowed or path.startswith(prefixes) and path not in before and path in after:
            continue
        raise PipelineError(f'Lumby unrelated work path changed: {path}')
    old_work = _json(root / work_path / 'work.json')
    new_work = _json(stage / work_path / 'work.json')
    validate_identity_update(old_work, new_work)
    expected_work = json.loads(json.dumps(old_work))
    if len(expected_work['textual_forms']) != 1:
        raise PipelineError('Lumby canonical textual forms differ')
    for form in expected_work['textual_forms']:
        if len(form['editions']) != 1 or form['editions'][0].get('category') is not None:
            raise PipelineError('Lumby canonical edition category differs')
        form['editions'][0]['category'] = 'commentary'
    if expected_work != new_work:
        raise PipelineError('Lumby category updates differ')
    load_work(_io_path(stage / work_path / 'work.json'))
    old_state = _json(root / work_path / 'state.json')
    new_state = _json(stage / work_path / 'state.json')
    old_targets = {item['target_id']: item for item in old_state['targets']}
    new_targets = {item['target_id']: item for item in new_state['targets']}
    if old_targets.keys() != new_targets.keys() or len(old_targets) != 2:
        raise PipelineError('Lumby state target identities differ')
    edition_ids = {Path(row['edition_path']).name for row in members.values()}
    for target_id, old in old_targets.items():
        new = new_targets[target_id]
        if target_id not in edition_ids:
            if new != old:
                raise PipelineError(f'Lumby acquisition state changed: {target_id}')
            continue
        edition = next(Path(row['edition_path']) for row in members.values() if Path(row['edition_path']).name == target_id)
        additions = [(edition / 'master.tei.xml').as_posix(), (edition / 'acceptance.json').as_posix()]
        if (old['stage'] != 'acquired' or new['stage'] != 'accepted'
                or new['evidence'] != old['evidence'] + additions
                or any(old.get(key) != new.get(key) for key in old if key not in {'stage', 'reason', 'updated_at', 'evidence'})):
            raise PipelineError(f'Lumby edition state transition differs: {target_id}')
    validate_state(_io_path(stage / work_path / 'state.json'), root=_io_path(stage))
    for member_id, row in members.items():
        edition = Path(row['edition_path']).relative_to(work_path)
        evidence = Path('integration') / (member_id + '-readable-electronic-v1')
        master = edition / 'master.tei.xml'
        if (after[master.as_posix()] != row['accepted_master_sha256']
                or after[master.as_posix()] != after[(evidence / 'candidate.tei.xml').as_posix()]
                or after[(edition / 'README.source.md').as_posix()] != after[(evidence / 'inputs/package/README.source.md').as_posix()]):
            raise PipelineError(f'{member_id} accepted source or master differs')
        acceptance_path = stage / work_path / edition / 'acceptance.json'
        if after[(edition / 'acceptance.json').as_posix()] != row['acceptance_sha256']:
            raise PipelineError(f'{member_id} acceptance bytes differ')
        accepted = validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
        if (accepted['identity']['work_id'] != WORK_ID or accepted['identity']['edition_id'] != edition.name
                or accepted['promotion']['status'] != 'promoted'
                or accepted['decision']['human_decision']['status'] != 'not-recorded'
                or accepted['promotion']['master']['sha256'] != row['accepted_master_sha256']):
            raise PipelineError(f'{member_id} staged acceptance differs')
        projection = project_accepted_commentary(_io_path(stage), acceptance_path=_io_path(acceptance_path))
        errors = verify_accepted_commentary(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                             rows=projection['rows'], receipt=projection['receipt'])
        if errors or len(projection['rows']) != MEMBERS[member_id][0]:
            raise PipelineError(f'{member_id} actual-master projection differs: {errors[:2]}')


def preflight(*, root_override: Path | None=None) -> tuple[dict, Path, Path, bool]:
    return _shared_preflight(root_override=root_override, CONTRACT=CONTRACT,
        FIXTURE_MARKER=FIXTURE_MARKER, RECEIPT=RECEIPT, RECEIPT_SHA=RECEIPT_SHA, ROOT=ROOT,
        STAGE=STAGE, _dependencies=_dependencies, _json=_json, _scope=_scope, _sha=_sha)


def _copy_generation(source: Path, target: Path, expected: dict[str, str]) -> None:
    if _io_path(target).exists():
        raise PipelineError('Expositors incoming generation already exists')
    _io_path(target).mkdir(parents=True)
    for relative, checksum in expected.items():
        original, destination = _io_path(source / relative), _io_path(target / relative)
        if not original.is_file() or _sha(original) != checksum:
            raise PipelineError(f'Expositors staged file changed: {relative}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
    if _files(target) != expected:
        raise PipelineError('Expositors incoming generation differs')


def install(*, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict:
    record, root, stage, fixture = preflight(root_override=root_override)
    row = record['work']
    work_path = Path(row['work_path'])
    target, source = root / work_path, stage / work_path
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != row['before'] or _files(source) != row['after']:
            raise PipelineError('Lumby work changed while acquiring lock')
        _dependencies(stage)
        operation = root / 'library/.sidecar-operations' / ('expositors-lumby-pair-' + uuid.uuid4().hex[:12])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ('incoming', 'previous', 'failed-new'))
        journal = dict(contract='ocd-expositors-readable-work-swap-v1', work_id=row['work_id'], phase='created',
                       before=row['before'], after=row['after'], receipt=RECEIPT.as_posix(), updated_at=_now())
        _write_json_durable(operation / 'operation.json', journal)
        moved = live = False
        try:
            _copy_generation(source, incoming, row['after'])
            if _files(target) != row['before']:
                raise PipelineError('Lumby work changed during incoming copy')
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
                raise PipelineError('Lumby installed generation differs')
            if not fixture:
                for member_row in row['members']:
                    validate_acceptance(_io_path(root / member_row['edition_path'] / 'acceptance.json'), root=_io_path(root))
                validate_state(_io_path(root / work_path / 'state.json'), root=_io_path(root))
            if fail_at:
                fail_at('after-validation')
            journal.update(phase='complete', updated_at=_now())
            _write_json_durable(operation / 'operation.json', journal)
            return dict(status='installed-and-validated', work_id=WORK_ID, operation=operation.as_posix(),
                        before_count=len(row['before']), after_count=len(row['after']),
                        master_sha256={x['member_id']: x['accepted_master_sha256'] for x in row['members']})
        except BaseException:
            try:
                if live:
                    if _files(target) != row['after']:
                        raise PipelineError('Lumby live generation differs during rollback')
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != row['before']:
                        raise PipelineError('Lumby previous generation differs during rollback')
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != row['before']:
                        raise PipelineError('Lumby rollback restored wrong bytes')
                journal.update(phase='rolled-back' if moved else 'failed-before-swap', updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
            except BaseException as exc:
                journal.update(phase='recovery-required', rollback_error=str(exc), updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
                raise PipelineError(f'Lumby rollback requires recovery: {operation}') from exc
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
                      masters={row['member_id']: row['accepted_master_sha256'] for row in record['work']['members']})
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
