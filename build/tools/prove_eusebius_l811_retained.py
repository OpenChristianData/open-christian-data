"""Fresh L811 whole-source readback or one intentional late-import negative."""
from pathlib import Path
import argparse,importlib.util,json,sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
HOME='sources/manifest-acquisitions/eusebius-l811-retained-install-20261004-v1'

def run_check(package,output=None,late=None):
    from ocd_kernel.reconstruction import SourceManifest,CandidatePackage
    from build.tools.reconstruct_candidate import _bound_callable
    source=SourceManifest.load(ROOT/(HOME+'/source-manifest.json'),repository_root=ROOT)
    candidate=CandidatePackage.load(package)
    function=_bound_callable(ROOT,source.record['validator'],role='validator')
    module=sys.modules[function.__module__]
    if late:
        path=Path(late).resolve(strict=True);original=module.guard;calls=[]
        def inject(manifest):
            calls.append(len(calls)+1)
            if len(calls)==2:
                spec=importlib.util.spec_from_file_location('_l811_unexpected_late',path)
                unexpected=importlib.util.module_from_spec(spec);sys.modules[spec.name]=unexpected;spec.loader.exec_module(unexpected)
                print(json.dumps(dict(checkpoint='after-full-source-and-P5-before-final-runtime-guard',late_module=path.as_posix())),flush=True)
            return original(manifest)
        module.guard=inject
    result=module.check(source,candidate)
    if output:
        p=Path(output)
        if p.exists():raise FileExistsError('Preserve earlier source proof: '+str(p))
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    return dict(status=result['status'],source_tomes=result['source_tomes'],complete_works=result['complete_authored_works'],actual_nodes=result['actual_source_carrier_nodes'],attributes=result['attributes_compared'],tei_sha256=result['actual_tei_sha256'],full_old_byte_inverse=result['full_old_tei_byte_inverse'])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True);parser.add_argument('--output');parser.add_argument('--late-import');args=parser.parse_args()
    try:print(json.dumps(run_check(args.package,args.output,args.late_import),sort_keys=True))
    except (ValueError,FileExistsError) as exc:
        print(json.dumps(dict(status='rejected',reason=str(exc)),ensure_ascii=True),file=sys.stderr);raise SystemExit(1)
