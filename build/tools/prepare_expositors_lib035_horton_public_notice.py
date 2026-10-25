"""Prepare a source-bound future data-path CCEL credit; do not publish."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.release.notices import _utf8_markdown
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path('D:/Library/Open Christian Data/candidate-reviews/expositors-lib035-horton-ccel-public-notice-20260927-v1')
WORK_ID = 'expositors-bible--robert-f-horton'
FORM_ID = 'expositors-bible--robert-f-horton--horton-expositorprov--retained-en'
EDITION_ID = 'expositors-bible--robert-f-horton--horton-expositorprov--ccel-electronic'
ACQUISITION_ID = 'expositors-bible--robert-f-horton--horton-expositorprov--acquired'
RETAINED = Path('raw/ccel/expositors-bible/horton_expositorprov.xml')
RETAINED_SHA256 = 'a7372596c60d053b539e957c01d29a54269da5c25b094cd7b373cb7e834e122d'
SOURCE_URL = 'https://www.ccel.org/ccel/horton/expositorprov.html'
NOTICE = Path('data/commentaries/expositors-bible--robert-f-horton/README.md')
SOURCE_NOTE = Path('sources/commentaries/expositors-bible/expositors-bible--robert-f-horton/README.source.md')


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _put(path: Path, data: bytes) -> None:
    target = _io_path(path)
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError(f'notice path has different bytes: {path}')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def main() -> None:
    source = _io_path(ROOT / RETAINED).read_bytes()
    if _sha(source) != RETAINED_SHA256:
        raise ValueError('retained Horton source differs')
    permission = _io_path(ROOT / 'sources/commentaries/expositors-bible/ccel-permission.md').read_bytes()
    if b'sourced via CCEL.org' not in permission or b'do not sell CCEL files' not in permission:
        raise ValueError('CCEL permission guidance differs')
    work_path = ROOT / 'library/works' / WORK_ID
    work = json.loads(_io_path(work_path / 'work.json').read_bytes())
    forms = work.get('textual_forms', [])
    if (work.get('work_id') != WORK_ID or len(forms) != 1 or
            forms[0].get('textual_form_id') != FORM_ID or len(forms[0].get('editions', [])) != 1):
        raise ValueError('Horton work or textual form differs')
    edition = forms[0]['editions'][0]
    if edition.get('edition_id') != EDITION_ID or edition.get('acquisition_ids') != [ACQUISITION_ID]:
        raise ValueError('Horton edition or acquisition identity differs')
    acquisition_path = (work_path / 'forms' / FORM_ID / 'editions' / EDITION_ID /
                        'acquisitions' / f'{ACQUISITION_ID}.json')
    acquisition_bytes = _io_path(acquisition_path).read_bytes()
    acquisition = json.loads(acquisition_bytes)
    files = acquisition.get('retained_files', [])
    if (acquisition.get('acquisition_id') != ACQUISITION_ID or
            acquisition.get('url') != SOURCE_URL or len(files) != 1 or
            files[0].get('path') != RETAINED.as_posix() or
            files[0].get('sha256') != RETAINED_SHA256):
        raise ValueError('Horton acquired source binding differs')

    notice = (
        "# Source credit: The Expositor's Bible: The Book of Proverbs\n\n"
        "This electronic text of R. F. Horton's *The Expositor's Bible: The Book of Proverbs* "
        f'was sourced via [CCEL.org]({SOURCE_URL}).\n\n'
        'CCEL permitted parsing its ThML/XML text for this reconstruction. CCEL files and '
        'formatting have separate conditions, including a restriction on selling CCEL files '
        'or derivatives of their formatting. This credit does not establish rights clearance '
        'or authorize a public release.\n'
    ).encode('utf-8')
    public_text = _utf8_markdown(notice, label='Horton future public notice')
    if _scan(public_text, 'Horton future public notice') or '<' in public_text or '>' in public_text:
        raise ValueError('future public notice contains private or unsupported text')
    source_note = (
        '# The Book of Proverbs electronic source and future credit\n\n'
        f'The exact retained electronic witness is `{RETAINED.as_posix()}` '
        f'(SHA-256 `{RETAINED_SHA256}`), acquired from {SOURCE_URL}. '
        f'It belongs to textual form `{FORM_ID}`, edition `{EDITION_ID}`, '
        f'and acquisition `{ACQUISITION_ID}`. The source is one complete CCEL '
        'ThML electronic edition with title, introduction, 31 chapters, a passage index, '
        'general index, and index. Its 678-row table is represented in TEI. Its inline '
        'image at source ID xi-p8.1 retains URL, alt text, and title, but the referenced '
        'PNG bytes are absent from the one-file retained acquisition. '
        'The electronic header names ccel as publisherID and London: Hodder and '
        'Stoughton, 1890 as printSourceInfo; those roles remain distinct from the '
        'acquisition provider and do not establish collated print lineage.\n\n'
        'The source-local CCEL permission record permits parsing and records a '
        'restriction on selling CCEL files or derivatives of their formatting. '
        f'For any public data release, include the human-visible notice at '
        f'`{NOTICE.as_posix()}` and bind this exact source note and notice through '
        '`public_notices`. This preparation does not '
        'establish rights clearance or authorize publication.\n'
    ).encode('utf-8')
    _utf8_markdown(source_note, label='Horton source notice')
    _put(ROOT / SOURCE_NOTE, source_note)
    external = HOME / NOTICE
    _put(external, notice)
    index = {
        'contract': 'ocd-expositors-lib035-horton-ccel-public-notice-handoff-v1',
        'status': 'future-release-notice-only',
        'work_id': WORK_ID,
        'textual_form_id': FORM_ID,
        'edition_id': EDITION_ID,
        'acquisition_id': ACQUISITION_ID,
        'acquisition_path': acquisition_path.relative_to(ROOT).as_posix(),
        'acquisition_sha256': _sha(acquisition_bytes),
        'retained_xml_path': RETAINED.as_posix(),
        'retained_xml_sha256': RETAINED_SHA256,
        'source_url': SOURCE_URL,
        'permission_sha256': _sha(permission),
        'source_path': SOURCE_NOTE.as_posix(),
        'source_sha256': _sha(source_note),
        'notice_path': NOTICE.as_posix(),
        'notice_sha256': _sha(notice),
        'external_notice_path': external.as_posix(),
    }
    index_path = HOME / 'notice-index.json'
    _put(index_path, (json.dumps(index, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')) + '\n').encode('utf-8'))
    print(json.dumps({'index': index_path.as_posix(),
                      'index_sha256': _sha(_io_path(index_path).read_bytes()),
                      'source_sha256': _sha(source_note),
                      'notice_sha256': _sha(notice)}, sort_keys=True))


if __name__ == '__main__':
    main()
