"""Split complete retained footer licenses into bounded work-specific paired notices."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import html
from build.tools.prepare_aquinas_four_current import ROOT,BASE,WORK_ID,EDITION,LOG,canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.release.notices import notice_texts_for_item
def main():
    pin=json.loads((ROOT/BASE/'stage-pin.json').read_bytes());promoted=Path(pin['receipt']).parent
    if sha256((promoted/'stage-receipt.json').read_bytes()).hexdigest()!=pin['receipt_sha256']:raise ValueError('Frozen stage differs')
    original=(ROOT/BASE/'README.source.md').read_bytes();text=original.decode();prefix=text.split('PG 17611 retained provider footer/license:',1)[0]
    if len(original)<=65536 or prefix==text:raise ValueError('Exact oversized four-footer source note not present')
    members=json.loads(io_path(ROOT/EDITION/'source-member-set.json').read_bytes())['members'];bindings=[];proof=[]
    for position,(member,pgid) in enumerate(zip(members,[17611,17897,18755,19950],strict=True),1):
        raw=io_path(ROOT/member['path']).read_bytes()
        if sha256(raw).hexdigest()!=member['sha256']:raise ValueError('Primary component changed')
        doc=html.fromstring(raw);footer=''.join(doc.xpath('//body/footer')[0].itertext()).strip()
        note=(prefix+'This paired notice carries the complete retained provider footer for component '+str(position)+' (PG '+str(pgid)+') of the same four-component work. It creates no new work identity.\n\nPG '+str(pgid)+' retained provider footer/license:\n\n'+footer+'\n').encode()
        if len(note)>65536 or note.decode()!=note.decode().strip('\n')+'\n':raise ValueError('Bounded notice framing differs')
        source=Path('sources/aquinas-four-publication')/('pg'+str(pgid))/WORK_ID/'README.source.md';data=Path('data/prose')/WORK_ID/('pg'+str(pgid))/'README.md'
        for target in [source,data]:
            p=ROOT/target;p.parent.mkdir(parents=True,exist_ok=True)
            if p.exists():raise FileExistsError(p)
            p.write_bytes(note)
        digest=sha256(note).hexdigest();bindings.append(dict(source_path=source.as_posix(),source_sha256=digest,notice_path=data.as_posix(),notice_sha256=digest));proof.append(dict(pg_id=pgid,component_position=position,source_member_sha256=member['sha256'],source_footer_sha256=sha256(footer.encode()).hexdigest(),complete_footer_embedded=footer in note.decode(),notice_bytes=len(note),notice_sha256=digest))
    item=dict(item_id=WORK_ID,category='prose',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=bindings)
    texts=notice_texts_for_item(ROOT,item,promoted/EDITION/'acceptance.json')
    if len(texts)!=4:raise ValueError('Maintained paired notice gate did not retain all four')
    result=dict(status='pass',notice_count=4,item=item,components=proof,publication_markdown_framing_exact=True,original_package_notice_sha256=sha256(original).hexdigest(),original_notice_preserved=True,stage_replay_projection_unchanged=True,qualification='The original complete four-footer source package note exceeds the per-notice64KiB limit. Four separately bounded work-specific paired source/data notices preserve whole-work scope/credits and each complete own retained footer/license. No source, master, package, stage, replay or completed projection proof is changed or repeated.')
    (ROOT/LOG/'notice-preflight.json').write_bytes(canonical(result));(ROOT/LOG/'publication-notice-supplement.json').write_bytes(canonical(result))
    print(json.dumps(dict(status='pass',notices=4,bytes=[p['notice_bytes'] for p in proof])),flush=True)
if __name__=='__main__':main()
