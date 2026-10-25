"""Read-only reconciliation of the already accepted Beatitudes witness."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from lxml import etree
from ocd_kernel.library._common import io_path, io_glob

WORK = 'watson-beatitudes'
BASE = Path('library/works') / WORK
EDITION = BASE / 'forms/watson-beatitudes-route-source-form/editions/watson-beatitudes-retained-thml-route'
OUT = Path('reports/_logs/watson-beatitudes-downstream-preflight-20261002-v1')
SOURCE = Path('raw/ccel/watson/beatitudes.xml')
MASTER_SHA = '07b0070649c6a6b8e6ebbfd300834299dc2d64cc3684e2198fc42dadb82b0aef'
SOURCE_SHA = 'd85ea8ded5de4feff3b2a9156bece9c471ffec3045eb8dc300b2784f5753f837'

def digest(path):
    return sha256(io_path(ROOT / path).read_bytes()).hexdigest()

def main():
    target = io_path(ROOT / OUT / 'preflight.json')
    if target.exists():
        raise FileExistsError('Reconcile existing preflight before replacing it')
    authority = {p.relative_to(ROOT).as_posix(): digest(p.relative_to(ROOT))
                 for p in io_glob(ROOT / BASE, '**/*') if io_path(p).is_file()}
    authority[SOURCE.as_posix()] = digest(SOURCE)
    assert digest(SOURCE) == SOURCE_SHA
    assert digest(EDITION / 'master.tei.xml') == MASTER_SHA
    acceptance = json.loads(io_path(ROOT / EDITION / 'acceptance.json').read_bytes())
    referenced = {}
    def check(value):
        if isinstance(value, dict):
            if all(k in value for k in ('path', 'sha256', 'bytes')):
                path = value['path']
                if isinstance(path, str) and path.startswith(('library/', 'raw/')):
                    data = io_path(ROOT / path).read_bytes()
                    assert sha256(data).hexdigest() == value['sha256'] and len(data) == value['bytes'], path
                    referenced[path] = value['sha256']
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(acceptance)
    source = etree.parse(str(io_path(ROOT / SOURCE)))
    header = source.find('ThML.head')
    units = [dict(position=i, native_id=x.get('id'), title=x.get('title'))
             for i, x in enumerate(source.xpath('/ThML/ThML.body/div1'), 1)]
    acquisition = json.loads(io_path(ROOT / EDITION / 'acquisitions/watson-beatitudes-retained-source.json').read_bytes())
    assert [x['native_id'] for x in units] == [x['native_id'] for x in acquisition['source_selection']['units']]
    index_path = Path('reports/_logs/retained-release-selection-index-20261002-v2/index.json')
    selection_hits = json.loads(io_path(ROOT / index_path).read_bytes())['by_work'][WORK]
    discovery = []
    for hit in selection_hits:
        p = Path(hit['selection_path'])
        assert digest(p) == hit['selection_sha256']
        old = json.loads(io_path(ROOT / p).read_bytes())
        matches = [x for x in old['items'] if x.get('work_id') == WORK]
        assert len(matches) == 1 and matches[0]['acceptance_path'] == (EDITION/'acceptance.json').as_posix()
        report = p.parent/'release-report.json'
        record = json.loads(io_path(ROOT / report).read_bytes())
        item = [x for x in record['items'] if x['item_id'] == matches[0]['item_id']][0]
        receipt = p.parent/item['receipt_path'].removeprefix('internal/')
        public = p.parent.parent/'public/data/prose/train.jsonl'
        discovery.append(dict(selection_path=p.as_posix(), selection_sha256=digest(p),
            report_path=report.as_posix(), report_sha256=digest(report), overall_status=record['status'],
            item_status=item['status'], row_count=item['row_count'],
            claimed_projection_receipt=receipt.as_posix(), claimed_receipt_physically_present=io_path(ROOT/receipt).exists(),
            prose_output_physically_present=io_path(ROOT/public).exists(),
            disposition='Exact selection and warned 25-row historical report remain leads; selected prose receipt/output are absent from this recovered ASV-specific readback. No standalone completed release is established by these files.'))
    evidence = dict(
        header_fields=[dict(path=source.getpath(x), attributes=list(x.attrib.items()), text=''.join(x.itertext()))
                       for x in header.iter() if isinstance(x.tag, str) and (x.tag.startswith('DC.') or x.tag=='published')],
        description=''.join(header.find('generalInfo/description').itertext()),
        native_units=units,
        boundary='Source title page, signed reader address, 21 numbered exposition chapters, appendix, and indexes stay together in the existing 25-member envelope. No new identity adoption, printed-witness claim, or scope expansion.')
    data = dict(status='pass', checked_at=datetime.now(timezone.utc).isoformat(), work_id=WORK,
        identity=acceptance['identity'], source_sha256=SOURCE_SHA, master_sha256=MASTER_SHA,
        acceptance_sha256=digest(EDITION/'acceptance.json'), input_bindings=authority,
        accepted_referenced_bindings=referenced, historical_discovery=discovery,
        primary_evidence=evidence, ownership=dict(active_threads_checked=['01a0db58-1041-7d51-9f37-3ecd6389432e','01a0f694-1263-7f32-ad87-4ad3099e2332'],
            observed_latest_scope=['Goforth release reconciliation','Revised Version CVW'], matching_work_collision_observed=False,
            limitation='Recent active-turn inspection only, supplemented by current PROJECT_STATE and explicit coordinator assignment.'),
        unchanged_master_route=True, reconstruction_performed=False, installation_needed=False,
        next_step='Current actual-master private projection, explicitly source-bound visible notices, independent verifier/statistics/both readers and exact final input hashes. Preserve existing scope and unresolved identity/human/rights qualifications.')
    for p, h in authority.items():
        assert digest(p) == h, p
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data,ensure_ascii=True,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(status='pass',path=(OUT/'preflight.json').as_posix(),sha256=sha256(target.read_bytes()).hexdigest(),input_bindings=len(authority),accepted_references=len(referenced),units=len(units))))

if __name__ == '__main__':
    main()
