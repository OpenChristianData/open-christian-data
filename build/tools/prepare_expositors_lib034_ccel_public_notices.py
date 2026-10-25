"""Prepare source-bound CCEL credit notices for future release; do not publish."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.release.notices import _utf8_markdown
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.install_accepted import _io_path

ROOT = Path(__file__).resolve().parents[2]
HOME = Path('D:/Library/Open Christian Data/candidate-reviews/expositors-lib034-ccel-public-notices-20260927-v1')
PERMISSION = ROOT / 'sources/commentaries/expositors-bible/ccel-permission.md'
DETAILS = {
    'burton-expositorluke': ('expositors-bible--henry-burton', 'The Gospel According to St. Luke',
                            'raw/ccel/expositors-bible/burton_expositorluke.xml',
                            'fdfc2914b0ea35c263c779c4067861364e3da3f9dbb899349cdddb6affa96614',
                            'https://www.ccel.org/ccel/burton/expositorluke.html'),
    'gibson-expositormatt': ('expositors-bible--j-monro-gibson', 'The Gospel of St. Matthew',
                             'raw/ccel/expositors-bible/gibson_expositormatt.xml',
                             '25c0a6febeaff9cd0ebe4e75a676b2cfab830f95ad3b0b1d384cf8777150c7f4',
                             'https://www.ccel.org/ccel/gibson/expositormatt.html'),
    'moule-expositorromans': ('expositors-bible--h-c-g-moule', 'The Epistle of St. Paul to the Romans',
                              'raw/ccel/expositors-bible/moule_expositorromans.xml',
                              'a6b919c200f4702fae4e3cb5f687676a503728233f5eb6c1a9468f835a533433',
                              'https://www.ccel.org/ccel/moule/expositorromans.html'),
    'skinner-expositorezek': ('expositors-bible--john-skinner', 'The Book of Ezekiel',
                              'raw/ccel/expositors-bible/skinner_expositorezek.xml',
                              '6ecab5f91bd497b0953143228d7f1b70c5b4768e8142c56268ef8e9a1294368f',
                              'https://www.ccel.org/ccel/skinner/expositorezek.html'),
}


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _put(path: Path, content: bytes) -> None:
    if _io_path(path).exists():
        if _io_path(path).read_bytes() != content:
            raise ValueError(f'CCEL notice path has different bytes: {path}')
        return
    _io_path(path).parent.mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)


def main() -> None:
    permission = _io_path(PERMISSION).read_bytes()
    if b'sourced via CCEL.org' not in permission or b'do not sell CCEL files' not in permission:
        raise ValueError('CCEL source permission or attribution guidance differs')
    rows = []
    for member, (work_id, title, retained, digest, url) in DETAILS.items():
        retained_bytes = _io_path(ROOT / retained).read_bytes()
        if _sha(retained_bytes) != digest:
            raise ValueError(f'{member} exact retained XML differs')
        work = json.loads(_io_path(ROOT / 'library/works' / work_id / 'work.json').read_bytes())
        editions = [edition for form in work['textual_forms'] for edition in form['editions']
                    if member in edition['edition_id']]
        if len(editions) != 1 or len(editions[0]['acquisition_ids']) != 1:
            raise ValueError(f'{member} edition/acquisition identity differs')
        form = next(form for form in work['textual_forms'] if editions[0] in form['editions'])
        acquisition = ROOT / 'library/works' / work_id / 'forms' / form['textual_form_id'] / 'editions' / editions[0]['edition_id'] / 'acquisitions' / (editions[0]['acquisition_ids'][0] + '.json')
        acquired = json.loads(_io_path(acquisition).read_bytes())
        retained_files = acquired.get('retained_files', [])
        if len(retained_files) != 1 or retained_files[0]['path'] != retained or retained_files[0]['sha256'] != digest:
            raise ValueError(f'{member} retained acquisition binding differs')
        source_path = Path('sources/commentaries/expositors-bible') / work_id / 'README.source.md'
        notice_path = Path('data/commentaries') / work_id / 'README.md'
        source_note = (
            f'# Electronic source and credit for {work_id}\n\n'
            f'The exact retained electronic edition is `{retained}` (SHA-256 `{digest}`). '
            f'The acquisition and work identity bind this one CCEL ThML witness to {title}. '
            f'The CCEL source page is {url}.\n\n'
            'The source-local CCEL permission note records permission to parse ThML/XML for text, '
            'a restriction on selling CCEL files or derivatives of their formatting, and the '
            'requested public acknowledgment “sourced via CCEL.org”. This is source evidence, '
            'not a rights-clearance or publication decision.\n\n'
            f'For any public data release, include the corresponding human-visible notice at '
            f'`{notice_path.as_posix()}` and bind the exact source-note and notice hashes through '
            '`public_notices`.\n'
        ).encode('utf-8')
        _put(ROOT / source_path, source_note)
        notice = (
            f'# Source credit: The Expositor\'s Bible — {title}\n\n'
            f'This electronic text was sourced via CCEL.org. See the '
            f'[CCEL source page]({url}).\n\n'
            'CCEL permitted parsing its electronic text for this reconstruction. '
            'Its files and formatting have separate conditions, including a restriction on '
            'selling CCEL files or derivatives of their formatting. This credit does not '
            'establish rights clearance or authorize a public release.\n'
        ).encode('utf-8')
        public_text = _utf8_markdown(notice, label=f'{member} future public notice')
        if _scan(public_text, f'{member} future public notice') or '<' in public_text or '>' in public_text:
            raise ValueError(f'{member} future public notice contains private or unsupported text')
        external = HOME / notice_path
        _put(external, notice)
        rows.append(dict(member=member, work_id=work_id, source_path=source_path.as_posix(),
                         source_sha256=_sha(source_note), notice_path=notice_path.as_posix(),
                         notice_sha256=_sha(notice), external_notice_path=external.as_posix(),
                         retained_xml_path=retained, retained_xml_sha256=digest,
                         acquisition_path=acquisition.relative_to(ROOT).as_posix()))
    index = dict(contract='ocd-expositors-lib034-ccel-public-notice-handoff-v1',
                 status='future-release-notice-only', permission_sha256=_sha(permission), items=rows)
    index_path = HOME / 'notice-index.json'
    _put(index_path, (json.dumps(index, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')) + '\n').encode('utf-8'))
    print(json.dumps(dict(index=index_path.as_posix(), index_sha256=_sha(_io_path(index_path).read_bytes()),
                          items=len(rows)), sort_keys=True))


if __name__ == '__main__':
    main()
