"""Scoped valid feature challenges and two fresh six-member Isaiah replays."""
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
import json,subprocess,sys
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from lxml import etree
from build.tei.smith_isaiah_complete_oracle import ROOT,WORK,KEY,MEMBERS,NS,XML,check,oracle,closure,canonical
from build.tools.prepare_smith_isaiah_complete import SOURCE,LOG,DESTINATION
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,validate

def sha(raw):return sha256(raw).hexdigest()
def write(path,value):
    target=ROOT/path
    if target.exists():raise FileExistsError('Preserve Isaiah proof: '+str(target))
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(canonical(value))

def main():
    source=SourceManifest.load(ROOT/SOURCE/'source-manifest.json',repository_root=ROOT);package=CandidatePackage.load(DESTINATION/'package')
    baseline=validate(source,package,oracle);direct=check(source,package)
    proof=DESTINATION/'proof-v2';proof.mkdir(exist_ok=False)
    root=etree.fromstring(package.member_bytes('content.tei.xml'));schema=etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))
    labels=('volume-order','volume-identity','volume-base','extra-volume','omit-front','omit-back','body-extra-div','root-extra-text','header-title','source-header-field','source-document-prefix','source-uri-note','paragraph-text','inline-tail','inline-role','note-attachment','page-number','relative-query-target','anonymous-relative-target','local-target','table-cell-text','table-cell-span','graphic-url','graphic-alt','style-attribute','volume-base-scope','outer-header-tail')
    mutations=[]
    for label in labels:
        changed=deepcopy(root);g=changed.find(NS+'text/'+NS+'group');volumes=list(g)
        if label=='volume-order':first=g[0];g.remove(first);g.insert(1,first)
        elif label=='volume-identity':g[0].set(XML+'id','smith-isaiah-unretained-volume')
        elif label=='volume-base':g[0].set(XML+'base','https://invalid.example/wrong/')
        elif label=='extra-volume':
            extra=etree.SubElement(g,NS+'text',{XML+'lang':'en'});body=etree.SubElement(extra,NS+'body');div=etree.SubElement(body,NS+'div');etree.SubElement(div,NS+'p').text='Invented third volume'
        elif label in {'omit-front','omit-back'}:g[0].remove(g[0].find(NS+label.removeprefix('omit-')))
        elif label=='body-extra-div':div=etree.SubElement(g[1].find(NS+'body'),NS+'div');etree.SubElement(div,NS+'p').text='Invented body payload'
        elif label=='root-extra-text':
            extra=etree.SubElement(changed,NS+'text');body=etree.SubElement(extra,NS+'body');div=etree.SubElement(body,NS+'div');etree.SubElement(div,NS+'p').text='Invented outer readable sibling'
        elif label=='header-title':changed.find('.//'+NS+'titleStmt/'+NS+'title').text+=' CHANGED'
        elif label=='source-header-field':changed.find('.//'+NS+'note[@type="retained-source-head-field"]').text+=' CHANGED'
        elif label=='source-document-prefix':changed.find('.//'+NS+'note[@type="retained-source-document-prefix"]').text+=' CHANGED'
        elif label=='source-uri-note':changed.find('.//'+NS+'note[@type="retained-source-uri-context"]').text='https://invalid.example/'
        elif label=='paragraph-text':next(n for n in g[0].iter(NS+'p') if n.text).text+=' CHANGED'
        elif label=='inline-tail':next(n for n in g[1].iter(NS+'hi') if n.tail).tail+=' CHANGED'
        elif label=='inline-role':next(n for n in g[0].iter(NS+'hi') if n.get('rend')).set('rend','wrong-inline-role')
        elif label=='note-attachment':
            n=next(g[1].iter(NS+'note'));n.getparent().remove(n);next(g[0].iter(NS+'p')).append(n)
        elif label=='page-number':next(g[1].iter(NS+'pb')).set('n','unretained-page')
        elif label in {'relative-query-target','anonymous-relative-target'}:
            refs=[n for n in g.iter(NS+'ref') if (n.get('target') or '').startswith('?')]
            n=next(n for n in refs if '-feature-' in n.get(XML+'id')) if label.startswith('anonymous') else refs[0];n.set('target',n.get('target')+'&invented=1')
        elif label=='local-target':next(n for n in g[0].iter(NS+'ref') if (n.get('target') or '').startswith('#')).set('target','#unretained-local-destination')
        elif label=='table-cell-text':next(n for n in g.iter(NS+'cell') if n.text).text+=' CHANGED'
        elif label=='table-cell-span':next(g.iter(NS+'cell')).set('cols','7')
        elif label=='graphic-url':next(g.iter(NS+'graphic')).set('url','unretained-image.png')
        elif label=='graphic-alt':next(g.iter(NS+'figDesc')).text+=' CHANGED'
        elif label=='style-attribute':next(n for n in g.iter() if n.get('style')).set('style','color: purple')
        elif label=='volume-base-scope':del g[0].attrib[XML+'base'];g.set(XML+'base','https://invalid.example/')
        elif label=='outer-header-tail':changed.find(NS+'teiHeader').tail='\n '
        if etree.tostring(changed)==etree.tostring(root):raise ValueError('Challenge did not change actual document: '+label)
        schema.assertValid(changed)
        target=proof/('challenge-'+label);target.mkdir()
        for name in package.member_names:(target/name).write_bytes(package.member_bytes(name))
        raw=etree.tostring(changed,encoding='UTF-8',xml_declaration=True);(target/'content.tei.xml').write_bytes(raw)
        manifest=json.loads((target/'manifest.json').read_bytes())
        for r in manifest['members']:
            if r['name']=='content.tei.xml':r.update(bytes=len(raw),sha256=sha(raw))
        (target/'manifest.json').write_bytes(canonical(manifest));mutant=CandidatePackage.load(target)
        try:validate(source,mutant,oracle)
        except ValueError as error:mutations.append(dict(label=label,schema_valid=True,rejected=True,reason=str(error),candidate_package_sha256=mutant.sha256))
        else:raise ValueError('Isaiah valid feature challenge admitted: '+label)
        print(json.dumps(dict(challenge=label,p5='pass',rejected=True)),flush=True)
    replays=[]
    for number in (1,2):
        target=proof/('fresh-replay-'+str(number));script='''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from build.tei.smith_isaiah_complete_prepare import convert
from ocd_kernel.reconstruction import SourceManifest,reconstruct
source=SourceManifest.load(sys.argv[2],repository_root=sys.argv[1])
print(reconstruct(source,sys.argv[3],convert).sha256)'''
        process=subprocess.run([sys.executable,'-I','-B','-c',script,str(ROOT),str(source.path),str(target)],check=True,capture_output=True,text=True)
        replay=CandidatePackage.load(target)
        if replay.sha256!=package.sha256 or any(replay.member_bytes(name)!=package.member_bytes(name) for name in package.member_names):raise ValueError('Fresh Isaiah six-member byte replay differs')
        replays.append(dict(number=number,path=target.as_posix(),exit_code=process.returncode,package_sha256=replay.sha256,all_six_members_byte_equal=True))
    negatives=[]
    for module,unexpected in [('build.tei.smith_isaiah_complete_oracle','build.tei.smith_isaiah_complete_prepare'),('build.tei.smith_isaiah_complete_prepare','build.tei.smith_isaiah_source_oracle')]:
        try:closure(module,unexpected)
        except ValueError as error:negatives.append(dict(module=module,unexpected=unexpected,rejected=True,reason=str(error)))
        else:raise ValueError('Fresh first-party import negative admitted')
    # Separate source/actual-native image context check; no pixels fetched/inferred.
    graphic_contexts=[];g=root.find(NS+'text/'+NS+'group')
    for member,volume in zip(MEMBERS,g,strict=True):
        raw=source.authority_path(member+'-raw').read_bytes();primary=ET.fromstring(raw);body=primary.find('ThML.body');images=list(body.iter('img'));actual=list(volume.iter(NS+'graphic'))
        if len(images)!=len(actual):raise ValueError('Native image source pointer census differs')
        for ordinal,(s,a) in enumerate(zip(images,actual,strict=True),1):
            if a.get('url')!=s.get('src') or urljoin(volume.get(XML+'base'),a.get('url'))!=urljoin(json.loads(source.authority_path(member+'-acquisition').read_bytes())['url'],s.get('src')):raise ValueError('Actual source image URI context differs')
            graphic_contexts.append(dict(member_id=member,ordinal=ordinal,literal_source_url=s.get('src'),actual_graphic_url=a.get('url'),base=volume.get(XML+'base'),resolved=urljoin(volume.get(XML+'base'),a.get('url')),pixels='not-acquired-or-reviewed'))
    assessment=json.loads(source.authority_path('scope-assessment').read_bytes())
    if {p:sha((ROOT/'library/works'/WORK/p).read_bytes()) for p in assessment['canonical_files_before']}!=assessment['canonical_files_before']:raise ValueError('Canonical preimage changed during source proof')
    record=dict(status='pass',complete_works=1,source_volumes=2,source_manifest_path=(SOURCE/'source-manifest.json').as_posix(),source_manifest_sha256=source.sha256,candidate_package_path=package.path.as_posix(),candidate_package_sha256=package.sha256,oracle_report_sha256=baseline.sha256,oracle_attestation=dict(baseline.attestation),direct_source_review=direct,mutations=mutations,replays=replays,closure_negatives=negatives,source_image_uri_contexts=graphic_contexts,canonical_preimage_exact=True,canonical_installation='not-performed',proof_implementation_sha256=sha(Path(__file__).read_bytes()))
    path=LOG/'candidate-completion-receipt-v3.json';write(path,record)
    print(json.dumps(dict(status='pass',mutations=len(mutations),fresh_six_member_replays=2,proof_path=path.as_posix(),proof_sha256=sha((ROOT/path).read_bytes()),package_sha256=package.sha256)),flush=True)
if __name__=='__main__':main()
