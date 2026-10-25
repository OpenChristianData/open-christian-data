"""Finish only LF framing and explicit data directions for four frozen notices."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import html
from build.tools.prepare_aquinas_four_current import ROOT, BASE, WORK_ID, EDITION, LOG, canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.release.notices import notice_texts_for_item


def main():
    evidence = ROOT / LOG / 'notice-framing-v2'
    evidence.mkdir(exist_ok=False)
    driver = ROOT / 'build/tools/prepare_aquinas_four_publication_notices.py'
    (evidence / driver.name).write_bytes(driver.read_bytes())
    original = (ROOT / BASE / 'README.source.md').read_bytes()
    prefix = original.decode().split('PG 17611 retained provider footer/license:', 1)[0]
    members = json.loads(io_path(ROOT / EDITION / 'source-member-set.json').read_bytes())['members']
    bindings, proof = [], []
    for position, (member, pgid) in enumerate(zip(members, [17611, 17897, 18755, 19950], strict=True), 1):
        raw = io_path(ROOT / member['path']).read_bytes()
        if sha256(raw).hexdigest() != member['sha256']:
            raise ValueError('Retained component differs')
        footer = ''.join(html.fromstring(raw).xpath('//body/footer')[0].itertext()).strip()
        before = (prefix + 'This paired notice carries the complete retained provider footer for component ' + str(position) + ' (PG ' + str(pgid) + ') of the same four-component work. It creates no new work identity.\n\nPG ' + str(pgid) + ' retained provider footer/license:\n\n' + footer + '\n').encode()
        source = Path('sources/aquinas-four-publication') / ('pg' + str(pgid)) / WORK_ID / 'README.source.md'
        data = Path('data/prose') / WORK_ID / ('pg' + str(pgid)) / 'README.md'
        directive = 'The paired human-visible data credit is `' + data.as_posix() + '`.\n\n'
        after = (directive + before.decode().replace('\r\n', '\n').replace('\r', '\n')).encode()
        if len(after) > 65536 or after.decode().removeprefix(directive) != before.decode().replace('\r\n', '\n').replace('\r', '\n'):
            raise ValueError('Only authorized notice framing is allowed')
        for label, relative in [('source', source), ('data', data)]:
            target = ROOT / relative
            if target.read_bytes() != before:
                raise ValueError('Exact failed notice preimage differs: ' + str(relative))
            (evidence / (str(pgid) + '-' + label + '-before.md')).write_bytes(before)
            target.write_bytes(after)
        digest = sha256(after).hexdigest()
        bindings.append(dict(source_path=source.as_posix(), source_sha256=digest, notice_path=data.as_posix(), notice_sha256=digest))
        proof.append(dict(pg_id=pgid, component_position=position, source_member_sha256=member['sha256'], source_footer_sha256=sha256(footer.encode()).hexdigest(), notice_before_sha256=sha256(before).hexdigest(), notice_sha256=digest, notice_bytes=len(after), complete_footer_LF_only_framing=True, sole_changes=['CRLF/CR to LF Markdown framing', 'explicit paired data path directive']))
    pin = json.loads((ROOT / BASE / 'stage-pin.json').read_bytes())
    promoted = Path(pin['receipt']).parent
    if sha256((promoted / 'stage-receipt.json').read_bytes()).hexdigest() != pin['receipt_sha256']:
        raise ValueError('Stage changed')
    item = dict(item_id=WORK_ID, category='prose', acceptance_path=(EDITION / 'acceptance.json').as_posix(), public_notices=bindings)
    texts = notice_texts_for_item(ROOT, item, promoted / EDITION / 'acceptance.json')
    if len(texts) != 4:
        raise ValueError('All four maintained notices required')
    result = dict(status='pass', notice_count=4, item=item, components=proof, original_package_notice_sha256=sha256(original).hexdigest(), original_notice_preserved=True, frozen_stage_sha256=pin['receipt_sha256'], failed_terminal_sha256=sha256((ROOT / LOG / 'notice-supplement-v1-terminal.json').read_bytes()).hexdigest(), stage_replay_projection_unchanged=True, qualification='Four complete retained provider footer/license texts, each with whole-work scope and own credits. Original source/package/stage receipts remain unchanged; only separately prepared publication notice LF framing and explicit selected data directives changed. No rights clearance or public publication.')
    for name in ['notice-preflight.json', 'publication-notice-supplement.json']:
        target = ROOT / LOG / name
        if target.exists():
            raise FileExistsError(target)
        target.write_bytes(canonical(result))
    print(json.dumps(dict(status='pass', notices=4, bytes=[p['notice_bytes'] for p in proof])), flush=True)


if __name__ == '__main__':
    main()
