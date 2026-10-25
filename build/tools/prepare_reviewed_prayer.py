"""Prepare technical acceptance handoffs for the four exact PRAYER-001 candidates.

This writes only to a caller-selected fresh stage. It does not promote a master
or change the canonical work, state, acquisition, or retained-source records.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.tei.acceptance import (
    build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
REVIEW_ROOT = Path('D:/Library/Open Christian Data/candidate-reviews')
LIBRARY_ROOT = REVIEW_ROOT.parent
REVIEW = REVIEW_ROOT / 'prayer-20260922-review/PRAYER-001-final-review-20260923.md'
REVIEW_SHA256 = 'a5a981f62789d88b502ec740a127b208598c854ba64216efaae24de11f7d40e3'
XSD_SHA256 = '2d886fb9354567ab91d8a52286ef66276c6a932228ccbec04d7c4c9b6aa5a05f'
STATE_TICKET = Path('plans/2026-08-31-library-pipeline-redesign/tickets/PRAYER-001-four-new-acquisitions-to-tei.md')
CASES = {
    'little': ('little-treasure-of-prayers', '35737', '3ebbf96b60b3ee1e91c03e31a51a7f0c3f2ddaffa799da68b91e964fbdea46e7', '96bc809954071e2390a79c1cf74bbb9d47352dfd40c64a83b41d475d47a4c1f6', 'af7d86e660f6f9db99fbfd55b1646d2dc6b2979b0e6336627d8c8b76c8c18c8c', 'cc68e6a0e8b0138010666a118428e641bde183b48e94c5c71d7638b3756e88b0'),
    'murray': ('murray-ministry-of-intercession', '29296', 'd212f79a978f5a224678db38209f0b99e56193d1a2b4af312383c60c008e5ec6', '74c08e0fad807cadd38a526ae5a48482bd23c6a71b22d34d3fb64e4e75564b50', '754ba605348adb1fe8c29964d47f65abef64d4d6047b739b63a3860a468f34e3', 'e768a217e36fdea495057435d20ad0f7e6863809b7ee9eefdc53bec68b7271df'),
    'gordon': ('gordon-quiet-talks-on-prayer', '13196', '654a2134fb82611ab8a5454a0c45ec0d3f8e6b725dfc841ad6cde0d50ec5c51b', '84230ca24a6844416e6e3cbd5c56c8824365f93309fe88c789d1ff5fa8da7020', 'c198fce347c11fe45af982666f0b5805903b244fd55d75837b7619e511cb0974', '6fe54a9188d4813e4c2afe44de1e40d4c6763144e5a24af6c7a57843ec4875c3'),
    'goforth': ('goforth-how-i-know-god-answers-prayer', '26033', '81a88cb591de28aac30a45e85136f185e1dc32bc1d86c9d46d4ec4198f5dcf1f', '996bcdb7d1a26f12e2777f0c7b91bc91cfff00e5c6a55f849248094a12af6213', '6b40fd3caa2f0989f2b7048111eefd9dd630676d6223cf83c5d039674cb54c6d', '9e98a3bbeafa98f0275e5002b8283e98daf5f6a463b8040a1c6acac25c7b6f93'),
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _checked_inputs(root: Path, short: str) -> tuple[dict, CandidatePackage, bytes, dict, Path]:
    work_id, pg, package_hash, manifest_hash, report_hash, validation_hash = CASES[short]
    final = REVIEW_ROOT / 'prayer-20260922' / f'final-{short}-02'
    try:
        package = CandidatePackage.load(final / 'package')
    except (OSError, ValueError) as exc:
        raise PipelineError(f'{short}: exact candidate package failed integrity') from exc
    if package.sha256 != package_hash or package.manifest['source_manifest']['sha256'] != manifest_hash:
        raise PipelineError(f'{short}: candidate or source manifest identity changed')
    validation_raw = (final / 'validation.json').read_bytes()
    validation = json.loads(validation_raw)
    if sha(validation_raw) != validation_hash or validation.get('contract') != 'ocd-validation-report-v1':
        raise PipelineError(f'{short}: validation sidecar changed')
    attestation = validation.get('attestation', {})
    if (validation.get('status') != 'pass' or validation.get('findings') != []
            or validation.get('candidate_sha256') != package_hash
            or validation.get('source_manifest_sha256') != manifest_hash
            or validation.get('report_sha256') != report_hash
            or attestation.get('status') != 'pass' or attestation.get('findings') != []
            or attestation.get('candidate_sha256') != package_hash
            or attestation.get('source_manifest_sha256') != manifest_hash
            or attestation.get('xsd_sha256') != XSD_SHA256):
        raise PipelineError(f'{short}: final validation does not bind reviewed candidate')
    work = root / 'library/works' / work_id
    acquisition_path = work / f'forms/english/editions/pg{pg}/acquisitions/pg{pg}-extracted-html-20260922.json'
    acquisition = json.loads(acquisition_path.read_bytes())
    source = acquisition['retained_files']
    if (acquisition.get('edition_id') != f'pg{pg}' or acquisition.get('acquisition_id') != f'pg{pg}-extracted-html-20260922'
            or len(source) != 1 or source[0]['path'] != acquisition.get('source_path')
            or source[0]['sha256'] != acquisition.get('source_sha256')
            or source[0]['bytes'] != acquisition.get('source_bytes')):
        raise PipelineError(f'{short}: canonical extracted-HTML acquisition binding changed')
    retained = resolve_repo_path(root, acquisition['source_path'])
    source_raw = retained.read_bytes()
    provenance = json.loads(package.member_bytes('provenance.json'))
    if (len(source_raw) != acquisition['source_bytes'] or sha(source_raw) != acquisition['source_sha256']
            or attestation.get('source_sha256') != acquisition['source_sha256']
            or provenance.get('work_id') != work_id or provenance.get('edition_id') != f'pg{pg}'
            or provenance.get('source_path') != acquisition['source_path']
            or provenance.get('source_sha256') != acquisition['source_sha256']):
        raise PipelineError(f'{short}: reviewed source differs from canonical acquisition')
    return acquisition, package, validation_raw, validation, acquisition_path


def prepare(root: Path, stage: Path, short: str) -> Path:
    """Build one pending, technically checked acceptance record in a fresh root."""
    if short not in CASES:
        raise PipelineError(f'unknown PRAYER-001 work: {short}')
    root, stage = Path(root).resolve(), Path(stage).resolve()
    if stage.exists() or stage == root or root in stage.parents or LIBRARY_ROOT == stage or LIBRARY_ROOT in stage.parents:
        raise PipelineError('stage must be fresh and outside the canonical checkout and durable library')
    receipt_raw = REVIEW.read_bytes()
    if sha(receipt_raw) != REVIEW_SHA256:
        raise PipelineError('final PRAYER-001 review receipt changed')
    acquisition, package, validation_raw, validation, acquisition_path = _checked_inputs(root, short)
    work_id, pg, package_hash, manifest_hash, report_hash, validation_hash = CASES[short]
    identity = dict(work_id=work_id, textual_form_id='english', edition_id=f'pg{pg}', acquisition_id=acquisition['acquisition_id'])
    source = {key: acquisition[key] for key in ('source_path', 'source_sha256', 'source_bytes', 'source_scope')}
    scope_text = acquisition['source_scope']
    revision = dict(id='reviewed-prayer-001-v1', date='2026-09-23', note='Reversible technical source and identity binding of the exact PRAYER-001 reviewed candidate; human acceptance remains unrecorded.')
    original = package.member_bytes('content.tei.xml')
    derived = bind_reviewed_header(original, expected_sha256=sha(original), identity=identity, source=source, source_url=acquisition['url'], declared_scope=scope_text, revision=revision)
    header = etree.fromstring(original).find('{http://www.tei-c.org/ns/1.0}teiHeader')
    header_end = f'</{header.prefix + ":" if header.prefix else ""}teiHeader>'.encode()
    if original.split(header_end, 1)[1] != derived.split(header_end, 1)[1]:
        raise PipelineError(f'{short}: reviewed text changed during header binding')
    sibling = acquisition_path.with_name(f'pg{pg}-html-20260922.json')
    selected_record = validate_acquisition(acquisition_path, root=root)
    bundle_record = validate_acquisition(sibling, root=root)
    if (selected_record != acquisition or bundle_record.get('edition_id') != f'pg{pg}'
            or bundle_record.get('acquisition_id') != sibling.stem
            or any(bundle_record.get(key) != acquisition.get(key)
                   for key in ('source_path', 'source_bytes', 'source_sha256', 'url'))):
        raise PipelineError(f'{short}: canonical acquisition records do not agree on the reviewed source')
    work = stage / 'library/works' / work_id
    evidence = work / 'integration/reviewed-prayer-001-v1'
    edition = work / f'forms/english/editions/pg{pg}'
    evidence.mkdir(parents=True)
    shutil.copy2(root / 'library/works' / work_id / 'work.json', work / 'work.json')
    shutil.copy2(root / 'library/works' / work_id / 'state.json', work / 'state.json')
    staged_acquisition = edition / 'acquisitions' / acquisition_path.name
    staged_acquisition.parent.mkdir(parents=True)
    shutil.copy2(acquisition_path, staged_acquisition)
    shutil.copy2(sibling, staged_acquisition.with_name(sibling.name))
    staged_ticket = stage / STATE_TICKET
    staged_ticket.parent.mkdir(parents=True)
    shutil.copy2(root / STATE_TICKET, staged_ticket)
    retained_bindings: dict[str, tuple[int, str]] = {}
    for record in (selected_record, bundle_record):
        for member in record['retained_files']:
            relative = member['path']
            binding = (member['bytes'], member['sha256'])
            prior = retained_bindings.get(relative)
            if prior is not None and prior != binding:
                raise PipelineError(f'{short}: conflicting acquisition bindings for {relative}')
            retained_bindings[relative] = binding
            raw = resolve_repo_path(root, relative).read_bytes()
            if len(raw) != binding[0] or sha(raw) != binding[1]:
                raise PipelineError(f'{short}: retained member changed: {relative}')
            staged_member = stage / relative
            staged_member.parent.mkdir(parents=True, exist_ok=True)
            if not staged_member.exists():
                staged_member.write_bytes(raw)
            if staged_member.stat().st_size != binding[0] or sha(staged_member.read_bytes()) != binding[1]:
                raise PipelineError(f'{short}: staged retained member differs: {relative}')
    shutil.copytree(package.path, evidence / 'original-package')
    if CandidatePackage.load(evidence / 'original-package').sha256 != package_hash:
        raise PipelineError(f'{short}: staged original package differs from reviewed package')
    (evidence / 'historical-review.md').write_bytes(receipt_raw)
    (evidence / 'historical-validation.json').write_bytes(validation_raw)
    candidate = evidence / 'candidate.tei.xml'
    candidate.write_bytes(derived)
    if validate_file(candidate):
        raise PipelineError(f'{short}: derived candidate does not pass current TEI schema')
    candidate_binding = make_file_binding(stage, candidate)
    member = acquisition['retained_files'][0]
    included = dict(path=member['path'], bytes=member['bytes'], sha256=member['sha256'], scope=member['scope'], position=1)
    scope = dict(kind='edition', declared=scope_text, expected_members=[dict(path=member['path'], position=1)], included_members=[included], excluded_members=[])
    common = dict(identity=identity, source=source, candidate=candidate_binding, scope=scope_text)
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    command = f'py -3 -m build.tools.prepare_reviewed_prayer --work {short} --stage {stage}'
    accounting = evidence / 'source-accounting.json'
    write(accounting, common | dict(accepted_scope=dict(kind='edition', declared=scope_text), expected_members=scope['expected_members'], included_members=scope['included_members'], excluded_members=[], missing_members=[], unknown_members=[], source_sha256=source['source_sha256'], source_bytes=source['source_bytes'], original_package_sha256=package_hash, source_manifest_sha256=manifest_hash))
    descriptions = {
        'validation': 'Pinned final validator sidecar is passing, finding-free, and binds the exact reviewed package and source manifest.',
        'accounting': 'Both canonical acquisition sidecars and every retained ZIP, HTML, and image member are byte-verified in the stage; the reviewed HTML source remains the acceptance binding.',
        'fidelity': 'Historical independent source oracle passed for the exact original candidate; the reviewed text bytes are unchanged.',
        'reproducibility': 'The pinned final receipt reports exact six-member and validation-sidecar reproduction; this stage preserves the original package.',
        'schema': 'Derived header-bound candidate passes the current vendored TEI P5 schema.',
        'closure': 'Pinned package, final review receipt, validation sidecar, source manifest identity, and current canonical acquisition agree.',
    }
    technical = dict(producer=dict(id='reviewed-prayer-001-header-adapter-v1'), checker=dict(id='historical-prayer-oracle-and-current-acceptance-validator'), shared_assumptions=['Historical reconstruction proof and current staging share the retained HTML hash.'], independent_corroboration='Pinned independent source oracle, exact reproduction receipt, and unchanged reviewed tei:text bytes.')
    for name, observation in descriptions.items():
        path = evidence / f'{name}.json'
        payload = common | dict(status='pass', command=command, exit_code=0, checked_at=now, observation=observation, historical_validation_sha256=validation_hash, historical_report_sha256=report_hash)
        if name == 'accounting':
            payload |= dict(accepted_scope=dict(kind='edition', declared=scope_text), expected_members=scope['expected_members'], included_members=scope['included_members'], excluded_members=[], missing_members=[], unknown_members=[])
        write(path, payload)
        technical[name] = dict(path=path, status='pass', command=command, exit_code=0)
    residuals = ['Historical visual review receipt reused; this staging run performed no fresh visual inspection.', 'Bounded selected-locus visual review only; uninspected source and TEI loci remain.', 'CVW panes were unlinked; no governed source-to-TEI locus correspondence was inferred.']
    if short == 'little':
        residuals.append('The wide litany table was horizontally clipped in CVW; its rows and cells were checked structurally, not fully visually.')
    if short == 'murray':
        residuals.append('All 79 image carriers and TEI graphics were checked structurally, but image visual comparison remains unverified; the CVW graphic locus was not selectable.')
    review = dict(reviewer='agent:prayer-001-technical-reconciliation', reviewed_at=now, coverage=dict(status='partial', declared=scope_text, reached=['selected-loci'], inspected=['selected-loci'], unreviewed=['uninspected-loci']), source_quality_uncertainty=['No independent print-edition collation or rights assessment.'], discrepancies=[], unreviewed_residuals=residuals)
    review_path = evidence / 'review.json'
    write(review_path, common | review | dict(historical_review_sha256=REVIEW_SHA256))
    decision = dict(source_local_disposition='Technical acceptance evidence staged with pending promotion; no master installed or human decision recorded.', blockers=[], agent_assessment=dict(status='accepted', actor='agent:prayer-001-technical-preparation', assessed_at=now, supported_scope=scope_text, unassessed_stronger_claims=['human acceptance', 'full visual comparison', 'rights clearance', 'publication'], unresolved_claims=residuals), human_decision=dict(status='not-recorded'))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting, scope=scope, technical=technical, review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
    acceptance = edition / 'acceptance.json'
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    validate_state(work / 'state.json', root=stage)
    return acceptance


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', choices=sorted(CASES), required=True)
    parser.add_argument('--stage', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(ROOT, args.stage, args.work))
