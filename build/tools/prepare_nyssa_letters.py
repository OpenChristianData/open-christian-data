"""Bind the retained titled Letters collection without changing sibling routes."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='gregory-of-nyssa-letters'
FORM_ID=WORK_ID+'-ccel-npnf205-retained-en'
EDITION_ID=WORK_ID+'-ccel-npnf205-electronic'
ACQUISITION_ID=WORK_ID+'-ccel-npnf205-acquired'
WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/manifest-acquisitions/nyssa-letters-npnf205')
SOURCE=Path('raw/ccel/npnf2/npnf205.xml')
SOURCE_SHA='43e87ed232457fd2d5862f72dd2d5d84fe1e8b69f4c3eec839bad04579327bf3'
TITLE=ORIGINAL_TITLE='Letters'
SCOPE='Complete retained CCEL NPNF2-05 direct ThML.body/div1 xiii, titled Letters.: collection title page xiii.i and all eighteen native addressed Letter divisions xiii.ii through xiii.xix, in original order. The collection introduction and Ogle translator note remain at their original attachment inside xiii.ii before Letter I. Constituent titles, notes, pages, references, and source-native wording are conserved. Shared volume title pages, preface, contents, other works, and index remain outside this complete titled collection. One collection TEI and one generic native prose collection row; eighteen letter boundaries remain nested structure, without new work identities.'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def put(p,b):
    q=io_path(ROOT/p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def binding(name,path,role):
    b=io_path(ROOT/path).read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
    roster=json.loads((ROOT/'plans/2026-09-22-source-preflight/whole-library-handoff-inventory-20260926.json').read_bytes())
    if len([v for v in roster['works'] if v['work_id']==WORK_ID and v['handoff_group']=='declared-edition'])!=1:raise ValueError('fixed755 membership differs')
    acq=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    raw=io_path(ROOT/SOURCE).read_bytes()
    if sha256(raw).hexdigest()!=SOURCE_SHA or acq['source_path']!=SOURCE.as_posix() or acq['source_sha256']!=SOURCE_SHA:raise ValueError('retained acquisition differs')
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,remove_comments=False,huge_tree=True));body=root.find('ThML.body');selected=root.xpath('//*[@id="xiii"]')[0]
    if len(body)!=16 or selected.getparent() is not body or selected.get('title')!='Letters.' or len(selected)!=19:raise ValueError('collection boundary differs')
    work=json.loads(io_path(ROOT/WORK/'work.json').read_bytes())
    if work['title']!=TITLE or work['textual_forms'][0]['editions'][0]['containing_source']['locator']!=SOURCE.as_posix()+'#xiii':raise ValueError('canonical title/locator differs')
    context_ids=['iii','iv','xiii.i','xiii.ii-p1','xiii.ii-p4','xiii.xix']
    literals={id:''.join(root.xpath('//*[@id=$id]',id=id)[0].itertext()) for id in context_ids}
    boundary=dict(scope=SCOPE,selected='ThML.body/div1[@id="xiii"]',source_sha256=SOURCE_SHA,selected_attributes=dict(selected.attrib),children=[dict(position=i,id=c.get('id'),attributes=dict(c.attrib),elements=len(list(c.iter()))) for i,c in enumerate(selected,1)],context_literals=literals,collection_introduction_owner='xiii.ii-p1 remains inside original first-letter carrier before its letter heading',translator_scope='Harman Chaloner Ogle: exact first fourteen letters per xiii.ii-p1.2; volume title page credits William Moore and Henry Austin Wilson, without supported allocation of remaining four letters.',historical_hold_resolution='Coordinator /root authorized one complete titled collection from actual source hierarchy and book-level intent; prior requirement for eighteen new child IDs is superseded. Original identities and locator unchanged.')
    put(BASE/'boundary-review.json',canonical(boundary))
    old=ROOT/'sources/structured-text/gregory-nyssa-npnf205-works'/WORK_ID
    profile=json.loads((old/'reconstruction-profile.json').read_bytes());profile.update(scope_note=SCOPE,boundary=boundary)
    put(BASE/'profile.json',canonical(profile))
    closure=['build/tei/nyssa_letters_oracle.py','build/tei/npnf205_work_oracle.py','build/tei/npnf2_lib047_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/tei/validate.py']
    policy=json.loads((ROOT/'sources/structured-text/gregory-nyssa-npnf205-works/validation-policy.json').read_bytes());policy['closure_inputs']=closure
    put(BASE/'validation-policy.json',canonical(policy))
    note=('# Gregory of Nyssa: Letters collection source credit\n\n'+SCOPE+'\n\nSourced via CCEL.org. The collection introduction credits Harman Chaloner Ogle for the first fourteen letters, with signed notes; retain that precise scope. The volume title page credits William Moore and Henry Austin Wilson as translators, and Philip Schaff and Henry Wace as editors. No narrower translator allocation is asserted for the remaining four letters. The retained electronic header states Public Domain and gives New York: Christian Literature Publishing Co., 1892; the canonical edition title says 1893, retained without conflating those source statements. CCEL permission permits ThML parsing and says not to sell CCEL files or derivatives of their formatting. Carry human-visible credits to `data/structured-text/gregory-of-nyssa-letters/README.md`. Human/visual review, print comparison, final rights and publication remain separate.\n').encode()
    put(BASE/'README.source.md',note)
    refs=[('retained-thml',SOURCE,'primary-source'),('selection-plan','sources/structured-text/gregory-nyssa-npnf205-works/selection-plan.json','complete-work-boundary-plan'),('reconstruction-profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('boundary-review',BASE/'boundary-review.json','literal-boundary-evidence'),('source-readme',BASE/'README.source.md','source-attribution'),('canonical-acquisition',ACQUISITION,'canonical-acquisition-evidence'),('legacy-projection-policy','sources/structured-text/gregory-nyssa-npnf205/gregory-nyssa-npnf205.validation-policy.json','source-projection-policy'),('legacy-mapper','build/tei/npnf2_lib047_reconstruction.py','reused-source-mapper'),('legacy-oracle','build/tei/npnf2_lib047_oracle.py','independent-source-rules'),('work-converter','build/tei/npnf205_work_reconstruction.py','reused-source-mapper'),('work-oracle','build/tei/npnf205_work_oracle.py','independent-source-checker'),('ccel-permission','docs/sources/ccel-permission.md','permission-evidence'),('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')]
    from build.tei import nyssa_letters_reconstruction as p,nyssa_letters_oracle as o
    manifest=dict(contract='ocd-source-manifest-v1',source_id=WORK_ID+'-complete-collection-v1',authorities=[binding(*r) for r in refs],converter=dict(id=p.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/nyssa_letters_reconstruction.py',implementation_sha256=sha256(Path(p.__file__).read_bytes()).hexdigest()),validator=dict(id=o.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/nyssa_letters_oracle.py',implementation_sha256=sha256(Path(o.__file__).read_bytes()).hexdigest(),import_closure_sha256=sha256(canonical([dict(path=path,sha256=sha256((ROOT/path).read_bytes()).hexdigest()) for path in closure])).hexdigest()),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
    put(BASE/'source-manifest.json',canonical(manifest));print(json.dumps(dict(status='prepared',elements=597,letters=18)))
if __name__=='__main__':main()
