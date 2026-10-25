"""Prepare source-bound work-local evidence for the full retained Matthew book."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import etree
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='chrysostom-homilies-on-matthew'
FORM_ID=WORK_ID+'-ccel-npnf110-retained-en'
EDITION_ID=WORK_ID+'-ccel-npnf110-electronic'
ACQUISITION_ID=WORK_ID+'-ccel-npnf110-acquired'
WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/manifest-acquisitions/matthew-collection-npnf110')
SOURCE=Path('raw/ccel/npnf1/npnf110.xml')
SOURCE_SHA='e110c98b1f444147bf7baf79e46e56ae6c6a1f0b2983e6fc52f2356fac7f858f'
TITLE=ORIGINAL_TITLE='Homilies on the Gospel of Matthew'
SCOPE='Complete retained CCEL NPNF1-10 ThML.body direct div1 iii, titled The Homilies of St. John Chrysostom.: native title page iii.i, Preface to the Oxford Edition iii.ii, Introductory Essay iii.iii and all 86 present native Homily divisions in source order, through the source closing Homily XC. All source wording, native headings and numbering jumps, notes/references/pages, inline language and hierarchy are retained without filling or correction. The volume title page, American Edition preface and both index divisions are outside this complete work body and retained as source context. One complete homily collection TEI; no new homily work identities. Electronic completeness is not printed-edition equivalence.'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def put(path,b):
    q=io_path(ROOT/path);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def binding(name,path,role):
    b=io_path(ROOT/path).read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
    preflight=json.loads(io_path(ROOT/'reports/_logs/chrysostom-matthew-reconciliation-20261001-v1/source-preflight.json').read_bytes())
    raw=io_path(ROOT/SOURCE).read_bytes()
    acq=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if sha256(raw).hexdigest()!=SOURCE_SHA or acq['source_sha256']!=SOURCE_SHA or acq['source_path']!=SOURCE.as_posix():raise ValueError('Canonical retained acquisition differs')
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True));selected=source.xpath('/ThML/ThML.body/div1[@id="iii"]')[0]
    ids=['iii.i-p7','iii.i-p8','iii.i-p9','iii.i-p10','iii.i-p11','iii.i-p12']
    literals={id:''.join(source.xpath('//*[@id=$id]',id=id)[0].itertext()) for id in ids}
    author=source.xpath('.//DC.Creator[@sub="Author"]')[0].text
    volume=source.find('.//DC.Title').text
    profile=dict(contract='ocd-matthew-complete-collection-profile-v1',work_id=WORK_ID,title=TITLE,scope=SCOPE,
        source_path=SOURCE.as_posix(),source_sha256=SOURCE_SHA,source_url='https://www.ccel.org/ccel/schaff/npnf110.xml',source_root_id='iii',source_title=selected.get('title'),source_root_c14n_sha256=sha256(etree.tostring(selected,method='c14n')).hexdigest(),elements=15971,
        author=author,volume_title=volume,print_source=''.join(source.find('ThML.head/printSourceInfo').itertext()),
        contributors=[dict(name='George Prevost',role='translator'),dict(name='M. B. Riddle',role='reviser, annotator, and introductory essay author'),dict(name='Philip Schaff',role='volume editor')],
        context_literals=literals,historical_review=preflight['historical_review'],
        acquisition_path=ACQUISITION.as_posix(),acquisition_sha256=sha256(io_path(ROOT/ACQUISITION).read_bytes()).hexdigest(),work_sha256=sha256(io_path(ROOT/WORK/'work.json').read_bytes()).hexdigest(),
        rights_statement='The retained electronic header states Public Domain. Sourced via CCEL.org. Retained permission permits parsing ThML/XML for text; do not sell CCEL files or derivatives of CCEL formatting. Human acceptance, print comparison, independent rights clearance and publication remain separate.')
    if 'george prevost' not in literals['iii.i-p8'].lower() or 'm. b. riddle' not in literals['iii.i-p11'].lower() or 'Philip Schaff' not in raw.decode():raise ValueError('Exact primary contributors absent')
    put(BASE/'profile.json',canonical(profile));put(BASE/'boundary-review.json',canonical(preflight))
    closure=['build/tei/matthew_collection_oracle.py','build/tei/npnf_chrysostom_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/tei/validate.py']
    policy=dict(contract='ocd-matthew-complete-collection-policy-v1',closure_inputs=closure,scope=SCOPE,shared_assumptions=['Historical source boundary exposed; source parser lxml shared; original independent checker does not import producer. Stdlib second parser compares complete literal source ledger.'],preserved_numbering='All 86 present native homily divisions retained literally, including source numbering jumps. No missing content inferred or filled.')
    put(BASE/'validation-policy.json',canonical(policy))
    note=('# Matthew homily collection source and data credits\n\n'+SCOPE+'\n\nSourced via CCEL.org. The retained work title page credits George Prevost as translator and M. B. Riddle as reviser, annotator and introductory essay author; Philip Schaff is the volume editor. The retained electronic header print-source statement is New York: Christian Literature Publishing Co., 1886; title-page statements remain in the body. The provider states Public Domain. CCEL permits parsing ThML/XML for text; do not sell CCEL files or derivatives of their formatting. Carry visible credits and restrictions to `data/structured-text/chrysostom-homilies-on-matthew/README.md`. Human review, print equivalence, final rights and publication remain separate.\n').encode()
    put(BASE/'README.source.md',note)
    refs=[('retained-thml',SOURCE,'primary-source'),('reconstruction-profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('boundary-review',BASE/'boundary-review.json','exact-source-historical-reconciliation'),('source-readme',BASE/'README.source.md','source-credit-direction'),('canonical-acquisition',ACQUISITION,'canonical-acquisition'),('historical-content','reports/_logs/chrysostom-romans-reconciliation-20261001-v1/historical-package/content.tei.xml','reviewed-historical-body-authority'),('historical-package','reports/_logs/chrysostom-romans-reconciliation-20261001-v1/historical-package/manifest.json','historical-package-identity'),('legacy-mapper','build/tei/npnf_chrysostom_reconstruction.py','unchanged-reviewed-source-mapper'),('legacy-oracle','build/tei/npnf_chrysostom_oracle.py','independent-original-source-rules'),('ccel-permission','docs/sources/ccel-permission.md','retained-permission-evidence'),('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')]
    from build.tei import matthew_collection_reconstruction as p,matthew_collection_oracle as o
    manifest=dict(contract='ocd-source-manifest-v1',source_id=WORK_ID+'-complete-collection-v1',authorities=[binding(*r) for r in refs],converter=dict(id=p.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/matthew_collection_reconstruction.py',implementation_sha256=sha256(Path(p.__file__).read_bytes()).hexdigest()),validator=dict(id=o.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/matthew_collection_oracle.py',implementation_sha256=sha256(Path(o.__file__).read_bytes()).hexdigest(),import_closure_sha256=sha256(canonical([dict(path=path,sha256=sha256((ROOT/path).read_bytes()).hexdigest()) for path in closure])).hexdigest()),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
    put(BASE/'source-manifest.json',canonical(manifest));print(json.dumps(dict(status='prepared',elements=15971,homilies=86)))
if __name__=='__main__':main()
