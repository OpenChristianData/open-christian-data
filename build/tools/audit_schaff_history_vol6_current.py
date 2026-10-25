"""Bound work-local preimages, replay, and literal CSS in the normal public route."""
from hashlib import sha256
import json
from pathlib import Path
from copy import deepcopy
from lxml import etree
from build.tools.prepare_schaff_history_vol6_current import ROOT,WORK,BASE,SOURCE,SOURCE_SHA,canonical
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.projection.categories.native_documents import project_document,verify_document

LOGS=Path('reports/_logs/schaff-history-vol-6-reconciliation-20261001-v1')
CANDIDATE=Path('D:/Library/Open Christian Data/candidate-reviews/schaff-history-vol6-current-20261001-v1')
REPLAY=Path('D:/Library/Open Christian Data/candidate-reviews/schaff-history-vol6-current-20261001-replay-v1')

def write(name,value):
    p=io_path(ROOT/LOGS/name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(canonical(value))

def main():
    pre=io_path(ROOT/LOGS/'canonical-preimage.json')
    own=_files(ROOT/WORK);siblings={}
    for w in ('schaff-history-vol-1','schaff-history-vol-2','schaff-history-vol-3','schaff-history-vol-4','schaff-history-vol-5'):
        files=_files(ROOT/'library/works'/w)
        siblings[w]={p:h for p,h in files.items() if not p.startswith('publication/')}
    historical=[Path('build/tei/schaff_history_vol6_reconstruction.py'),Path('sources/structured-text/schaff-history-vol-6/schaff-history-vol-6.source-manifest.json')]
    preimage=dict(status='pinned',own=own,sibling_authorities=siblings,
        live_sibling_owners={'schaff-history-vol-4':'prayers_baths_resume','schaff-history-vol-5':'gregory_reccared_resume'},
        source_sha256=SOURCE_SHA,historical_line_route_preserved={p.as_posix():sha256(io_path(ROOT/p).read_bytes()).hexdigest() for p in historical})
    if pre.exists():
        retained=json.loads(pre.read_bytes())
        if any(retained[k]!=preimage[k] for k in ('own','source_sha256','historical_line_route_preserved')):raise ValueError('pinned own/source/historical preimage changed')
    else:write('canonical-preimage.json',preimage)
    a=CandidatePackage.load(CANDIDATE/'package');b=CandidatePackage.load(REPLAY/'package')
    members={n:sha256(a.member_bytes(n)).hexdigest() for n in a.member_names}
    if a.sha256!=b.sha256 or any(a.member_bytes(n)!=b.member_bytes(n) for n in a.member_names) or (CANDIDATE/'validation.json').read_bytes()!=(REPLAY/'validation.json').read_bytes():raise ValueError('fresh source replay differs')
    processes=[json.loads((r/'process.json').read_bytes()) for r in (CANDIDATE,REPLAY)]
    if len({p['pid'] for p in processes})!=2 or any(p['exit_code']!=0 or p['candidate_sha256']!=a.sha256 for p in processes):raise ValueError('fresh process binding differs')
    write('fresh-process-exact-replay.json',dict(status='pass',candidate=CANDIDATE.as_posix(),replay=REPLAY.as_posix(),candidate_sha256=a.sha256,member_hashes=members,validation_sha256=sha256((CANDIDATE/'validation.json').read_bytes()).hexdigest(),processes=processes,authoritative_exit_codes=[0,0]))
    context=dict(identity=dict(work_id='schaff-history-vol-6',textual_form_id='schaff-history-vol-6-retained-electronic',edition_id='schaff-history-vol-6-retained-electronic-witness'),language='en',representation_revision='schaff-history-vol-6-electronic-v1',edition_title='Christian Classics Ethereal Library retained electronic witness',category='prose',_allow_acceptance_metadata=True)
    path=CANDIDATE/'package/content.tei.xml';result=project_document(path,**context);errors=verify_document(path,result['rows'],result['receipt'],**context)
    if errors or len(result['rows'])!=4:raise ValueError(errors or 'not four complete body roots')
    source=etree.fromstring(io_path(ROOT/SOURCE).read_bytes(),etree.XMLParser(huge_tree=True));css=source.xpath('ThML.body//*[@style]')
    def native_nodes(value):
        if isinstance(value,dict):
            if value.get('kind') and value['kind']!='text':yield value
            for child in value.values():yield from native_nodes(child)
        elif isinstance(value,list):
            for child in value:yield from native_nodes(child)
    tei=etree.fromstring(path.read_bytes(),etree.XMLParser(huge_tree=True));body=tei.find('{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body')
    mapped=list(body.iter())[1:];public_nodes=[n for row in result['rows'] for n in native_nodes(row['structure'])]
    if len(mapped)!=len(public_nodes):raise ValueError(f'public ordered element envelope differs: TEI={len(mapped)} public={len(public_nodes)}; first={public_nodes[0]}')
    positions={n.get('{http://www.w3.org/XML/1998/namespace}id'):i for i,n in enumerate(mapped)}
    observed={key:public_nodes[position] for key,position in positions.items() if key}
    disposition=[]
    for n in css:
        public=observed[n.get('id')]['attributes'];is_heading=n.tag.startswith('h')
        key='source_annotations' if is_heading else 'css_style';expected='source-css:'+n.get('style') if is_heading else n.get('style')
        if public.get(key)!=expected or public.get('style')!=n.get('class'):raise ValueError('literal class/CSS public mapping differs '+n.get('id'))
        disposition.append(dict(source_id=n.get('id'),source_tag=n.tag,source_class=n.get('class'),source_style=n.get('style'),public_attributes=public))
    if len(disposition)!=14:raise ValueError('CSS census differs')
    # Verify the saved public representation itself rejects loss/change/invention,
    # independently of the source-led TEI oracle mutation suite.
    challenges=[]
    for key in ('style','source_annotations'):
        for change in ('omission','change'):
            altered=deepcopy(result['rows']);node=[n for row in altered for n in native_nodes(row['structure'])][positions['i-p0.11']]
            if change=='omission':del node['attributes'][key]
            else:node['attributes'][key]='invented'
            findings=verify_document(path,altered,result['receipt'],**context)
            if not findings:raise ValueError('saved public CSS mutation accepted')
            challenges.append(dict(attribute=key,mutation=change,errors=findings))
    for key in ('style','source_annotations'):
        altered=deepcopy(result['rows']);node=[n for row in altered for n in native_nodes(row['structure'])][positions['i']]
        if key in node['attributes']:raise ValueError('invention fixture already carries attribute')
        node['attributes'][key]='invented';findings=verify_document(path,altered,result['receipt'],**context)
        if not findings:raise ValueError('saved public invented CSS accepted')
        challenges.append(dict(attribute=key,mutation='invention',errors=findings))
    write('whole-candidate-projection.json',result)
    write('literal-class-css-public-proof.json',dict(status='pass',source_sha256=SOURCE_SHA,candidate_sha256=sha256(path.read_bytes()).hexdigest(),rows=4,independent_errors=errors,literal_css=disposition,saved_public_mutation_rejections=challenges))
    print(json.dumps(dict(status='pass',css=14,public_mutations=len(challenges),rows=4,processes=processes)))
if __name__=='__main__':main()
