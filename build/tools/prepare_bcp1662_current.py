"""Bind all retained BCP1662 members and qualified electronic-edition metadata."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
import json
from lxml import etree
from build.tei import bcp1662_current_reconstruction as producer, bcp1662_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='bcp-1662'
FORM_ID='bcp-1662-retained-electronic'
EDITION_ID='bcp-1662-retained-electronic-witness'
ACQUISITION_ID='bcp-1662-retained-source-set'
SOURCE_SHA='88bf44c37c8ecf333c4e2cb171bff0fb91f2735ba5417812d72feea9344854dd'
WORK=Path('library/works/bcp-1662')
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/liturgies-bcp1662-current/bcp-1662')
LOG=Path('reports/_logs/bcp1662-current-reconciliation-20261002-v1')
HISTORICAL=LOG/'historical-package/content.tei.xml'
TITLE='The Book of Common Prayer (1662)'
DATA_NOTICE=Path('data/liturgies/bcp-1662/README.md')
SCOPE='Complete declared retained partial electronic BCP1662 witness: all25 ordered HTML textual members (20services and five calendar/collect parts),733,674 retained primary bytes,17,106 ordered lexical observations,1,701 source-derived blocks,255 speech turns,90 observance groups and85 collect markers. Five stored404 responses remain acquisition-failure evidence outside the textual body. All30 files in the two edition-specific retained directories are accounted. This is complete for the declared retained electronic scope; it is not the complete historical printed1662Book of Common Prayer. Source comments identify later1992wording in morning/evening prayer and communion. No source spelling corrections, invented missing services, child work IDs or resolved print/transcription identity are claimed.'
canonical=producer.canonical
NS='{http://www.tei-c.org/ns/1.0}'

def put(p,raw):
    target=io_path(ROOT/p); target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw)

def binding(name,p,role):
    raw=io_path(ROOT/p).read_bytes()
    return dict(name=name,path=p.as_posix(),role=role,bytes=len(raw),sha256=sha256(raw).hexdigest())

def main():
    acquired=validate_acquisition(ROOT/ACQUISITION,root=ROOT)
    original_manifest=Path('sources/structured-text/bcp-1662/bcp-1662.source-manifest.json')
    original=json.loads((ROOT/original_manifest).read_bytes())
    if acquired['source_sha256']!='88bf44c37c8ecf333c4e2cb171bff0fb91f2735ba5417812d72feea9344854dd':
        raise ValueError('Original acquired member set differs')
    primary=original['source_members']; failures=original['failed_acquisitions']
    if len(primary)!=25 or len(failures)!=5:
        raise ValueError('Declared source scope differs')
    declared={m['path']:m for m in primary+failures}
    physical=set()
    for directory in ('raw/bcp-full-text/bcp-1662','raw/bcp1662'):
        physical.update(p.relative_to(io_path(ROOT)).as_posix() for p in io_path(ROOT/directory).rglob('*') if p.is_file())
    if physical!=set(declared):
        raise ValueError(f'Unaccounted edition files: {physical ^ set(declared)}')
    for m in declared.values():
        raw=io_path(ROOT/m['path']).read_bytes()
        if len(raw)!=m['bytes'] or sha256(raw).hexdigest()!=m['sha256']:
            raise ValueError('Retained source bytes differ: '+m['path'])
    if [(m['path'],m['sha256']) for m in primary]!=[(m['path'],m['sha256']) for m in acquired['retained_files']]:
        raise ValueError('Canonical acquisition primary order differs')
    old=io_path(ROOT/HISTORICAL).read_bytes()
    if sha256(old).hexdigest()!='a866028989317cbe041b607f6799d2b78ad5b92f0b6fca771d22085d1df335d2':
        raise ValueError('Checked historical whole TEI differs')
    historical=etree.fromstring(old)
    aliases=[]
    for n in historical.find(NS+'text').iter():
        tag=etree.QName(n).localname
        if tag=='ab' and n.get('type')=='heading':
            before=f'<ns0:ab type="heading" subtype="{n.get("subtype")}">'.encode()
            after=f'<ns0:ab type="source-{n.get("subtype")}">'.encode()
        elif tag=='ab' and n.get('type')=='section-break':
            before=b'<ns0:ab type="section-break"'
            after=b'<ns0:ab type="source-block" subtype="section-break"'
        elif tag=='sp':
            before=f'<ns0:sp who="{n.get("who")}">'.encode()
            after=f'<ns0:sp ana="source-role-token:{n.get("who")}">'.encode()
        else:
            continue
        entry={'before':before.decode(),'after':after.decode()}
        if not any(a['before']==entry['before'] for a in aliases):
            aliases.append(entry | {'count':old.count(before)})
    if sum(a['count'] for a in aliases)!=341:
        raise ValueError('Exact35 heading/51 break/255 role-alias census differs')
    h=etree.Element(NS+'teiHeader',nsmap={'ns0':NS[1:-1]})
    fd=etree.SubElement(h,NS+'fileDesc')
    etree.SubElement(etree.SubElement(fd,NS+'titleStmt'),NS+'title').text='The Book of Common Prayer,1662:retained partial transcription'
    etree.SubElement(etree.SubElement(fd,NS+'publicationStmt'),NS+'p').text='Private technical candidate for the complete declared retained partial electronic witness. Human textual acceptance, historical print completeness, transcription/provider identity, rights clearance and public publication remain separate.'
    b=etree.SubElement(etree.SubElement(fd,NS+'sourceDesc'),NS+'bibl')
    etree.SubElement(b,NS+'title').text='Partial1662BCP retained HTML expression:20services and five calendar/collect parts'
    etree.SubElement(b,NS+'ptr',target=acquired['url'])
    for p in historical.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc').iter():
        if etree.QName(p).localname in ('title','ref','idno'):
            etree.SubElement(b,NS+'note',type='historical-source-description').text=''.join(p.itertext())
    etree.SubElement(b,NS+'note',type='work-scope').text=SCOPE
    etree.SubElement(b,NS+'note',type='source-credit').text='Source location retained from the acquisition: https://www.eskimo.com/~lhowell/bcp1662/. The source-config attribution "Transcription by Lesley Holwell" and the inherited Lesley Holwell/Lynda M.Howell/CVW holwell provider-name claims remain unresolved; no personal transcriber attribution is inferred from an account URL. Church of England is inherited work attribution, not a verified individual electronic contributor. Unknown print publisher, exact mixed-edition identity, electronic contributor/date and transcription rights remain unasserted.'
    etree.SubElement(b,NS+'note',type='source-edition-evidence').text='Four literal source comments remain outside readable body in the full external ledger: two say the sentence about the collect from Trinity21is new in the1992edition; communion says the following paragraph only appears in this wording in1992; matrimony preserves an explicit1662annotation. These claims qualify this mixed retained witness and do not authorize correction to another edition.'
    etree.SubElement(b,NS+'note',type='source-assets').text='The HTML contains787image occurrences:603text-bearing drop-cap alternatives are represented exactly and184navigation images remain evidence-only. No image payload is present among the30retained edition files. Image attributes, literal links, all source text/markup observations and byte anchors remain in the external source-accountability ledger. No graphic or alternate wording is fabricated.'
    etree.SubElement(b,NS+'note',type='source-overlap').text='The separate existing bcp-1662-collects identity overlaps the five retained calendar members. This complete25-member edition preserves that source context without changing or installing the sibling identity and without creating individual service IDs.'
    etree.SubElement(b,NS+'note',type='role-annotation').text='The historical reconstruction uses 255 generated who fragments with no matching person declarations. They are preserved reversibly as literal source-role-token annotations, alongside unchanged literal speaker labels and ordered utterances. These annotations identify no person and assert no resolving authority or response link. Existing 117 continuation/alternative target occurrences are preserved and independently resolved. Heading-level and section-break aliases likewise have exact whole-byte inverse conservation.'
    etree.SubElement(b,NS+'note',type='rights-qualification').text='The inherited source-config public-domain claim does not establish electronic transcription rights, provider identity, jurisdictional clearance or publication authorization. No explicit retained permission notice was identified in these HTML members. Technical fidelity is separate from rights clearance and human textual acceptance.'
    questions=[dict(id='bcp1662-'+kind,kind=kind,status='unresolved',detail=detail) for kind,detail in [('scope','Complete retained25-member partial electronic edition; full printed1662and mixed later source wording remain unresolved.'),('provider','Source URL does not resolve inherited Lesley Holwell/Lynda M.Howell/CVW holwell personal attribution claims.'),('assets','No retained image payloads; text alternatives and all image attributes are accounted.'),('rights','Underlying work/source-config public-domain claim is not electronic transcription rights clearance.'),('human','No human textual acceptance or full visual source/print collation.'),('publication','No public publication authorization or action.')]]
    profile=dict(work_id=WORK_ID,source_sha256=acquired['source_sha256'],scope=SCOPE,header_xml=etree.tostring(h,encoding='unicode'),questions=questions,historical_candidate_sha256=sha256(old).hexdigest(),source_bundle=original['source_bundle'],source_members=primary,failed_acquisitions=failures,supported_shape_aliases=aliases)
    put(BASE/'profile.json',canonical(profile))
    put(BASE/'validation-policy.json',canonical(dict(scope=SCOPE,rules=['complete lexical source/TEI semantic oracle','whole historical byte conservation after header restoration','fresh original mapper replay','all30retained files disposition','P5','fresh deterministic package replay','meaningful source and public mutations'],shared_assumptions='Both source readers use CPython HTMLParser; separate lexical state and semantic attachment check do not prove historical print collation.')))
    notice='# BCP1662 partial electronic edition:source and data credit\n\nRetained source location:[eskimo.com/~lhowell/bcp1662](https://www.eskimo.com/~lhowell/bcp1662/). This edition preserves the complete declared retained25-member electronic witness. It does **not** claim the complete printed1662BCP.\n\n'+SCOPE+'\n\nThe retained HTML explicitly comments on later1992wording. All four comments and five404responses remain accounted as evidence; source wording is unchanged. All603text-bearing image alternatives are retained. No image payloads were acquired, and184navigation images remain evidence-only. Literal HTML attributes/links and source-byte anchors are retained in private source accountability.\n\nThe inherited source-config attribution "Transcription by Lesley Holwell", other provider-name claims and public-domain claim remain unresolved. An account URL does not establish a transcriber identity. Exact print/electronic contributors, mixed-edition identity and electronic transcription rights are not inferred. No explicit permission notice was found in the retained HTML. Human textual acceptance, historical print collation, rights clearance and public publication remain separate.\n\nThe existing bcp-1662-collects identity overlaps five calendar members and is unchanged. Source-defined speaker labels, rubrics, drop-cap alternatives, block order and alternative relationships are conserved; no response links are invented. Carry this visible notice to `'+DATA_NOTICE.as_posix()+'`.\n'
    put(BASE/'README.source.md',notice.encode())
    paths=[(a['name'],Path(a['path']),{'complete-source-feature-profile':'readonly-original-profile','independent-validation-policy':'readonly-original-policy'}.get(a['role'],a['role'])) for a in original['authorities']]
    paths += [('profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy-current',BASE/'validation-policy.json','independent-validation-policy'),('source-readme',BASE/'README.source.md','visible-source-credit'),('historical-native-candidate',HISTORICAL,'whole-checked-native-handoff'),('historical-accountability',LOG/'historical-package/source-accountability.json','full-original-lexical-ledger'),('historical-manifest',LOG/'historical-package/manifest.json','dated-package-authority'),('original-source-manifest',original_manifest,'historical-source-authority'),('canonical-acquisition',ACQUISITION,'current-retained-member-set'),('original-mapper',Path('build/tei/bcp_1662_reconstruction.py'),'readonly-original-mapper'),('original-oracle',Path('build/tei/bcp_1662_oracle.py'),'readonly-original-independent-oracle')]
    authorities=[binding(*p) for p in paths]
    # Keep the original policy as validation-policy for the original oracle, while
    # the contract attestation binds the current work-local policy separately.
    manifest=dict(contract='ocd-source-manifest-v1',source_id='bcp1662-complete-retained-partial-current-v1',work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,source_bundle=original['source_bundle'],source_members=primary,failed_acquisitions=failures,authorities=authorities,converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable='_convert',implementation_path='build/tei/bcp1662_current_reconstruction.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable='_oracle',implementation_path='build/tei/bcp1662_current_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=original['package_schema'])
    put(BASE/'source-manifest.json',canonical(manifest))
    scope=dict(status='pass',created_utc=datetime.now(timezone.utc).isoformat(),textual_members=primary,retained_only=failures,physical_file_count=len(physical),scope=SCOPE,source_manifest_sha256=sha256(canonical(manifest)).hexdigest(),acquisition_sha256=sha256(io_path(ROOT/ACQUISITION).read_bytes()).hexdigest(),unchanged_source_bindings=[binding('retained-'+str(i+1),Path(m['path']),'primary' if m in primary else 'retained-404') for i,m in enumerate(primary+failures)])
    put(LOG/'current-source-scope.json',canonical(scope))
    print(json.dumps(dict(status='prepared',members=25,retained_only=5,source_sha256=acquired['source_sha256'],body_conservation='Exact inverse of341reviewed aliases restores original body')))

if __name__=='__main__':
    main()
