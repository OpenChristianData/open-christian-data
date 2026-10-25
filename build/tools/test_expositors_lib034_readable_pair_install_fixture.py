"""Exercise both Expositors guarded swaps through rollback on a marked fixture."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import uuid

from ocd_kernel.tei.install_accepted import _files, _io_path

from build.tools.install_expositors_lib034_readable_pair import (
    FIXTURE_MARKER, MEMBERS, ROOT, _json, install, preflight,
)


def main() -> None:
    receipt, _, _, _ = preflight()
    base = Path('D:/Library/Open Christian Data/candidate-reviews').resolve(strict=True)
    fixture = base / ('expositors-readable-pair-install-fixture-' + uuid.uuid4().hex[:12])
    if fixture.exists() or base not in fixture.resolve().parents:
        raise RuntimeError('unsafe or occupied Expositors fixture root')
    fixture.mkdir()
    _io_path(fixture / FIXTURE_MARKER).write_text('task-owned rollback fixture\n', encoding='utf-8')
    _io_path(fixture / 'library/.sidecar-operations').mkdir(parents=True)
    rows = {row['member_id']: row for row in receipt['works']}
    for member, (work_id, _, _) in MEMBERS.items():
        row = rows[member]
        target = fixture / row['work_path']
        for relative, checksum in row['before'].items():
            source = _io_path(ROOT / row['work_path'] / relative)
            destination = _io_path(target / relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if _files(target) != row['before']:
            raise RuntimeError(f'{member} fixture preimage differs')
    attempts = []
    for member in MEMBERS:
        row = rows[member]
        for boundary in ('after-old-rename', 'after-new-rename'):
            def fail_at(phase: str) -> None:
                if phase == boundary:
                    raise RuntimeError('intentional-fixture-' + boundary)
            try:
                install(member, root_override=fixture, fail_at=fail_at)
            except RuntimeError as exc:
                if str(exc) != 'intentional-fixture-' + boundary:
                    raise
            else:
                raise RuntimeError(f'{member} {boundary} did not interrupt')
            if _files(fixture / row['work_path']) != row['before']:
                raise RuntimeError(f'{member} {boundary} did not restore preimage bytes')
            operations = sorted(_io_path(fixture / 'library/.sidecar-operations').iterdir())
            journal = _json(operations[-1] / 'operation.json')
            if journal['phase'] != 'rolled-back' or journal['work_id'] != row['work_id']:
                raise RuntimeError(f'{member} {boundary} journal differs')
            attempts.append(dict(member=member, boundary=boundary, phase=journal['phase']))
    print(json.dumps(dict(status='rollback-fixture-passed', fixture=fixture.as_posix(), attempts=attempts), sort_keys=True))


if __name__ == '__main__':
    main()
