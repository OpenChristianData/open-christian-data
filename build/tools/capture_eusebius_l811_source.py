"""Observed L811 bootstrap only; freeze exact executed paths after completion."""
from pathlib import Path
from hashlib import sha256
import argparse,json,sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
HOME='sources/manifest-acquisitions/eusebius-l811-retained-install-20261004-v1'
LOG='reports/_logs/eusebius-l811-existing-install-20261004-v1'

def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha(v):return sha256(v).hexdigest()
def fresh(path,raw):
    p=ROOT/path
    if p.exists():raise FileExistsError('Preserve L811 capture: '+str(p))
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
def inventory():
    from ocd_kernel.lib.path_io import resolve_path
    root=resolve_path(ROOT,strict=True);library=resolve_path(Path('D:/Library/Open Christian Data'),strict=True)
    paths={resolve_path(Path(m.__file__),strict=True) for m in sys.modules.copy().values() if getattr(m,'__file__',None)}
    first=[];external=[]
    for p in sorted(paths,key=str):
        row=dict(bytes=p.stat().st_size,sha256=sha(p.read_bytes()))
        if p.is_relative_to(root):first.append(dict(path=p.relative_to(root).as_posix(),**row))
        elif p.is_relative_to(library):
            relative=p.relative_to(library)
            if relative.parts[0] not in ('reports','raw','exports'):raise ValueError('Unrouted physical Library execution: '+str(p))
            first.append(dict(path=relative.as_posix(),**row))
        else:external.append(dict(path=p.as_posix(),**row))
    p=resolve_path(Path(sys.executable),strict=True)
    return dict(first_party_files=first,external_runtime_files=external,runtime_executable=dict(path=p.as_posix(),bytes=p.stat().st_size,sha256=sha(p.read_bytes())))

def bootstrap(destination):
    from build.tools import reconstruct_candidate as cli
    from build.tools import prove_eusebius_l811_retained as proof
    approved=ROOT/(LOG+'/root-source-contract-successor-review-v2.json')
    if sha(approved.read_bytes())!='d5355cedc1d1c8c7a271d6b14d066d5d3ee258465b9d63c68483e7b8b9793377':raise ValueError('Root execution release pin differs')
    snapshots=[];loader=cli._bound_callable
    def recording_loader(*args,**kwargs):
        result=loader(*args,**kwargs);module=sys.modules[result.__module__]
        def record(source):
            observed=inventory();snapshots.append(dict(role=kwargs['role'],inventory=observed))
            return [r['path'] for r in observed['first_party_files']+observed['external_runtime_files']]
        module.guard=record;return result
    cli._bound_callable=recording_loader
    summary=cli.run(manifest=HOME+'/source-manifest.json',destination=destination,repository_root=str(ROOT))
    package=ROOT/destination/'package'
    readback=proof.run_check(package)
    observed=inventory()
    fresh(LOG+'/source-execution-capture-v1.json',enc(dict(status='bootstrap-observed-not-validation',supported_cli_summary=summary,bootstrap_source_readback=readback,guard_snapshots=snapshots,final_inventory=observed,qualification='Only in-memory producer/oracle guard callables were replaced with recording for bootstrap observation. No final guarded validation claim. All current source checks ran; only actual physical __file__ paths and external/executable files are inventoried.')))
    runtime=ROOT/(HOME+'/runtime.json');manifest=ROOT/(HOME+'/source-manifest.json')
    fresh(LOG+'/runtime-before-observed-capture-v1.json',runtime.read_bytes());fresh(LOG+'/source-manifest-before-observed-capture-v1.json',manifest.read_bytes())
    runtime.write_bytes(enc(dict(contract='ocd-l811-observed-source-runtime-v1',status='frozen',**observed)))
    record=json.loads(manifest.read_bytes())
    for row in record['authorities']:
        if row['name']=='runtime':row.update(bytes=runtime.stat().st_size,sha256=sha(runtime.read_bytes()))
    record['validator']['import_closure_sha256']=sha(runtime.read_bytes());manifest.write_bytes(enc(record))
    return dict(status='observed-bootstrap-frozen-pending-strict-validation',first_party_files=len(observed['first_party_files']),external_runtime_files=len(observed['external_runtime_files']),runtime_sha256=sha(runtime.read_bytes()),source_manifest_sha256=sha(manifest.read_bytes()))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True);args=parser.parse_args();print(json.dumps(bootstrap(args.destination),sort_keys=True))
