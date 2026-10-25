"""Prepare source-bound work-local evidence for the full retained First Corinthians book."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import etree
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='chrysostom-homilies-on-1-corinthians'
FORM_ID=WORK_ID+'-ccel-npnf112-retained-en'
EDITION_ID=WORK_ID+'-ccel-npnf112-electronic'
ACQUISITION_ID=WORK_ID+'-ccel-npnf112-acquired'
WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/manifest-acquisitions/first-corinthians-collection-npnf112')
SOURCE=Path('raw/ccel/npnf1/npnf112.xml')
SOURCE_SHA='b8b345e060625cdf495e888322d88e922f66e686863e818a978204c5f564a4dd'
TITLE=ORIGINAL_TITLE='Homilies on the First Epistle of Paul to the Corinthians'
SCOPE='Complete retained CCEL NPNF1-12 ThML.body direct div1 iv, titled Homilies on First Corinthians.: native Argument iv.i and all 44 present native Homily divisions iv.ii through iv.xlv in source order. All source wording, native headings, notes/references/pages, inline language, text/tails and hierarchy are retained without filling or correction. Series title, shared volume title page, shared Preface iii, neighboring Second Corinthians v and both indexes vi/vii remain outside this complete work body as retained context; exact shared credit statements are carried in the header/accounting and visible credits. One complete First Corinthians collection TEI; no new homily work identities. Electronic completeness is not printed-edition equivalence.'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def put(path,b):
    q=io_path(ROOT/path);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def binding(name,path,role):
    b=io_path(ROOT/path).read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
    preflight=json.loads(io_path(ROOT/'reports/_logs/first-corinthians-reconciliation-20261001-v1/source-preflight.json').read_bytes())
    raw=io_path(ROOT/SOURCE).read_bytes()
    acq=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if sha256(raw).hexdigest()!=SOURCE_SHA or acq['source_sha256']!=SOURCE_SHA or acq['source_path']!=SOURCE.as_posix():raise ValueError('Canonical retained acquisition differs')
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True));selected=source.xpath('/ThML/ThML.body/div1[@id="iv"]')[0]
    ids=['i-p15','i-p16','ii-p5','ii-p6','ii-p8','iii-p11','iii-p12','iii-p20','iii-p23','iii-p25']
    literals={id:''.join(source.xpath('//*[@id=$id]',id=id)[0].itertext()) for id in ids}
    author=source.xpath('.//DC.Creator[@sub="Author"]')[0].text
    volume=source.find('.//DC.Title').text
    profile=dict(contract='ocd-first-corinthians-complete-collection-profile-v1',work_id=WORK_ID,title=TITLE,scope=SCOPE,
        source_path=SOURCE.as_posix(),source_sha256=SOURCE_SHA,source_url='https://www.ccel.org/ccel/schaff/npnf112.xml',source_root_id='iv',source_title=selected.get('title'),source_root_c14n_sha256=sha256(etree.tostring(selected,method='c14n')).hexdigest(),elements=5008,original_global_ordinal_offset=preflight['original_global_ordinal_offset'],
        author=author,volume_title=volume,print_source=''.join(source.find('ThML.head/printSourceInfo').itertext()),
        contributors=[dict(name='Hubert Kestell Cornish',role='translator'),dict(name='John Medley',role='translator'),dict(name='Talbot W. Chambers',role='reviser and annotator'),dict(name='Philip Schaff',role='volume editor')],
        context_literals=literals,historical_review=preflight['historical_review'],
        acquisition_path=ACQUISITION.as_posix(),acquisition_sha256=sha256(io_path(ROOT/ACQUISITION).read_bytes()).hexdigest(),work_sha256=sha256(io_path(ROOT/WORK/'work.json').read_bytes()).hexdigest(),
        rights_statement='The retained electronic header states Public Domain. Sourced via CCEL.org. Retained permission permits parsing ThML/XML for text; do not sell CCEL files or derivatives of CCEL formatting. Human acceptance, print comparison, independent rights clearance and publication remain separate.')
    if 'Hubert Kestell Cornish' not in literals['iii-p11'] or 'John Medley' not in literals['iii-p11'] or 'TALBOT W. CHAMBERS' not in literals['ii-p8'] or 'Philip Schaff' not in raw.decode():raise ValueError('Exact primary contributors absent')
    put(BASE/'profile.json',canonical(profile));put(BASE/'boundary-review.json',canonical(preflight))
    closure=['build/tei/first_corinthians_collection_oracle.py','build/tei/npnf_chrysostom_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/tei/validate.py']
    policy=dict(contract='ocd-first-corinthians-complete-collection-policy-v1',closure_inputs=closure,scope=SCOPE,shared_assumptions=['Historical source boundary exposed; source parser lxml shared; original independent checker does not import producer. Stdlib second parser compares complete literal source ledger.'],preserved_numbering='All 44 native homily divisions retained literally, Homily I through XLIV. No missing content inferred or filled.')
    put(BASE/'validation-policy.json',canonical(policy))
    note=('# First Corinthians collection source and data credits\n\n'+SCOPE+'\n\nSourced via CCEL.org. The retained shared preface credits Hubert Kestell Cornish and John Medley for the First Epistle translation; volume title page credits Talbot W. Chambers for revision with additional notes. Philip Schaff is the volume editor. Retained electronic print statement: Edinburgh: T&T Clark, 1889; title-page statements remain retained context. The provider states Public Domain. CCEL permits parsing ThML/XML for text; do not sell CCEL files or derivatives of their formatting. Carry visible credits and restrictions to `data/structured-text/chrysostom-homilies-on-1-corinthians/README.md`. Human review, print equivalence, final rights and publication remain separate.\n').encode()
    put(BASE/'README.source.md',note)
    refs=[('retained-thml',SOURCE,'primary-source'),('reconstruction-profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('boundary-review',BASE/'boundary-review.json','exact-source-historical-reconciliation'),('source-readme',BASE/'README.source.md','source-credit-direction'),('canonical-acquisition',ACQUISITION,'canonical-acquisition'),('historical-content','reports/_logs/chrysostom-romans-reconciliation-20261001-v1/historical-package/content.tei.xml','reviewed-historical-body-authority'),('historical-package','reports/_logs/chrysostom-romans-reconciliation-20261001-v1/historical-package/manifest.json','historical-package-identity'),('legacy-mapper','build/tei/npnf_chrysostom_reconstruction.py','unchanged-reviewed-source-mapper'),('legacy-oracle','build/tei/npnf_chrysostom_oracle.py','independent-original-source-rules'),('ccel-permission','docs/sources/ccel-permission.md','retained-permission-evidence'),('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')]
    from build.tei import first_corinthians_collection_reconstruction as p,first_corinthians_collection_oracle as o
    manifest=dict(contract='ocd-source-manifest-v1',source_id=WORK_ID+'-complete-collection-v1',authorities=[binding(*r) for r in refs],converter=dict(id=p.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/first_corinthians_collection_reconstruction.py',implementation_sha256=sha256(Path(p.__file__).read_bytes()).hexdigest()),validator=dict(id=o.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/first_corinthians_collection_oracle.py',implementation_sha256=sha256(Path(o.__file__).read_bytes()).hexdigest(),import_closure_sha256=sha256(canonical([dict(path=path,sha256=sha256((ROOT/path).read_bytes()).hexdigest()) for path in closure])).hexdigest()),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
    put(BASE/'source-manifest.json',canonical(manifest));print(json.dumps(dict(status='prepared',elements=5008,original_global_ordinal_offset=preflight['original_global_ordinal_offset'],homilies=44)))
if __name__=='__main__':main()
