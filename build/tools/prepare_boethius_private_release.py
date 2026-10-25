"""Prepare source-grounded notices and direct runtime pins; preserve accepted authority."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.library._common import io_path, io_glob

ROOT = Path(__file__).resolve().parents[2]
WORK = 'boethius-theological-tractates'
BASE = ROOT / 'library/works' / WORK
PUB = BASE / 'publication'
PRE = ROOT / 'reports/_logs/boethius-theological-tractates-downstream-preflight-20261001-v1'
SOURCE_NOTE = 'sources/private-boethius-theological-tractates/README.source.md'
DATA_NOTE = 'data/prose/boethius-theological-tractates/README.md'


def digest(p):
    return sha256(io_path(p).read_bytes()).hexdigest()


def save(p, value):
    io_path(p).parent.mkdir(parents=True, exist_ok=True)
    io_path(p).write_text(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


def main():
    if PRE.exists() or PUB.exists():
        raise FileExistsError('Reconcile existing work-specific output before writing')
    authority = {p.relative_to(ROOT).as_posix(): digest(p) for p in io_glob(BASE, '**/*') if io_path(p).is_file()}
    acceptance_paths = list(io_glob(BASE, '**/acceptance.json'))
    if len(acceptance_paths) != 1:
        raise ValueError('Expected exact one accepted edition')
    acceptance_path = acceptance_paths[0]
    acceptance = json.loads(io_path(acceptance_path).read_bytes())
    source_rel = acceptance['source']['source_path']
    source = ROOT / source_rel
    master = ROOT / acceptance['promotion']['master']['path']
    if digest(master) != 'ea08dac6a62706f0618f70a900fee6d05286d9479a1ad63fa9997daa5b3c42d9':
        raise ValueError('Assigned accepted master differs')
    if digest(source) != acceptance['source']['source_sha256'] or io_path(source).stat().st_size != acceptance['source']['source_bytes']:
        raise ValueError('Retained source differs')
    # Check retained technical sidecar bindings without rerunning historical reconstruction.
    checked = []
    for field in ['accounting', 'closure', 'fidelity', 'reproducibility', 'schema', 'validation', 'candidate']:
        bound = acceptance['technical'][field]
        if digest(ROOT / bound['path']) != bound['sha256']:
            raise ValueError('Accepted technical binding differs: ' + field)
        checked.append(field)
    for field in ['source_manifest', 'accounting']:
        bound = acceptance['source'][field]
        if digest(ROOT / bound['path']) != bound['sha256']:
            raise ValueError('Accepted source binding differs: ' + field)
    review = acceptance['review']['report']
    if digest(ROOT / review['path']) != review['sha256']:
        raise ValueError('Accepted review differs')
    tree = etree.fromstring(io_path(source).read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True))
    body = tree.find('ThML.body')
    roots = [e for e in body if isinstance(e.tag, str)]
    if [e.get('id') for e in roots] != ['i', 'ii', 'iii', 'iv', 'v']:
        raise ValueError('Native envelope differs')
    tracts = roots[3].findall('div2')
    if [e.get('id') for e in tracts] != ['iv.i', 'iv.ii', 'iv.iii', 'iv.iv', 'iv.v']:
        raise ValueError('Native five-tract collection differs')
    title = ''.join(roots[0].itertext())
    introduction = ''.join(roots[2].itertext())
    for literal in ['H. F. STEWART', 'E. K. RAND', 'E. CAPPS', 'T. E. PAGE', 'W. H. D. ROUSE', 'WILLIAM HEINEMANN']:
        if literal not in title:
            raise ValueError('Own title credit differs: ' + literal)
    for literal in ['H.F.S.', 'E.K.R.', 'E. J. Thomas']:
        if literal not in introduction:
            raise ValueError('Own introduction acknowledgment differs: ' + literal)
    head = tree.find('ThML.head')
    published = head.findtext('printSourceInfo/published')
    dc = head.find('electronicEdInfo/DC')
    rights = dc.findtext('DC.Rights')
    created = dc.findtext('DC.Date')
    description = ''.join(head.find('generalInfo/description').itertext())
    if published != "London: W. Heinemann; New York: G.P. Putnam's Sons, 1918" or rights != 'Public Domain' or created != '2000-07-23':
        raise ValueError('Literal own header differs')
    evidence = {
        'source_path': source_rel, 'source_sha256': digest(source),
        'roots': [{'id': e.get('id'), 'title': e.get('title')} for e in roots],
        'tracts': [{'id': e.get('id'), 'title': e.get('title')} for e in tracts],
        'titlepage_literal': title, 'introduction_final_literal': introduction[-2200:],
        'published_literal': published, 'dc_rights_literal': rights, 'electronic_created_literal': created,
        'description_literal': description,
        'dc_creator_literals': [{'attributes': dict(e.attrib), 'text': e.text} for e in dc.findall('DC.Creator')],
        'qualification': 'Own retained primary statements only; print equivalence, public rights clearance and full visual proofreading remain unassessed.'}
    PRE.mkdir(parents=True)
    save(PRE / 'primary-credit-evidence.json', evidence)
    note = '''# The Theological Tractates — retained source and use notice

This private preparation uses Boethius, *The Theological Tractates*, sourced via CCEL.org, from the complete retained `raw/ccel/boethius/tracts.xml`. Its SHA-256 is `406487abffb39f63934771ce3b4d23b69ce4488d6bc1ccc6a6cad5b4b1e01de8`. The existing accepted master is unchanged.

The complete electronic witness includes its title page, Note on the Text, Introduction, all five theological tractates in their native order, and Greek-word and print-page indexes. The title page and introduction mention the companion *Consolation of Philosophy* and its “I. T.” translation; that is shared print-volume context. No Consolation text is present in this retained work, and this release does not represent it. The introduction's source-attribution discussion and the note concerning the fourth tract's genuineness remain source statements, not new editorial judgments.

The own title page credits the English translation of the tractates to **H. F. Stewart** and **E. K. Rand**. It identifies the Loeb Classical Library editors as **E. Capps, T. E. Page, and W. H. D. Rouse**. The Note on the Text is signed **E. K. R.**; the Introduction is signed **H.F.S. / E.K.R.** and acknowledges assistance from **E. J. Thomas**. These roles are distinct. The electronic DC translator token `steward_hf` is retained as supplied; the human-readable title page spells **STEWART**. No transcription contributor is identified in the empty Digitizer field.

The retained printSourceInfo reads **London: W. Heinemann; New York: G.P. Putnam's Sons, 1918**. The title page gives William Heinemann and G. P. Putnam's Sons. This is a retained bibliographic claim, not a newly collated identification of a print copy. **2000-07-23** is the CCEL electronic creation date, not a print date. The CCEL descriptive essay is signed Kathleen O’Bannon, CCEL Staff; that name is credit only for the description, not translation or edition editing. The original Unicode description and name are preserved literally in the source-bound evidence.

The provider's own DC.Rights label is **Public Domain**. It is recorded as a source statement; it does not itself establish independent clearance of all translation, editorial, transcription, file or formatting rights. The retained project permission record `docs/sources/ccel-permission.md` records permission to parse CCEL ThML/XML for text and distinguishes CCEL files/formatting from the underlying texts. **Do not sell CCEL files or derivatives of their formatting.** Source credit is provided here and in the private release README. No source or media acquisition occurred.

Keep wording, source uncertainty, notes, page markers, local links and native structure as retained. Current technical projection and private offline verification do not establish human acceptance, complete visual proofreading, print collation, independent rights clearance or public publication authorization.

For data at `data/prose/boethius-theological-tractates`, maintain this complete source/use notice in `data/prose/boethius-theological-tractates/README.md` and in any release README containing these rows.
'''
    for rel in [SOURCE_NOTE, DATA_NOTE]:
        path = ROOT / rel
        if io_path(path).exists():
            raise FileExistsError(path)
        io_path(path).parent.mkdir(parents=True, exist_ok=True)
        io_path(path).write_text(note, encoding='utf-8', newline='\n')
    # Direct implementation pins, not an explanatory freeze receipt.
    previous = json.loads((ROOT / 'library/works/edwards-select-sermons/publication/runtime-freeze.json').read_bytes())
    runtime = {p: digest(ROOT / p) for p in previous if p != 'ocd_kernel/projection/categories/sermons.py'}
    expected = {'schemas/v2/native-content.schema.json': '8e6cb79b79c2c72e1b896404fa6ed7f1d1c49e6043cf01b0de50a6883391c30a',
                'ocd_kernel/projection/source_projection_evidence.py': 'd749eb107efc8e762642a05dc35c7ebcd7789b37459851f74d9faf14c7c1c013',
                'ocd_kernel/reconstruction/contract.py': 'ee9fe78b88bfe68c04223a4273918e065b9bc2f5abbd002405eb7ae063c08ce9'}
    if any(runtime[p] != h for p, h in expected.items()):
        raise ValueError('Assigned stable shared runtime differs')
    PUB.mkdir(parents=True)
    save(PUB / 'runtime-freeze.json', runtime)
    item = dict(item_id=WORK, category='prose', acceptance_path=acceptance_path.relative_to(ROOT).as_posix(),
                public_notices=[dict(source_path=SOURCE_NOTE, source_sha256=digest(ROOT / SOURCE_NOTE),
                                     notice_path=DATA_NOTE, notice_sha256=digest(ROOT / DATA_NOTE))])
    save(PUB / 'selection-draft.json', dict(schema_version='2.0', release_id='boethius-theological-tractates-private-offline-20261001-v1', items=[item]))
    authority[source_rel] = digest(source)
    for p, h in authority.items():
        if digest(ROOT / p) != h:
            raise ValueError('Accepted authority changed during preparation: ' + p)
    save(PRE / 'preflight.json', dict(status='pass', checked_at=datetime.now(timezone.utc).isoformat(), work_id=WORK,
         authority_bindings=authority, runtime_bindings=runtime, reused_technical_bindings=checked,
         accepted_master_sha256=digest(master), source_sha256=digest(source), acceptance_sha256=digest(acceptance_path),
         primary_evidence_sha256=digest(PRE / 'primary-credit-evidence.json'),
         prior_search='Root bounded reconciliation: 255 dated JSON receipts plus current work publication tree, no matching private completion; not a global absence claim.',
         accepted_fidelity_reused=True, reconstruction_performed=False, authority_unchanged=True,
         remaining=['actual-master projection and independent saved linkage', 'private assembly/verification/statistics/readers', 'final current binding audit']))
    print(json.dumps(dict(status='pass', authority_bindings=len(authority), runtime_bindings=len(runtime), preflight_sha256=digest(PRE / 'preflight.json'))))


if __name__ == '__main__':
    main()
