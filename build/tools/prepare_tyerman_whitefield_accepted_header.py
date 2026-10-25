"""Bounded header/metadata draft; never stages or installs the biography."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.library.identities import validate_record
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/tyerman-whitefield-complete-20261004-v1')
PROPOSAL=Path('sources/manifest-acquisitions/tyerman-life-george-whitefield-identity-proposal-20261004-v1')
DRAFT=Path('sources/manifest-acquisitions/tyerman-life-george-whitefield-accepted-header-draft-20261004-v1')
PACKAGE=Path('D:/Library/Open Christian Data/candidate-reviews/tyerman-whitefield-complete-20261004-v4/package')
IDENTITY=dict(work_id='tyerman-life-george-whitefield',textual_form_id='tyerman-life-george-whitefield--retained-en',edition_id='tyerman-life-george-whitefield--pg44280-62023-1876-1877',acquisition_id='tyerman-life-george-whitefield--pg44280-62023-retained-member-set')
EXPECTED_CONTENT='fd2e1d4b5b51bb16175f269093b97686cede9d54b45c4549181271acdcb1b8a9'
EXPECTED_REVIEW='5c2736b63ac2eb100e2fc6604c4715327b3346b86b0a96ca8584d4cde7c77a9a'
OLD_STATUS='Nonaccepted complete-work reconstruction candidate. Technical validation, human acceptance, rights clearance, and publication are separate.'
CURRENT_STATUS='Evidence-backed complete-biography TEI master representation. Technical agent source review passed. Current technical acceptance is recorded separately by acceptance and state sidecars; dated nonaccepted source-package and proposal labels describe preserved historical evidence. Human verification, applicable rights, disclosure, print/CVW collation, and publication remain separate.'
REVISION_ID='tyerman-whitefield-complete-retained-20261004-v1'
REVISION_NOTE='Complete authored biography: both full retained electronic volumes I and II, with exact source wording, structure, media, and volume ownership preserved; primary title and ordered retained member-set identity bound after agent source review.'
NS='{http://www.tei-c.org/ns/1.0}'

def enc(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def pin(path):
 raw=path.read_bytes();return dict(path=path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix(),bytes=len(raw),sha256=sha(raw))
def read(path):return json.loads((ROOT/path).read_bytes())
def write(relative,raw):
 path=ROOT/DRAFT/relative
 if path.exists():raise FileExistsError('Preserve draft '+str(path))
 path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);return path

def publication_successor(raw):
 old=OLD_STATUS.encode();new=CURRENT_STATUS.encode()
 if raw.count(old)!=1 or new in raw:raise ValueError('Exact source publication statement differs')
 updated=raw.replace(old,new,1)
 if updated.replace(new,old,1)!=raw:raise ValueError('Publication statement inverse differs')
 return updated

def bind(raw,acquisition,revision):
 if sha(raw)!=EXPECTED_CONTENT:raise ValueError('Frozen source candidate changed')
 if acquisition['acquisition_id']!=IDENTITY['acquisition_id'] or acquisition['edition_id']!=IDENTITY['edition_id']:raise ValueError('Exact selected member-set identity differs')
 original=publication_successor(raw)
 source={key:acquisition[key] for key in ['source_path','source_sha256','source_bytes','source_scope','source_kind']}
 bound=bind_reviewed_header(original,expected_sha256=sha(original),identity=IDENTITY,source=source,source_url=acquisition['url'],declared_scope=acquisition['source_scope'],revision=revision)
 # No XML serializer is allowed to touch the reviewed outer text/group.
 if bound.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise ValueError('Header draft changed complete source text bytes')
 return bound

def inverse(bound,raw,acquisition,revision):
 expected=bind(raw,acquisition,revision)
 if bound!=expected:raise ValueError('Actual draft is not exact header recomputation')
 tree=etree.fromstring(bound,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True));header=tree.find(NS+'teiHeader')
 old=etree.fromstring(publication_successor(raw),etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True)).find(NS+'teiHeader')
 sd=header.find(NS+'fileDesc/'+NS+'sourceDesc');oldsd=old.find(NS+'fileDesc/'+NS+'sourceDesc')
 if len(sd)!=len(oldsd)+1:raise ValueError('Header binding cardinality differs')
 binding=etree.tostring(sd[-1],encoding='UTF-8')
 changes=header.findall(NS+'revisionDesc/'+NS+'change')
 if len(changes)!=1 or changes[0].get('{http://www.w3.org/XML/1998/namespace}id')!=revision['id']:raise ValueError('Exact revision differs')
 # Prefix-independent lexical bounds identify only the two added header blocks.
 prefix=bound.split(b'</teiHeader>',1)[0]
 marker=b'<bibl xmlns="http://www.tei-c.org/ns/1.0">'
 start=prefix.rfind(marker);end=prefix.find(b'</bibl>',start)+len(b'</bibl>')
 if start<0 or end<len(b'</bibl>'):raise ValueError('Exact binding lexical boundary absent')
 added_binding=prefix[start:end]
 revstart=prefix.rfind(b'<revisionDesc xmlns="http://www.tei-c.org/ns/1.0">');revend=prefix.find(b'</revisionDesc>',revstart)+len(b'</revisionDesc>')
 if revstart<0 or revend<len(b'</revisionDesc>'):raise ValueError('Exact revision lexical boundary absent')
 added_revision=prefix[revstart:revend]
 recovered=bound.replace(added_binding,b'',1).replace(added_revision,b'',1).replace(CURRENT_STATUS.encode(),OLD_STATUS.encode(),1)
 if recovered!=raw:raise ValueError('Deleting only exact header additions and restoring publication statement did not recover original')
 return recovered,dict(added_binding_sha256=sha(added_binding),added_revision_sha256=sha(added_revision),original_whole_document_byte_inverse=True,complete_outer_text_byte_conservation=True)

def prepare():
 if (ROOT/DRAFT).exists() or (ROOT/'library/works'/IDENTITY['work_id']).exists():raise FileExistsError('Fresh work-local draft and absent canonical work required')
 review=ROOT/LOG/'root-final-source-identity-review-v4.json'
 if sha(review.read_bytes())!=EXPECTED_REVIEW:raise ValueError('Root review authority differs')
 proposal=read(PROPOSAL/'proposal.json')
 if proposal['identity']!=IDENTITY:raise ValueError('Approved proposal identity differs')
 for row in proposal['files']:
  actual=pin(ROOT/row['path'])
  if actual!=row:raise ValueError('Approved proposal record changed '+row['path'])
 work=read(PROPOSAL/'work.json');state=read(PROPOSAL/'state.json');acquisition=read(PROPOSAL/(IDENTITY['acquisition_id']+'.json'))
 for name,record in [('work',work),('state',state),('acquisition',acquisition)]:validate_record(name,record,context='L635 accepted-header metadata draft')
 descriptor=(ROOT/acquisition['source_path']).read_bytes()
 if descriptor!=source_member_set_bytes(acquisition) or len(descriptor)!=acquisition['source_bytes'] or sha(descriptor)!=acquisition['source_sha256']:raise ValueError('Exact derived descriptor differs')
 at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z');revision=dict(id=REVISION_ID,date=at[:10],note=REVISION_NOTE)
 raw=(PACKAGE/'content.tei.xml').read_bytes();bound=bind(raw,acquisition,revision);restored,inversion=inverse(bound,raw,acquisition,revision)
 candidate=write(Path('candidate.tei.xml'),bound);errors=validate_file(candidate)
 if errors:raise ValueError('Header draft P5 failed '+repr(errors))
 original=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True))
 write(Path('original-reviewed-header.xml'),etree.tostring(original.find(NS+'teiHeader'),encoding='UTF-8'))
 inverse_path=write(Path('header-inverse-original.tei.xml'),restored)
 # Run the actual source inverse inside its frozen admitted source process.
 # Installation/identity imports in this outer process must not broaden that envelope.
 code='''import json,sys
from pathlib import Path
r=Path(sys.argv[1]);sys.path.insert(0,str(r))
import build.tools.prepare_tyerman_whitefield_complete
import build.tools.prove_tyerman_whitefield_complete as proof
from build.tei import tyerman_whitefield_complete_oracle as o
from build.tei.tyerman_whitefield_runtime import guard
from ocd_kernel.reconstruction import SourceManifest
m=SourceManifest.load(proof.SOURCE,repository_root=r)
guard(m,'before-oracle')
rows=o.check_content(Path(sys.argv[2]).read_bytes(),json.loads(m.authority_path('profile').read_bytes()))
guard(m,'after-oracle')
print(json.dumps({'status':'pass','actual_source_inverse':rows}))'''
 args=[sys.executable,'-I','-B','-c',code,str(ROOT),str(inverse_path)];run=subprocess.run(args,check=False,capture_output=True,text=True,cwd=ROOT)
 stdout=write(Path('source-inverse-stdout.txt'),run.stdout.encode('utf-8'));stderr=write(Path('source-inverse-stderr.txt'),run.stderr.encode('utf-8'))
 process=write(Path('source-inverse-process.json'),enc(dict(arguments=args,exit_code=run.returncode,stdout=pin(stdout),stderr=pin(stderr),saved_before_assertions=True)))
 if run.returncode!=0:raise ValueError('Actual inverse source process failed '+str(run.returncode))
 source_result=json.loads(run.stdout)
 if source_result['status']!='pass':raise ValueError('Actual source inverse failed')
 credit=(ROOT/PROPOSAL/'SOURCE_CREDIT.md').read_bytes()
 credit+=('\n## Current technical representation\n\nThe agent-reviewed complete biography is prepared as one evidence-backed TEI master representation. The exact current identity is '+IDENTITY['work_id']+' / '+IDENTITY['textual_form_id']+' / '+IDENTITY['edition_id']+' / '+IDENTITY['acquisition_id']+'. Current technical acceptance and installation are recorded by the acceptance/state sidecars. Dated nonaccepted source-package/proposal labels remain historical evidence, not a competing current work or title assignment.\n\nThis artifact is a header/metadata draft only. Supported staging, actual two-volume prose-reader projection, fixture rollback proof, canonical installation, and coordinator readback remain pending. Human verification, rights/jurisdiction, disclosure, print/CVW collation, and publication remain separate.\n').encode('utf-8')
 credit_path=write(Path('SOURCE_CREDIT.draft.md'),credit)
 metadata=[write(Path('metadata')/Path(row['path']).name,(ROOT/row['path']).read_bytes()) for row in proposal['files']]
 receipt=dict(contract='ocd-l635-header-bound-technical-master-draft-v1',status='P5-valid-header-and-metadata-draft',prepared_at=at,revision=revision,identity=IDENTITY,source_scope=acquisition['source_scope'],selected_source_acquisition=acquisition,root_review=pin(review),source_candidate=pin(PACKAGE/'content.tei.xml'),draft=pin(candidate),original_header=pin(ROOT/DRAFT/'original-reviewed-header.xml'),inverse_original=pin(inverse_path),inversion=inversion,complete_text_bytes=dict(bytes=len(raw.split(b'</teiHeader>',1)[1]),sha256=sha(raw.split(b'</teiHeader>',1)[1])),P5=dict(status='pass',errors=[],schema_pins=[pin(p) for p in sorted((ROOT/'ocd_kernel/tei/vendor/xsd').glob('*.xsd'))]),actual_source_inverse=source_result,source_inverse_process=pin(process),source_credit=pin(credit_path),historical_metadata_copies=[pin(p) for p in metadata],publication_statement_transition=dict(original=OLD_STATUS,current=CURRENT_STATUS),primary_source_title_assignment=work['title'],canonical_writes=False,acceptance_or_state_promotion=False,staging='HELD until maintained two-volume reader readiness and separate root release',dependencies=[pin(Path(__file__)),pin(ROOT/'ocd_kernel/tei/reviewed_integration.py'),pin(ROOT/'ocd_kernel/tei/validate.py')])
 result=write(Path('draft-receipt.json'),enc(receipt));print(json.dumps(pin(result)|dict(status=receipt['status'],candidate_sha256=sha(bound),source_text_byte_conservation=True)));return receipt

if __name__=='__main__':prepare()
