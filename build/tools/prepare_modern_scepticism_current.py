"""Renew exact PG42957 handoff bindings without regenerating source text."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import etree
from build.tei import modern_scepticism_current_reconstruction as producer,modern_scepticism_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='modern-scepticism-christian-evidence-society-1871'
FORM_ID=WORK_ID+'-gutenberg-retained-en'
EDITION_ID=WORK_ID+'-gutenberg-electronic'
ACQUISITION_ID=EDITION_ID+'-acquired'
WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/prose')/WORK_ID
LOG=Path('reports/_logs/modern-scepticism-current-reconciliation-20261002-v1')
SOURCE=Path('raw/clean-ready-acquisition-to-tei/master-4/28')/WORK_ID/'42957-h.htm'
SOURCE_SHA=checker.SOURCE_SHA
TITLE='Modern Scepticism: A Course of Lectures Delivered at the Request of the Christian Evidence Society'
SCOPE=('Complete retained Project Gutenberg 42957 legacy XHTML body, one titled 1871 volume: '
       'four front units (provider start marker, title page, Harrowby preface and contents), eleven lectures '
       'and one explanatory paper, four back units (181 footnotes, notes/printer, transcriber notes and provider end marker). '
       'All 526 source page labels, 362 note links, 26 contents rows/40 cells, poetry/Greek/inline readings and source order '
       'are conserved. Only 59 generated carrier aliases are reversibly adapted to supported native grammar; '
       'no wording or source IDs are changed. Primary legacy body is distinct from retained current supporting witnesses '
       'and ZIP/cover; full retained PG license and production credits are carried visibly as support-source terms. '
       'No physical print collation, worldwide rights clearance, human acceptance or public publication claim.')
canonical=producer.canonical

def put(path,raw):
    p=io_path(ROOT/path);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
def binding(name,path,role):
    raw=io_path(ROOT/Path(path)).read_bytes()
    return {'name':name,'path':Path(path).as_posix(),'role':role,'bytes':len(raw),'sha256':sha256(raw).hexdigest()}

def main():
    acquisition=validate_acquisition(io_path(ROOT/ACQUISITION),root=ROOT)
    if len(acquisition['retained_files'])!=2 or acquisition['source_sha256']!=SOURCE_SHA:raise ValueError('Exact existing source acquisition differs')
    historical=LOG/'historical-package/baseline/package'
    raw,counts=producer.build(io_path(ROOT/historical/'content.tei.xml').read_bytes())
    root=producer.parse(raw);header=root.find(producer.NS+'teiHeader')
    ts=header.find(producer.NS+'fileDesc/'+producer.NS+'titleStmt')
    resp=etree.SubElement(ts,producer.NS+'respStmt');etree.SubElement(resp,producer.NS+'resp').text='Electronic production, as credited in retained pg42957.txt support witness'
    etree.SubElement(resp,producer.NS+'name').text='Charlene Taylor, Marilynda Fraser-Cunliffe, Charlie Howard, and the Online Distributed Proofreading Team'
    bibl=header.find(producer.NS+'fileDesc/'+producer.NS+'sourceDesc/'+producer.NS+'bibl')
    etree.SubElement(bibl,producer.NS+'note',type='source-scope-qualification').text=SCOPE
    etree.SubElement(bibl,producer.NS+'note',type='primary-role-qualification').text=('The title page identifies the Christian Evidence Society as requester, not aggregate author; '
       'eleven named lecturers and C. J. Ellicott\'s explanatory paper form the complete volume. HARROWBY signs the preface as Chairman of Committee. '
       'The retained title page gives New York: Anson D. F. Randolph and Co., 770 Broadway, MDCCCLXXI, issued by special arrangement '
       'with Hodder and Stoughton. This electronic witness description is not physical print collation. '
       'The current corroborating PG text is separately updated October 23, 2024; it does not replace the legacy text or its source title/spelling.')
    etree.SubElement(bibl,producer.NS+'note',type='rights-qualification').text=('Project Gutenberg identifies the work as public domain in the United States. '
       'Full retained provider license terms and credited electronic producers accompany the visible data/source notices. '
       'Worldwide rights clearance, human verification and public publication are not recorded.')
    raw=etree.tostring(root,encoding='UTF-8',xml_declaration=True)
    facts=checker.inspect(io_path(ROOT/SOURCE).read_bytes(),io_path(ROOT/historical/'content.tei.xml').read_bytes(),raw)
    put(LOG/'fresh-candidate.tei.xml',raw);put(LOG/'whole-text-inverse-proof.json',canonical(facts))
    put(LOG/'fresh-header.xml',etree.tostring(header,encoding='UTF-8',xml_declaration=True))
    old_manifest=json.loads((ROOT/'sources/manifest-acquisitions/pg42957-modern-scepticism/source-manifest.json').read_bytes())
    put(LOG/'historical-source-manifest.before.json',(ROOT/'sources/manifest-acquisitions/pg42957-modern-scepticism/source-manifest.json').read_bytes())
    support=io_path(ROOT/SOURCE.parent/'pg42957.txt').read_text(encoding='utf-8-sig')
    license_text=support[support.index('START: FULL LICENSE'):]
    if '1.E.1.' not in license_text or 'THE FULL PROJECT GUTENBERG' not in license_text:raise ValueError('Retained complete PG license not located')
    notice=Path('data/prose')/WORK_ID/'README.md'
    visible=('# Modern Scepticism: retained source and data credit\n\n'
       'Sourced from [Project Gutenberg ebook 42957](https://www.gutenberg.org/ebooks/42957), specifically '
       '[the retained legacy XHTML](https://www.gutenberg.org/files/42957/42957-h/42957-h.htm). '
       'This one complete electronic volume preserves its title pages, Harrowby preface, contents, eleven lectures, '
       'C. J. Ellicott\'s explanatory paper, 181 notes, printer line, transcriber interventions and provider start/end markers. '
       'The requesting Christian Evidence Society is not assigned aggregate authorship. The source names William Thomson, '
       'James H. Rigg, William Jackson, Robert Payne Smith, John Stoughton, Harvey Goodwin, George Rawlinson, '
       'Charles A. Row, Stanley Leathes, James R. Woodford and Frederick C. Cook as lecturers; HARROWBY signs '
       'the preface as Chairman of Committee.\n\n'
       'The title page records New York: Anson D. F. Randolph and Co., 770 Broadway, 1871 (MDCCCLXXI), '
       'issued by special arrangement with the English publishers Hodder and Stoughton. The legacy electronic release '
       'is dated June 16, 2013. These retained electronic descriptions are not independent print collation. '
       'The separate retained current pg42957.txt credits Charlene Taylor, Marilynda Fraser-Cunliffe, Charlie Howard '
       'and the Online Distributed Proofreading Team at [pgdp.net](https://www.pgdp.net), and records an October 23, 2024 '
       'update. Its spelling, metadata and license context are not substituted into the authored legacy body.\n\n'
       'The complete source-normalized text has 731,071 characters including all note bodies. The supported public '
       'projection has 20 ordered units and 674,384 plain-text characters; note bodies remain in structured note elements '
       'while the native route omits them from plain text and applies its own block/row whitespace. All four front and '
       'four back units remain included. These different normalization and note policies do not describe a narrower work scope.\n\n'
       'Eight retained files remain hash-bound: the primary legacy XHTML, legacy text, current HTML/text, ZIP, landing '
       'page and two indexes. Canonical acquisition lists the primary XHTML and ZIP; the ZIP/current witnesses and '
       'cover are support evidence, not duplicate textual members or an invented primary-body illustration. Source bytes '
       'are unchanged. The HTML head/CSS are retained source envelope context outside readable body accounting.\n\n'
       'Project Gutenberg identifies the work as public domain in the United States. Its source-directed developer and '
       'publisher terms are reproduced below from the complete retained current pg42957.txt witness. No worldwide '
       'rights clearance, human textual acceptance or public publication is recorded; this is private technical preparation.\n\n'
       '## Complete retained Project Gutenberg license\n\n'+license_text)
    put(BASE/'README.source.md',(visible+'\n\nCarry this complete visible source credit and provider terms to `'+notice.as_posix()+'`.\n').encode())
    put(notice,visible.encode())
    profile={'work_id':WORK_ID,'source_sha256':SOURCE_SHA,'scope':SCOPE,'alias_counts':counts,'source_facts':facts,
             'header_xml':etree.tostring(header,encoding='unicode'),'historical_source_proof_reused':True,
             'historical_mutations_reused':10,'source_manifest_drift':'Current dependency closure renewed; original source/profile/source-oracle bytes unchanged. Historical old-manifest success remains dated, not claimed current.',
             'count_qualification':'731071 complete source-normalized characters vs 674384 native plain text; structured notes and all20units retained.'}
    put(BASE/'profile.json',canonical(profile));put(BASE/'validation-policy.json',canonical({'scope':SCOPE,'alias_counts':counts,'rules':['exact complete historical text inverse','independently closed source-backed aliases','pinned renewed header and current package closure','retain old whole-source/replay/10mutation evidence without rerunning solely for dependency drift','qualified full visible PG credits/license','fresh alias replay and sensitivity']}))
    authorities=[('primary-source',SOURCE,'primary-source'),('historical-candidate',historical/'content.tei.xml','complete-native-body-evidence'),
        ('historical-accounting',historical/'source-accountability.json','historical-complete-source-accounting'),
        ('historical-unresolved',historical/'unresolved.jsonl','historical-qualified-unresolved'),
        ('profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),
        ('source-readme',BASE/'README.source.md','complete-visible-source-credit'),('canonical-acquisition',ACQUISITION,'retained-source-identity'),
        ('historical-source-profile',Path('sources/manifest-acquisitions/pg42957-modern-scepticism/profile.json'),'unchanged-source-native-profile'),
        ('historical-source-oracle',Path('build/tei/modern_scepticism_manifest_oracle.py'),'dated-source-oracle-evidence'),
        ('historical-closeout',Path('plans/2026-09-23-acquisition-manifest-source-to-TEI/evidence/L879_PG42957_MODERN_SCEPTICISM_TECHNICAL_CLOSEOUT_20261001.json'),'dated-whole-source-proof'),
        ('historical-mutations',LOG/'historical-mutation-receipt.json','dated-ten-whole-source-mutations'),
        ('historical-reconciliation',LOG/'retained-package-reconciliation.json','exact-latest-package-and-replay-proof'),
        ('tei-p5-xsd',Path('ocd_kernel/tei/vendor/xsd/tei_all.xsd'),'tei-validation-schema'),
        ('candidate-package-schema',Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'),'candidate-package-schema')]
    for a in old_manifest['authorities']:
        if a['role']=='retained-source-member':authorities.append(('support-'+a['name'],Path(a['path']),'retained-source-support'))
    authorities += [('project-instructions',Path('AGENTS.md'),'project-agent-instructions'),('source-to-tei-skill',Path('.agents/skills/source-to-tei/SKILL.md'),'active-source-to-tei-method'),('reconstruction-contract',Path('ocd_kernel/reconstruction/contract.py'),'current-dependency')]
    manifest={'contract':'ocd-source-manifest-v1','source_id':'pg42957-complete-native-current-v1','work_id':WORK_ID,'textual_form_id':FORM_ID,'edition_id':EDITION_ID,'acquisition_id':ACQUISITION_ID,'scope':SCOPE,'authorities':[binding(*a) for a in authorities],
       'converter':{'id':producer.CONVERTER_ID,'version':'1','callable':'_convert','implementation_path':'build/tei/modern_scepticism_current_reconstruction.py','implementation_sha256':sha256(Path(producer.__file__).read_bytes()).hexdigest()},
       'validator':{'id':checker.ORACLE_ID,'version':'1','callable':'_oracle','implementation_path':'build/tei/modern_scepticism_current_oracle.py','implementation_sha256':sha256(Path(checker.__file__).read_bytes()).hexdigest(),'import_closure_sha256':checker.closure_sha(ROOT)},
       'package_schema':{'path':'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','sha256':sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()}}
    put(BASE/'source-manifest.json',canonical(manifest))
    print(json.dumps({'status':'prepared','candidate_sha256':sha256(raw).hexdigest(),'aliases':counts,'whole_text_inverse':True,'source_normalized_characters':facts['source_normalized_characters']}))

if __name__=='__main__':main()
