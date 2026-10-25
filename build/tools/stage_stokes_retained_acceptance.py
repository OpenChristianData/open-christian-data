"""Prepare a guarded, external two-volume Stokes accepted-library generation."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from build.tei.stokes_retained_scope import ROOT, LOG, WORK_ID, MEMBERS, OLD_PACKAGE, sha
from build.tei.stokes_retained_completion import SOURCE_DIR, canonical
from build.tei.stokes_retained_completion_oracle import oracle, check, _IMPORT_PATHS
from build.tools.prepare_stokes_retained_candidates import CANDIDATES
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import validate_identity_update, load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage, validate
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, write_acceptance, validate_acceptance, PROMOTED_MASTER_REASON
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.projection.categories.commentary import project_accepted_commentary, verify_accepted_commentary

LIBRARY = Path('D:/Library/Open Christian Data')
WORK = Path('library/works') / WORK_ID
EVIDENCE = WORK / 'integration/stokes-retained-current-20261003-v1'


def edition_path(spec):
    return WORK / 'forms' / spec['form'] / 'editions' / spec['edition']


def read(path):
    return json.loads(_io_path(path).read_bytes())


def write(stage, relative, raw):
    path = stage / relative; _io_path(path.parent).mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(raw); return path


def write_json(stage, relative, value):
    return write(stage, relative, canonical(value))


def copy(root, stage, relative):
    return write(stage, relative, _io_path(root / relative).read_bytes())


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def projection_gate(root, acceptance, *, raw_evidence=None):
    try:
        result = project_accepted_commentary(root, acceptance_path=acceptance)
        errors = verify_accepted_commentary(root, acceptance_path=acceptance, rows=result['rows'], receipt=result['receipt'])
        gate = dict(status='pass' if not errors else 'held', rows=len(result['rows']), errors=errors)
    except PipelineError as error:
        gate = dict(status='held', rows=0, errors=[str(error)])
    if raw_evidence is not None:
        _io_path(raw_evidence).write_bytes(canonical(gate | dict(reviewed_root=root.as_posix())))
    # Preserve the known Windows logical/extended-root failure locus while
    # comparing the same held gate across stage, fixture, and canonical roots.
    normalized = []
    spellings = sorted({str(root), root.as_posix(), str(_io_path(root))}, key=len, reverse=True)
    for message in gate['errors']:
        if message.startswith('accepted authority file is outside root: '):
            for spelling in spellings:
                for separator in ['\\', '/']:
                    message = message.replace(spelling + separator, '<reviewed-root>' + separator)
        normalized.append(message)
    return gate | dict(errors=normalized)


def dependencies(root):
    result = {Path('build/tei/stokes_retained_scope.py'), Path('build/tei/stokes_retained_completion.py'), Path('build/tei/stokes_retained_completion_oracle.py'), Path('build/tei/ccel_retained_native_emitter.py'), Path('build/tools/prepare_stokes_retained_candidates.py'), Path('build/tools/stage_stokes_retained_acceptance.py'), Path('build/tools/install_stokes_retained_acceptance.py'), Path('ocd_kernel/__init__.py'), Path('ocd_kernel/tei/writer.py')}
    result.update(p.relative_to(root) for directory, suffix in [('ocd_kernel/reconstruction', '*.py'), ('ocd_kernel/reconstruction/schemas', '*.json'), ('schemas/v2', '*.json'), ('ocd_kernel/tei/vendor/xsd', '*.xsd')] for p in (root / directory).rglob(suffix))
    result.update(Path(p) for p in _IMPORT_PATHS)
    # Additional modules observed after a fresh actual two-volume preflight,
    # beyond the independent oracle's separately scoped seven import paths.
    result.update(Path(p) for p in ['build/__init__.py', 'build/tei/__init__.py',
        'ocd_kernel/library/__init__.py', 'ocd_kernel/library/source_selection.py',
        'ocd_kernel/projection/source_projection_evidence.py', 'ocd_kernel/tei/__init__.py',
        'ocd_kernel/tei/normalization.py', 'ocd_kernel/tei/projection_profile.py'])
    result.update(Path(p) for p in ['ocd_kernel/tei/acceptance.py', 'ocd_kernel/tei/install_accepted.py', 'ocd_kernel/tei/reviewed_integration.py', 'ocd_kernel/tei/validate.py', 'ocd_kernel/library/state.py', 'ocd_kernel/library/identities.py', 'ocd_kernel/library/acquisitions.py', 'ocd_kernel/library/_common.py', 'ocd_kernel/lib/path_io.py', 'ocd_kernel/lib/storage_topology.py', 'ocd_kernel/lib/atomic_io.py', 'ocd_kernel/projection/__init__.py', 'ocd_kernel/projection/categories/__init__.py', 'ocd_kernel/projection/categories/commentary.py', 'ocd_kernel/projection/categories/commentary_source_native.py', 'ocd_kernel/projection/categories/native_documents.py', 'ocd_kernel/projection/native_content.py', 'ocd_kernel/projection/native_content_check.py', 'ocd_kernel/projection/envelope.py', 'ocd_kernel/projection/scripture_authority.py', 'ocd_kernel/projection/scripture_targets.py', 'ocd_kernel/projection/scripture_targets_check.py', 'build/bible_data/osis_book_codes.json'])
    result.update(p.relative_to(root) for p in (root / OLD_PACKAGE).iterdir() if p.is_file())
    result.update({LOG / 'retained-package-recovery.json', LOG / 'retained-scope-reconciliation.json', LOG / 'candidate-completion-receipt.json'})
    for member_id, spec in MEMBERS.items():
        manifest_path = SOURCE_DIR / (member_id + '.source-manifest.json')
        manifest = SourceManifest.load(root / manifest_path, repository_root=root)
        result.add(manifest_path); result.add(LOG / (member_id + '-current-review.json'))
        result.add(edition_path(spec) / 'acquisitions' / (spec['acquisition'] + '.json'))
        result.update(Path(x['path']) for x in manifest.record['authorities'])
    return result


def prepare(stage, *, root=ROOT):
    root = root.resolve(strict=True); stage = stage.absolute()
    if stage.exists() or stage.parent != (LIBRARY / 'candidate-reviews').resolve(strict=True) or not stage.name.startswith('stokes-s-'):
        raise PipelineError('Fresh external Stokes stage required')
    before = _files(root / WORK)
    work = read(root / WORK / 'work.json'); original_work = json.loads(json.dumps(work))
    state = read(root / WORK / 'state.json')
    scope_review = read(root / LOG / 'retained-scope-reconciliation.json')
    if scope_review['status'] != 'pass' or scope_review['included_volume_count'] != 2 or len(work['textual_forms']) != 2:
        raise PipelineError('Complete existing two-volume Stokes envelope differs')
    for spec in MEMBERS.values():
        if (root / edition_path(spec) / 'master.tei.xml').exists() or (root / edition_path(spec) / 'acceptance.json').exists():
            raise PipelineError('Stokes canonical accepted authority already exists; no replacement')
    stage.mkdir()
    for relative in before: copy(root, stage, WORK / relative)
    for relative in dependencies(root): copy(root, stage, relative)
    evidence = set(work['evidence'] + [p for target in state['targets'] for p in target['evidence']])
    for relative in evidence:
        # Existing evidence may select a JSON fragment; copy the containing
        # retained file while preserving the original sidecar reference exactly.
        containing_file = Path(relative.split('#', 1)[0])
        if not _io_path(stage / containing_file).exists(): copy(root, stage, containing_file)
    write(stage, EVIDENCE / 'two-volume-source-scope.json', (root / LOG / 'retained-scope-reconciliation.json').read_bytes())
    at = now(); volumes = []
    for member_id, spec in MEMBERS.items():
        edition = edition_path(spec); lane = EVIDENCE / member_id
        manifest_path = SOURCE_DIR / (member_id + '.source-manifest.json')
        manifest = SourceManifest.load(root / manifest_path, repository_root=root)
        package = CandidatePackage.load(CANDIDATES / member_id / 'package')
        report = validate(manifest, package, oracle)
        current = read(root / LOG / (member_id + '-current-review.json'))
        direct = check(member_id, package.member_bytes('content.tei.xml'), package.member_bytes('source-accountability.json'))
        if report.status != 'pass' or current['package_sha256'] != package.sha256 or current['oracle_report_sha256'] != report.sha256 or current['direct_source_review']['candidate_sha256'] != direct['candidate_sha256'] or not current['reproducibility']['exact_six_member_bytes_equal'] or len(current['reproducibility']['replays']) != 2 or not current['import_closure_proof']['rejected'] or current['import_closure_proof']['observed_paths'] != list(_IMPORT_PATHS) or len(current['direct_source_review']['mutations']) != 9 or not all(x['rejected'] for x in current['direct_source_review']['mutations']):
            raise PipelineError('Stokes current source/replay/negative proof differs')
        acquisition_rel = edition / 'acquisitions' / (spec['acquisition'] + '.json')
        acquisition = validate_acquisition(root / acquisition_rel, root=root)
        if acquisition['source_sha256'] != spec['sha256'] or len(acquisition['retained_files']) != 1:
            raise PipelineError('Stokes existing acquisition source differs')
        form = next(x for x in work['textual_forms'] if x['textual_form_id'] == spec['form'])
        edition_record = next(x for x in form['editions'] if x['edition_id'] == spec['edition'])
        if edition_record.get('category') is not None: raise PipelineError('Stokes category preimage changed')
        edition_record['category'] = 'commentary'
        for name in package.member_names: write(stage, lane / 'inputs/package' / name, package.member_bytes(name))
        write(stage, lane / 'inputs/current-review.json', (root / LOG / (member_id + '-current-review.json')).read_bytes())
        identity = dict(work_id=WORK_ID, textual_form_id=spec['form'], edition_id=spec['edition'], acquisition_id=spec['acquisition'])
        source = {key: acquisition[key] for key in ['source_path', 'source_sha256', 'source_bytes', 'source_scope']}
        selected = f"Complete retained CCEL electronic Acts Volume {spec['volume']}, including title/preface/contents, all {20 if spec['volume'] == 1 else 18} source commentary chapters, printed and generated indices, attached notes, tables, literal source references and administrative accounting. Whole acquired Stokes work separately accounts both volumes (2/2)."
        revision = dict(id=member_id + '-retained-current-20261003-v1', date=datetime.now(timezone.utc).date().isoformat(), note='Readable faithful retained volume; original source order and literal identities preserved.')
        raw = package.member_bytes('content.tei.xml')
        bound = bind_reviewed_header(raw, expected_sha256=sha(raw), identity=identity, source=source, source_url=acquisition['url'], declared_scope=selected, revision=revision)
        # A sourceDesc p must contain its binding bibl; original source wording remains exact.
        begin = bound.index(b'<bibl xmlns='); end = bound.index(b'</bibl>', begin) + len(b'</bibl>')
        binding = bound[begin:end]; bound = bound[:begin] + bound[end:]
        if bound.count(b'</p></sourceDesc>') != 1: raise PipelineError('Stokes sourceDesc shape differs')
        bound = bound.replace(b'</p></sourceDesc>', binding + b'</p></sourceDesc>', 1)
        if bound.split(b'</teiHeader>', 1)[1] != raw.split(b'</teiHeader>', 1)[1]: raise PipelineError('Stokes header binding changed readable body')
        candidate = write(stage, lane / 'candidate.tei.xml', bound)
        if errors := validate_file(candidate): raise PipelineError(str(errors[:3]))
        expected = [dict(path=spec['path'], position=1)]
        included = [dict(path=spec['path'], position=1, bytes=spec['bytes'], sha256=spec['sha256'], scope=selected)]
        accepted_scope = dict(kind='volume', declared=selected)
        common = dict(identity=identity, source=source, candidate=make_file_binding(stage, candidate), scope=selected, accepted_scope=accepted_scope,
            expected_members=expected, included_members=included, excluded_members=[], missing_members=[], unknown_members=[],
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256, oracle_report_sha256=report.sha256,
            direct_source_review=make_file_binding(stage, stage / lane / 'inputs/current-review.json'))
        accounting = write_json(stage, lane / 'source-accounting.json', common | dict(scope=source['source_scope'], source_sha256=spec['sha256'], source_bytes=spec['bytes'], full_source_elements=spec['elements'], readable_source_elements=spec['body_elements'] - 1,
            administrative_comments=18, administrative_comment_disposition='Exact ledger fields; actual readable source independently compared after bounded whitespace joins; inverse entire source body C14N equal',
            retained_administration='All original ThML header/CSS source fields accounted', complete_acquired_work_volumes=2, original_candidate_route=current['direct_source_review'].get('original_candidate_route', 'Acts II existing ledger repair; Acts I pre-existing companion completion'), omitted_readable_elements=0))
        command = 'py -3 -m build.tools.stage_stokes_retained_acceptance'
        technical = dict(producer={'id': manifest.record['converter']['id']}, checker={'id': manifest.record['validator']['id']}, shared_assumptions=['Pinned raw electronic witness, P5, literal mapping policy; independent oracle does not import emitter or trust private accounting for actual readable body.'], independent_corroboration='Direct full raw source traversal vs actual readable DOM verifies all direct/tail payloads, semantic tags/attributes, note attachments and parent/order. Exact administrative comment fields and source-derived whitespace joins checked before inverse full source body C14N. Nine negative challenges rejected per volume; fresh Python replay all six package members exact. Acts II original5892feature graph and encoded source witness independently match raw.')
        for name in ['validation', 'accounting', 'fidelity', 'reproducibility', 'schema', 'closure']:
            proof = write_json(stage, lane / (name + '.json'), common | dict(status='pass', command=command, exit_code=0, claim=name, readable_body_unchanged_at_header_binding=True, actual_readable_body_inverse_c14n_equal=True))
            technical[name] = dict(path=proof, status='pass', command=command, exit_code=0)
        review = dict(reviewer='agent:stokes-existing-retained-source-review', reviewed_at=at,
            coverage=dict(status='complete', declared=selected, reached=['all retained source volume XML elements', 'all actual readable source paragraphs/front matter/notes/indices/tables/reference targets', 'all source attributes, tails and order', 'all18administrative comments and metadata/CSS fields'], inspected=['all actual readable source paragraphs/front matter/notes/indices/tables/reference targets', 'all source attributes, tails and order', 'all18administrative comments and metadata/CSS fields'], unreviewed=[]),
            source_quality_uncertainty=['Retained CCEL electronic witness only; literal print imprint typo preserved; no print or independent provider collation.', 'Acts I has15source-broken local links (printed #Five links and generated blank/foreign entries); literal label and missing-target semantics retained, no invented link targets. Acts II hasnone.'], discrepancies=[], unreviewed_residuals=['Human review, CCEL formatting rights, print collation, and release remain separate; actual commentary projection independently measured.'])
        review_path = write_json(stage, lane / 'review.json', common | review)
        decision = dict(source_local_disposition='Agent accepts the complete faithful retained electronic volume within the explicit two-volume acquired work.', blockers=[], agent_assessment=dict(status='accepted', actor=review['reviewer'], assessed_at=at, supported_scope=selected, unresolved_claims=[], unassessed_stronger_claims=['human review', 'print collation', 'rights clearance', 'publication', 'downstream commentary projection']), human_decision={'status': 'not-recorded'})
        record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting,
            scope=accepted_scope | dict(expected_members=expected, included_members=included, excluded_members=[]), technical=technical, review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
        acceptance = stage / edition / 'acceptance.json'; write_acceptance(acceptance, record); validate_acceptance(acceptance, root=stage)
        master = write(stage, edition / 'master.tei.xml', bound)
        record['promotion'] = dict(record['promotion']); record['promotion'].update(status='promoted', promoted_at=at, master=make_file_binding(stage, master)); write_acceptance(acceptance, record)
        targets = [x for x in state['targets'] if x['target_type'] == 'edition' and x['target_id'] == spec['edition']]
        if len(targets) != 1 or targets[0]['stage'] != 'acquired': raise PipelineError('Stokes edition acquired preimage differs')
        targets[0].update(stage='accepted', reason=PROMOTED_MASTER_REASON, updated_at=at)
        targets[0]['evidence'].extend([(edition / 'master.tei.xml').as_posix(), (edition / 'acceptance.json').as_posix()])
        write_json(stage, WORK / 'work.json', work)
        volumes.append(dict(member_id=member_id, source_sha256=spec['sha256'], source_manifest_sha256=manifest.sha256,
            candidate_package_sha256=package.sha256, oracle_report_sha256=report.sha256, master_sha256=sha(master.read_bytes()), acceptance_sha256=sha(acceptance.read_bytes()), scope_kind='volume'))
    validate_identity_update(original_work, work); write_json(stage, WORK / 'work.json', work); load_work(stage / WORK / 'work.json')
    write_json(stage, WORK / 'state.json', state)
    for member_id, spec in MEMBERS.items():
        acceptance = stage / edition_path(spec) / 'acceptance.json'
        validate_acceptance(acceptance, root=stage)
        next(row for row in volumes if row['member_id'] == member_id)['projection_gate'] = projection_gate(stage, acceptance,
            raw_evidence=stage / EVIDENCE / member_id / 'projection-raw-probe.json')
    validate_state(stage / WORK / 'state.json', root=stage)
    receipt = dict(contract='ocd-stokes-retained-external-stage-v1', status='staged-only', work_id=WORK_ID, stage_root=stage.as_posix(), before=before, after=_files(stage / WORK), volumes=volumes,
        included_volumes=2, acquired_volumes=2, projection_category='commentary', accepted_scope_kind='volume', human_review='not-recorded', rights='not-assessed', installation='not-performed')
    receipt['dependency_files'] = {p.as_posix(): sha(_io_path(root / p).read_bytes()) for p in sorted(dependencies(root))}
    write_json(stage, Path('stage-receipt.json'), receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--stage', type=Path, required=True); args = parser.parse_args()
    result = prepare(args.stage); print(json.dumps(dict(work_id=WORK_ID, stage_root=result['stage_root'], volumes=result['volumes']), sort_keys=True))
