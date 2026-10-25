"""Work-local observed runtime pin guard; contains no source mapping logic."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys


def observed():
    files = set()
    intrinsic = set()
    for name, module in sys.modules.copy().items():
        value = getattr(module, '__file__', None)
        spec = getattr(module, '__spec__', None)
        if value:
            path = Path(value).resolve(strict=True)
            if path.suffix == '.pyc' and path.with_suffix('.py').exists():
                path = path.with_suffix('.py')
            files.add(path)
        elif getattr(spec, 'origin', None) in {'built-in', 'frozen'}:
            intrinsic.add(name)
    rows = []
    for path in sorted(files, key=lambda p: str(p).casefold()):
        data = path.read_bytes()
        rows.append({'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    executable = Path(sys.executable).resolve(strict=True)
    binary = executable.read_bytes()
    return {'contract': 'ocd-l635-observed-execution-runtime-v1', 'python': f'{platform.python_implementation()} {platform.python_version()}', 'executable': {'path': str(executable), 'bytes': len(binary), 'sha256': hashlib.sha256(binary).hexdigest()}, 'files': rows, 'intrinsic_modules': sorted(intrinsic)}


def guard(manifest, phase):
    expected = json.loads(manifest.authority_path('execution-runtime').read_bytes())
    actual = observed()
    if set(expected) != set(actual) or expected['contract'] != actual['contract'] or expected['python'] != actual['python'] or expected['executable'] != actual['executable']:
        raise ValueError('L635 runtime envelope differs at ' + phase)
    allowed = {r['path']: r for r in expected['files']}
    for row in actual['files']:
        if allowed.get(row['path']) != row:
            raise ValueError('L635 unexpected or changed executed file at ' + phase + ': ' + row['path'])
    if not set(actual['intrinsic_modules']).issubset(expected['intrinsic_modules']):
        raise ValueError('L635 unexpected intrinsic module at ' + phase)
    return actual
