"""Export a deterministic public-field metadata view, without publishing it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.library.views import library_browse_snapshot
from ocd_kernel.library.rights import public_rights
from ocd_kernel.library._common import PipelineError, canonical_bytes


def export_metadata(root: Path) -> dict:
    snapshot = library_browse_snapshot(root)
    if any(issue.get('severity') == 'error' for issue in snapshot['issues']):
        raise PipelineError('metadata export requires valid declared records and rights bindings')
    works = []
    for work in snapshot['works']:
        labels = work['normalized']
        works.append({'work_id': work['work_id'], 'title': work['title'],
                      'description': labels['description'], 'coverage': work['coverage'],
                      'source_metadata': labels['source_metadata'],
                      'creators': [{'name': c['name'], 'role': c['role'], 'scope': c['scope']}
                                   for c in labels['creators']],
                      'facets': [{'kind': f['kind'], 'vocabulary': f['authority'],
                                  'term_id': f['term_id'], 'label': f['label']}
                                 for f in labels['facets'] if f['adoption'] == 'adopted'],
                      'editions': [{'edition_id': e['edition_id'], 'textual_form_id': e['textual_form_id'],
                                    'title': e['title'], 'form_title': e['form_title'],
                                    'containing_source': {'title': e['containing_source']['title']}
                                                         if e['containing_source'] else None,
                                    'sources': e['sources'], 'coverage': e['coverage'],
                                    'language': e['language'], 'download_category': e['category'],
                                    'providers': e['providers'], 'rights': public_rights(e['rights'])}
                                   for e in work['editions']]})
    result = {'contract': 'ocd-library-metadata-v3', 'profile': snapshot['label_profile'],
              'coverage': snapshot['metadata_coverage'],
              'scope': 'recorded descriptions and indexed claims; source accuracy, adoption and release eligibility not reverified',
              'works': works}
    from ocd_kernel.release.public_allowlist import _scan
    errors = _scan(result, 'library metadata export')
    if errors:
        raise PipelineError('; '.join(errors))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        body = canonical_bytes(export_metadata(args.root))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('xb') as stream:
            stream.write(body)
    except (PipelineError, OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({'path': str(args.output), 'bytes': len(body)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
