"""Freeze the exact successful stage and check paired source-directed notices."""
from pathlib import Path
from hashlib import sha256
import argparse,json
from build.tools.prepare_aquinas_four_current import ROOT,BASE,WORK_ID,EDITION,DATA_NOTICE,LOG,canonical
from ocd_kernel.release.notices import notice_texts_for_item
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--promoted',type=Path,required=True);args=parser.parse_args()
    receipt=args.promoted/'stage-receipt.json';raw=receipt.read_bytes();record=json.loads(raw)
    if record['status']!='pass' or record['rows']!=4 or record['source_facts']['source_units']!=35488:raise ValueError('Stage scope differs')
    pin=dict(work_id=WORK_ID,receipt=receipt.as_posix(),receipt_sha256=sha256(raw).hexdigest(),native_schema_sha256=sha256((ROOT/'schemas/v2/native-content.schema.json').read_bytes()).hexdigest())
    target=ROOT/BASE/'stage-pin.json'
    if target.exists():raise FileExistsError(target)
    target.write_bytes(canonical(pin))
    source=BASE/'README.source.md';item=dict(item_id=WORK_ID,category='prose',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[dict(source_path=source.as_posix(),source_sha256=sha256((ROOT/source).read_bytes()).hexdigest(),notice_path=DATA_NOTICE.as_posix(),notice_sha256=sha256((ROOT/DATA_NOTICE).read_bytes()).hexdigest())])
    texts=notice_texts_for_item(ROOT,item,args.promoted/EDITION/'acceptance.json')
    if len(texts)!=1 or any(s not in texts[0] for s in ['Sandra K. Perry','David McClamrock','English Dominican Province','Supplement','17611','17897','18755','19950']):raise ValueError('Complete own notices absent')
    (ROOT/LOG/'notice-preflight.json').write_bytes(canonical(dict(status='pass',notice_count=1,item=item,source_notice_verbatim_sha256=sha256(texts[0].encode()).hexdigest(),publication_markdown_framing_exact=texts[0]==texts[0].strip('\n')+'\n',qualification='Maintained paired notice checker against staged identity, complete own four retained provider footer/license texts and specific contributor/partialscope statements; no rights/publication clearance.')))
    print(json.dumps(pin),flush=True)
if __name__=='__main__':main()
