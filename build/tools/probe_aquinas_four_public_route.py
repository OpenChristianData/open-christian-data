"""Probe the existing native prose contract against the retained Aquinas handoff."""
from pathlib import Path
from hashlib import sha256
import json
from build.tools.preflight_aquinas_four_current import ROOT,LOG,CANDIDATE,WORK
from ocd_kernel.projection.categories.native_documents import project_document,verify_document
from ocd_kernel.library._common import PipelineError
def main():
    pin=['schemas/v2/native-content.schema.json','schemas/v2/categories/prose.schema.json','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/categories/native_documents.py','ocd_kernel/projection/source_projection_evidence.py']
    record=dict(candidate_sha256=sha256((ROOT/CANDIDATE).read_bytes()).hexdigest(),dependencies={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in pin})
    kwargs=dict(identity=dict(work_id=WORK,textual_form_id=WORK+'-gutenberg-retained-en',edition_id=WORK+'-gutenberg-electronic'),language='en',representation_revision='aquinas-four-retained-probe-v1',edition_title='Project Gutenberg four-component English witness (Parts I, I-II, II-II, III)',category='prose')
    try:
        result=project_document(ROOT/CANDIDATE,**kwargs)
        record.update(status='pass',rows=len(result['rows']))
    except (ValueError,PipelineError) as error:
        record.update(status='located-route-gap',error_type=type(error).__name__,error=str(error))
    path=LOG/'public-route-probe.json'
    if path.exists():raise FileExistsError(path)
    path.write_bytes((json.dumps(record,indent=2,sort_keys=True)+'\n').encode())
    print(json.dumps(record))
if __name__=='__main__':main()
