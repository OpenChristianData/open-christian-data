"""Preflight or guardedly install the frozen Marrant N17016 electronic stage.

Default is read-only. ``--apply`` swaps only the complete Marrant work directory
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
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
from build.tools.stage_marrant_n17016_acceptance import SOURCE, SOURCE_SHA

ROOT = Path(__file__).resolve().parents[2]
WORK = Path('library/works/marrant-prince-hall-african-lodge-sermon')
EDITION = Path('forms/marrant-prince-hall-african-lodge-sermon-tcp-retained-en/editions/marrant-prince-hall-african-lodge-sermon-tcp-electronic')
ACQUISITION = EDITION / 'acquisitions/marrant-prince-hall-african-lodge-sermon-tcp-acquired.json'
ACCEPTANCE = EDITION / 'acceptance.json'
MASTER = EDITION / 'master.tei.xml'
EVIDENCE = Path('integration/marrant-n17016-electronic-acceptance-v1')
STAGE = Path('D:/Library/Open Christian Data/candidate-reviews/marrant-n17016-electronic-stage-20260927-v1')
RECEIPT = STAGE / 'marrant-n17016-stage-receipt.json'
RECEIPT_SHA = '445bfe84c14f4ea9e256453e7986f308787c7b7ec098aeaee2f1fc2ad1575c35'
CONTRACT = 'ocd-marrant-n17016-electronic-stage-v1'
FIXTURE_MARKER = '.ocd-marrant-n17016-install-fixture'


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _copy_generation(source: Path, target: Path, expected: dict[str, str]) -> None:
    if _io_path(target).exists():
        raise PipelineError('Marrant N17016 incoming generation already exists')
    _io_path(target).mkdir(parents=True)
    for relative, checksum in expected.items():
        original = _io_path(source / relative)
        destination = _io_path(target / relative)
        if not original.is_file() or _sha(original) != checksum:
            raise PipelineError(f'Marrant N17016 staged file changed: {relative}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
    if _files(target) != expected:
        raise PipelineError('Marrant N17016 incoming generation differs')


def _dependencies(stage: Path) -> None:
    prefix = WORK.as_posix() + '/'
    for relative, checksum in _files(stage).items():
        if relative.startswith(prefix) or relative == RECEIPT.name:
            continue
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise PipelineError(f'unsafe Marrant N17016 staged dependency: {relative}')
        source = (resolve_repo_path(ROOT, relative)
                  if path.parts[0] in {'raw', 'reports', 'exports'} else ROOT / path)
        if not _io_path(source).is_file() or _sha(source) != checksum:
            raise PipelineError(f'Marrant N17016 external source/evidence differs: {relative}')


def _scope(root: Path, stage: Path, before: dict[str, str], after: dict[str, str]) -> None:
    if len(before) != 4 or len(after) != 24:
        raise PipelineError('Marrant N17016 complete-generation file count differs')
    if set(before) != {'work.json', 'state.json', 'SOURCE_CREDIT.md', ACQUISITION.as_posix()}:
        raise PipelineError('Marrant N17016 canonical work preimage differs')
    allowed = {'work.json', 'state.json', ACQUISITION.as_posix(),
               ACCEPTANCE.as_posix(), MASTER.as_posix()}
    prefix = EVIDENCE.as_posix() + '/'
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        if path in allowed or path.startswith(prefix) and path not in before and path in after:
            continue
        raise PipelineError(f'Marrant N17016 unrelated work path differs: {path}')
    old_work = json.loads(_io_path(root / WORK / 'work.json').read_bytes())
    new_work = json.loads(_io_path(stage / WORK / 'work.json').read_bytes())
    expected = json.loads(json.dumps(old_work))
    form = expected['textual_forms'][0]
    edition = form['editions'][0]
    if edition.get('category') is not None or edition.get('language') != 'en' or form.get('language') != 'en':
        raise PipelineError('Marrant N17016 edition language/category preimage differs')
    edition['category'] = 'sermons'
    if expected != new_work:
        raise PipelineError('Marrant N17016 work identity differs beyond sermon category')
    old_acquisition = json.loads(_io_path(root / WORK / ACQUISITION).read_bytes())
    new_acquisition = json.loads(_io_path(stage / WORK / ACQUISITION).read_bytes())
    if (old_acquisition.get('source_path') != SOURCE.as_posix()
            or old_acquisition.get('source_sha256') != SOURCE_SHA
            or old_acquisition.get('source_bytes') != 48484
            or len(old_acquisition.get('retained_files', [])) != 1):
        raise PipelineError('Marrant N17016 source preimage differs')
    retained = old_acquisition['retained_files'][0]
    if (retained.get('path') != SOURCE.as_posix()
            or retained.get('bytes') != 48484 or retained.get('sha256') != SOURCE_SHA
            or old_acquisition.get('source_scope') != retained.get('scope')):
        raise PipelineError('Marrant N17016 retained source preimage differs')
    if new_acquisition != old_acquisition:
        raise PipelineError('Marrant N17016 acquisition changed')
    validate_acquisition(_io_path(stage / WORK / ACQUISITION), root=_io_path(stage))
    old_state = json.loads(_io_path(root / WORK / 'state.json').read_bytes())
    new_state = json.loads(_io_path(stage / WORK / 'state.json').read_bytes())
    old_targets = {item['target_id']: item for item in old_state['targets']}
    new_targets = {item['target_id']: item for item in new_state['targets']}
    if old_targets.keys() != new_targets.keys():
        raise PipelineError('Marrant N17016 state target identities differ')
    for target_id, old in old_targets.items():
        new = new_targets[target_id]
        if target_id != EDITION.name:
            if new != old:
                raise PipelineError('Marrant N17016 acquisition state changed')
            continue
        additions = [(WORK / MASTER).as_posix(), (WORK / ACCEPTANCE).as_posix()]
        if (old['stage'] != 'acquired' or new['stage'] != 'accepted'
                or new['evidence'] != old['evidence'] + additions
                or any(old.get(key) != new.get(key) for key in old if key not in {'stage', 'reason', 'updated_at', 'evidence'})):
            raise PipelineError('Marrant N17016 edition state transition differs')
    if after[MASTER.as_posix()] != after[(EVIDENCE / 'candidate.tei.xml').as_posix()]:
        raise PipelineError('Marrant N17016 master differs from accepted candidate')
    acceptance = validate_acceptance(_io_path(stage / WORK / ACCEPTANCE), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / 'state.json'), root=_io_path(stage))
    if (acceptance['identity']['work_id'] != 'marrant-prince-hall-african-lodge-sermon'
            or acceptance['promotion']['status'] != 'promoted'
            or acceptance['decision']['human_decision']['status'] != 'not-recorded'
            or acceptance['promotion']['master']['sha256'] != after[MASTER.as_posix()]):
        raise PipelineError('Marrant N17016 staged electronic-witness acceptance differs')


def preflight(*, root_override: Path | None = None) -> tuple[dict, Path, Path, bool]:
    if not _io_path(RECEIPT).is_file() or _sha(RECEIPT) != RECEIPT_SHA:
        raise PipelineError('Marrant N17016 frozen stage receipt differs')
    record = json.loads(_io_path(RECEIPT).read_bytes())
    if (record.get('contract') != CONTRACT or record.get('status') != 'staged-only'
            or record.get('work_id') != 'marrant-prince-hall-african-lodge-sermon' or record.get('installation') != 'not-performed'
            or Path(record.get('stage_root', '')).resolve(strict=True) != STAGE.resolve(strict=True)
            or Path(record.get('canonical_root', '')).resolve(strict=True) != ROOT.resolve(strict=True)):
        raise PipelineError('Marrant N17016 stage receipt contract or roots differ')
    stage = STAGE.resolve(strict=True)
    fixture = root_override is not None
    root = root_override.resolve(strict=True) if fixture else ROOT.resolve(strict=True)
    if fixture:
        scratch = Path('C:/Scratch/Open Christian Data').resolve(strict=True)
        if scratch not in root.parents or not _io_path(root / FIXTURE_MARKER).is_file():
            raise PipelineError('Marrant N17016 override requires a marked C:/Scratch/Open Christian Data fixture')
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError('Marrant N17016 install roots overlap')
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != record['before'] or after != record['after']:
        raise PipelineError('Marrant N17016 complete-generation receipt is stale')
    _scope(root, stage, before, after)
    _dependencies(stage)
    if record['source_sha256'] != SOURCE_SHA or record['accepted_master_sha256'] != after[MASTER.as_posix()]:
        raise PipelineError('Marrant N17016 source/master pins differ')
    return record, root, stage, fixture


def install(*, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict:
    record, root, stage, fixture = preflight(root_override=root_override)
    target, source = root / WORK, stage / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != record['before'] or _files(source) != record['after']:
            raise PipelineError('Marrant N17016 work changed while acquiring lock')
        _dependencies(stage)
        operation = root / 'library/.sidecar-operations' / ('marrant-n17016-' + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ('incoming', 'previous', 'failed-new'))
        journal = dict(contract='ocd-marrant-n17016-work-swap-v1', work_id='marrant-prince-hall-african-lodge-sermon', phase='created',
                       before=record['before'], after=record['after'], receipt=RECEIPT.as_posix(), updated_at=_now())
        _write_json_durable(operation / 'operation.json', journal)
        moved = live = False
        try:
            _copy_generation(source, incoming, record['after'])
            if _files(target) != record['before']:
                raise PipelineError('Marrant N17016 work changed during incoming copy')
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
                raise PipelineError('Marrant N17016 installed generation differs')
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
                        raise PipelineError('Marrant N17016 live generation differs during rollback')
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != record['before']:
                        raise PipelineError('Marrant N17016 previous generation differs during rollback')
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != record['before']:
                        raise PipelineError('Marrant N17016 rollback restored wrong bytes')
                journal.update(phase='rolled-back' if moved else 'failed-before-swap', updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
            except BaseException as exc:
                journal.update(phase='recovery-required', rollback_error=str(exc), updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
                raise PipelineError(f'Marrant N17016 rollback requires recovery: {operation}') from exc
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
