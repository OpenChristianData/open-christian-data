"""Bind the complete retained Hilary collection and exact native contributor evidence."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import etree
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='hilary-of-poitiers-select-works'
FORM_ID=WORK_ID+'-ccel-npnf209-retained-en'
EDITION_ID=WORK_ID+'-ccel-npnf209-electronic'
ACQUISITION_ID=WORK_ID+'-ccel-npnf209-acquired'
WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/manifest-acquisitions/hilary-select-works-collection-npnf209')
SOURCE=Path('raw/ccel/npnf2/npnf209.xml')
SOURCE_SHA='b07e2fac0851444a42d2bbd11d39eb7384c518f6fd79e64b7f7bdc404e8a3cc7'
TITLE=ORIGINAL_TITLE='Select Works'
SCOPE='Complete retained CCEL NPNF2-09 ThML.body direct div1 ii: the source title page explicitly names St. Hilary of Poitiers, Select Works. The entire collection retains its initial page break and six ordered constituent divisions: Title Page ii.i, Preface ii.ii, Introduction ii.iii, De Synodis or On the Councils ii.iv, De Trinitate or On the Trinity ii.v, and Homilies on Psalms I., LIII., CXXX. ii.vi. Preserve all literal headings, wording, annotations, references, pages, language/style attributes, text/tails and hierarchy. Source-defined selected Psalms do not assert a complete Psalms corpus. Series title i, neighboring John of Damascus iii and indexes iv remain outside this one complete collection as retained context. No individual treatise work identities. Electronic completeness is distinct from print equivalence.'
PREFLIGHT=Path('reports/_logs/hilary-select-works-reconciliation-20261001-v1')
HISTORICAL=PREFLIGHT/'historical-package'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def put(path,b):
    q=io_path(ROOT/path);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def binding(name,path,role):
    b=io_path(ROOT/path).read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
    preflight=json.loads(io_path(ROOT/PREFLIGHT/'source-preflight.json').read_bytes())
    raw=io_path(ROOT/SOURCE).read_bytes();acq=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if sha256(raw).hexdigest()!=SOURCE_SHA or acq['source_sha256']!=SOURCE_SHA or acq['source_path']!=SOURCE.as_posix():raise ValueError('Canonical retained acquisition differs')
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True));selected=source.xpath('/ThML/ThML.body/div1[@id="ii"]')[0]
    literals=dict(preflight['literal_primary_credits'])
    for id in ('ii.i-p3','ii.i-p4','ii.i-p10','ii.i-p11'):
        literals[id]=''.join(source.xpath('//*[@id=$id]',id=id)[0].itertext())
    for id,literal in literals.items():
        if ''.join(source.xpath('//*[@id=$id]',id=id)[0].itertext())!=literal:raise ValueError('Exact primary credit drift '+id)
    if literals['ii.i-p2']!='Select Works.' or 'St. Hilary' not in literals['ii.i-p1']:raise ValueError('Literal collection identity absent')
    profile=dict(contract='ocd-hilary-select-works-complete-collection-profile-v1',work_id=WORK_ID,title=TITLE,scope=SCOPE,source_path=SOURCE.as_posix(),source_sha256=SOURCE_SHA,source_url='https://www.ccel.org/ccel/schaff/npnf209.xml',source_root_id='ii',source_title=selected.get('title'),source_root_c14n_sha256=sha256(etree.tostring(selected,method='c14n')).hexdigest(),elements=8156,original_global_ordinal_offset=19031,author='Hilary of Poitiers',volume_title=source.find('.//DC.Title').text,print_source=''.join(source.find('ThML.head/printSourceInfo').itertext()),contributors=[dict(name='E. W. Watson',role='Introduction author; translator of De Trinitate Books I–VII'),dict(name='L. Pullan',role='translator of De Synodis'),dict(name='E. N. Bennett',role='translator of De Trinitate Books VIII and XII'),dict(name='S. C. Gayford',role='translator of De Trinitate Books IX–XI'),dict(name='H. F. Stewart',role='translator of the selected Psalms; compiler of the separately retained double Index'),dict(name='W. Sanday',role='collection editor and Preface author'),dict(name='Philip Schaff',role='series editor'),dict(name='Henry Wace',role='series editor')],context_literals=literals,historical_review=preflight['historical_review'],print_year_discrepancy='Electronic print statement 1898; inherited canonical source citation 1899. Both retained, no metadata correction.',acquisition_path=ACQUISITION.as_posix(),acquisition_sha256=sha256(io_path(ROOT/ACQUISITION).read_bytes()).hexdigest(),work_sha256=sha256(io_path(ROOT/WORK/'work.json').read_bytes()).hexdigest(),rights_statement='The retained electronic header states Public Domain. Sourced via CCEL.org. Retained permission permits parsing ThML/XML for text; do not sell CCEL files or derivatives of CCEL formatting. Human acceptance, print comparison, independent rights clearance and publication remain separate.')
    put(BASE/'profile.json',canonical(profile));put(BASE/'boundary-review.json',canonical(preflight))
    closure=['build/tei/hilary_select_works_collection_oracle.py','build/tei/npnf2_lib048_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/tei/validate.py']
    policy=dict(contract='ocd-hilary-select-works-complete-collection-policy-v1',closure_inputs=closure,scope=SCOPE,shared_assumptions=['Historical source boundary exposed; lxml parser shared. Independent LIB048 checker does not import producer. Stdlib second parser compares complete literal source ledger.'],original_ids='Exact original global ordinal prefix starting 19032, every selected source node; no normalization.',references='Literal retained source passage/osisRef; no Hilary neutral reference exceptions in reviewed policy.')
    put(BASE/'validation-policy.json',canonical(policy))
    note=('# Hilary Select Works source and data credits\n\n'+SCOPE+'\n\nSourced via CCEL.org. Native title page credits E. W. Watson, L. Pullan, and Others as translators, and W. Sanday as editor. The Preface specifically assigns the Introduction and De Trinitate I–VII to Watson, De Synodis to Pullan, De Trinitate VIII and XII to E. N. Bennett, IX–XI to S. C. Gayford, and selected Psalms to H. F. Stewart; Stewart also compiled the separately retained double Index. Sanday edited and signed the Preface; Philip Schaff and Henry Wace edited the series. Electronic print statement: Edinburgh: T&T Clark, 1898; inherited source citation says 1899. Preserve both pending print review. Provider states Public Domain. CCEL permits parsing ThML/XML for text; do not sell CCEL files or derivatives of their formatting. Carry these visible credits and restrictions to `data/structured-text/hilary-of-poitiers-select-works/README.md`. Human acceptance, print equivalence, independent rights clearance and publication remain separate.\n').encode()
    put(BASE/'README.source.md',note)
    refs=[('retained-thml',SOURCE,'primary-source'),('reconstruction-profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('boundary-review',BASE/'boundary-review.json','exact-source-historical-reconciliation'),('source-readme',BASE/'README.source.md','source-credit-direction'),('canonical-acquisition',ACQUISITION,'canonical-acquisition'),('historical-content',HISTORICAL/'content.tei.xml','reviewed-historical-body-authority'),('historical-package',HISTORICAL/'manifest.json','historical-package-identity'),('historical-accounting',HISTORICAL/'source-accountability.json','historical-global-ordinal-authority'),('legacy-mapper','build/tei/npnf2_lib048_reconstruction.py','unchanged-reviewed-source-mapper'),('legacy-oracle','build/tei/npnf2_lib048_oracle.py','independent-original-source-rules'),('legacy-policy','sources/structured-text/npnf2-lib048/npnf2-lib048.validation-policy.json','original-source-attribute-rules'),('ccel-permission','docs/sources/ccel-permission.md','retained-permission-evidence'),('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')]
    from build.tei import hilary_select_works_collection_reconstruction as p,hilary_select_works_collection_oracle as o
    manifest=dict(contract='ocd-source-manifest-v1',source_id=WORK_ID+'-complete-collection-v1',authorities=[binding(*r) for r in refs],converter=dict(id=p.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/hilary_select_works_collection_reconstruction.py',implementation_sha256=sha256(Path(p.__file__).read_bytes()).hexdigest()),validator=dict(id=o.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/hilary_select_works_collection_oracle.py',implementation_sha256=sha256(Path(o.__file__).read_bytes()).hexdigest(),import_closure_sha256=sha256(canonical([dict(path=path,sha256=sha256((ROOT/path).read_bytes()).hexdigest()) for path in closure])).hexdigest()),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
    put(BASE/'source-manifest.json',canonical(manifest));print(json.dumps(dict(status='prepared',elements=8156,original_global_ordinal_offset=19031,constituent_divisions=6)))
if __name__=='__main__':main()
