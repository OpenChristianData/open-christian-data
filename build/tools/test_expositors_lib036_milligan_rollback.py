"""Exercise Milligan's guarded one-work swap on marked external fixtures only."""

from __future__ import annotations

from pathlib import Path
import shutil

from ocd_kernel.tei.install_accepted import _files, _io_path

from build.tools import install_expositors_lib036_milligan as installer


BASE = Path('D:/Library/Open Christian Data/candidate-reviews/expositors-lib036-milligan-install-fixture-20260927-v1')


def _fixture(label: str, before: dict[str, str]) -> Path:
    root = BASE / label
    if _io_path(root).exists():
        raise ValueError(f'fresh Milligan fixture required: {root}')
    _io_path(root).mkdir(parents=True)
    _io_path(root / installer.FIXTURE_MARKER).write_text('Milligan isolated installer fixture\n', encoding='utf-8')
    source = installer.ROOT / 'library/works' / installer.WORK_ID
    target = root / 'library/works' / installer.WORK_ID
    for relative, digest in before.items():
        origin, destination = _io_path(source / relative), _io_path(target / relative)
        if not origin.is_file() or installer._sha(origin) != digest:
            raise ValueError(f'Milligan canonical fixture source changed: {relative}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    if _files(target) != before:
        raise ValueError('Milligan fixture preimage differs')
    return root


def main() -> None:
    record, _, _, _ = installer.preflight()
    before, after = record['work']['before'], record['work']['after']
    for label in ('after-old-rename', 'after-new-rename'):
        root = _fixture(label, before)

        def stop(phase: str) -> None:
            if phase == label:
                raise RuntimeError('intentional Milligan rollback seam: ' + label)

        try:
            installer.install(root_override=root, fail_at=stop)
        except RuntimeError as exc:
            if str(exc) != 'intentional Milligan rollback seam: ' + label:
                raise
        else:
            raise ValueError(f'Milligan {label} rollback seam did not fire')
        if _files(root / 'library/works' / installer.WORK_ID) != before:
            raise ValueError(f'Milligan {label} rollback did not restore the preimage')
        operations = list((root / 'library/.sidecar-operations').iterdir())
        if len(operations) != 1 or installer._json(operations[0] / 'operation.json')['phase'] != 'rolled-back':
            raise ValueError(f'Milligan {label} rollback journal differs')
    root = _fixture('success', before)
    result = installer.install(root_override=root)
    if (result['status'] != 'installed-and-validated'
            or _files(root / 'library/works' / installer.WORK_ID) != after):
        raise ValueError('Milligan fixture success generation differs')
    print('Milligan one-work swap: after-old and after-new rollback restored 4 files; success fixture installed 23')


if __name__ == '__main__':
    main()
