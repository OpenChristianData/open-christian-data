"""Prepare L811-only reviewable source contracts; no candidate generation here.

The oracle exports only the exact authority-layout declaration for this builder.
All inventory values below are separately read from the retained raw XML, not
from producer accounting or the oracle's source comparison implementation.
Runtime remains explicitly noninstallable and fail-closed until actual capture.
"""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json,sys
from lxml import etree

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
HOME='sources/manifest-acquisitions/eusebius-l811-retained-install-20261004-v1'
LOG='reports/_logs/eusebius-l811-existing-install-20261004-v1'
WORK='eusebius-commentarii-in-psalmos';EDITION='pta-ef861ab3-commentarii-psalmos'
SOURCE='pta-l811-retained-three-tome-repair-ef861ab3-v1';COMMIT='ef861ab391ea35c5d85b41dd8d7ba2bf65530b21'
PRODUCER='build/tei/eusebius_l811_retained_repair.py';ORACLE='build/tei/eusebius_l811_source_oracle.py'
NS='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}'
TOMES=['I','II','III'];NAMES=['manifest.json','content.tei.xml','provenance.json','source-accountability.json','README.source.md','unresolved.jsonl']

def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha(v):return sha256(v).hexdigest()
def pin(path):
    b=(ROOT/path).read_bytes();return dict(path=path,bytes=len(b),sha256=sha(b))
def fresh(path,payload):
    p=ROOT/path
    if p.exists():raise FileExistsError('Preserve existing L811 evidence: '+str(p))
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(payload)
def kind(n):return n.tag if isinstance(n.tag,str) else '#comment' if n.tag==etree.Comment else '#processing-instruction'

def prepare():
    from build.tei.eusebius_l811_source_oracle import authority_spec
    spec=authority_spec()
    version=(ROOT/(LOG+'/scoped-source-version-proposal-v1.json')).read_bytes()
    if sha(version)!='8560c5f788f4251e63c6b14f65918c85e3eca491a610c098903a7eb20678902f':raise ValueError('Reviewed scoped row/source-version pin differs')
    scoped=json.loads(version);members=[];attribution=[]
    by_name={n:p for n,p,r in spec}
    for i,tome in enumerate(TOMES,1):
        raw=(ROOT/by_name['primary-source-tome-'+tome]).read_bytes()
        if sha(raw)!=scoped['source_members'][i-1]['source_sha256']:raise ValueError('Scoped primary source pin differs')
        t=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,recover=False))
        h=t.find(NS+'teiHeader');body=t.find(NS+'text/'+NS+'body');title=h.find(NS+'fileDesc/'+NS+'titleStmt/'+NS+'title')
        ids=[n.get(X+'id') for n in t.iter() if isinstance(n.tag,str) and n.get(X+'id')]
        ps=[int(n.get('n')[3:]) for n in body[1] if isinstance(n.tag,str) and n.get('n','').startswith('Ps_') and n.get('n')[3:].isdigit()]
        members.append(dict(source_authority='primary-source-tome-'+tome,receipt_authority='acquisition-receipt-tome-'+tome,position=i,tome=tome,source_sha256=sha(raw),source_bytes=len(raw),title=''.join(title.itertext()),source_root_language=t.get(X+'lang'),preface_language=body[0].get(X+'lang'),edition_language=body[1].get(X+'lang'),source_revision_status=h.find(NS+'revisionDesc').get('status'),psalm_numbers=ps,source_ids=len(ids),source_body_nodes=sum(1 for _ in body.iter()),source_document_census=dict(sorted(Counter(kind(n).removeprefix(NS) for n in t.iter()).items())),source_uri_attributes=[dict(path=t.getroottree().getpath(n),attribute=k,value=v) for n in t.iter() if isinstance(n.tag,str) for k,v in n.attrib.items() if k in ('target','corresp','wit','ref','source','sameAs')],document_prefix=raw[:raw.index(b'<TEI')].decode(),document_suffix=raw[raw.rindex(b'</TEI>')+6:].decode()))
        attribution.append((ROOT/by_name['attribution-tome-'+tome]).read_bytes().decode().strip())
    order=dict(primary_members=['primary-source-tome-'+t for t in TOMES],complete_works=1,tome_order=TOMES,scope='All three complete retained XML documents; one titled work; complete source bodies and header children plus exact located wrapper/prolog administration; no source exclusions.')
    limitation='Complete retained three-tome digital edition, including all prefatory and supplementary matter. Tomes I/II are source-declared works in progress, not a claimed finished printed critical edition.'
    mapping='Historical ID and #fragment scoping, ordered header-child scope labels, and three source-body carriers; restore one exact witness trailing space and preserve omitted document wrappers/prologs as located typed-note paragraphs. No source wording changes.'
    profile=dict(contract='ocd-l811-retained-complete-source-profile-v1',work_id=WORK,edition_id=EDITION,source_id=SOURCE,complete_authored_works=1,members=members,source_order=order,original_package_members={n:dict(authority='original-'+n,bytes=pin(LOG+'/retained-original-package/'+n)['bytes'],sha256=pin(LOG+'/retained-original-package/'+n)['sha256']) for n in NAMES},authority_layout=[dict(name=n,path=p,role=r) for n,p,r in spec],scoped_source_version_sha256=sha(version),mapping=mapping,limitations=limitation)
    uri='Literal source reference values remain unchanged except already-declared #fragment ID scoping. Bare target identifiers and bibliographic corresp labels are not converted into fabricated HTTP links. The acquisition URL is the retained document context, not evidence that every ambiguous source target resolves.'
    converter=dict(id='ocd-l811-retained-composite-bounded-repair',version='3',callable='_convert',implementation_path=PRODUCER,implementation_sha256=pin(PRODUCER)['sha256'])
    provenance=dict(contract='ocd-l811-retained-composite-provenance-v1',work_id=WORK,edition_id=EDITION,source_id=SOURCE,manifest_row='L811',pinned_commit=COMMIT,source_scope=limitation,status='nonaccepted',human_acceptance='pending',rights_clearance='pending human review',publication='not-authorized',composite_producer=dict(historical_package_manifest_sha256=pin(LOG+'/retained-original-package/manifest.json')['sha256'],historical_tei_sha256=pin(LOG+'/retained-original-package/content.tei.xml')['sha256'],historical_producer_sha256=pin(by_name['historical-producer'])['sha256'],bounded_repair=converter,recipe='Retained original six-member package plus exact three raw tomes and acquisition receipts; supported reconstruct_candidate CLI with the work-local bounded repair. Historical converter is lineage, not the sole current producer.'),file_level_license=dict(name='Creative Commons Attribution-ShareAlike 4.0 International',target='https://creativecommons.org/licenses/by-sa/4.0/',authority='All three exact raw publicationStmt/availability/licence fields, retained in the readable header and original member attribution files.'),source_uri_disposition=uri)
    policy=dict(contract='ocd-l811-whole-object-validation-policy-v1',candidate_status='nonaccepted',provenance=provenance,unresolved=[dict(id='l811-source-draft-tomes',status='source-declared',detail='Tomes I/II retain source status draft and work-in-progress statements; III status approved. All retained digital content is included; no completed print-critical-edition claim.'),dict(id='l811-literal-ambiguous-references',status='source-declared',detail=uri),dict(id='l811-human-acceptance',status='unresolved',detail='No human verification or acceptance is implied by technical source proof.'),dict(id='l811-rights-review',status='unresolved',detail='CC BY-SA 4.0 source statements and attribution retained; broader rights clearance remains pending.'),dict(id='l811-publication',status='not-authorized',detail='No publication authorization recorded.')])
    readme='''# Eusebius Caesariensis: Commentarii in Psalmos\n\nThis work-local successor repairs the already retained PTA three-tome digital edition at commit ef861ab391ea35c5d85b41dd8d7ba2bf65530b21. One titled work contains all three ordered tomes, all source Psalms 1-150, German prefaces, supplementary Periochai and Hypotheseis, source notes and apparatus, and all copied header metadata. The Greek authored edition and German editorial prefaces remain distinct from root language en. The legacy path label pta-english is an opaque stable ID, not a claim of English translation.\n\nTomes I and II explicitly say Work in progress and retain revision status draft; Tome III retains status approved. Including all retained digital content does not establish a finished printed critical edition, print collation, or visual verification.\n\nThis is a bounded repair of the exact original six-member package. It restores one witness attribute trailing space at its exact raw-backed locus and adds three located source-document administration notes. Each typed note preserves source wrapper attributes, direct text/tails, namespace declarations, literal XML declaration/xml-model prolog and suffix, source quality statements, and exact retained acquisition URI context. The rest of the existing TEI remains byte-conserved under an independently checked whole-original inverse. That inverse alone does not prove newly added readable administration; actual fields are separately compared against all three raw sources.\n\nOriginal ID scoping prefixes each source ID by its tome. Literal targets that actually bind to a source XML ID retain the same scoped fragment and require closure. Source sigla without declared XML IDs, #xpath selectors, bare target identifiers, and bibliographic Field labels remain literal and explicitly qualified rather than silently given fabricated targets or network bases.\n\nThe retained source specifies Creative Commons Attribution-ShareAlike 4.0 International: https://creativecommons.org/licenses/by-sa/4.0/. Preserve PTA attribution and share-alike terms. Exact source-member credits and license notices follow below. Technical proof is not human verification, rights clearance, or acceptance; no publication authorization is recorded. The original package, all original five canonical files, and recovered byte-exact historical source authorities remain historical evidence. Current L811 row/source-version snapshots govern current scope; dated whole-file roster hashes are retained as historical context, not assertions about today's entire roster.\n\n'''
    readme+='\n\n---\n\n'.join(attribution)+'\n'
    fresh(HOME+'/scoped-source-version.json',version);fresh(HOME+'/profile.json',enc(profile));fresh(HOME+'/policy.json',enc(policy));fresh(HOME+'/README.source.md',readme.encode())
    fresh(HOME+'/runtime.json',enc(dict(contract='ocd-l811-observed-source-runtime-v1',status='capture-pending-noninstallable',first_party_files=[],external_runtime_files=[],runtime_executable=None)))
    manifest=dict(contract='ocd-source-manifest-v1',work_id=WORK,edition_id=EDITION,source_id=SOURCE,manifest_row='L811',source_order=order,authorities=[dict(name=n,role=r,**pin(p)) for n,p,r in spec],converter=converter,validator=dict(id='ocd-l811-whole-object-source-oracle',version='1',callable='_oracle',implementation_path=ORACLE,implementation_sha256=pin(ORACLE)['sha256'],import_closure_sha256=pin(HOME+'/runtime.json')['sha256']),package_schema={k:v for k,v in pin('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').items() if k!='bytes'})
    fresh(HOME+'/source-manifest.json',enc(manifest))
    proposal=dict(contract='ocd-l811-runtime-execution-proposal-v1',status='review-required-before-execution',supported_cli=['py','-3','-I','-B','build/tools/reconstruct_candidate.py','--manifest',HOME+'/source-manifest.json','--destination','<new durable work-local candidate directory>','--repository-root',str(ROOT)],capture='A fresh work-local driver invokes the supported CLI, substitutes only guard callables in memory with physical-path recording, and records producer entry/exit plus oracle entry/exit after all P5 lazy modules. That run is bootstrap observation, not validation. Freeze only actual sys.modules __file__ paths, external files, Python executable and all hashes; preserve bootstrap stdout/stderr/exit before assertion. Broader retained authorities never grant execution admission.',fresh_proof='Final supported CLI after the exact runtime has been frozen; independent fresh oracle driver and two isolated six-member replays. Work-local proof runner imports must be observed separately before admitting them; never infer execution from authority paths.',negatives='Late unexpected checkout and physical Library imports must reject at the end guard; code/runtime/executable drift rejects. P5-valid actual-source feature changes and resealed accounting/identity omissions must reject for intended field reasons.',current_runtime='capture-pending-noninstallable; no execution evidence yet',source_generation='not run')
    fresh(LOG+'/source-contract-draft-v1/runtime-execution-proposal.json',enc(proposal))
    return {n:pin(HOME+'/'+n) for n in ['source-manifest.json','profile.json','policy.json','scoped-source-version.json','runtime.json','README.source.md']}

if __name__=='__main__':print(json.dumps(prepare(),sort_keys=True))
