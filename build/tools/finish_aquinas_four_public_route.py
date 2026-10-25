"""Finish the saved projection probe after a work-local result-shape error."""
import json
from hashlib import sha256
from build.tools.prepare_aquinas_four_current import ROOT,LOG,BASE,WORK_ID,FORM_ID,EDITION_ID,canonical
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection import native_content
def main():
    path=ROOT/BASE/'header-renewal-candidate.tei.xml';saved=ROOT/LOG/'renewed-header-projection.json';result=json.loads(saved.read_bytes())
    terminal=json.loads((ROOT/LOG/'current-public-route-v3-terminal.json').read_bytes())
    if terminal['exit_code']!=1 or 'list indices must be integers' not in terminal['stderr']:raise ValueError('Exact own result-shape failure differs')
    def forbidden(*a,**kw):raise AssertionError('Producer disabled for independent check')
    native_content.project_content=forbidden;native_content.readable_content=forbidden;native_documents.project_document=forbidden
    kwargs=dict(identity=dict(work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID),language='en',representation_revision='aquinas-four-header-probe-v1',edition_title='Project Gutenberg four-component English witness (Parts I, I-II, II-II, III)',category='prose',_allow_acceptance_metadata=True)
    checked=native_documents.verify_document(path,result['rows'],result['receipt'],**kwargs)
    if checked:raise ValueError(checked)
    counts=dict(rows=len(result['rows']),text_characters=sum(len(row['text']) for row in result['rows']))
    (ROOT/LOG/'renewed-header-projection-check.json').write_bytes(canonical(dict(status='pass',producer_disabled=True,candidate_sha256=sha256(path.read_bytes()).hexdigest(),saved_projection_sha256=sha256(saved.read_bytes()).hexdigest(),errors=checked,counts=counts,failed_wrapper_terminal_sha256=sha256((ROOT/LOG/'current-public-route-v3-terminal.json').read_bytes()).hexdigest(),projection_repeated=False,qualification='Nonaccepted ordinary prose current-header route probe. First producer result saved unchanged; missing durable checker receipt renewed after list/dict result-shape mistake. This is not canonical acceptance or final actual-master release.')))
    print(json.dumps(dict(status='pass',**counts)),flush=True)
if __name__=='__main__':main()
