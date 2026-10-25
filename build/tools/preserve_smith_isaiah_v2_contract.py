"""Preserve the initial anonymous-link checker rejection and exact v2 inputs."""
from pathlib import Path
from hashlib import sha256
import json
from ocd_kernel.reconstruction import CandidatePackage
ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/smith-isaiah-complete-20261003-v1')
def main():
    dest=ROOT/LOG/'initial-v2-contract';dest.mkdir(exist_ok=False);pins=[]
    paths=[Path('build/tei/smith_isaiah_complete_oracle.py'),Path('build/tei/smith_isaiah_complete_prepare.py'),Path('build/tei/smith_isaiah_source_oracle.py'),Path('build/tools/prepare_smith_isaiah_complete.py')]+list(Path('sources/commentaries/expositors-bible/smith-isaiah-complete-20261003-v2').glob('*'))
    for path in paths:
        p=ROOT/path
        if not p.is_file():continue
        raw=p.read_bytes();target=dest/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);pins.append(dict(original_path=path.as_posix(),preserved_path=target.relative_to(ROOT).as_posix(),sha256=sha256(raw).hexdigest(),bytes=len(raw)))
    before=CandidatePackage.load('D:/Library/Open Christian Data/candidate-reviews/smith-isaiah-complete-20261003-v1/package');current=CandidatePackage.load('D:/Library/Open Christian Data/candidate-reviews/smith-isaiah-complete-20261003-v2/package')
    if before.member_bytes('content.tei.xml')!=current.member_bytes('content.tei.xml'):raise ValueError('Initial metadata renewal altered readable TEI')
    record=dict(status='rejected',reason='URI checker assumed source @id for every relative hyperlink. Some are anonymous and must be independently bound by raw preorder feature ordinal. Raw inverse had passed for first tested actual volume; no whole-source pass claim yet.',candidate_package_sha256=current.sha256,tei_sha256=sha256(current.member_bytes('content.tei.xml')).hexdigest(),pins=pins,tei_bytes_equal_to_v1=True,canonical_changes=False)
    (dest/'aborted-baseline.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
