"""Actual bounded Bible API probe: retained generated book ordinal vs source name."""
from copy import deepcopy
from hashlib import sha256
import json
from lxml import etree
from build.tools.prepare_webster_current import *
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.projection.categories.bible import project_bible_document,verify_bible_document
def main():
 profile=json.loads((ROOT/BASE/'profile.json').read_bytes());acq=json.loads(io_path(ROOT/ACQUISITION).read_bytes());m=acq['retained_files'][0]
 source=dict(source_path=m['path'],source_sha256=m['sha256'],source_bytes=m['bytes'],source_scope=m['scope'])
 raw=io_path(ROOT/BASELINE/'content.tei.xml').read_bytes();d=etree.fromstring(raw);ns='{http://www.tei-c.org/ns/1.0}'
 d.replace(d[0],etree.fromstring(profile['header_xml'].encode()));body=d.find(ns+'text/'+ns+'body');book=body[0]
 for child in list(body)[1:]:body.remove(child)
 for child in list(book)[2:]:book.remove(child)
 chapter=book[1]
 for child in list(chapter)[1:]:chapter.remove(child)
 identity=dict(work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID)
 kwargs=dict(identity={k:v for k,v in identity.items() if k!='acquisition_id'},language='en',representation_revision='webster-book-label-diagnostic-v1',edition_title=TITLE,versification='source-native-webster',source_url=acq['url'],source_sha256=SOURCE_SHA,retained_sha256=SOURCE_SHA)
 observed=[]
 for label in ('1','Genesis'):
  book.set('n',label);before=etree.tostring(d,encoding='utf-8',xml_declaration=True);bound=bind_reviewed_header(before,expected_sha256=sha256(before).hexdigest(),identity=identity,source=source,source_url=acq['url'],declared_scope='Diagnostic first retained Webster verse only; not full work, not accepted candidate.',revision=dict(id='webster-book-label-diagnostic-v1',date='2026-10-02',note='Bounded actual supported route diagnostic.'))
  path=ROOT/LOG/('book-label-'+label+'.tei.xml');io_path(path).write_bytes(bound);projection=project_bible_document(io_path(path),**kwargs);errors=verify_bible_document(io_path(path),projection['rows'],projection['receipt'],**kwargs)
  if errors or len(projection['rows'])!=1 or projection['rows'][0]['locator']['book']!=label:raise ValueError((label,errors))
  observed.append(dict(input_book_n=label,public_locator=projection['rows'][0]['locator'],text=projection['rows'][0]['text'],tei_sha256=sha256(bound).hexdigest(),independent_errors=errors))
 proof=dict(status='pass',diagnostic_scope='One exact source-derived first verse and own current header only. This is not complete source acceptance evidence.',source_sha256=SOURCE_SHA,observed=observed,need='Existing generated n ordinal1 routes as book1 despite literal Genesis head; source-backed book n repair routes Genesis without verse/identity changes.',runtime_sha256=sha256((ROOT/'ocd_kernel/projection/categories/bible.py').read_bytes()).hexdigest())
 put(LOG/'book-label-route-probe.json',canonical(proof));print(json.dumps(proof))
if __name__=='__main__':main()
