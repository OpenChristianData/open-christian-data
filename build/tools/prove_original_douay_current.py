"""Bounded full-source/current-route proof for the retained Original Douay repair."""
from hashlib import sha256
import json,os
from lxml import etree
from ocd_kernel.library._common import io_path
from build.tools.probe_original_douay_route import ROOT,LOG,OLD,SOURCE,header,WORK_ID,FORM_ID,EDITION_ID,REVISION,VERSIFICATION
from build.tei.original_douay_current_reconstruction import adapt,add_missing_articles,canonical
from build.tei.original_douay_current_oracle import source_check,inverse
from ocd_kernel.projection.categories.bible import project_bible_document,verify_bible_document

def main():
 ms=json.loads(io_path(ROOT/SOURCE).read_bytes());docs={}
 for m in ms['members']:
  if '/bible/tagged/' in m['path']:docs[m['path'].split('/original-douay-rheims-1.0/',1)[1]]=json.loads(io_path(ROOT/m['path']).read_bytes())
 old=io_path(ROOT/OLD/'content.tei.xml').read_bytes();native=add_missing_articles(old,docs)
 proof,records,verse_fields=source_check(ms,lambda p:io_path(ROOT/p).read_bytes(),native)
 source_sha=sha256(io_path(ROOT/SOURCE).read_bytes()).hexdigest();h=etree.tostring(header(source_sha),encoding='UTF-8')
 new=adapt(native,h,proof['historical_null_encoding_errors'])
 inverse(new,old,h,proof['historical_null_encoding_errors'],native)
 folder=io_path(ROOT/LOG/'renewed-native-v1');folder.mkdir(parents=True,exist_ok=True)
 outputs={'source-complete-native.tei.xml':native,'content.tei.xml':new,'independent-source-fields.json':canonical(proof),'source-field-inventory.json':canonical(records),'verse-field-inventory.json':canonical(verse_fields)}
 for name,raw in outputs.items():
  p=folder/name
  if p.exists() and p.read_bytes()!=raw:raise ValueError('Refusing changed frozen diagnostic '+name)
  p.write_bytes(raw)
 context=dict(identity=dict(work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID),language='en',representation_revision=REVISION,edition_title='Original Douay-Rheims structured release v1.0',versification=VERSIFICATION,source_sha256=source_sha,retained_sha256=source_sha,source_url='https://github.com/janvier-s/original-douay-rheims')
 result=project_bible_document(folder/'content.tei.xml',**context)
 errors=verify_bible_document(folder/'content.tei.xml',result['rows'],result['receipt'],**context)
 if errors:raise ValueError(errors)
 (folder/'projection.json').write_bytes(canonical(result))
 summary=dict(status='pass',pid=os.getpid(),original_sha256=sha256(old).hexdigest(),renewed_native_sha256=sha256(native).hexdigest(),candidate_sha256=sha256(new).hexdigest(),source=proof,rows=len(result['rows']),characters=sum(len(r['text']) for r in result['rows']),independent_projection_errors=errors)
 (folder/'proof.json').write_bytes(canonical(summary));print(json.dumps({k:v for k,v in summary.items() if k!='source'}))
if __name__=='__main__':main()
