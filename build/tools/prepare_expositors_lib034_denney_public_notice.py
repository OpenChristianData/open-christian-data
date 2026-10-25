"""Prepare future public CCEL credit for Denney's two distinct editions; do not publish."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.release.notices import _utf8_markdown
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = 'expositors-bible--james-denney'
HOME = Path('D:/Library/Open Christian Data/candidate-reviews/expositors-lib034-denney-ccel-public-notice-20260927-v1')
PERMISSION = ROOT / 'sources/commentaries/expositors-bible/ccel-permission.md'
MEMBERS = {
    'denney-expositor2cor': ('The Second Epistle to the Corinthians',
                            'raw/ccel/expositors-bible/denney_expositor2cor.xml',
                            'afdf1cb907eb7d79f2f20582dd8d5e96a84614c253bb193903cc1cac76d16bc7',
                            'https://www.ccel.org/ccel/denney/expositor2cor.html'),
    'denney-expositorthess': ('The Epistles to the Thessalonians',
                             'raw/ccel/expositors-bible/denney_expositorthess.xml',
                             '47417f9447e9558951594ba2bd35eb5958be1293041e83b1af6e990ee8d2fffc',
                             'https://www.ccel.org/ccel/denney/expositorthess.html'),
}


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _put(path: Path, data: bytes) -> None:
    target = _io_path(path)
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError(f'Denney notice path has different bytes: {path}')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def main() -> None:
    permission = _io_path(PERMISSION).read_bytes()
    if b'sourced via CCEL.org' not in permission or b'do not sell CCEL files' not in permission:
        raise ValueError('Denney CCEL permission or attribution guidance differs')
    work_path = ROOT / 'library/works' / WORK_ID
    work = json.loads(_io_path(work_path / 'work.json').read_bytes())
    if work['work_id'] != WORK_ID or len(work['textual_forms']) != 2:
        raise ValueError('Denney textual-form boundary differs')
    rows = []
    for member, (title, retained, digest, url) in MEMBERS.items():
        if _sha(_io_path(ROOT / retained).read_bytes()) != digest:
            raise ValueError(f'{member} exact retained XML differs')
        forms = [form for form in work['textual_forms'] if member in form['textual_form_id']]
        if len(forms) != 1 or len(forms[0]['editions']) != 1:
            raise ValueError(f'{member} edition identity differs')
        form, edition = forms[0], forms[0]['editions'][0]
        if member not in edition['edition_id'] or len(edition['acquisition_ids']) != 1:
            raise ValueError(f'{member} acquisition identity differs')
        acquisition = work_path / 'forms' / form['textual_form_id'] / 'editions' / edition['edition_id'] / 'acquisitions' / (edition['acquisition_ids'][0] + '.json')
        acquired = json.loads(_io_path(acquisition).read_bytes())
        retained_files = acquired.get('retained_files', [])
        if (len(retained_files) != 1 or retained_files[0]['path'] != retained
                or retained_files[0]['sha256'] != digest or acquired['url'] != url):
            raise ValueError(f'{member} retained acquisition binding differs')
        rows.append(dict(member=member, title=title, textual_form_id=form['textual_form_id'],
                         edition_id=edition['edition_id'], acquisition_id=acquired['acquisition_id'],
                         acquisition_path=acquisition.relative_to(ROOT).as_posix(),
                         retained_xml_path=retained, retained_xml_sha256=digest, source_url=url))
    source_path = Path('sources/commentaries/expositors-bible') / WORK_ID / 'README.source.md'
    notice_path = Path('data/commentaries') / WORK_ID / 'README.md'
    lines = [f'# Electronic sources and credit for {WORK_ID}', '',
             'This work has two distinct CCEL ThML electronic editions and acquisitions:','']
    for row in rows:
        lines.append(f"- {row['title']}: `{row['retained_xml_path']}` (SHA-256 `{row['retained_xml_sha256']}`); {row['source_url']}.")
    lines += ['', 'The source-local CCEL permission note records permission to parse ThML/XML for text,',
              'a restriction on selling CCEL files or derivatives of their formatting, and the',
              'requested public acknowledgment “sourced via CCEL.org”. This is source evidence,',
              'not a rights-clearance or publication decision.', '',
              f'For any public data release, include a human-visible notice at `{notice_path.as_posix()}`',
              'and bind this exact source-note and notice through `public_notices`.', '']
    source_note = '\n'.join(lines).encode('utf-8')
    _put(ROOT / source_path, source_note)
    notice = (
        "# Source credit: The Expositor's Bible — James Denney\n\n"
        'These two electronic editions were sourced via CCEL.org:\n\n'
        '- [The Second Epistle to the Corinthians](https://www.ccel.org/ccel/denney/expositor2cor.html).\n'
        '- [The Epistles to the Thessalonians](https://www.ccel.org/ccel/denney/expositorthess.html).\n\n'
        'CCEL permitted parsing its electronic text for this reconstruction. Its files and formatting '
        'have separate conditions, including a restriction on selling CCEL files or derivatives of '
        'their formatting. This credit does not establish rights clearance or authorize a public release.\n'
    ).encode('utf-8')
    public_text = _utf8_markdown(notice, label='Denney future public notice')
    if _scan(public_text, 'Denney future public notice') or '<' in public_text or '>' in public_text:
        raise ValueError('Denney future public notice contains private or unsupported text')
    external = HOME / notice_path
    _put(external, notice)
    index = dict(contract='ocd-expositors-lib034-denney-ccel-public-notice-handoff-v1',
                 status='future-release-notice-only', permission_sha256=_sha(permission),
                 work_id=WORK_ID, source_path=source_path.as_posix(), source_sha256=_sha(source_note),
                 notice_path=notice_path.as_posix(), notice_sha256=_sha(notice),
                 external_notice_path=external.as_posix(), editions=rows)
    index_path = HOME / 'notice-index.json'
    _put(index_path, (json.dumps(index, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')) + '\n').encode('utf-8'))
    print(json.dumps(dict(index=index_path.as_posix(), index_sha256=_sha(_io_path(index_path).read_bytes()),
                          editions=len(rows)), sort_keys=True))


if __name__ == '__main__':
    main()
