"""Prove the current ordinary prose producer and disabled-producer checker route."""
from pathlib import Path
from hashlib import sha256
import json
from build.tools.prepare_aquinas_four_current import ROOT,LOG,BASE,WORK_ID,FORM_ID,EDITION_ID,canonical
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection import native_content
def main():
    path=ROOT/BASE/'header-renewal-candidate.tei.xml'
    kwargs=dict(identity=dict(work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID),language='en',representation_revision='aquinas-four-header-probe-v1',edition_title='Project Gutenberg four-component English witness (Parts I, I-II, II-II, III)',category='prose',_allow_acceptance_metadata=True)
    result=native_documents.project_document(path,**kwargs)
    (ROOT/LOG/'renewed-header-projection.json').write_bytes(canonical(result))
    def forbidden(*a,**kw):raise AssertionError('Producer disabled for independent check')
    native_content.project_content=forbidden;native_content.readable_content=forbidden
    checked=native_documents.verify_document(path,result['rows'],result['receipt'],**kwargs)
    if checked['status']!='pass':raise ValueError(checked)
    counts=dict(rows=len(result['rows']),text_characters=sum(len(row['text']) for row in result['rows']))
    (ROOT/LOG/'renewed-header-projection-check.json').write_bytes(canonical(dict(status='pass',producer_disabled=True,candidate_sha256=sha256(path.read_bytes()).hexdigest(),saved_projection_sha256=sha256((ROOT/LOG/'renewed-header-projection.json').read_bytes()).hexdigest(),check=checked,counts=counts,qualification='Nonaccepted current-header route probe, not canonical acceptance or final actual-master release.')))
    print(json.dumps(dict(status='pass',**counts)),flush=True)
if __name__=='__main__':main()
