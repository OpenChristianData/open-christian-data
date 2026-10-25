"""Schema-valid identity proposal for the one retained two-volume biography.

Writes work-local proposal metadata only; never creates a canonical work home.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import html5lib
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.library.identities import validate_record, schema_enum

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='tyerman-life-george-whitefield'
TITLE='The Life of the Rev. George Whitefield, B.A.'
IDENTITY=dict(work_id=WORK_ID,textual_form_id=WORK_ID+'--retained-en',edition_id=WORK_ID+'--pg44280-62023-1876-1877',acquisition_id=WORK_ID+'--pg44280-62023-retained-member-set')
VOLUME_ACQUISITIONS=[WORK_ID+'--pg44280-retained',WORK_ID+'--pg62023-retained']
PROPOSAL=Path('sources/manifest-acquisitions/tyerman-life-george-whitefield-identity-proposal-20261004-v1')
SOURCE=Path('sources/manifest-acquisitions/tyerman-life-george-whitefield-complete-20261004-v3/source-manifest.json')
PACKAGE=Path('D:/Library/Open Christian Data/candidate-reviews/tyerman-whitefield-complete-20261004-v4/package')

def enc(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def sha(data):return hashlib.sha256(data).hexdigest()
def pin(path):
 data=path.read_bytes();return dict(path=path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix(),bytes=len(data),sha256=sha(data))
def write(name,data):
 path=ROOT/PROPOSAL/name
 if path.exists():raise FileExistsError('Preserve proposal '+str(path))
 path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
 return pin(path)

def propose():
 if (ROOT/PROPOSAL).exists() or (ROOT/'library/works'/WORK_ID).exists():raise FileExistsError('Fresh isolated proposal and absent canonical work required')
 wanted=set(IDENTITY.values())|set(VOLUME_ACQUISITIONS);collisions=[];aliases=[];catalogs=0
 for path in (ROOT/'library/works').glob('*/work.json'):
  record=json.loads(path.read_bytes());catalogs+=1
  ids={record['work_id']}
  for form in record['textual_forms']:
   ids.add(form['textual_form_id'])
   for edition in form['editions']:ids.add(edition['edition_id']);ids.update(edition.get('acquisition_ids',[]))
  collisions.extend(sorted(ids&wanted))
  if 'tyerman' in record['work_id'].lower() or ('whitefield' in record['title'].lower() and 'life' in record['title'].lower()):aliases.append({'work_id':record['work_id'],'title':record['title'],'work':pin(path)})
 if collisions:raise ValueError('Proposed identity collision '+repr(collisions))
 now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z');acquisitions=[];members=[];primary=[];lineage=[]
 for eid,roman,year,acqid in zip(['44280','62023'],['I','II'],['1876','1877'],VOLUME_ACQUISITIONS):
  receipt_path=ROOT/f'raw/gutenberg/{eid}/acquisition-receipt.json';receipt=json.loads(receipt_path.read_bytes());archive=ROOT/receipt['package']['path'];rawhtml=ROOT/receipt['html']['path']
  for key,path in [('package',archive),('html',rawhtml)]:
   actual=pin(path)
   if any(actual[field]!=receipt[key][field] for field in ['bytes','sha256']):raise ValueError('Original retained receipt mismatch '+eid+' '+key)
  parsed=html5lib.parse(rawhtml.read_text(encoding='utf-8'),treebuilder='etree',namespaceHTMLElements=False);body=parsed.find('body')
  title_nodes=list(body)[:20] if eid=='44280' else [next(node for node in body if node.get('id')=='p_i')]
  title_text='\n'.join(''.join(node.itertext()) for node in title_nodes)
  tokens=['WHITEFIELD','TYERMAN','IN TWO VOLUMES','HODDER','STOUGHTON','PATERNOSTER','MDCCCLXXVI' if eid=='44280' else 'MDCCCLXXVII']
  if any(token not in title_text for token in tokens):raise ValueError('Primary title/imprint boundary absent '+eid)
  primary.append(dict(ebook_id=eid,volume=roman,imprint_year=year,html=pin(rawhtml),locator='Direct body children 1 through 20 including preceding advertisement context' if eid=='44280' else 'Direct body div @id=p_i',literal_title_zone=title_text,complete_two_volume_statement=True,publisher_literal='Hodder and Stoughton',place_literal='London',author_literal='L. Tyerman',boundary='Volume I and II are ordered parts of this biography, not distinct authored works. Advertisements remain source context.'))
  selected=[]
  with ZipFile(archive) as zipfile:
   for index,info in enumerate(zipfile.infolist(),1):
    if info.is_dir():raise ValueError('Unexpected directory member')
    raw=zipfile.read(info.filename);path=Path(f'raw/gutenberg/{eid}/html')/info.filename
    if (ROOT/path).read_bytes()!=raw:raise ValueError('Extracted archive member mismatch '+path.as_posix())
    media='text/html' if path.suffix=='.html' else 'image/jpeg' if path.suffix=='.jpg' else 'image/png' if path.suffix=='.png' else None
    if media is None:raise ValueError('Unclassified retained member '+str(path))
    row=dict(path=path.as_posix(),bytes=len(raw),sha256=sha(raw),media_type=media,scope=f'Complete retained Volume {roman} ({year}, PG{eid}); archive member {index}: {info.filename}; native source or explicitly accounted support.')
    members.append(row);selected.append(row)
  scope=f'Whole already downloaded retained electronic Volume {roman} ({year}, PG{eid}) of the complete two-volume Tyerman Whitefield biography, including provider matter, advertisements, notes, tables, index, and archive media.'
  acquisitions.append(dict(schema_version='2.0',acquisition_id=acqid,edition_id=IDENTITY['edition_id'],provider='Project Gutenberg',url=receipt['source_url'],accessed_at=receipt['downloaded_utc'][:10],route='born-digital',rights=receipt['rights'],source_path=receipt['html']['path'],source_bytes=receipt['html']['bytes'],source_sha256=receipt['html']['sha256'],source_scope=scope,retained_files=[dict(**receipt['package'],media_type='application/zip',scope='Exact original downloaded archive; all members independently bound below.'),*selected],warnings=['The source unit is one volume, not a distinct complete work; both volumes are bound by the selected derived acquisition.','Exact original download timestamp and provider package URL are preserved in the unchanged acquisition receipt and identity crosswalk. No new download, human rights clearance, or publication is asserted.']))
  oldhome=ROOT/f'sources/manifest-acquisitions/tyerman-life-george-whitefield-vol-{1 if eid=="44280" else 2}-{year}'
  oldmanifest=json.loads((oldhome/'source-manifest.json').read_bytes())
  lineage.append(dict(ebook_id=eid,original_source_identity={key:oldmanifest[key] for key in ['work_id','source_id']},original_source_manifest=pin(oldhome/'source-manifest.json'),original_profile=pin(oldhome/'profile.json'),original_policy=pin(oldhome/'policy.json'),acquisition_receipt=pin(receipt_path),exact_original_acquisition_receipt=receipt,new_volume_acquisition_id=acqid,source_fields_preserved=True,obsolete_distinct_work_policy='Preserved historical claim, explicitly superseded for current complete-work scope.'))
 scope='One complete authored biography, both entire retained electronic volumes I (1876, PG44280) and II (1877, PG62023), in that order; every HTML and image archive member, including source context and support media.'
 derived=dict(schema_version='2.0',acquisition_id=IDENTITY['acquisition_id'],edition_id=IDENTITY['edition_id'],provider='Project Gutenberg',url=acquisitions[0]['url'],route='born-digital',rights=acquisitions[0]['rights'],source_kind='retained-member-set',source_path=(PROPOSAL/'source-member-set.json').as_posix(),source_scope=scope,retained_files=members,warnings=['The entry URL is the exact original Volume I acquired URL, not a provider URL for a combined edition. Volume II source URL: '+acquisitions[1]['url']+'.','This is a deterministic ordered descriptor of already retained members, not a new download. Per-volume download timestamps and original archives remain unchanged lineage.','No derived download/access date is invented; source edition identity is primary-title/imprint backed, not a claim of print-page collation or human acceptance.'])
 descriptor=source_member_set_bytes(derived);derived.update(source_bytes=len(descriptor),source_sha256=sha(descriptor));acquisitions.append(derived)
 evidence=[SOURCE.as_posix(),(PROPOSAL/'identity-crosswalk.json').as_posix(),(PROPOSAL/'SOURCE_CREDIT.md').as_posix()]
 work=dict(schema_version='2.0',work_id=WORK_ID,title=TITLE,creators=[dict(name='L. Tyerman',role='author',evidence=[row['html']['path'] for row in primary])],evidence=evidence,textual_forms=[dict(textual_form_id=IDENTITY['textual_form_id'],language='en',category='prose',editions=[dict(edition_id=IDENTITY['edition_id'],title=TITLE+' — complete retained electronic volumes I (1876) and II (1877)',language='en',category='prose',acquisition_ids=[*VOLUME_ACQUISITIONS,IDENTITY['acquisition_id']])])])
 stages=schema_enum('state','stage')
 if 'acquired' not in stages or 'review' not in stages:raise ValueError('Current schema stages changed')
 targets=[dict(target_id=record['acquisition_id'],target_type='acquisition',stage='acquired',updated_at=lineage[index]['exact_original_acquisition_receipt']['downloaded_utc'] if index<2 else now,evidence=[(PROPOSAL/(record['acquisition_id']+'.json')).as_posix(),*evidence],reason='Already downloaded retained source.' if index<2 else 'Ordered derived member-set identity for already retained sources; this timestamp records proposal, not download.') for index,record in enumerate(acquisitions)]
 targets.append(dict(target_id=IDENTITY['edition_id'],target_type='edition',stage='review',updated_at=now,evidence=evidence,reason='Complete source candidate prepared for technical acceptance review; canonical installation and acceptance remain held.'))
 state=dict(schema_version='2.0',work_id=WORK_ID,targets=targets)
 for name,record in [('work',work),('state',state),*[('acquisition',a) for a in acquisitions]]:validate_record(name,record,context='L635 isolated identity proposal')
 if descriptor!=source_member_set_bytes(derived):raise ValueError('Derived descriptor not exact')
 crosswalk=dict(contract='ocd-l635-primary-complete-biography-identity-proposal-v1',proposed_at=now,identity=IDENTITY,primary_title=TITLE,author_literal='L. Tyerman',primary_source_title_imprints=primary,lineage=lineage,ordered_source_urls=[record['url'] for record in acquisitions[:2]],complete_authored_works=1,source_volumes=2,ordered_archive_members=members,selected_derived_acquisition=derived,canonical_home_absent=True,collision_scan=dict(work_catalogs_read=catalogs,proposed_ids=sorted(wanted),collisions=collisions,related_aliases=aliases),canonical_writes=False,new_downloads=False,historical_policy_disposition='Original per-volume distinct-work claims remain immutable historical lineage; the explicit IN TWO VOLUMES statement governs this complete authored biography.',qualification='Schema-valid isolated proposal, not acceptance, a projection pass, human rights clearance, or publication.')
 credit=('# Source credit: '+TITLE+'\n\nBy L. Tyerman. Complete ordered volumes I and II. Primary titlepages: London, Hodder and Stoughton, 27 Paternoster Row, E.C.; 1876 and 1877. The literal IN TWO VOLUMES statement governs the work boundary.\n\nBoth sources were already downloaded on September 23, 2026. Provider records: '+acquisitions[0]['url']+' and '+acquisitions[1]['url']+'. Their full provider notices and original acquisition facts are retained in the complete TEI and source envelope; source advertisements, including the John Wesley biography advertisement, remain context.\n\n'+acquisitions[0]['rights']+'\n\nThe current candidate repairs representation from exact retained HTML and media while preserving both original TEI packages and historical policies. It does not assert additive whole-body byte conservation, print-page collation, CVW review, human rights clearance, acceptance, or publication. Original source defects/transcriber interventions and source contact/disclosure facts are retained; disclosure decisions remain separate.\n').encode('utf-8')
 files=[write('work.json',enc(work)),write('state.json',enc(state)),write('identity-crosswalk.json',enc(crosswalk)),write('source-member-set.json',descriptor),write('SOURCE_CREDIT.md',credit)]
 files.extend(write(record['acquisition_id']+'.json',enc(record)) for record in acquisitions)
 if (ROOT/'library/works'/WORK_ID).exists():raise ValueError('Unexpected canonical home appeared')
 result=dict(status='schema-valid-isolated-proposal',identity=IDENTITY,work_title=TITLE,files=files,primary_complete_work_boundary=True,canonical_writes=False,source_package=pin(PACKAGE/'manifest.json'),source_manifest=pin(ROOT/SOURCE),schema_pins=[pin(ROOT/f'schemas/v2/{name}.schema.json') for name in ['work','state','acquisition']],helper=pin(Path(__file__)),qualification='Physical acceptance/state/acquisition validators will run against the separately authorized stage; this proposal schema validation alone is not their pass.')
 receipt=write('proposal.json',enc(result));print(json.dumps(receipt|{'status':result['status'],'files':len(files)}))
 return result

if __name__=='__main__':propose()
