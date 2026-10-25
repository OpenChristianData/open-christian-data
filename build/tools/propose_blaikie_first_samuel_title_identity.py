"""Draft additive title identity using one existing acquired First Samuel witness."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.lib.path_io import io_path, resolve_path
from ocd_kernel.library.identities import load_work, validate_record
from ocd_kernel.library.acquisitions import load_acquisition

ROOT = resolve_path(Path(__file__)).parents[2]
LOG = Path('reports/_logs/blaikie-first-samuel-existing-install-20261003-v1')
OLD_WORK = 'expositors-bible--william-g-blaikie'
OLD_FORM = OLD_WORK + '--blaikie-expositor8--retained-en'
OLD_EDITION = OLD_WORK + '--blaikie-expositor8--ccel-electronic'
OLD_ACQUISITION = OLD_WORK + '--blaikie-expositor8--acquired'
WORK = 'blaikie-first-book-of-samuel'
FORM = WORK + '--retained-en'
EDITION = WORK + '--ccel-electronic'
ACQUISITION = WORK + '--acquired'
RAW = Path('raw/ccel/expositors-bible/blaikie_expositor8.xml')
RAW_SHA = 'b46bd6cb856df0819dedc06b23a657f7763b49501248db63ce762585d67603d4'


def digest(path):
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def canonical(record):
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def main():
    output = ROOT / LOG / 'title-specific-identity-proposal-v1'
    if io_path(output).exists():
        raise FileExistsError('Preserve earlier title identity proposal')
    if io_path(ROOT / 'library/works' / WORK).exists():
        raise ValueError('Canonical title-specific work collision')
    old_home = ROOT / 'library/works' / OLD_WORK
    before = {p.relative_to(io_path(old_home)).as_posix(): digest(p)
              for p in sorted(io_path(old_home).rglob('*')) if p.is_file()}
    old_acq_rel = Path('library/works') / OLD_WORK / 'forms' / OLD_FORM / 'editions' / OLD_EDITION / 'acquisitions' / (OLD_ACQUISITION + '.json')
    old_acq = load_acquisition(ROOT / old_acq_rel)
    old_state = json.loads(io_path(old_home / 'state.json').read_bytes())
    raw = io_path(ROOT / RAW).read_bytes()
    if len(raw) != 818071 or hashlib.sha256(raw).hexdigest() != RAW_SHA:
        raise ValueError('Original acquired raw bytes differ')
    if old_acq['retained_files'][0]['sha256'] != RAW_SHA or old_acq['url'] != 'https://www.ccel.org/ccel/blaikie/expositor8.html':
        raise ValueError('Original acquisition identity differs')
    crosswalk_rel = LOG / 'title-specific-identity-proposal-v1' / 'old-to-new-identity-crosswalk.json'
    new_acq_rel = Path('library/works') / WORK / 'forms' / FORM / 'editions' / EDITION / 'acquisitions' / (ACQUISITION + '.json')
    evidence = [RAW.as_posix(), crosswalk_rel.as_posix(), old_acq_rel.as_posix(),
                'sources/commentaries/expositors-bible/ccel-permission.md']
    work = dict(schema_version='2.0', work_id=WORK, title='The First Book of Samuel',
                creators=[dict(name='W. G. Blaikie', role='author', evidence=[RAW.as_posix() + '#i'])],
                evidence=evidence,
                textual_forms=[dict(textual_form_id=FORM, language='en', editions=[dict(
                    edition_id=EDITION, title='The First Book of Samuel', language='en', category='commentary',
                    acquisition_ids=[ACQUISITION], containing_source=dict(
                        title="The Expositor's Bible", locator='Complete CCEL electronic witness blaikie_expositor8.xml; source title page i',
                        evidence=[RAW.as_posix() + '#i']))])])
    acquisition = copy.deepcopy(old_acq)
    acquisition['acquisition_id'] = ACQUISITION
    acquisition['edition_id'] = EDITION
    targets = []
    for old_id, new_id in [(OLD_ACQUISITION, ACQUISITION), (OLD_EDITION, EDITION)]:
        selected = [r for r in old_state['targets'] if r['target_id'] == old_id]
        if len(selected) != 1 or selected[0]['stage'] != 'acquired':
            raise ValueError('Original selected acquired state differs')
        target = copy.deepcopy(selected[0])
        target['target_id'] = new_id
        target['evidence'] = list(dict.fromkeys(target['evidence'] + evidence + [new_acq_rel.as_posix()]))
        targets.append(target)
    state = dict(schema_version='2.0', work_id=WORK, targets=targets)
    for kind, record in [('work', work), ('acquisition', acquisition), ('state', state)]:
        validate_record(kind, record, context='First Samuel title proposal')
    preserved = {k: v for k, v in old_acq.items() if k not in {'acquisition_id', 'edition_id'}}
    if preserved != {k: v for k, v in acquisition.items() if k not in {'acquisition_id', 'edition_id'}}:
        raise ValueError('Original acquisition fields altered')
    crosswalk = dict(contract='ocd-first-samuel-title-identity-proposal-v1', status='proposal-only',
        proposed_at=datetime.now(timezone.utc).isoformat(),
        source_scope='One complete authored work: The First Book of Samuel; Second Samuel and Joshua excluded.',
        identity_map=dict(old=dict(work_id=OLD_WORK, textual_form_id=OLD_FORM, edition_id=OLD_EDITION, acquisition_id=OLD_ACQUISITION),
                          new=dict(work_id=WORK, textual_form_id=FORM, edition_id=EDITION, acquisition_id=ACQUISITION)),
        original_acquisition=dict(path=old_acq_rel.as_posix(), sha256=digest(ROOT / old_acq_rel)),
        proposed_acquisition_path=new_acq_rel.as_posix(),
        original_author_container_preimages=before,
        original_source=dict(path=RAW.as_posix(), bytes=len(raw), sha256=RAW_SHA, url=old_acq['url']),
        acquisition_field_delta=['acquisition_id', 'edition_id'],
        acquisition_accessed_at_present='accessed_at' in old_acq, acquisition_rights_present='rights' in old_acq,
        absence_qualification='Original acquisition has no accessed_at or rights field; neither is invented. Source DC.Rights Public Domain remains a source assertion; rights remain unresolved.',
        state_timestamp_disposition='Original acquired target updated_at timestamps retained; these are not acquisition access dates.',
        original_scope_warning_disposition='Original author-container source_scope and warning strings are preserved literally as historical acquisition statements. Primary title evidence supplies the new title identity.',
        original_author_container_unchanged=True, new_download_or_witness=False, canonical_install_performed=False,
        source_package_unchanged=True, candidate_readable_body_unchanged=True,
        header_binding_disposition='Final accepted header will bind new title identity and derived sidecar, with original acquisition linked by this crosswalk; source/body package remains unchanged.',
        schema_validation=dict(work='pass', acquisition='pass', state='pass'),
        approval_disposition='Parent and coordinating identity owner review required before final title stage.')
    io_path(output).mkdir(parents=True)
    for name, record in [('work.json', work), ('acquisition.json', acquisition), ('state.json', state), ('old-to-new-identity-crosswalk.json', crosswalk)]:
        io_path(output / name).write_bytes(canonical(record))
    load_work(output / 'work.json')
    load_acquisition(output / 'acquisition.json')
    if before != {p.relative_to(io_path(old_home)).as_posix(): digest(p)
                  for p in sorted(io_path(old_home).rglob('*')) if p.is_file()}:
        raise ValueError('Original author container changed while drafting proposal')
    receipt = dict(status='schema-valid-proposal', canonical_collision=False, canonical_install_performed=False,
                   work_id=WORK, original_author_container_unchanged=True,
                   files={p.name: digest(p) for p in sorted(io_path(output).iterdir()) if p.is_file()})
    io_path(output / 'proposal-receipt.json').write_bytes(canonical(receipt))
    print(json.dumps(dict(receipt, receipt_sha256=digest(output / 'proposal-receipt.json')), sort_keys=True))


if __name__ == '__main__':
    main()
