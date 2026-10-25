"""Preserve initial Isaiah contract and SDK tuple/list rejection before renewal."""
from pathlib import Path
from hashlib import sha256
import json
ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/smith-isaiah-complete-20261003-v1')
def main():
    dest=ROOT/LOG/'initial-v1-contract';dest.mkdir(exist_ok=False);pins=[]
    paths=[Path('build/tei/smith_isaiah_complete_oracle.py'),Path('build/tei/smith_isaiah_complete_prepare.py'),Path('build/tei/smith_isaiah_source_oracle.py'),Path('build/tools/prepare_smith_isaiah_complete.py')]+list(Path('sources/commentaries/expositors-bible/smith-isaiah-complete-20261003-v1').glob('*'))
    for path in paths:
        p=ROOT/path
        if not p.is_file():continue
        raw=p.read_bytes();target=dest/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);pins.append(dict(original_path=path.as_posix(),preserved_path=target.relative_to(ROOT).as_posix(),sha256=sha256(raw).hexdigest(),bytes=len(raw)))
    record=dict(status='rejected',reason='SDK source.scope ordered_members freezes to tuple; initial strict comparison expected list. This is a contract representation check defect, before raw source proof. No current pass claim.',package='D:/Library/Open Christian Data/candidate-reviews/smith-isaiah-complete-20261003-v1/package',candidate_package_sha256='df481b0fcdb1618d2543b22914d976f550ae3d048b216a0f4916a247bf990f0e',pins=pins,source_or_body_changes=False,canonical_changes=False)
    (dest/'aborted-baseline.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
