"""Finite actual L811 acceptance capture; bootstrap is never installable."""
from pathlib import Path
import argparse,json,sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from build.tools import eusebius_l811_install as installer
from build.tools import prove_eusebius_l811_install as fixture
from ocd_kernel.lib.path_io import resolve_path,io_path


def capture():
    installer.insist(installer.EXECUTION_RELEASED,'L811 execution remains coordinator-held')
    target=ROOT/installer.CAPTURE
    if io_path(target).exists():raise FileExistsError('Preserve L811 actual acceptance capture')
    before=installer.original_five()
    result=installer.prepare(installer.BOOTSTRAP_STAGE,bootstrap=True)
    canonical=resolve_path(ROOT,strict=True);library=resolve_path(installer.LIBRARY,strict=True)
    first=set();external={resolve_path(Path(sys.executable),strict=True)}
    for module in sys.modules.copy().values():
        filename=getattr(module,'__file__',None)
        if not filename:continue
        physical=resolve_path(Path(filename),strict=True)
        if physical.is_relative_to(canonical):first.add(physical.relative_to(canonical).as_posix())
        elif physical.is_relative_to(library):
            relative=physical.relative_to(library)
            installer.insist(relative.parts[0] in {'raw','reports','exports'}
                and resolve_path(ROOT/relative,strict=True)==physical,'Observed physical Library alias differs')
            first.add(relative.as_posix())
        else:external.add(physical)
    forbidden={resolve_path(ROOT/p,strict=False) for p in installer.SOURCE_PROCESS_ONLY}
    installer.insist(not forbidden.intersection(resolve_path(ROOT/p,strict=True) for p in first),
                     'Frozen source implementation entered actual accepted execution')
    pins=[dict(path=p,bytes=io_path(ROOT/p).stat().st_size,sha256=installer.digest(ROOT/p)) for p in sorted(first)]
    runtime=[dict(path=p.as_posix(),bytes=io_path(p).stat().st_size,sha256=installer.digest(p)) for p in sorted(external)]
    installer.insist(installer.original_five()==before and installer.digest(installer.PACKAGE/'content.tei.xml')==installer.TEI_SHA
        and installer.digest(ROOT/installer.MASTER_PROPOSAL)==installer.MASTER_SHA,'Capture changed conserved source/header/preimages')
    record=dict(contract='ocd-l811-actual-acceptance-execution-v1',status='pass',identity=installer.identity(),
        complete_works=1,source_tomes=3,first_party_files=pins,external_runtime_files=runtime,
        python_executable=resolve_path(Path(sys.executable),strict=True).as_posix(),
        fixture_helper_loaded=True,source_process_only_imported=False,bootstrap_stage=result,bootstrap_installable=False,
        covered='Actual header/P5/metadata/source member-set/state/acceptance generation and promoted-master maintained native prose projection with independent actual tree checker; frozen source oracle executes only in separate admitted fresh process.',
        closure_sha256=installer.sha256(installer.enc(pins)).hexdigest())
    installer.acceptance_execution_policy(record,{row['path']:row['sha256'] for row in pins})
    installer.dump(ROOT,installer.CAPTURE,record)
    return dict(status='pass',capture=target.as_posix(),sha256=installer.digest(target),
                first_party_files=len(pins),external_runtime_files=len(runtime),bootstrap=result)


if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(capture(),sort_keys=True))
