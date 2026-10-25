"""Preflight or guardedly install the frozen Hodge Volume III electronic stage.

Default is read-only. ``--apply`` swaps only the complete Hodge work directory
under a lock and retains journaled rollback bytes. It does not publish data.
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
WORK = Path('library/works/hodge-systematic-theology-vol-3')
EDITION = Path('forms/hodge-systematic-theology-vol-3-english/editions/hodge-systematic-theology-vol-3-retained-electronic-witness')
ACQUISITION = EDITION / 'acquisitions/hodge-systematic-theology-vol-3-retained-source.json'
ACCEPTANCE = EDITION / 'acceptance.json'
MASTER = EDITION / 'master.tei.xml'
EVIDENCE = Path('integration/hodge-vol3-electronic-acceptance-v1')
STAGE = Path('D:/Library/Open Christian Data/candidate-reviews/hodge-vol3-electronic-stage-20260927-v2')
RECEIPT = STAGE / 'hodge-vol3-stage-receipt.json'
RECEIPT_SHA = '8eed420467e1a1c1b8358f587207f69a1149a6100c78d07e67ce98f5d650ab0d'
CONTRACT = 'ocd-hodge-vol3-electronic-stage-v1'
FIXTURE_MARKER = '.ocd-hodge-vol3-install-fixture'


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _copy_generation(source: Path, target: Path, expected: dict[str, str]) -> None:
    if _io_path(target).exists():
        raise PipelineError('Hodge Volume III incoming generation already exists')
    _io_path(target).mkdir(parents=True)
    for relative, checksum in expected.items():
        original = _io_path(source / relative)
        destination = _io_path(target / relative)
        if not original.is_file() or _sha(original) != checksum:
            raise PipelineError(f'Hodge Volume III staged file changed: {relative}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
    if _files(target) != expected:
        raise PipelineError('Hodge Volume III incoming generation differs')


def _dependencies(stage: Path) -> None:
    prefix = WORK.as_posix() + '/'
    for relative, checksum in _files(stage).items():
        if relative.startswith(prefix) or relative == RECEIPT.name:
            continue
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise PipelineError(f'unsafe Hodge Volume III staged dependency: {relative}')
        source = (resolve_repo_path(ROOT, relative)
                  if path.parts[0] in {'raw', 'reports', 'exports'} else ROOT / path)
        if not _io_path(source).is_file() or _sha(source) != checksum:
            raise PipelineError(f'Hodge Volume III external source/evidence differs: {relative}')


def _scope(root: Path, stage: Path, before: dict[str, str], after: dict[str, str]) -> None:
    if len(before) != 3 or len(after) != 26:
        raise PipelineError('Hodge Volume III complete-generation file count differs')
    if set(before) != {'work.json', 'state.json', ACQUISITION.as_posix()}:
        raise PipelineError('Hodge Volume III canonical work preimage differs')
    if after.get(ACQUISITION.as_posix()) != before[ACQUISITION.as_posix()]:
        raise PipelineError('Hodge Volume III acquisition changed')
    allowed = {'work.json', 'state.json', ACCEPTANCE.as_posix(), MASTER.as_posix()}
    prefix = EVIDENCE.as_posix() + '/'
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        if path in allowed or path.startswith(prefix) and path not in before and path in after:
            continue
        raise PipelineError(f'Hodge Volume III unrelated work path differs: {path}')
    old_work = json.loads(_io_path(root / WORK / 'work.json').read_bytes())
    new_work = json.loads(_io_path(stage / WORK / 'work.json').read_bytes())
    expected = json.loads(json.dumps(old_work))
    edition = expected['textual_forms'][0]['editions'][0]
    if edition.get('category') is not None:
        raise PipelineError('Hodge Volume III edition is already categorized')
    edition['category'] = 'prose'
    if expected != new_work:
        raise PipelineError('Hodge Volume III work identity differs beyond prose category')
    old_state = json.loads(_io_path(root / WORK / 'state.json').read_bytes())
    new_state = json.loads(_io_path(stage / WORK / 'state.json').read_bytes())
    old_targets = {item['target_id']: item for item in old_state['targets']}
    new_targets = {item['target_id']: item for item in new_state['targets']}
    if old_targets.keys() != new_targets.keys():
        raise PipelineError('Hodge Volume III state target identities differ')
    for target_id, old in old_targets.items():
        new = new_targets[target_id]
        if target_id != EDITION.name:
            if new != old:
                raise PipelineError('Hodge Volume III acquisition state changed')
            continue
        additions = [(WORK / MASTER).as_posix(), (WORK / ACCEPTANCE).as_posix()]
        if (old['stage'] != 'acquired' or new['stage'] != 'accepted'
                or new['evidence'] != old['evidence'] + additions
                or any(old.get(key) != new.get(key) for key in old if key not in {'stage', 'reason', 'updated_at', 'evidence'})):
            raise PipelineError('Hodge Volume III edition state transition differs')
    if after[MASTER.as_posix()] != after[(EVIDENCE / 'candidate.tei.xml').as_posix()]:
        raise PipelineError('Hodge Volume III master differs from accepted candidate')
    acceptance = validate_acceptance(_io_path(stage / WORK / ACCEPTANCE), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / 'state.json'), root=_io_path(stage))
    if (acceptance['identity']['work_id'] != 'hodge-systematic-theology-vol-3'
            or acceptance['promotion']['status'] != 'promoted'
            or acceptance['decision']['human_decision']['status'] != 'not-recorded'
            or acceptance['promotion']['master']['sha256'] != after[MASTER.as_posix()]):
        raise PipelineError('Hodge Volume III staged electronic-witness acceptance differs')


def preflight(*, root_override: Path | None = None) -> tuple[dict, Path, Path, bool]:
    if not _io_path(RECEIPT).is_file() or _sha(RECEIPT) != RECEIPT_SHA:
        raise PipelineError('Hodge Volume III frozen stage receipt differs')
    record = json.loads(_io_path(RECEIPT).read_bytes())
    if (record.get('contract') != CONTRACT or record.get('status') != 'staged-only'
            or record.get('work_id') != 'hodge-systematic-theology-vol-3' or record.get('installation') != 'not-performed'
            or Path(record.get('stage_root', '')).resolve(strict=True) != STAGE.resolve(strict=True)
            or Path(record.get('canonical_root', '')).resolve(strict=True) != ROOT.resolve(strict=True)):
        raise PipelineError('Hodge Volume III stage receipt contract or roots differ')
    stage = STAGE.resolve(strict=True)
    fixture = root_override is not None
    root = root_override.resolve(strict=True) if fixture else ROOT.resolve(strict=True)
    if fixture:
        scratch = Path('C:/Scratch/Open Christian Data').resolve(strict=True)
        if scratch not in root.parents or not _io_path(root / FIXTURE_MARKER).is_file():
            raise PipelineError('Hodge Volume III override requires a marked C:/Scratch/Open Christian Data fixture')
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError('Hodge Volume III install roots overlap')
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != record['before'] or after != record['after']:
        raise PipelineError('Hodge Volume III complete-generation receipt is stale')
    _scope(root, stage, before, after)
    _dependencies(stage)
    if record['source_sha256'] != 'aeb92566e8ce5019f6f43c56585538c67bafcea177d9d6f1df286006f24dda54' or record['accepted_master_sha256'] != after[MASTER.as_posix()]:
        raise PipelineError('Hodge Volume III source/master pins differ')
    return record, root, stage, fixture


def install(*, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict:
    record, root, stage, fixture = preflight(root_override=root_override)
    target, source = root / WORK, stage / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != record['before'] or _files(source) != record['after']:
            raise PipelineError('Hodge Volume III work changed while acquiring lock')
        _dependencies(stage)
        operation = root / 'library/.sidecar-operations' / ('hodge-vol3-' + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ('incoming', 'previous', 'failed-new'))
        journal = dict(contract='ocd-hodge-vol3-work-swap-v1', work_id='hodge-systematic-theology-vol-3', phase='created',
                       before=record['before'], after=record['after'], receipt=RECEIPT.as_posix(), updated_at=_now())
        _write_json_durable(operation / 'operation.json', journal)
        moved = live = False
        try:
            _copy_generation(source, incoming, record['after'])
            if _files(target) != record['before']:
                raise PipelineError('Hodge Volume III work changed during incoming copy')
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
            if _files(target) != record['after']:
                raise PipelineError('Hodge Volume III installed generation differs')
            validate_acceptance(_io_path((stage if fixture else root) / WORK / ACCEPTANCE), root=_io_path(stage if fixture else root))
            if fail_at:
                fail_at('after-validation')
            journal.update(phase='complete', updated_at=_now())
            _write_json_durable(operation / 'operation.json', journal)
            return dict(status='installed-and-validated', operation=operation.as_posix(),
                        before_count=len(record['before']), after_count=len(record['after']),
                        master_sha256=record['accepted_master_sha256'])
        except BaseException:
            try:
                if live:
                    if _files(target) != record['after']:
                        raise PipelineError('Hodge Volume III live generation differs during rollback')
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != record['before']:
                        raise PipelineError('Hodge Volume III previous generation differs during rollback')
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != record['before']:
                        raise PipelineError('Hodge Volume III rollback restored wrong bytes')
                journal.update(phase='rolled-back' if moved else 'failed-before-swap', updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
            except BaseException as exc:
                journal.update(phase='recovery-required', rollback_error=str(exc), updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
                raise PipelineError(f'Hodge Volume III rollback requires recovery: {operation}') from exc
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        result = install()
    else:
        record, _, _, _ = preflight()
        result = dict(status='ready-for-review', before_count=len(record['before']), after_count=len(record['after']))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
