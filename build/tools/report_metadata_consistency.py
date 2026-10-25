"""Report label inconsistencies without adopting or rewriting metadata."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.library.labels import profile, label
from ocd_kernel.library.views import library_browse_snapshot
from ocd_kernel.library._common import PipelineError, _reject_duplicate_keys


def metadata_consistency(root: Path) -> dict:
    vocabulary = profile()
    snapshot = library_browse_snapshot(root)
    issues = list(snapshot['issues'])
    for work in snapshot['works']:
        for creator in work.get('normalized', {}).get('creators', []):
            if creator['role']['mapping'] != 'mapped':
                issues.append({'code': 'unmapped-contributor-role', 'path': work['work_path'], 'severity': 'warning', 'raw': creator['role']['raw']})
        for edition in work['editions']:
            language = edition['language']
            if language['mapping'] == 'unmapped' or language['value'] != language['raw']:
                issues.append({'code': 'language-label-alias' if language['mapping'] == 'mapped' else 'unmapped-language',
                               'path': work['work_path'], 'severity': 'info' if language['mapping'] == 'mapped' else 'warning', **language})
            for provider in edition['providers']:
                if provider['mapping'] == 'unmapped':
                    issues.append({'code': 'unmapped-provider', 'path': work['work_path'], 'severity': 'warning', 'raw': provider['raw']})
    legacy = json.loads((ROOT / 'schemas/v1/structured_text.schema.json').read_text(encoding='utf-8'))
    properties = legacy['properties']['meta']['properties']
    configurations = 0
    formats = []
    for path in sorted((root / 'sources').rglob('config.json')):
        configurations += 1
        try:
            body = path.read_bytes()
            config = json.loads(body.decode('utf-8-sig'), object_pairs_hook=_reject_duplicate_keys)
            if not isinstance(config, dict):
                raise PipelineError('source configuration must be an object')
            provenance = config.get('provenance', {})
            if not isinstance(provenance, dict):
                raise PipelineError('source configuration provenance must be an object')
            original_format = config.get('source_format', provenance.get('source_format'))
            if original_format is not None:
                normalized = label('formats', original_format, vocabulary=vocabulary)
                formats.append({'path': path.relative_to(root).as_posix(), 'format': normalized,
                                'source_type': config.get('source_type'),
                                'encoding': config.get('source_encoding', config.get('encoding'))})
                if normalized['mapping'] == 'unmapped':
                    issues.append({'code': 'unmapped-source-format', 'path': path.relative_to(root).as_posix(),
                                   'severity': 'warning', 'raw': original_format})
            if config.get('schema_type') == 'structured_text':
                for field in ('era', 'audience'):
                    if field in config and config[field] not in properties[field]['enum']:
                        issues.append({'code': 'unsupported-legacy-label', 'path': path.relative_to(root).as_posix(),
                                       'severity': 'error', 'field': field, 'raw': config[field], 'canonical': None})
        except (PipelineError, OSError, UnicodeError, ValueError) as exc:
            issues.append({'code': 'invalid-source-config', 'path': path.relative_to(root).as_posix(), 'severity': 'error', 'message': str(exc)})
    return {'contract': 'ocd-metadata-consistency-v3', 'profile': vocabulary['version'],
            'counts': snapshot['counts'], 'configurations': configurations,
            'completeness': snapshot['metadata_coverage'],
            'assessment': 'validity issues and recorded completeness are separate; zero issues does not establish source accuracy or completeness',
            'issues': issues, 'source_formats': formats,
            'authority': 'current work/source records and reviewed vocabulary; no per-record overrides'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        report = metadata_consistency(args.root)
    except (PipelineError, OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any(issue['severity'] == 'error' for issue in report['issues']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
