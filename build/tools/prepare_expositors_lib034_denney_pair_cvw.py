"""Stage exact Denney editions and a transient one-work, two-route CVW catalog."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from cvw_app.stage_candidate import stage_candidate

ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = Path('D:/Library/Open Christian Data/candidate-reviews')
CANDIDATES = EXTERNAL / 'expositors-lib034-denney-pair-candidates-20260927-v1'
CATALOG = EXTERNAL / 'expositors-lib034-denney-pair-cvw-catalog-20260927-v1.json'
WORK_ID = 'expositors-bible--james-denney'
MEMBERS = ('denney-expositor2cor', 'denney-expositorthess')


def main() -> None:
    source_catalog = json.loads((ROOT / 'reports/publish/work_catalog.json').read_text(encoding='utf-8'))
    routes = []
    for member in MEMBERS:
        package = CANDIDATES / member
        validation = CANDIDATES / (member + '.validation.json')
        destination = EXTERNAL / (member + '-readable-cvw-20260927-v1')
        result = stage_candidate(package=package, validation=validation,
                                 destination=destination, repository_root=ROOT)
        routes.append(dict(association='source_hash+exact_id', candidate_verification='verified',
                           manifest=f'sources/commentaries/expositors-bible/readable-denney-pair-v4/{member}/source-manifest.json',
                           scope='edition', source_id=f'ccel-expositors-lib034-readable-{member}-v4',
                           validation_verification='verified', verification='verified'))
        print(json.dumps(dict(member=member, stage=result), sort_keys=True))
    work = next(item for item in source_catalog['works'] if item['work_id'] == WORK_ID)
    work = json.loads(json.dumps(work))
    work['reconstruction_state'] = {
        'retained_source': 'manifest_bound', 'tei_candidate': 'verified',
        'validation': 'verified', 'human_review': 'required',
        'publication': 'not_ready', 'accepted_ir': 'not_accepted', 'blocker': None,
        'routes': routes,
    }
    prior = json.loads((EXTERNAL / 'expositors-lib034-readable-pair-cvw-catalog-20260927-v1.json').read_text(encoding='utf-8'))
    catalog = dict(methodology=prior['methodology'], summary=dict(works=1,
                   note='CVW-only transient one-work, two-edition route; not canonical WorkCatalog'), works=[work])
    content = (json.dumps(catalog, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if CATALOG.exists() and CATALOG.read_bytes() != content:
        raise FileExistsError(f'CVW catalog identity differs: {CATALOG}')
    CATALOG.write_bytes(content)
    print(json.dumps(dict(catalog=CATALOG.as_posix(), sha256=sha256(content).hexdigest()), sort_keys=True))


if __name__ == '__main__':
    main()
