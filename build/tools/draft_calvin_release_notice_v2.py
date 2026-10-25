"""Preserve sealed notice history and satisfy the maintained one-LF card gate."""
from pathlib import Path
from hashlib import sha256
from build.tools.prepare_calvin_complete_native import ROOT,NOTICE_BASE,DATA_NOTICE,EDITION,WORK_ID,canonical
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.public_allowlist import render_dataset_card
NEW_SOURCE=Path('sources/private-pg-allen-calvin-notice-v2')/WORK_ID/'README.source.md'
NEW_DATA=Path('data/prose')/WORK_ID/'private-offline-20261001-v2/README.md'
def main():
    original=(ROOT/NOTICE_BASE/'README.source.md').read_bytes()
    text=original.decode('utf-8');old='`'+DATA_NOTICE.as_posix()+'`';new='`'+NEW_DATA.as_posix()+'`'
    if text.count(old)!=1:raise ValueError('literal maintained direction cardinality differs')
    payload=(text.replace(old,new).rstrip('\n')+'\n').encode('utf-8')
    for path in (NEW_SOURCE,NEW_DATA):
        target=ROOT/path
        if target.exists() and target.read_bytes()!=payload:raise FileExistsError('new maintained notice already differs')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(payload)
    item=dict(item_id=WORK_ID,category='prose',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[dict(source_path=NEW_SOURCE.as_posix(),source_sha256=sha256(payload).hexdigest(),notice_path=NEW_DATA.as_posix(),notice_sha256=sha256(payload).hexdigest())])
    notices=notice_texts_for_item(ROOT,item,ROOT/EDITION/'acceptance.json')
    render_dataset_card([dict(category='prose',path='public/data/prose/train.jsonl',row_count=16)],notices=notices)
    if payload.decode().replace(new,old).rstrip('\n')!=text.rstrip('\n'):raise ValueError('source credit/license wording altered')
    receipt=dict(status='pass',original_bound_notice_sha256=sha256(original).hexdigest(),new_source_path=NEW_SOURCE.as_posix(),new_data_path=NEW_DATA.as_posix(),new_notice_sha256=sha256(payload).hexdigest(),changes=['explicit directed new data README path','exactly one terminal LF; no source/license wording change'],old_bound_source_data_pair_preserved=True,maintained_notice_and_dataset_card_gates='pass')
    log=ROOT/'reports/_logs/calvin-institutes-current-reconciliation-20261001-v1/notice-v2-repair.json';log.write_bytes(canonical(receipt));print(canonical(receipt).decode())
if __name__=='__main__':main()
