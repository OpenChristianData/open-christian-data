"""Preflight and guardedly install Milligan's accepted index repair as one work generation.

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
from ocd_kernel.projection.categories.commentary import project_accepted_commentary, verify_accepted_commentary
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
from build.tools.expositors_review import preflight as _shared_preflight

ROOT = Path(__file__).resolve().parents[2]
STAGE = Path('D:/Library/Open Christian Data/candidate-reviews/expositors-lib036-milligan-index-repair-stage-20260928-v2')
RECEIPT = STAGE / 'expositors-milligan-index-repair-stage-receipt.json'
RECEIPT_SHA = '693aabb7a1ac1755243bfcb7fc1aa183cd477f684c5a9dd644b7563124e3f098'
CONTRACT = 'ocd-expositors-milligan-index-repair-stage-v1'
FIXTURE_MARKER = '.ocd-expositors-milligan-index-repair-fixture'
WORK_ID = 'expositors-bible--william-milligan'
MEMBER = 'milligan-expositorrev'
SOURCE = 'raw/ccel/expositors-bible/milligan_expositorrev.xml'
EVIDENCE = 'integration/milligan-expositorrev-readable-electronic-index-v2/'


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
        raise PipelineError('Milligan staged dependencies differ from frozen receipt')
    for relative, checksum in deps.items():
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise PipelineError(f'unsafe Milligan dependency: {relative}')
        source = (resolve_repo_path(ROOT, relative)
                  if path.parts[0] in {'raw', 'reports', 'exports'} else ROOT / path)
        if not _io_path(source).is_file() or _sha(source) != checksum:
            raise PipelineError(f'Milligan source or evidence changed: {relative}')


def _scope(root: Path, stage: Path, row: dict) -> None:
    work_path = Path(row['work_path'])
    before, after = _files(root / work_path), _files(stage / work_path)
    if (work_path != Path('library/works') / WORK_ID or row['work_id'] != WORK_ID
            or before != row['before'] or after != row['after']
            or len(before) != 23 or len(after) != 40
            or row['source_path'] != SOURCE or row['native_rows'] != 21):
        raise PipelineError('Milligan accepted-generation receipt is stale')
    acceptance_rel = [x for x in before if x.endswith('/acceptance.json')]
    if len(acceptance_rel) != 1:
        raise PipelineError('Milligan accepted edition identity differs')
    acceptance_rel = acceptance_rel[0]
    master_rel = acceptance_rel.removesuffix('acceptance.json') + 'master.tei.xml'
    if (before[acceptance_rel] != row['prior_acceptance_sha256']
            or before[master_rel] != row['prior_master_sha256']
            or after[acceptance_rel] != row['new_acceptance_sha256']
            or after[master_rel] != row['new_master_sha256']):
        raise PipelineError('Milligan old/new acceptance or master differs')
    for relative in set(before) | set(after):
        if before.get(relative) == after.get(relative):
            continue
        if relative in {acceptance_rel, master_rel}:
            continue
        if relative.startswith(EVIDENCE) and relative not in before and relative in after:
            continue
        raise PipelineError(f'Milligan unrelated accepted-work file changed: {relative}')
    correction = _json(stage / work_path / EVIDENCE / 'correction.json')
    if (correction['prior_master_sha256'] != row['prior_master_sha256']
            or correction['prior_acceptance_sha256'] != row['prior_acceptance_sha256']
            or len(correction['accepted_master_delta']) != 2
            or {x['tei_id'] for x in correction['accepted_master_delta']} != {
                'milligan-expositorrev-feature-003885', 'milligan-expositorrev-feature-003909'}):
        raise PipelineError('Milligan source index delta differs')
    if after[EVIDENCE + 'correction.json'] != row['correction_sha256']:
        raise PipelineError('Milligan correction proof hash differs')
    if after[EVIDENCE + 'candidate.tei.xml'] != row['new_master_sha256']:
        raise PipelineError('Milligan corrected master and candidate differ')
    accepted = validate_acceptance(_io_path(stage / work_path / acceptance_rel), root=_io_path(stage))
    if (accepted['identity']['work_id'] != WORK_ID
            or accepted['identity']['edition_id'] != Path(acceptance_rel).parent.name
            or accepted['promotion']['master']['sha256'] != row['new_master_sha256']
            or accepted['representation_revision']['id'] != 'milligan-expositorrev-ccel-electronic-index-v2'
            or accepted['decision']['human_decision']['status'] != 'not-recorded'):
        raise PipelineError('Milligan corrected acceptance differs')
    validate_state(_io_path(stage / work_path / 'state.json'), root=_io_path(stage))
    from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
    from build.tei.expositors_bible_lib036_readable_milligan_index_v2_oracle import _oracle
    manifest = SourceManifest.load(ROOT / 'sources/commentaries/expositors-bible/readable-milligan-index-v2/milligan-expositorrev/source-manifest.json', repository_root=ROOT)
    candidate = CandidatePackage.load(Path('D:/Library/Open Christian Data/candidate-reviews/expositors-lib036-milligan-index-v2-candidate-20260928-v1/milligan-expositorrev'))
    report = validate(manifest, candidate, _oracle)
    if (manifest.sha256 != row['source_manifest_sha256']
            or candidate.sha256 != row['candidate_package_sha256'] or report.status != 'pass'):
        raise PipelineError('Milligan corrected source oracle differs')
    projection = project_accepted_commentary(_io_path(stage), acceptance_path=_io_path(stage / work_path / acceptance_rel))
    errors = verify_accepted_commentary(_io_path(stage), acceptance_path=_io_path(stage / work_path / acceptance_rel),
                                         rows=projection['rows'], receipt=projection['receipt'])
    if errors or len(projection['rows']) != 21:
        raise PipelineError(f'Milligan corrected native projection differs: {errors[:2]}')


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
            raise PipelineError('Milligan work changed while acquiring lock')
        _dependencies(stage)
        operation = root / 'library/.sidecar-operations' / ('expositors-milligan-index-repair-' + uuid.uuid4().hex[:12])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ('incoming', 'previous', 'failed-new'))
        journal = dict(contract='ocd-expositors-readable-work-swap-v1', work_id=row['work_id'], phase='created',
                       before=row['before'], after=row['after'], receipt=RECEIPT.as_posix(), updated_at=_now())
        _write_json_durable(operation / 'operation.json', journal)
        moved = live = False
        try:
            _copy_generation(source, incoming, row['after'])
            if _files(target) != row['before']:
                raise PipelineError('Milligan work changed during incoming copy')
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
                raise PipelineError('Milligan installed generation differs')
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
                        raise PipelineError('Milligan live generation differs during rollback')
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != row['before']:
                        raise PipelineError('Milligan previous generation differs during rollback')
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != row['before']:
                        raise PipelineError('Milligan rollback restored wrong bytes')
                journal.update(phase='rolled-back' if moved else 'failed-before-swap', updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
            except BaseException as exc:
                journal.update(phase='recovery-required', rollback_error=str(exc), updated_at=_now())
                _write_json_durable(operation / 'operation.json', journal)
                raise PipelineError(f'Milligan rollback requires recovery: {operation}') from exc
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
