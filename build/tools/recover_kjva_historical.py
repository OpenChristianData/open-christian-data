"""Recover only the explicitly declared, byte-bound historical KJVA package."""
from pathlib import Path
from hashlib import sha256
import json
from ocd_kernel.library._common import io_path
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'reports/_logs/kjva-current-reconciliation-20261001-v1'
ORIGINAL=Path('D:/Library/Open Christian Data/candidate-reviews/37c-240-kjva-20260919-v1')
def main():
    audit=json.loads(io_path(ROOT/'reports/_logs/retained-master-gap-review-20261001-v1/audit.json').read_bytes())
    entry=next(e for e in audit['ranked_works'] if e['work_id']=='kjva')
    package=io_path(ORIGINAL/'package/manifest.json').read_bytes()
    if sha256(package).hexdigest()!=entry['package']['sha256']:raise ValueError('Historical package manifest differs')
    manifest=json.loads(package);target=io_path(BASE/'historical-package');target.mkdir(parents=True,exist_ok=False)
    records=[]
    for row in manifest['members']:
        if row['name'] not in {'content.tei.xml','README.source.md','source-accountability.json','provenance.json','unresolved.jsonl'}:raise ValueError('Unexpected historical member')
        raw=io_path(ORIGINAL/'package'/row['name']).read_bytes()
        if sha256(raw).hexdigest()!=row['sha256'] or len(raw)!=row['bytes']:raise ValueError('Historical member differs')
        (target/row['name']).write_bytes(raw);records.append(dict(name=row['name'],bytes=len(raw),sha256=sha256(raw).hexdigest()))
    (target/'manifest.json').write_bytes(package)
    validation=io_path(ORIGINAL/'validation.json').read_bytes()
    if sha256(validation).hexdigest()!=entry['historical_validation']['sha256']:raise ValueError('Historical validation differs')
    (target/'validation.json').write_bytes(validation)
    (io_path(BASE)/'historical-recovery.json').write_text(json.dumps(dict(status='pass',historical_package_sha256=sha256(package).hexdigest(),historical_validation_sha256=sha256(validation).hexdigest(),members=records,qualification='Exact retained original artifacts copied read-only; historical receipts remain dated, no new source acquisition or proof resealing.'),sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(status='pass',members=len(records),source_candidate_sha256=entry['candidate']['sha256'])))
if __name__=='__main__':main()
