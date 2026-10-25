"""Preflight the frozen Moule/Skinner stage; guardedly install one work at a time.

Default is read-only. ``--apply --member`` swaps exactly one complete work
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

ROOT = Path(__file__).resolve().parents[2]
STAGE = Path('D:/Library/Open Christian Data/candidate-reviews/expositors-lib034-moule-skinner-stage-20260927-v1')
RECEIPT = STAGE / 'expositors-moule-skinner-stage-receipt.json'
RECEIPT_SHA = '2802b9497abcb6d98decdd30320cc565240f2412f9a9bcca618c42ba3cfbd03c'
CONTRACT = 'ocd-expositors-lib034-moule-skinner-stage-v1'
FIXTURE_MARKER = '.ocd-expositors-moule-skinner-install-fixture'
MEMBERS = {
    'moule-expositorromans': ('expositors-bible--h-c-g-moule', 36, 36),
    'skinner-expositorezek': ('expositors-bible--john-skinner', 36, 8),
}


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _json(path: Path) -> dict:
    return json.loads(_io_path(path).read_bytes())


def _dependencies(stage: Path) -> None:
    work_prefixes = tuple('library/works/' + work + '/' for work, _, _ in MEMBERS.values())
    for relative, checksum in _files(stage).items():
        if relative.startswith(work_prefixes) or relative == RECEIPT.name:
            continue
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise PipelineError(f'unsafe Expositors staged dependency: {relative}')
        source = (resolve_repo_path(ROOT, relative)
                  if path.parts[0] in {'raw', 'reports', 'exports'} else ROOT / path)
        if not _io_path(source).is_file() or _sha(source) != checksum:
            raise PipelineError(f'Expositors external source or evidence changed: {relative}')


def _scope(root: Path, stage: Path, row: dict, expected_count: int, expected_rows: int) -> None:
    work_path = Path(row['work_path'])
    edition = Path(row['edition_path']).relative_to(work_path)
    acquisition = Path(row['acquisition_path']).relative_to(work_path)
    evidence = Path('integration') / (row['member_id'] + '-readable-electronic-v1')
    before, after = _files(root / work_path), _files(stage / work_path)
    if before != row['before'] or after != row['after'] or len(before) != 4 or len(after) != expected_count:
        raise PipelineError(f"{row['member_id']} complete-generation receipt is stale")
    if set(before) != {'SOURCE_CREDIT.md', 'state.json', 'work.json', acquisition.as_posix()}:
        raise PipelineError(f"{row['member_id']} canonical preimage differs")
    if after.get(acquisition.as_posix()) != before[acquisition.as_posix()]:
        raise PipelineError(f"{row['member_id']} acquisition changed")
    allowed = {'work.json', 'state.json', (edition / 'master.tei.xml').as_posix(),
               (edition / 'acceptance.json').as_posix(), (edition / 'README.source.md').as_posix()}
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        if path in allowed or path.startswith(evidence.as_posix() + '/') and path not in before and path in after:
            continue
        raise PipelineError(f"{row['member_id']} unrelated work path changed: {path}")
    old_work = _json(root / work_path / 'work.json')
    new_work = _json(stage / work_path / 'work.json')
    validate_identity_update(old_work, new_work)
    expected_work = json.loads(json.dumps(old_work))
    expected_edition = expected_work['textual_forms'][0]['editions'][0]
    if len(expected_work['textual_forms']) != 1 or len(expected_work['textual_forms'][0]['editions']) != 1 or expected_edition.get('category') is not None:
        raise PipelineError(f"{row['member_id']} canonical edition identity differs")
    expected_edition['category'] = 'commentary'
    if expected_work != new_work:
        raise PipelineError(f"{row['member_id']} category update differs")
    load_work(_io_path(stage / work_path / 'work.json'))
    old_state = _json(root / work_path / 'state.json')
    new_state = _json(stage / work_path / 'state.json')
    old_targets = {item['target_id']: item for item in old_state['targets']}
    new_targets = {item['target_id']: item for item in new_state['targets']}
    if old_targets.keys() != new_targets.keys():
        raise PipelineError(f"{row['member_id']} state target identities differ")
    for target_id, old in old_targets.items():
        new = new_targets[target_id]
        if target_id != edition.name:
            if new != old:
                raise PipelineError(f"{row['member_id']} unrelated state changed")
            continue
        additions = [(work_path / edition / 'master.tei.xml').as_posix(),
                     (work_path / edition / 'acceptance.json').as_posix()]
        if (old['stage'] != 'acquired' or new['stage'] != 'accepted'
                or new['evidence'] != old['evidence'] + additions
                or any(old.get(key) != new.get(key) for key in old if key not in {'stage', 'reason', 'updated_at', 'evidence'})):
            raise PipelineError(f"{row['member_id']} edition state transition differs")
    master = edition / 'master.tei.xml'
    if after[master.as_posix()] != row['accepted_master_sha256'] or after[master.as_posix()] != after[(evidence / 'candidate.tei.xml').as_posix()]:
        raise PipelineError(f"{row['member_id']} accepted master differs")
    if after[(edition / 'README.source.md').as_posix()] != after[(evidence / 'inputs/package/README.source.md').as_posix()]:
        raise PipelineError(f"{row['member_id']} source credit differs")
    accepted = validate_acceptance(_io_path(stage / work_path / edition / 'acceptance.json'), root=_io_path(stage))
    validate_state(_io_path(stage / work_path / 'state.json'), root=_io_path(stage))
    if (accepted['identity']['work_id'] != row['work_id'] or accepted['promotion']['status'] != 'promoted'
            or accepted['decision']['human_decision']['status'] != 'not-recorded'
            or accepted['promotion']['master']['sha256'] != row['accepted_master_sha256']):
        raise PipelineError(f"{row['member_id']} staged acceptance differs")
    projection = project_accepted_commentary(_io_path(stage), acceptance_path=_io_path(stage / work_path / edition / 'acceptance.json'))
    errors = verify_accepted_commentary(_io_path(stage), acceptance_path=_io_path(stage / work_path / edition / 'acceptance.json'),
                                         rows=projection['rows'], receipt=projection['receipt'])
    if errors or len(projection['rows']) != expected_rows or row['projection_rows'] != expected_rows:
        raise PipelineError(f"{row['member_id']} actual-master projection differs: {errors[:2]}")


def preflight(*, root_override: Path | None = None, member: str | None = None) -> tuple[dict, Path, Path, bool]:
    if not _io_path(RECEIPT).is_file() or _sha(RECEIPT) != RECEIPT_SHA:
        raise PipelineError('Expositors frozen stage receipt differs')
    record = _json(RECEIPT)
    if (record.get('contract') != CONTRACT or record.get('status') != 'staged-only'
            or record.get('installation') != 'not-performed' or record.get('rights') != 'not-assessed'
            or Path(record.get('stage_root', '')).resolve(strict=True) != STAGE.resolve(strict=True)
            or Path(record.get('canonical_root', '')).resolve(strict=True) != ROOT.resolve(strict=True)):
        raise PipelineError('Expositors stage contract or roots differ')
    stage = STAGE.resolve(strict=True)
    fixture = root_override is not None
    root = root_override.resolve(strict=True) if fixture else ROOT.resolve(strict=True)
    if fixture:
        scratch = Path('D:/Library/Open Christian Data/candidate-reviews').resolve(strict=True)
        if scratch not in root.parents or not _io_path(root / FIXTURE_MARKER).is_file():
            raise PipelineError('Expositors override requires a marked review-area fixture')
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError('Expositors install roots overlap')
    rows = {row['member_id']: row for row in record['works']}
    if set(rows) != set(MEMBERS) or len(record['works']) != len(MEMBERS):
        raise PipelineError('Expositors frozen member set differs')
    _dependencies(stage)
    for member_id, (work_id, count, projection_rows) in MEMBERS.items():
        row = rows[member_id]
        if row['work_id'] != work_id or row['source_path'] not in {
                'raw/ccel/expositors-bible/moule_expositorromans.xml',
                'raw/ccel/expositors-bible/skinner_expositorezek.xml'}:
            raise PipelineError(f'{member_id} source identity differs')
        if member is None or member == member_id:
            _scope(root, stage, row, count, projection_rows)
    return record, root, stage, fixture


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


def install(member: str, *, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict:
    if member not in MEMBERS:
        raise PipelineError(f'unknown Expositors member: {member}')
    record, root, stage, fixture = preflight(root_override=root_override, member=member)
    row = next(item for item in record['works'] if item['member_id'] == member)
    work_path = Path(row['work_path'])
    target, source = root / work_path, stage / work_path
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != row['before'] or _files(source) != row['after']:
            raise PipelineError(f'{member} work changed while acquiring lock')
        _dependencies(stage)
        operation = root / 'library/.sidecar-operations' / ('expositors-' + member + '-' + uuid.uuid4().hex[:12])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ('incoming', 'previous', 'failed-new'))
        journal = dict(contract='ocd-expositors-readable-work-swap-v1', work_id=row['work_id'], phase='created',
                       before=row['before'], after=row['after'], receipt=RECEIPT.as_posix(), updated_at=_now())
        _write_json_durable(operation / 'operation.json', journal)
        moved = live = False
        try:
            _copy_generation(source, incoming, row['after'])
            if _files(target) != row['before']:
                raise PipelineError(f'{member} work changed during incoming copy')
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
                raise PipelineError(f'{member} installed generation differs')
            if not fixture:
                validate_acceptance(_io_path(root / work_path / Path(row['edition_path']).relative_to(work_path) / 'acceptance.json'), root=_io_path(root))
            if fail_at:
                fail_at('after-validation')
            journal.update(phase='complete', updated_at=_now())
            _write_json_durable(operation / 'operation.json', journal)
            return dict(status='installed-and-validated', member=member, operation=operation.as_posix(),
                        before_count=len(row['before']), after_count=len(row['after']),
                        master_sha256=row['accepted_master_sha256'])
        except BaseException:
            try:
                if live:
                    if _files(target) != row['after']:
                        raise PipelineError(f'{member} live generation differs during rollback')
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != row['before']:
                        raise PipelineError(f'{member} previous generation differs during rollback')
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != row['before']:
                        raise PipelineError(f'{member} rollback restored wrong bytes')
                journal.update(phase='rolled-back' if moved else 'failed-before-swap', updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
            except BaseException as exc:
                journal.update(phase='recovery-required', rollback_error=str(exc), updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
                raise PipelineError(f'{member} rollback requires recovery: {operation}') from exc
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--member', choices=sorted(MEMBERS))
    args = parser.parse_args()
    if args.apply:
        if args.member is None:
            parser.error('--apply requires --member for serial work installs')
        result = install(args.member)
    else:
        record, _, _, _ = preflight(member=args.member)
        result = dict(status='ready-for-review', receipt_sha256=RECEIPT_SHA,
                      works=[dict(member_id=row['member_id'], before_count=len(row['before']),
                                  after_count=len(row['after']), master_sha256=row['accepted_master_sha256'])
                             for row in record['works'] if args.member is None or row['member_id'] == args.member])
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
