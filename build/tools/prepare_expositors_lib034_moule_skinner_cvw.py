"""Stage exact Moule/Skinner candidates and a transient two-work CVW catalog."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from cvw_app.stage_candidate import stage_candidate

ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = Path('D:/Library/Open Christian Data/candidate-reviews')
CANDIDATES = EXTERNAL / 'expositors-lib034-moule-skinner-candidates-20260927-v1'
CATALOG = EXTERNAL / 'expositors-lib034-moule-skinner-cvw-catalog-20260927-v1.json'
MEMBERS = {
    'moule-expositorromans': 'expositors-bible--h-c-g-moule',
    'skinner-expositorezek': 'expositors-bible--john-skinner',
}


def main() -> None:
    source_catalog = json.loads((ROOT / 'reports/publish/work_catalog.json').read_text(encoding='utf-8'))
    works = []
    for member, work_id in MEMBERS.items():
        package = CANDIDATES / member
        validation = CANDIDATES / (member + '.validation.json')
        destination = EXTERNAL / (member + '-readable-cvw-20260927-v1')
        result = stage_candidate(package=package, validation=validation,
                                 destination=destination, repository_root=ROOT)
        work = next(item for item in source_catalog['works'] if item['work_id'] == work_id)
        work = json.loads(json.dumps(work))
        work['reconstruction_state'] = {
            'retained_source': 'manifest_bound', 'tei_candidate': 'verified',
            'validation': 'verified', 'human_review': 'required',
            'publication': 'not_ready', 'accepted_ir': 'not_accepted', 'blocker': None,
            'routes': [dict(association='source_hash+exact_id', candidate_verification='verified',
                            manifest=f'sources/commentaries/expositors-bible/readable-moule-skinner-v3/{member}/source-manifest.json',
                            scope='edition', source_id=f'ccel-expositors-lib034-readable-{member}-v3',
                            validation_verification='verified', verification='verified')],
        }
        works.append(work)
        print(json.dumps(dict(member=member, stage=result), sort_keys=True))
    prior = json.loads((EXTERNAL / 'expositors-lib034-readable-pair-cvw-catalog-20260927-v1.json').read_text(encoding='utf-8'))
    catalog = dict(methodology=prior['methodology'], summary=dict(works=2,
                   note='CVW-only transient two-work route; not canonical WorkCatalog'), works=works)
    content = (json.dumps(catalog, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if CATALOG.exists() and CATALOG.read_bytes() != content:
        raise FileExistsError(f'CVW catalog identity differs: {CATALOG}')
    CATALOG.write_bytes(content)
    print(json.dumps(dict(catalog=CATALOG.as_posix(), sha256=sha256(content).hexdigest()), sort_keys=True))


if __name__ == '__main__':
    main()
