"""Observe actual Joshua producer/source/title/accepted projection execution."""
from pathlib import Path
from hashlib import sha256
import json,sys
ROOT=Path.cwd().resolve(strict=True);sys.path.insert(0,str(ROOT));before=set(sys.modules)
from build.tei.blaikie_joshua_retained_native_prepare import _convert
from build.tei.blaikie_joshua_retained_native_oracle import _oracle
from build.tools.blaikie_joshua_title_install import WORK_ID,WORK,EDITION_PATH,LOG,SOURCE,PACKAGE,projection_gate,canonical
from build.tools.propose_blaikie_joshua_title_identity import records,ACQ_REL
from ocd_kernel.lib.path_io import resolve_path,io_path
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,validate
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance

if sys.argv[2:] not in ([],['--rehearsal']):raise ValueError('Only the fixed rehearsal output flag is supported')
rehearsal=sys.argv[2:]==['--rehearsal']
stage=Path(sys.argv[1]).resolve(strict=True);source=SourceManifest.load(ROOT/SOURCE,repository_root=ROOT);package=CandidatePackage.load(PACKAGE);payload=_convert(source)
if set(payload)!=set(package.member_names)-{'manifest.json'} or any(raw!=package.member_bytes(name) for name,raw in payload.items()):raise ValueError('Actual fresh Joshua five payloads differ')
report=validate(source,package,_oracle);records();validate_acquisition(stage/ACQ_REL,root=stage)
validate_acceptance(stage/EDITION_PATH/'acceptance.json',root=stage);validate_state(stage/WORK/'state.json',root=stage)
gate=projection_gate(stage,stage/EDITION_PATH/'acceptance.json')
files=set();external={resolve_path(Path(sys.executable),strict=True)};physical_root=resolve_path(ROOT,strict=True);library=resolve_path(Path('D:/Library/Open Christian Data'),strict=True)
for name,module in sys.modules.copy().items():
 filename=getattr(module,'__file__',None)
 if not filename:continue
 path=resolve_path(Path(filename),strict=True)
 if path.is_relative_to(physical_root):
  if name not in before:files.add(path.relative_to(physical_root).as_posix())
 elif path.is_relative_to(library):
  logical=path.relative_to(library)
  if not logical.parts or logical.parts[0] not in {'raw','reports','exports'}:raise ValueError('Unexpected Library execution path '+path.as_posix())
  if resolve_path(ROOT/logical,strict=True)!=path:raise ValueError('Library execution logical/physical alias differs')
  files.add(logical.as_posix())
 else:external.add(path)
pins=[dict(path=p,sha256=sha256(io_path(ROOT/p).read_bytes()).hexdigest()) for p in sorted(files)]
runtime=[dict(path=p.as_posix(),bytes=io_path(p).stat().st_size,sha256=sha256(io_path(p).read_bytes()).hexdigest()) for p in sorted(external)]
result=dict(status='pass',work_id=WORK_ID,complete_works=1,source_members=1,fresh_python_process=True,covered='Actual five-payload producer byte equality, exact full raw-backed independent source oracle, raw-backed additive title identity, exact acquisition/state/acceptance and actual accepted-master commentary projection attempt; bounded initial-title installer/fixture functions loaded.',stage_root=stage.as_posix(),first_party_files=pins,external_runtime_files=runtime,execution_import_closure_sha256=sha256(canonical(pins)).hexdigest(),producer_five_payloads_byte_equal=True,oracle_report_sha256=report.sha256,projection_gate=gate,probe_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
target=ROOT/LOG/('title-execution-imports-rehearsal-v1.json' if rehearsal else 'title-execution-imports-v1.json')
if target.exists():raise FileExistsError('Preserve actual Joshua execution evidence')
target.write_bytes(canonical(result));print(json.dumps(dict(status='pass',first_party_files=len(pins),external_runtime_files=len(runtime),projection_gate=gate,execution_import_closure_sha256=result['execution_import_closure_sha256']),sort_keys=True))
