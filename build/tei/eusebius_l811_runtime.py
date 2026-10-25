"""L811-only execution admission; retained authorities are not import permission."""
from pathlib import Path
from hashlib import sha256
import json,sys
from ocd_kernel.lib.path_io import resolve_path

ROOT=Path(__file__).resolve().parents[2]

def guard(source):
    record=json.loads(source.authority_path('runtime').read_bytes())
    if record.get('contract')!='ocd-l811-observed-source-runtime-v1' or record.get('status')!='frozen':
        raise ValueError('L811 source runtime is not frozen')
    root=resolve_path(ROOT,strict=True);library=resolve_path(Path('D:/Library/Open Christian Data'),strict=True)
    def mapping(rows,local):
        answer={}
        for row in rows:
            p=resolve_path(ROOT/row['path'] if local else Path(row['path']),strict=True)
            if p in answer or p.stat().st_size!=row['bytes'] or sha256(p.read_bytes()).hexdigest()!=row['sha256']:
                raise ValueError('L811 runtime duplicate or changed file: '+str(p))
            if local != (p.is_relative_to(root) or p.is_relative_to(library)):
                raise ValueError('L811 runtime physical boundary differs: '+str(p))
            answer[p]=row['sha256']
        return answer
    first=mapping(record['first_party_files'],True);external=mapping(record['external_runtime_files'],False)
    executable=resolve_path(Path(sys.executable),strict=True)
    actual=dict(path=executable.as_posix(),bytes=executable.stat().st_size,sha256=sha256(executable.read_bytes()).hexdigest())
    if record['runtime_executable']!=actual:raise ValueError('L811 executed Python differs')
    observed=[]
    for module in sys.modules.copy().values():
        filename=getattr(module,'__file__',None)
        if not filename:continue
        p=resolve_path(Path(filename),strict=True)
        allowed=first if p.is_relative_to(root) or p.is_relative_to(library) else external
        if p not in allowed or sha256(p.read_bytes()).hexdigest()!=allowed[p]:
            raise ValueError('Unexpected or changed L811 executed dependency: '+p.as_posix())
        observed.append(p.as_posix())
    forbidden=[source.authority_path(a['name']) for a in source.record['authorities'] if a['role'] in ('historical-producer-lineage','historical-oracle-lineage')]
    # Absent original paths stay absent; their normalized identities still cannot
    # be admitted if a later process restores or imports one of these ancestors.
    forbidden.extend(ROOT/p for p in ('build/tei/pta_l811_three_tome.py','build/tei/pta_l811_three_tome_oracle.py'))
    if any(resolve_path(p,strict=False) in first for p in forbidden):
        raise ValueError('Historical L811 authority incorrectly admitted for execution')
    return sorted(set(observed))
