"""Exact journal-pinned acquired generations for LIB031 historical guards."""
from hashlib import sha256
import json
from pathlib import Path
from ocd_kernel.tei.install_accepted import _files, _io_path


def _put(root, logical, raw):
    relative = Path(logical)
    assert not relative.is_absolute() and '..' not in relative.parts
    target = _io_path(root / relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == raw
    else:
        target.write_bytes(raw)


def _before(root, work_id):
    home = Path(__file__).parent / 'fixtures/lib031-acquired-before'
    cases = json.loads((home / 'cases.json').read_bytes())
    case = cases[work_id]
    work = Path('library/works') / work_id
    for relative, expected in case['files'].items():
        raw = (home / work_id / relative).read_bytes()
        assert sha256(raw).hexdigest() == expected
        _put(root, work / relative, raw)
    assert _files(root / work) == case['files']


def historical_bounds_power(input_root, destination, stage):
    _before(destination, 'bounds-power-through-prayer')
    work = Path('library/works/bounds-power-through-prayer')
    for relative in _files(stage):
        if relative == 'stage-receipt.json' or relative.startswith(work.as_posix() + '/'):
            continue
        _put(destination, relative, _io_path(stage / relative).read_bytes())
    _put(destination, '.ocd-lib031-bounds-power-install-fixture', b'fixture-only\n')
    return destination


def historical_lib031_family(input_root, destination):
    source_set = Path('sources/structured-text/bounds-essentials-of-prayer/lib031-retained-source-set.json')
    members = json.loads((input_root / source_set).read_bytes())['members']
    paths = {
        source_set,
        source_set.with_name('lib031.reconstruction-profile.json'),
        source_set.with_name('lib031.source-manifest.json'),
        Path('plans/2026-09-22-source-preflight/ccel-direct-family-handoff-20260926.json'),
        Path('plans/2026-09-22-source-preflight/ccel-lib031-bounds-necessity-standalone-20260926.json'),
    }
    for ordinal, member in enumerate(members):
        work_id = member['work_id']
        _before(destination, work_id)
        source = Path('raw') / member['logical_path']
        raw = _io_path(input_root / source).read_bytes()
        assert len(raw) == member['bytes'] and sha256(raw).hexdigest() == member['sha256']
        _put(destination, source, raw)
        manifest = Path('sources/structured-text') / work_id / 'lib031-work.source-manifest.json'
        paths.add(manifest)
        record = json.loads((input_root / manifest).read_bytes())
        for authority in record['authorities']:
            logical = Path(authority['path'])
            raw = _io_path(input_root / logical).read_bytes()
            assert len(raw) == authority['bytes'] and sha256(raw).hexdigest() == authority['sha256']
            _put(destination, logical, raw)
        paths.update(Path(record[key]['implementation_path']) for key in ('converter', 'validator'))
        paths.add(Path(record['package_schema']['path']))
        if ordinal < 7:
            ticket = f'37c-{79 + ordinal:03d}'
            review = Path('plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews')
            paths.update(review / (ticket + suffix) for suffix in ('.md', '-cvw-start-20260920.capture.json', '-cvw-start-20260920.frame.png'))
    for logical in paths:
        _put(destination, logical, _io_path(input_root / logical).read_bytes())
    return destination
