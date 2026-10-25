"""One complete-source regression: replay and loss/attachment mutations."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest
from build.tei.wikisource_l594_complete_oracle import findings

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL_MANIFEST=ROOT/'sources/manifest-acquisitions/wikisource-chrysostom-l594/source-manifest-complete.json'
MANIFEST=ROOT/'tests/fixtures/reconstruction-runtime/wikisource-l594-complete.source-manifest.json'
T='{http://www.tei-c.org/ns/1.0}'

def test_complete_replay_and_source_carrier_mutations(tmp_path):
    manifest=SourceManifest.load(MANIFEST,repository_root=ROOT)
    outputs=[]
    for name in ['first','second']:
        out=tmp_path/name
        run=subprocess.run([sys.executable,'-m','build.tools.reconstruct_candidate','--manifest',MANIFEST.relative_to(ROOT).as_posix(),'--repository-root',str(ROOT),'--destination',str(out)],cwd=ROOT,capture_output=True,text=True,check=True)
        assert json.loads(run.stdout.splitlines()[-1])['status']=='pass'
        outputs.append({p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()})
    assert outputs[0]==outputs[1]
    raw=(tmp_path/'first/package/content.tei.xml').read_bytes()
    assert findings(manifest,raw)==[]
    mutations=[]
    x=etree.fromstring(raw);node=x.find('.//'+T+'body//'+T+'p');node.text='INVENTED';mutations.append(x)
    x=etree.fromstring(raw);row=x.find('.//'+T+'row');row.getparent().remove(row);mutations.append(x)
    x=etree.fromstring(raw);pb=x.find('.//'+T+'pb');pb.set('n','999');mutations.append(x)
    x=etree.fromstring(raw);graphic=x.find('.//'+T+'graphic');graphic.set('url','https://example.invalid/other.png');mutations.append(x)
    for x in mutations:
        assert findings(manifest,etree.tostring(x)), 'source-carrier mutation passed'

def test_complete_native_public_projection(tmp_path):
    from copy import deepcopy
    from ocd_kernel.projection.categories.liturgies import project_liturgies_document,verify_liturgies_document
    from ocd_kernel.projection.categories.liturgies_chrysostom import PROFILE,IDENTITY
    from build.tei.wikisource_l594_complete import _convert
    path=tmp_path/'complete.tei.xml'
    path.write_bytes(_convert(SourceManifest.load(MANIFEST,repository_root=ROOT))['content.tei.xml'])
    context=dict(identity=IDENTITY,language='en',representation_revision='chrysostom-liturgy-complete-1866-v1',edition_title='Service of the Divine and Sacred Liturgy of our Holy Father John Chrysostom',projection_profile=PROFILE)
    projected=project_liturgies_document(path,**context)
    assert len(projected['rows'])==2
    assert verify_liturgies_document(path,projected['rows'],projected['receipt'],**context)==[]
    public=json.dumps(projected['rows'])
    assert 'Liturgy_of_John_Chrysostom_diagram.png' in public
    assert 'IC_XC_NI_KA_-_Liturgy_of_John_Chrysostom.png' in public
    assert 'The Holy Lamb.' in public and 'Portions for the dead.' in public
    altered=deepcopy(projected['rows']);altered[0]['text']='invented'
    assert verify_liturgies_document(path,altered,projected['receipt'],**context)
    altered=deepcopy(projected['rows']);altered[0]['structure']=[]
    assert verify_liturgies_document(path,altered,projected['receipt'],**context)
    assert verify_liturgies_document(path,list(reversed(projected['rows'])),projected['receipt'],**context)


def test_complete_accepted_source_support_binding(tmp_path):
    from copy import deepcopy
    import pytest
    from ocd_kernel.library._common import PipelineError
    from ocd_kernel.projection.categories.liturgies_chrysostom import IDENTITY,accepted_source_member
    aid='chrysostom-divine-and-sacred-liturgy-wikisource-complete-20261007'
    work=ROOT/'library/works'/IDENTITY['work_id']
    path=work/'forms'/IDENTITY['textual_form_id']/'editions'/IDENTITY['edition_id']/'acquisitions'/(aid+'.json')
    acq=json.loads(path.read_bytes())
    source={key:acq[key] for key in ('source_path','source_sha256','source_bytes')}
    included=[dict(item,position=i) for i,item in enumerate(acq['retained_files'],1)]
    for item in included:
        dest=tmp_path/item['path'];dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes((ROOT/item['path']).read_bytes())
    assert accepted_source_member(tmp_path,IDENTITY,acq,source,included)['sha256']==acq['source_sha256']
    with pytest.raises(PipelineError):accepted_source_member(tmp_path,IDENTITY,acq,source,included[:-1])
    altered=deepcopy(included);altered[0]['sha256']='0'*64
    with pytest.raises(PipelineError):accepted_source_member(tmp_path,IDENTITY,acq,source,altered)
    (tmp_path/included[-1]['path']).write_bytes(b'changed image')
    with pytest.raises(PipelineError):accepted_source_member(tmp_path,IDENTITY,acq,source,included)


def test_runtime_manifest_preserves_the_complete_source_record():
    from build.tei.wikisource_l594_complete_oracle import closure
    original_raw = ORIGINAL_MANIFEST.read_bytes()
    assert hashlib.sha256(original_raw).hexdigest() == "02ca0f37157f49f29a9d80e8b4e9d84f3e268d06293e077d3d833d14ab5192d3"
    expected = json.loads(original_raw)
    expected["validator"]["import_closure_sha256"] = closure(ROOT)
    assert json.loads(MANIFEST.read_bytes()) == expected
