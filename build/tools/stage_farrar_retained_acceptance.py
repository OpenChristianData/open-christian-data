"""Prepare a guarded, external three-edition Farrar accepted-library generation."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from build.tei.farrar_retained_native_prepare import ROOT, LOG, WORK_ID, SPECS as MEMBERS, OLD_PACKAGE, sha
from build.tei.farrar_retained_native_prepare import SOURCE_DIR, canonical
from build.tei.farrar_retained_native_oracle import _oracle as oracle, check, ORACLE_IMPORTS, PRODUCER_IMPORTS
from build.tools.prepare_farrar_retained_candidates import CANDIDATES
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
EVIDENCE = WORK / 'integration/farrar-retained-current-20261003-v1'
MEMBERS={m:spec|dict(comments=10 if m!='farrar-expositordan' else 14) for m,spec in MEMBERS.items()}


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


def projection_gate(root, acceptance):
    try:
        result = project_accepted_commentary(root, acceptance_path=acceptance)
        errors = verify_accepted_commentary(root, acceptance_path=acceptance, rows=result['rows'], receipt=result['receipt'])
        return dict(status='pass' if not errors else 'held', rows=len(result['rows']), errors=errors, raw_errors=errors)
    except PipelineError as error:
        # The same held authority-path failure contains the caller's root. Keep
        # the exact error and relative locus comparable across stage/fixture/live.
        detail = str(error)
        for prefix in sorted({str(root), root.as_posix(), str(_io_path(root))}, key=len, reverse=True):
            detail = detail.replace(prefix, '<reviewed-root>')
        return dict(status='held', rows=0, errors=[detail], raw_errors=[str(error)])



def projection_signature(gate):
    return {key:gate[key] for key in ('status','rows','errors')}

def declared_scope(edition_record):
    return f"Complete retained CCEL electronic volume: {edition_record['title']}; all source introduction, commentary, chronology note, appendices, indexes, notes, tables, preformatted genealogical or chronological text, verse lines and inline roles remain readable in source order. All source direct/tail fields and native attributes/attachment independently match acquired raw XML. Exact original flat LIB033 crosswalk and ordered carriers reconcile to the same raw bytes; historical six-member package remains unchanged. The complete raw source body including comments and tbody wrappers is restored from verified actual native fields plus exact retained source metadata. Source head, CSS, literal prolog and all administrative comment payloads remain human-visible. Query link literals retain acquired URL context. This is one of three separately acquired editions under the existing author catalog; author/series completeness, print collation, browser pixel/stylesheet equivalence, human review, CCEL formatting rights and release are separate."

def bind_master(raw, *, identity, source, source_url, declared_scope, revision):
    bound=bind_reviewed_header(raw,expected_sha256=sha(raw),identity=identity,source=source,source_url=source_url,declared_scope=declared_scope,revision=revision)
    old=b'Reconstruction candidate of an existing acquired electronic witness. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
    new=b'Agent-accepted faithful retained electronic volume. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
    if bound.count(old)!=1:raise PipelineError('Farrar candidate publication status preimage differs')
    return bound.replace(old,new,1)

def dependencies(root, *, bootstrap=False):
    result = {Path('build/tei/farrar_retained_native_prepare.py'), Path('build/tei/farrar_retained_native_emitter.py'), Path('build/tei/farrar_retained_native_oracle.py'), Path('build/tei/farrar_original_scope.py'), Path('build/tools/prepare_farrar_retained_candidates.py'), Path('build/tools/stage_farrar_retained_acceptance.py'), Path('build/tools/install_farrar_retained_acceptance.py'), Path('ocd_kernel/__init__.py'), Path('ocd_kernel/tei/writer.py')}
    result.update(p.relative_to(root) for directory, suffix in [('ocd_kernel/reconstruction', '*.py'), ('ocd_kernel/reconstruction/schemas', '*.json'), ('schemas/v2', '*.json'), ('ocd_kernel/tei/vendor/xsd', '*.xsd')] for p in (root / directory).rglob(suffix))
    result.update(Path(p) for p in ORACLE_IMPORTS+PRODUCER_IMPORTS)
    result.add(Path('build/tools/prove_farrar_retained_install.py'))
    result.add(Path('build/tools/probe_farrar_retained_execution.py'))
    if not bootstrap:
        result.add(LOG / 'execution-imports-v1.json')
        execution = read(root / LOG / 'execution-imports-v1.json')
        if execution.get('status') != 'pass' or execution.get('work_id') != WORK_ID:
            raise PipelineError('Farrar execution evidence differs')
        for item in execution['first_party_files']:
            if sha(_io_path(root / item['path']).read_bytes()) != item['sha256']:
                raise PipelineError('Farrar actual execution dependency drifted: ' + item['path'])
        result.update(Path(item['path']) for item in execution['first_party_files'])
    result.update(Path(p) for p in ['ocd_kernel/tei/acceptance.py', 'ocd_kernel/tei/install_accepted.py', 'ocd_kernel/tei/reviewed_integration.py', 'ocd_kernel/tei/validate.py', 'ocd_kernel/library/state.py', 'ocd_kernel/library/identities.py', 'ocd_kernel/library/acquisitions.py', 'ocd_kernel/library/_common.py', 'ocd_kernel/lib/path_io.py', 'ocd_kernel/lib/storage_topology.py', 'ocd_kernel/lib/atomic_io.py', 'ocd_kernel/projection/__init__.py', 'ocd_kernel/projection/categories/__init__.py', 'ocd_kernel/projection/categories/commentary.py', 'ocd_kernel/projection/categories/commentary_source_native.py', 'ocd_kernel/projection/categories/native_documents.py', 'ocd_kernel/projection/native_content.py', 'ocd_kernel/projection/native_content_check.py', 'ocd_kernel/projection/envelope.py', 'ocd_kernel/projection/scripture_authority.py', 'ocd_kernel/projection/scripture_targets.py', 'ocd_kernel/projection/scripture_targets_check.py', 'build/bible_data/osis_book_codes.json'])
    result.update(p.relative_to(root) for p in (root / OLD_PACKAGE).iterdir() if p.is_file())
    result.update({Path('build/tools/farrar_retained_assess.py'), LOG / 'existing-scope-assessment.json', LOG / 'original-source-scope-reconciliation.json', LOG / 'candidate-completion-receipt-v1.json', Path('build/tools/farrar_stage_adapt.py')})
    for member_id, spec in MEMBERS.items():
        manifest_path = SOURCE_DIR / (member_id + '.source-manifest.json')
        manifest = SourceManifest.load(root / manifest_path, repository_root=root)
        result.add(manifest_path); result.add(LOG / (member_id + '-current-review-v1.json'))
        result.add(edition_path(spec) / 'acquisitions' / (spec['acquisition'] + '.json'))
        result.update(Path(x['path']) for x in manifest.record['authorities'])
    return result


def prepare(stage, *, root=ROOT, bootstrap=False):
    root = root.resolve(strict=True); stage = stage.absolute()
    if stage.exists() or stage.parent != (LIBRARY / 'candidate-reviews').resolve(strict=True) or not stage.name.startswith('farrar-s-'):
        raise PipelineError('Fresh external Farrar stage required')
    before = _files(root / WORK)
    work = read(root / WORK / 'work.json'); original_work = json.loads(json.dumps(work))
    state = read(root / WORK / 'state.json')
    scope_review = read(root / LOG / 'existing-scope-assessment.json')
    if scope_review['status'] != 'assessed' or scope_review['finite_denominator'] != 3 or len(work['textual_forms']) != 3:
        raise PipelineError('Complete existing three-edition Farrar envelope differs')
    for spec in MEMBERS.values():
        if (root / edition_path(spec) / 'master.tei.xml').exists() or (root / edition_path(spec) / 'acceptance.json').exists():
            raise PipelineError('Farrar canonical accepted authority already exists; no replacement')
    stage.mkdir()
    for relative in before: copy(root, stage, WORK / relative)
    for relative in dependencies(root, bootstrap=bootstrap): copy(root, stage, relative)
    evidence = set(work['evidence'] + [p for target in state['targets'] for p in target['evidence']])
    for relative in evidence:
        physical = Path(relative.split('#', 1)[0])
        if not _io_path(stage / physical).exists(): copy(root, stage, physical)
    write(stage, EVIDENCE / 'three-edition-source-scope.json', (root / LOG / 'existing-scope-assessment.json').read_bytes())
    at = now(); volumes = []
    for member_id, spec in MEMBERS.items():
        edition = edition_path(spec); lane = EVIDENCE / member_id
        manifest_path = SOURCE_DIR / (member_id + '.source-manifest.json')
        manifest = SourceManifest.load(root / manifest_path, repository_root=root)
        package = CandidatePackage.load(CANDIDATES / member_id / 'package')
        report = validate(manifest, package, oracle)
        current = read(root / LOG / (member_id + '-current-review-v1.json'))
        direct = check(member_id, package.path)
        if report.status != 'pass' or current['package_sha256'] != package.sha256 or current['oracle_report_sha256'] != report.sha256 or current['direct_source_review']['tei_sha256'] != direct['tei_sha256'] or not current['reproducibility']['exact_six_member_bytes_equal'] or len(current['reproducibility']['replays']) != 2 or not current['closure_negative']['rejected'] or not current['closure_negative']['producer_rejected'] or len(current['direct_source_review']['mutations']) != 23 or not all(x['rejected'] for x in current['direct_source_review']['mutations']):
            raise PipelineError('Farrar current source/replay/negative proof differs')
        acquisition_rel = edition / 'acquisitions' / (spec['acquisition'] + '.json')
        acquisition = validate_acquisition(root / acquisition_rel, root=root)
        if acquisition['source_sha256'] != spec['sha256'] or len(acquisition['retained_files']) != 1:
            raise PipelineError('Farrar existing acquisition source differs')
        form = next(x for x in work['textual_forms'] if x['textual_form_id'] == spec['form'])
        edition_record = next(x for x in form['editions'] if x['edition_id'] == spec['edition'])
        if edition_record.get('category') is not None: raise PipelineError('Farrar category preimage changed')
        edition_record['category'] = 'commentary'
        for name in package.member_names: write(stage, lane / 'inputs/package' / name, package.member_bytes(name))
        write(stage, lane / 'inputs/current-review.json', (root / LOG / (member_id + '-current-review-v1.json')).read_bytes())
        identity = dict(work_id=WORK_ID, textual_form_id=spec['form'], edition_id=spec['edition'], acquisition_id=spec['acquisition'])
        source = {key: acquisition[key] for key in ['source_path', 'source_sha256', 'source_bytes', 'source_scope']}
        selected = declared_scope(edition_record)
        revision = dict(id=member_id + '-retained-current-20261003-v1', date=datetime.now(timezone.utc).date().isoformat(), note='Readable faithful retained volume; original source order and literal identities preserved.')
        raw = package.member_bytes('content.tei.xml')
        bound = bind_master(raw, identity=identity, source=source, source_url=acquisition['url'], declared_scope=selected, revision=revision)
        if bound.split(b'</teiHeader>', 1)[1] != raw.split(b'</teiHeader>', 1)[1]: raise PipelineError('Farrar header binding changed readable body')
        candidate = write(stage, lane / 'candidate.tei.xml', bound)
        if errors := validate_file(candidate): raise PipelineError(str(errors[:3]))
        expected = [dict(path=spec['path'], position=1)]
        included = [dict(path=spec['path'], position=1, bytes=spec['bytes'], sha256=spec['sha256'], scope=selected)]
        accepted_scope = dict(kind='edition', declared=selected)
        common = dict(identity=identity, source=source, candidate=make_file_binding(stage, candidate), scope=selected, accepted_scope=accepted_scope,
            expected_members=expected, included_members=included, excluded_members=[], missing_members=[], unknown_members=[],
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256, oracle_report_sha256=report.sha256,
            direct_source_review=make_file_binding(stage, stage / lane / 'inputs/current-review.json'))
        accounting = write_json(stage, lane / 'source-accounting.json', common | dict(scope=source['source_scope'], source_sha256=spec['sha256'], source_bytes=spec['bytes'], full_source_elements=spec['elements'], readable_source_elements=spec['body_elements'] - 1,
            administrative_comments=spec['comments'], administrative_comment_disposition='Exact ledger fields; actual readable source independently compared after bounded whitespace joins; inverse entire source body C14N equal',
            retained_administration='All original ThML header/CSS/prolog/body-comment fields visible and accounted', complete_acquired_work_volumes=3, original_candidate_route='Existing flat LIB033 carrier recovery and source-backed native hierarchy repair; no new acquisition', relative_uri_bases=direct['relative_nonfragment_links'], preformatted_carriers=direct['preformatted_count'], notes=direct['note_count'], original_scope=direct['original_scope'], current_producer_recipe=dict(manifest.record['converter']), original_package_sha256='a335a3ea251871d23f418434dc95a1dff7e564e1c6ab3539cdcfce449078c8b2', omitted_readable_elements=0))
        command = 'py -3 -m build.tools.stage_farrar_retained_acceptance'
        technical = dict(producer=dict(id=manifest.record['converter']['id']), checker=dict(id=manifest.record['validator']['id']), shared_assumptions=['Pinned acquired raw XML, exact historical package, P5 and declared reversible native mapping; producer policy exposure is stated.'], independent_corroboration='Stdlib raw source plus lxml corroboration checks every actual native field, semantic attribute, ownership and order, exact complete header/outer readable envelope, all original 23,605 source crosswalk fields and old actual carriers, full actual-backed source-body inverse, 2,453 notes, eight preformatted carriers, nineteen tables and 999 query link contexts. All source head/CSS/prolog/admin comments visible. Twenty-three schema-valid mutants per edition rejected; two fresh six-member byte replays per edition. Logical regions preserve all introductions/chronology/appendices/indexes; browser pixel/layout and print claims remain qualified.')
        for name in ['validation', 'accounting', 'fidelity', 'reproducibility', 'schema', 'closure']:
            proof = write_json(stage, lane / (name + '.json'), common | dict(status='pass', command=command, exit_code=0, claim=name, readable_body_unchanged_at_header_binding=True, actual_readable_body_inverse_c14n_equal=True))
            technical[name] = dict(path=proof, status='pass', command=command, exit_code=0)
        review = dict(reviewer='agent:farrar-existing-retained-source-review', reviewed_at=at,
            coverage=dict(status='complete', declared=selected, reached=['all retained source edition XML elements', 'all actual readable source paragraphs/front matter/notes/indices/tables/reference targets and URI context', 'all source attributes, tails, order, preformatted space and acquired query link contexts', 'all exact administrative comments and metadata/CSS/prolog fields'], inspected=['all actual readable source paragraphs/front matter/notes/indices/tables/reference targets and URI context', 'all source attributes, tails, order, preformatted space and acquired query link contexts', 'all exact administrative comments and metadata/CSS/prolog fields'], unreviewed=[]),
            source_quality_uncertainty=['Retained CCEL electronic witness only; no print or independent provider collation.', 'Source XML titles and visible chapter numbers are preserved literally, including Second Kings chapter XVII/XXVII discrepancy and Daniel Prophetic Secion spelling; no corrections.', 'Heading paragraphs, tbody flattening, source comment header retention and browser-only attribute ledger policies are declared; no browser/CSS pixel equivalence claim.'], discrepancies=['Existing original flat feature ledger was repaired to readable native hierarchy with independent full source proof.'], unreviewed_residuals=['Human review, CCEL formatting rights, print collation and release remain separate; actual commentary projection measured independently.'])
        review_path = write_json(stage, lane / 'review.json', common | review)
        decision = dict(source_local_disposition='Agent accepts the complete faithful retained electronic volume within the explicit three-edition acquired author catalog work; all exact source comments, preformatted space, table labels and acquired query link contexts are included.', blockers=[], agent_assessment=dict(status='accepted', actor=review['reviewer'], assessed_at=at, supported_scope=selected, unresolved_claims=[], unassessed_stronger_claims=['human review', 'print collation', 'rights clearance', 'publication', 'downstream commentary projection']), human_decision={'status': 'not-recorded'})
        record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting,
            scope=accepted_scope | dict(expected_members=expected, included_members=included, excluded_members=[]), technical=technical, review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
        acceptance = stage / edition / 'acceptance.json'; write_acceptance(acceptance, record); validate_acceptance(acceptance, root=stage)
        master = write(stage, edition / 'master.tei.xml', bound)
        record['promotion'] = dict(record['promotion']); record['promotion'].update(status='promoted', promoted_at=at, master=make_file_binding(stage, master)); write_acceptance(acceptance, record)
        targets = [x for x in state['targets'] if x['target_type'] == 'edition' and x['target_id'] == spec['edition']]
        if len(targets) != 1 or targets[0]['stage'] != 'acquired': raise PipelineError('Farrar edition acquired preimage differs')
        targets[0].update(stage='accepted', reason=PROMOTED_MASTER_REASON, updated_at=at)
        targets[0]['evidence'].extend([(edition / 'master.tei.xml').as_posix(), (edition / 'acceptance.json').as_posix()])
        write_json(stage, WORK / 'work.json', work)
        write_json(stage, WORK / 'state.json', state)
        volumes.append(dict(member_id=member_id, source_sha256=spec['sha256'], source_manifest_sha256=manifest.sha256,
            candidate_package_sha256=package.sha256, oracle_report_sha256=report.sha256, master_sha256=sha(master.read_bytes()), acceptance_sha256=sha(acceptance.read_bytes()), projection_gate=projection_gate(stage, acceptance), scope_kind='edition', representation_revision=revision))
    validate_identity_update(original_work, work); write_json(stage, WORK / 'work.json', work); load_work(stage / WORK / 'work.json')
    write_json(stage, WORK / 'state.json', state)
    for spec in MEMBERS.values(): validate_acceptance(stage / edition_path(spec) / 'acceptance.json', root=stage)
    validate_state(stage / WORK / 'state.json', root=stage)
    receipt = dict(contract='ocd-farrar-retained-external-stage-v1', status='bootstrap-only' if bootstrap else 'staged-only', work_id=WORK_ID, stage_root=stage.as_posix(), staged_at=at, before=before, after=_files(stage / WORK), volumes=volumes,
        included_volumes=3, acquired_volumes=3, projection_category='commentary', accepted_scope_kind='edition', human_review='not-recorded', rights='not-assessed', installation='not-performed')
    if not bootstrap:receipt['external_runtime_files']=read(root/LOG/'execution-imports-v1.json')['external_runtime_files']
    receipt['dependency_files'] = {p.as_posix(): sha(_io_path(root / p).read_bytes()) for p in sorted(dependencies(root, bootstrap=bootstrap))}
    write_json(stage, Path('stage-receipt.json'), receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--stage', type=Path, required=True); parser.add_argument('--bootstrap', action='store_true'); args = parser.parse_args()
    result = prepare(args.stage, bootstrap=args.bootstrap); print(json.dumps(dict(work_id=WORK_ID, stage_root=result['stage_root'], volumes=result['volumes']), sort_keys=True))
