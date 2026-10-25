"""Prepare a source-bound future data-path CCEL credit; do not publish."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.release.notices import _utf8_markdown
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path('D:/Library/Open Christian Data/candidate-reviews/owen-lib052-sin-grace-ccel-public-notice-20260928-v1')
WORK_ID = 'john-owen-sin-grace'
FORM_ID = 'john-owen-sin-grace-english'
EDITION_ID = 'john-owen-sin-grace-ccel-thml-electronic'
ACQUISITION_ID = 'john-owen-sin-grace-ccel-retained-xml'
RETAINED = Path('raw/ccel/owen/sin_grace.xml')
RETAINED_SHA256 = 'f5d5d1f26e38f78f5cf370eb529d9f0198517a20b168bb1087da0ae7dee62039'
SOURCE_URL = 'https://www.ccel.org/ccel/owen/sin_grace.html'
NOTICE = Path('data/prose/john-owen-sin-grace/README.md')
SOURCE_NOTE = Path('sources/structured-text/lib052-john-owen/john-owen-sin-grace/README.source.md')


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
        raise ValueError('retained Owen Sin and Grace source differs')
    permission = _io_path(ROOT / 'sources/structured-text/lib052-john-owen/README.md').read_bytes()
    if b'CCEL.org' not in permission or b'do not sell CCEL files' not in permission:
        raise ValueError('CCEL permission guidance differs')
    work_path = ROOT / 'library/works' / WORK_ID
    work = json.loads(_io_path(work_path / 'work.json').read_bytes())
    forms = work.get('textual_forms', [])
    if (work.get('work_id') != WORK_ID or len(forms) != 1 or
            forms[0].get('textual_form_id') != FORM_ID or len(forms[0].get('editions', [])) != 1):
        raise ValueError('Owen Sin and Grace work or textual form differs')
    edition = forms[0]['editions'][0]
    if edition.get('edition_id') != EDITION_ID or edition.get('acquisition_ids') != [ACQUISITION_ID]:
        raise ValueError('Owen Sin and Grace edition or acquisition identity differs')
    acquisition_path = (work_path / 'forms' / FORM_ID / 'editions' / EDITION_ID /
                        'acquisitions' / f'{ACQUISITION_ID}.json')
    acquisition_bytes = _io_path(acquisition_path).read_bytes()
    acquisition = json.loads(acquisition_bytes)
    files = acquisition.get('retained_files', [])
    if (acquisition.get('acquisition_id') != ACQUISITION_ID or
            acquisition.get('url') != SOURCE_URL or len(files) != 1 or
            files[0].get('path') != RETAINED.as_posix() or
            files[0].get('sha256') != RETAINED_SHA256):
        raise ValueError('Owen Sin and Grace acquired source binding differs')

    notice = (
        "# Source credit: A Treatise of the Dominion of Sin and Grace\n\n"
        "This electronic text of John Owen's *A Treatise of the Dominion of Sin and Grace* "
        f'was sourced via [CCEL.org]({SOURCE_URL}). Its electronic header says the '
        'base text was extracted from the AGES Digital Library John Owen Collection.\n\n'
        'CCEL permitted parsing its ThML/XML text for this reconstruction. CCEL files and '
        'formatting have separate conditions, including a restriction on selling CCEL files '
        'or derivatives of their formatting. Rights to the AGES-derived electronic base remain '
        'unresolved. This credit does not establish rights clearance or authorize a public release.\n'
    ).encode('utf-8')
    public_text = _utf8_markdown(notice, label='Owen Sin and Grace future public notice')
    if _scan(public_text, 'Owen Sin and Grace future public notice') or '<' in public_text or '>' in public_text:
        raise ValueError('future public notice contains private or unsupported text')
    source_note = (
        '# A Treatise of the Dominion of Sin and Grace electronic source and future credit\n\n'
        f'The exact retained electronic witness is `{RETAINED.as_posix()}` '
        f'(SHA-256 `{RETAINED_SHA256}`), acquired from {SOURCE_URL}. '
        f'It belongs to textual form `{FORM_ID}`, edition `{EDITION_ID}`, '
        f'and acquisition `{ACQUISITION_ID}`. The source is one CCEL ThML '
        'electronic edition with its treatise and indexes. The electronic header names '
        'ccel as publisherID, a Banner of Truth Trust Edinburgh 1965 print source, '
        'and an AGES Digital Library electronic base with an AGES Software copyright '
        'assertion. These roles remain distinct. The print source has not been '
        'independently collated, and rights to the AGES-derived base remain unresolved.\n\n'
        'The source-local CCEL permission record permits parsing and records a '
        'restriction on selling CCEL files or derivatives of their formatting. '
        f'For any public data release, include the human-visible notice at '
        f'`{NOTICE.as_posix()}` and bind this exact source note and notice through '
        '`public_notices`. This preparation does not establish rights clearance '
        'or authorize publication.\n'
    ).encode('utf-8')
    _utf8_markdown(source_note, label='Owen Sin and Grace source notice')
    _put(ROOT / SOURCE_NOTE, source_note)
    external = HOME / NOTICE
    _put(external, notice)
    index = {
        'contract': 'ocd-owen-lib052-sin-grace-ccel-public-notice-handoff-v1',
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
