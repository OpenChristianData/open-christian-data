"""Bind the complete retained Hodge volume without altering historical evidence."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import etree
from build.tei import hodge_vol1_complete_reconstruction as producer,hodge_vol1_complete_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='hodge-systematic-theology-vol-1'
FORM_ID=WORK_ID+'-english'
EDITION_ID=WORK_ID+'-retained-electronic-witness'
ACQUISITION_ID=WORK_ID+'-retained-source'
WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/prose')/WORK_ID
LOG=Path('reports/_logs/hodge-vol1-current-reconciliation-20261002-v1')
SOURCE=Path('raw/ccel/hodge/theology1.xml')
SOURCE_SHA=producer.SOURCE_SHA
TITLE='Systematic Theology, Vol. 1'
SCOPE=('Complete retained CCEL theology1.xml volume I: all five ordered source roots i Title, ii Prefatory '
       '(CARD acknowledgment and full contents), iii Introduction, iv Part I. Theology Proper., and v Indexes '
       '(all seven fully rendered indexes). All 10,898 body descendants plus the body carrier, 594 source cells '
       '(553 td and 41 th), 57 literal row spans, 42 column spans, 263 table rows, 2,165 index links, seven source index '
       'markers, 610 notes, 659 page markers and 624 scripture references are conserved. The retained source head '
       'and two ordered prolog comments are private source evidence. The historical Introduction and Theology Proper '
       'remain unchanged after stripping only eight new source-backed cell annotations. Two explicit grammar wrappers '
       'preserve source sibling order. Source hrefs and queries remain literal in reversible annotations/accounting; '
       'internal target fragments rebase through an independently checked source-ID/TEI-ID crosswalk. No corrected '
       'reading, new work identity, print collation, source download or rights/publication claim.')
canonical=producer.canonical

def put(path,raw):
    target=io_path(ROOT/path);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)

def binding(name,path,role):
    raw=io_path(ROOT/Path(path)).read_bytes()
    return {'name':name,'path':Path(path).as_posix(),'role':role,'bytes':len(raw),'sha256':sha256(raw).hexdigest()}

def main():
    acquisition=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if len(acquisition['retained_files'])!=1 or acquisition['retained_files'][0]['sha256']!=SOURCE_SHA:
        raise ValueError('Hodge source acquisition member identity differs')
    historical=LOG/'historical-package'
    candidate,account=producer.build(io_path(ROOT/SOURCE).read_bytes(),io_path(ROOT/historical/'content.tei.xml').read_bytes(),io_path(ROOT/historical/'source-accountability.json').read_bytes())
    source_facts=checker.inspect(io_path(ROOT/SOURCE).read_bytes(),candidate,account,io_path(ROOT/historical/'content.tei.xml').read_bytes())
    questions=[{'id':'rights-human-print-publication','status':'unresolved','evidence':'Physical print collation, human acceptance, rights clearance and public publication remain separate.'}]
    profile={'work_id':WORK_ID,'source_sha256':SOURCE_SHA,'scope':SCOPE,'accounting':json.loads(account),
             'header_xml':etree.tostring(producer.parse(candidate).getroot().find(producer.NS+'teiHeader'),encoding='unicode'),
             'questions':questions,'source_facts':source_facts}
    put(BASE/'profile.json',canonical(profile))
    put(BASE/'validation-policy.json',canonical({'work_id':WORK_ID,'scope':SCOPE,'rules':['complete source-native five-root tree; exact ordered source attributes, text and tails','all table/header/span/layout roles explicit','literal href and resolved-target crosswalk','historical sound-body inverse conservation','source header/prolog metadata evidence','qualified own primary credits and P5','fresh process replay and meaningful mutations'],'projection_profile':producer.PROFILE}))
    visible=('# Hodge, Systematic Theology, volume I: source credit\n\n'
             'Sourced via [CCEL.org](https://www.ccel.org/ccel/hodge/theology1.html). Charles Hodge is the author; '
             'the electronic publisher is Grand Rapids, MI: Christian Classics Ethereal Library. The retained electronic '
             'header records creation on June 20, 2005. Tim Perrine is credited only for the CCEL Staff Writer description, '
             'not as editor, translator or transcriber of this volume.\n\n'
             'The retained title pages name WM. B. EERDMANS PUBLISHING CO., GRAND RAPIDS, MICH., 1940, and separately '
             'state an 1871 copyright entry by CHARLES SCRIBNER AND COMPANY. These are retained electronic witness '
             'descriptions, not independent physical print collation. An inherited local 1872–1873 edition claim remains '
             'distinct and unverified.\n\n'
             'The complete retained volume includes its title pages, prefatory CARD and contents table, Introduction, '
             'Theology Proper and seven rendered indexes. Notes, page markers, all three tables and all 57 row spans '
             'are preserved. Index link fragments have a checked correspondence to the source targets; the original '
             'hrefs and queries remain recorded without claiming independent link navigation or additional source retrieval.\n\n'
             'The source DC.Rights field is empty; no license is inferred from that absence. Its prolog states '
             'Copyright Christian Classics Ethereal Library. Retained CCEL permission evidence permits parsing ThML/XML '
             'for text, reserves rights in its files and formatting, prohibits selling CCEL files or derivatives of '
             'their formatting, and requests publication credit. Human textual acceptance, print equivalence, independent '
             'rights clearance and public publication remain separate.\n')
    notice=Path('data/prose')/WORK_ID/'README.md'
    put(BASE/'README.source.md',(visible+'\nCarry this visible source credit to `'+notice.as_posix()+'`.\n').encode())
    put(notice,visible.encode())
    authorities=[('primary-source',SOURCE,'primary-source'),('historical-candidate',historical/'content.tei.xml','retained-valid-body-evidence'),
                 ('historical-accounting',historical/'source-accountability.json','historical-source-correspondence'),
                 ('profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),
                 ('source-readme',BASE/'README.source.md','source-attribution'),('canonical-acquisition',ACQUISITION,'retained-source-identity'),
                 ('ccel-permission',Path('docs/sources/ccel-permission.md'),'source-permission-evidence'),
                 ('tei-p5-xsd',Path('ocd_kernel/tei/vendor/xsd/tei_all.xsd'),'tei-validation-schema'),
                 ('candidate-package-schema',Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'),'candidate-package-schema')]
    manifest={'contract':'ocd-source-manifest-v1','source_id':'ccel-hodge-theology1-complete-current-v1','work_id':WORK_ID,
              'textual_form_id':FORM_ID,'edition_id':EDITION_ID,'acquisition_id':ACQUISITION_ID,'scope':SCOPE,
              'authorities':[binding(*a) for a in authorities],
              'converter':{'id':producer.CONVERTER_ID,'version':'1','callable':'_convert','implementation_path':'build/tei/hodge_vol1_complete_reconstruction.py','implementation_sha256':sha256(Path(producer.__file__).read_bytes()).hexdigest()},
              'validator':{'id':checker.ORACLE_ID,'version':'1','callable':'_oracle','implementation_path':'build/tei/hodge_vol1_complete_oracle.py','implementation_sha256':sha256(Path(checker.__file__).read_bytes()).hexdigest(),'import_closure_sha256':checker.closure_sha(ROOT)},
              'package_schema':{'path':'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','sha256':sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()}}
    put(BASE/'source-manifest.json',canonical(manifest))
    print(json.dumps({'status':'prepared','complete_source_elements':10943,'candidate_sha256':sha256(candidate).hexdigest(),'source_facts':source_facts}))

if __name__=='__main__':main()
