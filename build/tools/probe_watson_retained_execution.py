"""Observe fresh actual Watson producer, source and accepted commentary execution."""
import json
import sys
from hashlib import sha256
from pathlib import Path
ROOT=Path.cwd().resolve(strict=True);sys.path.insert(0,str(ROOT));before=set(sys.modules)
from build.tei.watson_retained_native_prepare import LOG,SOURCE_DIR,WORK_ID,SPECS,_convert,canonical
from build.tei.watson_retained_native_oracle import _oracle
from build.tools.prepare_watson_retained_candidates import CANDIDATES
from build.tools.stage_watson_retained_acceptance import projection_gate,edition_path
from build.tools.install_watson_retained_acceptance import loaded_code_pins
from build.tools.prove_watson_retained_install import prove
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,validate
stage=Path(sys.argv[1]).resolve(strict=True);results=[]
for member,spec in SPECS.items():
 manifest=SourceManifest.load(ROOT/SOURCE_DIR/(member+'.source-manifest.json'),repository_root=ROOT);package=CandidatePackage.load(CANDIDATES/member/'package');payload=_convert(manifest)
 if any(raw!=package.member_bytes(name) for name,raw in payload.items()):raise ValueError('Actual fresh Watson producer/package payloads differ')
 report=validate(manifest,package,_oracle)
 if report.status!='pass':raise ValueError('Actual fresh full Watson source gate failed')
 acceptance=stage/edition_path(spec)/'acceptance.json';validate_acceptance(acceptance,root=stage)
 results.append(dict(member_id=member,producer_all_five_payload_members_byte_equal=True,source_report_sha256=report.sha256,source_gate='pass',actual_commentary_projection=projection_gate(stage,acceptance)))
validate_state(stage/'library/works'/WORK_ID/'state.json',root=stage)
files=[]
for name in set(sys.modules)-before:
 file=getattr(sys.modules[name],'__file__',None)
 if file is None:continue
 path=Path(file).resolve(strict=True)
 if path.is_relative_to(ROOT):files.append(path.relative_to(ROOT).as_posix())
records=[dict(path=p,sha256=sha256((ROOT/p).read_bytes()).hexdigest()) for p in sorted(set(files))]
external={Path(sys.executable).resolve(strict=True)}
for module in sys.modules.copy().values():
 filename=getattr(module,'__file__',None)
 if filename and Path(filename).is_file():
  path=Path(filename).resolve(strict=True)
  if not path.is_relative_to(ROOT) and not path.is_relative_to(Path('D:/Library/Open Christian Data')):external.add(path)
external_records=[dict(path=p.as_posix(),bytes=p.stat().st_size,sha256=sha256(p.read_bytes()).hexdigest()) for p in sorted(external)]
result=dict(status='pass',work_id=WORK_ID,fresh_python_process=True,covered='All three actual existing-source producers, complete raw/old-package source oracles, actual acceptance/state validation and accepted commentary projection attempts; guarded installer and fixture modules loaded',import_time_closure='Separately sealed fixed allowlist; additional inventory includes lazy execution imports',stage_root=stage.as_posix(),external_runtime_files=external_records,results=results,first_party_files=records,execution_import_closure_sha256=sha256(canonical(records)).hexdigest(),probe_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
(ROOT/LOG/'execution-imports-v1.json').write_bytes(canonical(result))
print(json.dumps(dict(status='pass',first_party_files=len(records),execution_import_closure_sha256=result['execution_import_closure_sha256']),sort_keys=True))
