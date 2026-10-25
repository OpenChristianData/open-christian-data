"""Bounded source-candidate preparation; never writes library identities/state."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from build.tei import tyerman_whitefield_complete_oracle as oracle
from ocd_kernel.reconstruction import SourceManifest

SOURCE = ROOT / 'sources/manifest-acquisitions/tyerman-life-george-whitefield-complete-20261004-v3'
LOG = ROOT / 'reports/_logs/tyerman-whitefield-complete-20261004-v1'


def enc(v):
    return (json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def pin(path):
    p = ROOT / path
    data = p.read_bytes()
    return {'path': path, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def authority_paths():
    return oracle.authority_spec()


def prepare():
    if SOURCE.exists():
        raise ValueError('Source successor already exists: preserve; explicitly version any revision')
    SOURCE.mkdir(parents=True)
    (SOURCE/'profile.json').write_bytes(enc(oracle.expected_profile()))
    (SOURCE/'policy.json').write_bytes(enc(oracle.expected_policy()))
    (SOURCE/'execution-runtime.json').write_bytes(enc({'draft':'execution capture not yet performed; final guarded call rejects this placeholder'}))
    readme = '''# L635: retained complete Tyerman Whitefield biography

The Life of the Rev. George Whitefield, B.A., by L. Tyerman. London: Hodder
and Stoughton, volumes I (MDCCCLXXVI, 1876) and II (MDCCCLXXVII, 1877).
The primary title pages explicitly identify one work in two volumes.

Sourced from the exact already downloaded Project Gutenberg eBooks 44280
and 62023 and their retained ZIP archives. Preserve all Gutenberg credits,
license/contact notices, the transcriber's statements and electronic readings.
Source statements of public domain in the USA are retained, not rights clearance.
Do not infer acceptance, worldwide rights, disclosure approval or publication.

Both exact historical v4 TEIs and their six-member packages/proof receipts
remain unchanged in retained-components evidence. The old assertion that the
volumes are distinct complete works is superseded only for this successor.
The current candidate is a source-backed repaired representation, not an
additive whole-body byte inverse. Existing component normalized wording and
whole native field fingerprints are separately bound; current fidelity rests
on the independent full actual-object source inverse.

All front/context matter is retained, including the John Wesley advertisement;
the biography's quoted letters/journals do not become separate works. Provider
headers and full hierarchical linked footers remain volume-owned. All raw
HTML head/styles/prolog and original candidate headers are visible source
annotations. Literal inline styles are retained as TEI style; CSS classes and
the full stylesheet are retained, but identical CSS rendering is not claimed.
Figure ownership/caption targets, actual literal languages, abbreviation
expansions, tooltip notices, table summary labels and two source-height 2em
brace occurrences are explicit native semantics. Tbody wrapper fields and row
ownership are explicitly losslessly accounted; no invented table layout.

Each volume's IDs/internal fragment links are reversibly volume-qualified.
Actual source HTML URLs and original acquired catalog/package URLs are bound.
Graphics contain exact retained image bytes and exact archive-member identity;
the Volume I cover remains archive/head support, not invented body content.
Source defects and electronic corrections remain; no print collation, CVW
review or reconstruction of original print typography is claimed. Actual image
pixels were inspected only for the five unique retained assets.
'''
    (SOURCE/'README.source.md').write_text(readme,encoding='utf-8')
    converter=pin('build/tei/tyerman_whitefield_complete.py')
    validator=pin('build/tei/tyerman_whitefield_complete_oracle.py')
    schema=pin('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json')
    manifest={'contract':'ocd-source-manifest-v1','work_id':oracle.WORK,'source_id':'gutenberg-44280-62023-retained-biography','manifest_row':'L635','scope':oracle.SCOPE,'source_order':list(oracle.DATA),'authorities':[{'name':name,'role':role,**pin(path)} for name,path,role in authority_paths()], 'converter':{'id':'ocd-l635-retained-complete-whitefield-biography','version':'1','callable':'_convert','implementation_path':converter['path'],'implementation_sha256':converter['sha256']},'validator':{'id':oracle.ORACLE_ID,'version':'1','callable':'_oracle','implementation_path':validator['path'],'implementation_sha256':validator['sha256'],'import_closure_sha256':oracle.closure()},'package_schema':{'path':schema['path'],'sha256':schema['sha256']}}
    (SOURCE/'source-manifest.json').write_bytes(enc(manifest))
    SourceManifest.load(SOURCE/'source-manifest.json',repository_root=ROOT)
    return {'source_files':[pin((SOURCE/name).relative_to(ROOT).as_posix()) for name in ['source-manifest.json','profile.json','policy.json','README.source.md']], 'converter':converter,'oracle':validator,'producer_import_closure':oracle.closure('producer'),'oracle_import_closure':manifest['validator']['import_closure_sha256'],'status':'draft-source-contract-prepared-not-yet-proven'}


def prototype():
    from build.tei.tyerman_whitefield_complete import _build
    manifest=SourceManifest.load(SOURCE/'source-manifest.json',repository_root=ROOT)
    output=_build(manifest)
    target=ROOT/'.tmp_audit/tyerman-whitefield-complete-prototype-v3'
    if target.exists():raise ValueError('Preserve existing prototype')
    target.mkdir(parents=True)
    for name,data in output.items():(target/name).write_bytes(data)
    profile=json.loads((SOURCE/'profile.json').read_bytes())
    results=oracle.check_content(output['content.tei.xml'],profile)
    return {'status':'draft-native-source-inverse-and-P5-pass','prototype':str(target),'actual_source_inverse':results,'tei':pin((target/'content.tei.xml').relative_to(ROOT).as_posix())}


def capture():
    directory=ROOT/'.tmp_audit/tyerman-whitefield-runtime-capture-v3b'
    if directory.exists():raise ValueError('Preserve existing runtime capture')
    directory.mkdir(parents=True)
    record=json.loads((SOURCE/'source-manifest.json').read_bytes())
    (directory/'predecessor-source-manifest.json').write_bytes((SOURCE/'source-manifest.json').read_bytes())
    for role in ['converter','validator']:
        record[role]['implementation_sha256']=pin(record[role]['implementation_path'])['sha256']
    record['validator']['import_closure_sha256']=oracle.closure()
    record['authorities']=[{'name':name,'role':role,**pin(p)} for name,p,role in authority_paths()]
    (SOURCE/'source-manifest.json').write_bytes(enc(record))
    record['converter']['callable']='_build';record['validator']['callable']='_inspect'
    path=directory/'source-manifest.json';path.write_bytes(enc(record))
    destination='D:/Library/Open Christian Data/candidate-reviews/tyerman-whitefield-runtime-capture-20261004-v3b'
    program='''import json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root))
import build.tools.prepare_tyerman_whitefield_complete
import build.tools.prove_tyerman_whitefield_complete
from build.tools.reconstruct_candidate import run
from build.tei.tyerman_whitefield_runtime import observed
result=run(manifest=sys.argv[2],destination=sys.argv[3],repository_root=str(root))
print(json.dumps({'qualification':'Execution admission capture only. Unguarded core callables explicitly bound in scratch; not final guarded source proof or acceptance.','cli':result,'observed_complete_execution':observed()},sort_keys=True))'''
    result=subprocess.run([sys.executable,'-I','-B','-c',program,str(ROOT),path.relative_to(ROOT).as_posix(),destination],capture_output=True,text=True)
    (directory/'stdout.txt').write_text(result.stdout,encoding='utf-8');(directory/'stderr.txt').write_text(result.stderr,encoding='utf-8')
    if result.returncode!=0:raise ValueError('Execution admission capture exited '+str(result.returncode)+': '+result.stderr[-1000:])
    receipt=json.loads(result.stdout)
    (LOG/'complete-execution-admission-capture-v3b.json').write_bytes(enc(receipt))
    (SOURCE/'execution-runtime.json').write_bytes(enc(receipt['observed_complete_execution']))
    final=json.loads((SOURCE/'source-manifest.json').read_bytes())
    final['authorities']=[{'name':name,'role':role,**pin(p)} for name,p,role in authority_paths()]
    (SOURCE/'source-manifest.json').write_bytes(enc(final))
    return {'status':'guarded-source-contract-prepared-from-complete-execution-admission','execution_files':len(receipt['observed_complete_execution']['files']),'runtime':pin((SOURCE/'execution-runtime.json').relative_to(ROOT).as_posix()),'source_manifest':pin((SOURCE/'source-manifest.json').relative_to(ROOT).as_posix())}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','prototype','capture']);args=p.parse_args()
    print(json.dumps({'prepare':prepare,'prototype':prototype,'capture':capture}[args.action](),ensure_ascii=False,sort_keys=True))
