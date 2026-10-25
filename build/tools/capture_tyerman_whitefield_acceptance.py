"""Capture actual acceptance execution separately from the frozen source process.

The bootstrap generation is explicitly noninstallable. This work-specific probe
runs only after the maintained reader owner releases its current implementation.
"""
from pathlib import Path
from hashlib import sha256
import argparse,json,sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from build.tools import tyerman_whitefield_install as install
from build.tools import prove_tyerman_whitefield_install as fixture
from ocd_kernel.lib.path_io import resolve_path,io_path

def capture(stage):
    target=ROOT/install.LOG/'accepted-execution-imports-v1.json'
    if io_path(target).exists():raise FileExistsError('Preserve Whitefield acceptance execution receipt')
    result=install.prepare(stage,bootstrap=True)
    install.source_modules_absent()
    root=resolve_path(ROOT,strict=True);library=resolve_path(install.LIBRARY,strict=True)
    files=set();external={resolve_path(Path(sys.executable),strict=True)}
    for module in sys.modules.copy().values():
        filename=getattr(module,'__file__',None)
        if not filename:continue
        path=resolve_path(Path(filename),strict=True)
        if path.is_relative_to(root):files.add(path.relative_to(root).as_posix())
        elif path.is_relative_to(library):
            relative=path.relative_to(library)
            if relative.parts[0] not in {'raw','reports','exports'} or resolve_path(ROOT/relative,strict=True)!=path:
                raise ValueError('Unexpected physical Library execution path '+path.as_posix())
            files.add(relative.as_posix())
        else:external.add(path)
    pins=[dict(path=p,bytes=io_path(ROOT/p).stat().st_size,sha256=install.sha(ROOT/p)) for p in sorted(files)]
    runtime=[dict(path=p.as_posix(),bytes=io_path(p).stat().st_size,sha256=install.sha(p)) for p in sorted(external)]
    record=dict(status='pass',identity=install.identity(),complete_works=1,retained_textual_witnesses=2,
        covered='Actual accepted header inverse/P5, title/acquisition/state/acceptance generation and promoted-master maintained prose projection/verification. Source fidelity is an independently admitted fresh subprocess; no source producer/oracle is imported here.',
        first_party_files=pins,external_runtime_files=runtime,python_executable=Path(sys.executable).as_posix(),
        bootstrap_stage=result,bootstrap_installable=False,fixture_helper_loaded=True,
        source_oracle_imported='build.tei.tyerman_whitefield_complete_oracle' in sys.modules,
        source_producer_imported='build.tei.tyerman_whitefield_complete' in sys.modules,
        source_modules_absent=True,
        execution_import_closure_sha256=sha256(install.enc(pins)).hexdigest())
    if record['source_oracle_imported'] or record['source_producer_imported']:raise ValueError('Frozen source module leaked into acceptance process')
    install.dump(ROOT,target.relative_to(ROOT),record)
    return dict(status='pass',receipt=target.as_posix(),receipt_sha256=install.sha(target),first_party_files=len(pins),external_runtime_files=len(runtime),bootstrap_stage=result)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',type=Path);args=parser.parse_args()
    print(json.dumps(capture(args.stage),sort_keys=True))
