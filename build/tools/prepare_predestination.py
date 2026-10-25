"""Bind the complete retained two-book Predestination work, excluding siblings."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from build.tei import npnf105_reconstruction as family

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='augustine-predestination-of-saints'
FORM_ID=WORK_ID+'-ccel-npnf105-retained-en'
EDITION_ID=WORK_ID+'-ccel-npnf105-electronic'
ACQUISITION_ID=WORK_ID+'-ccel-npnf105-acquired'
WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/manifest-acquisitions/predestination-npnf105')
SOURCE=Path('raw/ccel/npnf1/npnf105.xml')
SOURCE_SHA=family.SOURCE_SHA256
TITLE=ORIGINAL_TITLE='A Treatise on the Predestination of the Saints'
SCOPE='Complete retained NPNF1-05 CCEL ThML div1 xxi: A Treatise on the Predestination of the Saints, including its title page xxi.i, Book I xxi.ii (43 chapters), and Book II xxi.iii (title page, introduction and 68 chapters), separately titled A Treatise on the Gift of Perseverance. Native first/second-book identity statements and alternate-title note preserved. The disputed shared Contents statement One Book remains outside-work context, explicitly accounted without correction. Shared volume front matter, credits, contents, sibling works, and indexes remain outside this complete work edition.'
def canonical(v): return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def put(p,b):
    q=io_path(ROOT/p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def binding(name,path,role):
    b=io_path(ROOT/path).read_bytes();return dict(name=name,path=Path(path).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
    roster=json.loads((ROOT/'plans/2026-09-22-source-preflight/whole-library-handoff-inventory-20260926.json').read_bytes())
    rows=[w for w in roster['works'] if w['work_id']==WORK_ID and w['handoff_group']=='declared-edition']
    if len(rows)!=1:raise ValueError('fixed755 membership differs')
    acq=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if acq['source_sha256']!=SOURCE_SHA or acq['source_path']!=SOURCE.as_posix():raise ValueError('retained acquisition differs')
    raw=(ROOT/SOURCE).read_bytes()
    if sha256(raw).hexdigest()!=SOURCE_SHA:raise ValueError('retained source drift')
    t=family._parse(ROOT/SOURCE);divs=family._source_divisions(t);e=divs[20]
    work=json.loads(io_path(ROOT/WORK/'work.json').read_bytes())
    if work['title']!=TITLE or work['textual_forms'][0]['editions'][0]['containing_source']['locator']!=SOURCE.as_posix()+'#xxi':raise ValueError('canonical identity/locator differs')
    evidence_ids=['xxi.ii-p3','xxi.iii.ii','iii-p70','iii-p71','iii-p74','ix-p14','ii-p9','ii-p10']
    literals={id:''.join(t.xpath('//*[@id=$id]',id=id)[0].itertext()) for id in evidence_ids}
    # The exact complete selected opening is stronger than a guessed paragraph ID.
    boundary=dict(scope=SCOPE,source_sha256=SOURCE_SHA,selected='ThML.body/div1[@id="xxi"]',selected_attributes=dict(e.attrib),children=[dict(id=c.get('id'),attributes=dict(c.attrib),elements=sum(isinstance(n.tag,str) for n in c.iter()),comments=sum(not isinstance(n.tag,str) for n in c.iter()),chapters=[n.get('id') for n in c.iter('div3')]) for c in e],book_openings={c.get('id'):''.join(c.itertext())[:2200] for c in e},context_literals=literals,decision='Coordinator /root: proceed with source-defined complete two-book work, no separate work from nested Book II title; contents count discrepancy retained as context.')
    put(BASE/'boundary-review.json',canonical(boundary))
    count=sum(isinstance(n.tag,str) for n in e.iter())
    offset=sum(sum(isinstance(n.tag,str) for n in d.iter()) for d in divs[9:20])
    profile=dict(contract='ocd-npnf105-work-profile-v1',work_id=WORK_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,acquisition_path=ACQUISITION.as_posix(),acquisition_sha256=sha256(io_path(ROOT/ACQUISITION).read_bytes()).hexdigest(),work_sha256=sha256(io_path(ROOT/WORK/'work.json').read_bytes()).hexdigest(),div1_id='xxi',source_title=e.get('title'),feature_offset=offset,feature_count=count,source_div1_c14n_sha256=sha256(etree.tostring(e,method='c14n')).hexdigest(),translator='Robert Ernest Wallis',translator_evidence_id='ix-p14',scope=SCOPE,boundary=boundary,independence='Unchanged work producer uses aggregate mapper; independent work checker uses separate aggregate source rules, not producer mapping. Work-local accounting checker independently traverses stdlib ElementTree source with comments. Prior source/body exposure disclosed; no blind-review claim.')
    put(BASE/'profile.json',canonical(profile))
    closure=['build/tei/predestination_oracle.py','build/tei/npnf105_work_oracle.py','build/tei/npnf105_oracle.py','ocd_kernel/reconstruction/contract.py']
    policy=dict(contract='ocd-npnf105-work-policy-v1',credit_evidence_ids=['ix-p14','iii-p70','iii-p74'],closure_inputs=closure,scope=SCOPE)
    put(BASE/'validation-policy.json',canonical(policy))
    note=('# On the Predestination of the Saints: retained two-book work\n\nComplete CCEL NPNF1-05 div1 xxi, including title page, Book I and Book II On the Gift of Perseverance. Native explanatory book identity and alternate-title notes are retained. The outside contents entry says One Book; this discrepancy is preserved as context, without rewriting either reading. Shared volume matter and siblings excluded.\n\nTranslator Robert Ernest Wallis (retained preface ix-p14); Philip Schaff volume editor; Benjamin B. Warfield translation reviser and introduction author (retained volume credits). Sourced via CCEL.org. Retained header states Public Domain; CCEL permission evidence permits ThML parsing and says not to sell CCEL files or derivatives of its formatting. Carry visible credits and restrictions to `data/structured-text/augustine-predestination-of-saints/README.md`. Human/visual review, print equivalence, final rights and publication remain separate.\n').encode()
    put(BASE/'README.source.md',note)
    refs=[('retained-thml',SOURCE,'primary-source'),('reconstruction-profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('boundary-review',BASE/'boundary-review.json','literal-boundary-evidence'),('source-readme',BASE/'README.source.md','source-attribution-readme'),('canonical-acquisition',ACQUISITION,'canonical-acquisition-evidence'),('work-converter','build/tei/npnf105_work_reconstruction.py','reused-source-mapper'),('aggregate-mapper','build/tei/npnf105_reconstruction.py','reused-source-mapper'),('work-oracle','build/tei/npnf105_work_oracle.py','independent-source-checker'),('aggregate-oracle','build/tei/npnf105_oracle.py','independent-source-rules'),('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')]
    from build.tei import predestination_reconstruction as p, predestination_oracle as o
    manifest=dict(contract='ocd-source-manifest-v1',source_id=WORK_ID+'-npnf105-two-book-v1',authorities=[binding(*r) for r in refs],converter=dict(id=p.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/predestination_reconstruction.py',implementation_sha256=sha256(Path(p.__file__).read_bytes()).hexdigest()),validator=dict(id=o.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/predestination_oracle.py',implementation_sha256=sha256(Path(o.__file__).read_bytes()).hexdigest(),import_closure_sha256=sha256(canonical([dict(path=path,sha256=sha256((ROOT/path).read_bytes()).hexdigest()) for path in closure])).hexdigest()),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
    put(BASE/'source-manifest.json',canonical(manifest));print(json.dumps(dict(status='prepared',feature_count=count,comments=2,source_manifest_sha256=sha256(canonical(manifest)).hexdigest())))
if __name__=='__main__':main()
