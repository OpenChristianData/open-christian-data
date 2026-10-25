"""Pin the staged complete corpus and maintained source/data notice gate."""
import argparse,json
from pathlib import Path
from hashlib import sha256
from build.tools.prepare_calvin_complete_native import ROOT,BASE,NOTICE_BASE,DATA_NOTICE,WORK_ID,EDITION,canonical
from ocd_kernel.release.notices import notice_texts_for_item
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--promoted',type=Path,required=True);args=p.parse_args()
    path=args.promoted/'stage-receipt.json';raw=path.read_bytes();record=json.loads(raw)
    if record['status']!='pass' or record['rows']!=16 or record['source_facts']['source_lines']!=69897:raise ValueError('complete stage gate differs')
    source=NOTICE_BASE/'README.source.md'
    item=dict(item_id=WORK_ID,category='prose',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[dict(source_path=source.as_posix(),source_sha256=sha256((ROOT/source).read_bytes()).hexdigest(),notice_path=DATA_NOTICE.as_posix(),notice_sha256=sha256((ROOT/DATA_NOTICE).read_bytes()).hexdigest())])
    notices=notice_texts_for_item(ROOT,item,args.promoted/EDITION/'acceptance.json')
    if len(notices)!=1 or 'John Allen' not in notices[0] or notices[0].count('START: FULL LICENSE')!=2:raise ValueError('own full visible paired source notice absent')
    pin=dict(work_id=WORK_ID,receipt=path.as_posix(),receipt_sha256=sha256(raw).hexdigest(),native_schema_sha256=record['schema_pins']['schemas/v2/native-content.schema.json'])
    (ROOT/BASE/'stage-pin.json').write_bytes(canonical(pin));(ROOT/BASE/'notice-preflight.json').write_bytes(canonical(dict(status='pass',notice_count=len(notices),item=item,staged_acceptance_only=True)))
    print(json.dumps(pin))
if __name__=='__main__':main()
