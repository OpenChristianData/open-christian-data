"""Finish only the unchanged accepted Rutherford electronic selection privately."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
from collections import Counter
import json
import os
import subprocess
import sys
from lxml import etree
from ocd_kernel.library._common import io_path, io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.projection.categories.prose import project_accepted_prose
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader

ROOT = Path(__file__).resolve().parents[2]
WORK = Path('library/works/rutherford-letters')
PUB = WORK / 'publication'
PRE = Path('reports/_logs/rutherford-letters-downstream-preflight-20261001')
OUT = Path('D:/Library/Open Christian Data/reports/_logs/rutherford-letters-private-release-20261001-v1')
SOURCE = Path('raw/ccel/rutherford/letters.xml')
SOURCE_NOTE = Path('sources/private-ccel-rutherford/rutherford-letters/README.source.md')
DATA_NOTE = Path('data/prose/rutherford-letters/README.md')
SCOPE = 'Complete retained CCEL electronic member A Selection from his Letters, including Title Page, Contents, Foreword, Letters, Glossary and Indexes; not all surviving Rutherford correspondence or a verified print edition.'

def digest(p): return sha256(io_path(p).read_bytes()).hexdigest()
def read(p): return json.loads(io_path(p).read_bytes())
def save(p, value):
    q = io_path(p); q.parent.mkdir(parents=True, exist_ok=True)
    q.write_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode())
def runtime():
    names = ['ocd_kernel/projection/categories/prose.py', 'ocd_kernel/projection/categories/native_documents.py', 'ocd_kernel/projection/native_content.py', 'ocd_kernel/projection/native_content_check.py', 'ocd_kernel/projection/source_projection_evidence.py', 'ocd_kernel/release/assemble.py', 'ocd_kernel/release/verify.py', 'ocd_kernel/release/notices.py', 'build/tools/report_release_stats.py', 'build/tools/check_release_reader.py', 'ocd_kernel/tei/acceptance.py', 'ocd_kernel/library/state.py', 'ocd_kernel/reconstruction/contract.py']
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in io_glob(ROOT/'schemas/v2', '**/*.json')} | {p: digest(ROOT/p) for p in names}
def preflight():
    if io_path(ROOT/PRE/'preflight-v2.json').exists(): raise FileExistsError('Preserve existing preflight')
    paths = list(io_glob(ROOT/WORK, '**/acceptance.json'))
    if len(paths) != 1 or io_path(ROOT/PUB/'completion.json').exists(): raise ValueError('Reconcile acceptance or existing completion')
    acceptance = read(paths[0]); master = ROOT/acceptance['promotion']['master']['path']
    if digest(master) != acceptance['promotion']['master']['sha256'] or digest(ROOT/SOURCE) != acceptance['source']['source_sha256']: raise ValueError('Accepted bindings differ')
    audit_path = ROOT/'reports/_logs/downstream-reconciliation-review-20261001-v1/audit.json'
    audit = read(audit_path); entry = next(e for e in audit['ranked_candidates'] if e['work_id'] == WORK.name)
    if entry['dated_report_search_matches'] or entry['current_local_publication_receipts']: raise ValueError('Prior proof needs reconciliation')
    src = etree.fromstring(io_path(ROOT/SOURCE).read_bytes(), etree.XMLParser(load_dtd=False, no_network=True))
    tei = etree.fromstring(io_path(master).read_bytes()); body = src.find('ThML.body')
    texts = lambda n: ''.join(n.itertext())
    fields = [{'tag': n.tag, 'attributes': dict(n.attrib), 'text': texts(n)} for n in src.findall('.//DC/*')]
    units = [{'tag': n.tag, 'id': n.get('id'), 'title': n.get('title'), 'headings': [texts(h) for h in n if isinstance(h.tag,str) and h.tag.startswith('h')]} for n in body]
    counts = dict(Counter(etree.QName(n).localname for n in tei.iter() if isinstance(n.tag,str)))
    authority = {p.relative_to(ROOT).as_posix(): digest(p) for p in io_glob(ROOT/WORK, '**/*') if io_path(p).is_file() and 'publication' not in p.relative_to(ROOT/WORK).parts}
    authority[SOURCE.as_posix()] = digest(ROOT/SOURCE)
    authority['docs/sources/ccel-permission.md'] = digest(ROOT/'docs/sources/ccel-permission.md')
    authority['build/tools/complete_rutherford_letters_private_release.py'] = digest(Path(__file__))
    authority[audit_path.relative_to(ROOT).as_posix()] = digest(audit_path)
    search = ROOT/'reports/_logs/downstream-reconciliation-review-20261001-v1/receipt-search.json'
    authority[search.relative_to(ROOT).as_posix()] = digest(search)
    result = dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(), acceptance_path=paths[0].relative_to(ROOT).as_posix(), accepted_master_sha256=digest(master), source_sha256=digest(ROOT/SOURCE), scope=SCOPE, native_body_units=units, source_dc_fields=fields, source_general_description=texts(src.find('.//generalInfo/description')), print_published=texts(src.find('.//printSourceInfo/published')), master_tags=counts, source_table_rows=len(src.findall('.//tr')), source_cells=len(src.findall('.//td')), source_div2=len(src.findall('.//div2')), prior_search=dict(reused_dated_bounded_receipt_search_sha256=digest(search), searched=read(search)['searched'], exact_work_matches=entry['dated_report_search_matches'], canonical_publication_files=[p.relative_to(ROOT).as_posix() for p in io_glob(ROOT/PUB,'**/*') if io_path(p).is_file()], qualification='No completion located by bounded dated search; not an assertion about unsearched external records'), current_authority_bindings=authority, runtime_bindings=runtime(), patterns=['RP-13 historical proof reuse', 'RP-14 source credit roles', 'RP-04 readable table structure'])
    result['source_header_cells'] = len(src.findall('.//th'))
    result['source_letters'] = len(body.find("div1[@id='iv']").findall('div2'))
    result['caller_correction'] = 'Initial preflight scope sentence named unattested memoir/closing matter. Literal six-unit inventory was correct; corrected scope uses that inventory. Initial receipt preserved; no authority edited.'
    save(ROOT/PRE/'preflight-v2.json',result)
    print(json.dumps({k:result[k] for k in ['native_body_units','source_dc_fields','print_published','source_div2','source_table_rows','source_cells','master_tags']},ensure_ascii=True,indent=2))

def project():
    pre = read(ROOT/PRE/'preflight-v2.json')
    if io_path(ROOT/PRE/'actual-master-projection.json').exists(): raise FileExistsError('Preserve previous projection')
    for p,h in pre['current_authority_bindings'].items():
        if digest(ROOT/p)!=h: raise ValueError('Preflight authority changed '+p)
    if runtime()!=pre['runtime_bindings']: raise ValueError('Runtime changed')
    with cached_edition_lookups():
        a=ROOT/pre['acceptance_path']; validate_acceptance(a,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
        projected=project_accepted_prose(ROOT,acceptance_path=a)
        save(ROOT/PRE/'actual-master-projection.json',projected)
    print(json.dumps(dict(status='projected',rows=len(projected['rows']),characters=sum(len(r['text']) for r in projected['rows']),receipt=projected['receipt']),ensure_ascii=True))

if __name__ == '__main__':
    if len(sys.argv)==1:preflight()
    elif sys.argv[1]=='project':project()
    else:raise ValueError('Unknown action')
