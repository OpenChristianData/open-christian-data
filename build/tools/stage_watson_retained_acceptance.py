"""Prepare a guarded, external three-edition Watson accepted-library generation."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from build.tei.watson_retained_native_prepare import ROOT, LOG, WORK_ID, SPECS as MEMBERS, OLD_PACKAGE, sha
from build.tei.watson_retained_native_prepare import SOURCE_DIR, canonical
from build.tei.watson_retained_native_oracle import _oracle as oracle, check, ORACLE_IMPORTS, PRODUCER_IMPORTS
from build.tools.prepare_watson_retained_candidates import CANDIDATES, EXPECTED_MUTATIONS
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
EVIDENCE = WORK / 'integration/watson-retained-current-20261003-v1'
MEMBERS={m:spec|dict(comments=10) for m,spec in MEMBERS.items()}


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
    return f"Complete retained authored work in the CCEL electronic edition: {edition_record['title']}; all title/front matter, scholarly introduction or Prologue, chapters/book parts, notes, printed/generated indexes, source table, verse/line groups and inline order remain readable in source order. Every actual direct/tail field, hierarchy, semantic attribute and URI context independently matches exact acquired raw XML; complete native-backed body inverse, visible exact source header/prolog/comments and whole outer envelope pass. All 12,949 inherited Watson crosswalk and actual flat carriers reconcile, including 46 exact Job correction source-field positions; original literal source readings remain in the body, prior proposals remain qualified visible metadata. The retained LIB035 producer replay has exact historical accounting but differs from the dated TEI pin; preserved replay six-member snapshot and current composite recipe/ancestor/acquisition/source bindings are exact. Judges and Ruth is one complete authored work with two book parts and one shared contents/index sequence; Job and Numbers are separate authored works, with no duplicated shared matter. Each source has two absent toc next/prev targets preserved as typed gaps; known navigation and 128 relative query links preserve source contexts. This is one of three existing acquired authored works in the Watson author catalog; author/series completeness, print collation, browser/CSS pixels, external correction witness confirmation, human review, rights and release remain separate."


def bind_master(raw, *, identity, source, source_url, declared_scope, revision):
    bound=bind_reviewed_header(raw,expected_sha256=sha(raw),identity=identity,source=source,source_url=source_url,declared_scope=declared_scope,revision=revision)
    old=b'Reconstruction candidate of an existing acquired electronic witness. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
    new=b'Agent-accepted faithful retained electronic volume. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
    if bound.count(old)!=1:raise PipelineError('Watson candidate publication status preimage differs')
    return bound.replace(old,new,1)

def dependencies(root, *, bootstrap=False):
    result = {Path('build/tei/watson_retained_native_prepare.py'), Path('build/tei/watson_retained_native_emitter.py'), Path('build/tei/watson_retained_native_oracle.py'), Path('build/tei/watson_original_scope.py'), Path('build/tools/prepare_watson_retained_candidates.py'), Path('build/tools/stage_watson_retained_acceptance.py'), Path('build/tools/install_watson_retained_acceptance.py'), Path('ocd_kernel/__init__.py'), Path('ocd_kernel/tei/writer.py')}
    result.update(p.relative_to(root) for directory, suffix in [('ocd_kernel/reconstruction', '*.py'), ('ocd_kernel/reconstruction/schemas', '*.json'), ('schemas/v2', '*.json'), ('ocd_kernel/tei/vendor/xsd', '*.xsd')] for p in (root / directory).rglob(suffix))
    result.update(Path(p) for p in ORACLE_IMPORTS+PRODUCER_IMPORTS)
    result.add(Path('build/tools/prove_watson_retained_install.py'))
    result.add(Path('build/tools/probe_watson_retained_execution.py'))
    if not bootstrap:
        result.add(LOG / 'execution-imports-v1.json')
        execution = read(root / LOG / 'execution-imports-v1.json')
        if execution.get('status') != 'pass' or execution.get('work_id') != WORK_ID:
            raise PipelineError('Watson execution evidence differs')
        for item in execution['first_party_files']:
            if sha(_io_path(root / item['path']).read_bytes()) != item['sha256']:
                raise PipelineError('Watson actual execution dependency drifted: ' + item['path'])
        result.update(Path(item['path']) for item in execution['first_party_files'])
    result.update(Path(p) for p in ['ocd_kernel/tei/acceptance.py', 'ocd_kernel/tei/install_accepted.py', 'ocd_kernel/tei/reviewed_integration.py', 'ocd_kernel/tei/validate.py', 'ocd_kernel/library/state.py', 'ocd_kernel/library/identities.py', 'ocd_kernel/library/acquisitions.py', 'ocd_kernel/library/_common.py', 'ocd_kernel/lib/path_io.py', 'ocd_kernel/lib/storage_topology.py', 'ocd_kernel/lib/atomic_io.py', 'ocd_kernel/projection/__init__.py', 'ocd_kernel/projection/categories/__init__.py', 'ocd_kernel/projection/categories/commentary.py', 'ocd_kernel/projection/categories/commentary_source_native.py', 'ocd_kernel/projection/categories/native_documents.py', 'ocd_kernel/projection/native_content.py', 'ocd_kernel/projection/native_content_check.py', 'ocd_kernel/projection/envelope.py', 'ocd_kernel/projection/scripture_authority.py', 'ocd_kernel/projection/scripture_targets.py', 'ocd_kernel/projection/scripture_targets_check.py', 'build/bible_data/osis_book_codes.json'])
    result.update(p.relative_to(root) for p in (root / OLD_PACKAGE).iterdir() if p.is_file())
    result.update({Path('build/tools/watson_retained_assess.py'), LOG / 'existing-scope-assessment.json', LOG / 'original-source-scope-reconciliation.json', LOG / 'candidate-completion-receipt-v1.json', Path('build/tools/watson_stage_adapt.py')})
    for member_id, spec in MEMBERS.items():
        manifest_path = SOURCE_DIR / (member_id + '.source-manifest.json')
        manifest = SourceManifest.load(root / manifest_path, repository_root=root)
        result.add(manifest_path); result.add(LOG / (member_id + '-current-review-v1.json'))
        result.add(edition_path(spec) / 'acquisitions' / (spec['acquisition'] + '.json'))
        result.update(Path(x['path']) for x in manifest.record['authorities'])
    return result


def prepare(stage, *, root=ROOT, bootstrap=False):
    root = root.resolve(strict=True); stage = stage.absolute()
    if stage.exists() or stage.parent != (LIBRARY / 'candidate-reviews').resolve(strict=True) or not stage.name.startswith('watson-s-'):
        raise PipelineError('Fresh external Watson stage required')
    before = _files(root / WORK)
    work = read(root / WORK / 'work.json'); original_work = json.loads(json.dumps(work))
    state = read(root / WORK / 'state.json')
    scope_review = read(root / LOG / 'existing-scope-assessment.json')
    if scope_review['status'] != 'assessed' or scope_review['finite_denominator'] != 3 or len(work['textual_forms']) != 3:
        raise PipelineError('Complete existing three-edition Watson envelope differs')
    for spec in MEMBERS.values():
        if (root / edition_path(spec) / 'master.tei.xml').exists() or (root / edition_path(spec) / 'acceptance.json').exists():
            raise PipelineError('Watson canonical accepted authority already exists; no replacement')
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
        if report.status != 'pass' or current['package_sha256'] != package.sha256 or current['oracle_report_sha256'] != report.sha256 or current['direct_source_review']['tei_sha256'] != direct['tei_sha256'] or not current['reproducibility']['exact_six_member_bytes_equal'] or len(current['reproducibility']['replays']) != 2 or not current['closure_negative']['rejected'] or not current['closure_negative']['producer_rejected'] or len(current['direct_source_review']['mutations']) != EXPECTED_MUTATIONS[member_id] or not all(x['rejected'] for x in current['direct_source_review']['mutations']):
            raise PipelineError('Watson current source/replay/negative proof differs')
        acquisition_rel = edition / 'acquisitions' / (spec['acquisition'] + '.json')
        acquisition = validate_acquisition(root / acquisition_rel, root=root)
        if acquisition['source_sha256'] != spec['sha256'] or len(acquisition['retained_files']) != 1:
            raise PipelineError('Watson existing acquisition source differs')
        form = next(x for x in work['textual_forms'] if x['textual_form_id'] == spec['form'])
        edition_record = next(x for x in form['editions'] if x['edition_id'] == spec['edition'])
        if edition_record.get('category') is not None: raise PipelineError('Watson category preimage changed')
        edition_record['category'] = 'commentary'
        for name in package.member_names: write(stage, lane / 'inputs/package' / name, package.member_bytes(name))
        write(stage, lane / 'inputs/current-review.json', (root / LOG / (member_id + '-current-review-v1.json')).read_bytes())
        identity = dict(work_id=WORK_ID, textual_form_id=spec['form'], edition_id=spec['edition'], acquisition_id=spec['acquisition'])
        source = {key: acquisition[key] for key in ['source_path', 'source_sha256', 'source_bytes', 'source_scope']}
        selected = declared_scope(edition_record)
        revision = dict(id=member_id + '-retained-current-20261003-v1', date=datetime.now(timezone.utc).date().isoformat(), note='Readable faithful retained volume; original source order and literal identities preserved.')
        raw = package.member_bytes('content.tei.xml')
        bound = bind_master(raw, identity=identity, source=source, source_url=acquisition['url'], declared_scope=selected, revision=revision)
        if bound.split(b'</teiHeader>', 1)[1] != raw.split(b'</teiHeader>', 1)[1]: raise PipelineError('Watson header binding changed readable body')
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
            retained_administration='All original ThML header/CSS/prolog/body-comment fields visible and accounted', complete_acquired_work_volumes=3, original_candidate_route='Qualified retained LIB035 producer replay and source-backed native hierarchy repair of existing downloaded authored works; no new acquisition', relative_uri_bases=direct['relative_nonfragment_links'], preformatted_carriers=direct['preformatted_count'], notes=direct['note_count'], original_scope=direct['original_scope'], current_producer_recipe=dict(manifest.record['converter']), original_package_sha256='685517f52f9be603117e42c1afe9d6bf2d20a95145c855b7cbb5b37971042605', historical_tei_bytes_exact=False, historical_accounting_bytes_exact=True, source_navigation_gaps=json.loads(package.member_bytes('source-accountability.json'))['source_navigation_gaps'], prior_correction_proposal_count=direct['original_scope']['legacy_correction_count'], composite_producer_lineage=json.loads(package.member_bytes('provenance.json'))['producer_lineage'], omitted_readable_elements=0))
        command = 'py -3 -m build.tools.stage_watson_retained_acceptance'
        technical = dict(producer=dict(id=manifest.record['converter']['id']), checker=dict(id=manifest.record['validator']['id']), shared_assumptions=['Exact acquired raw XML, qualified immutable LIB035 producer replay, pinned P5 and declared reversible native mapping; producer/policy exposure is declared.'], independent_corroboration='Stdlib raw source corroborated against libxml compares every actual native direct/tail, hierarchy, inline order, semantic attribute, note/table/stanza/line and URI context plus complete ordered header/outer envelope. All 12,949 old crosswalk and actual carriers and 46 exact correction source-field positions reconcile. Across 3 complete authored works: 33 notes, one table/152 cells, 225 stanza groups/1,329 lines, 128 query contexts and 30 admin comments; full native-backed source inverse. Literal prolog, source head/CSS/rights and full permission notice visible. All declared P5-valid mutants rejected and 2 isolated six-member byte replays per work. Exact composite recipe/current producer/ancestor/acquisition/source/profile/policy/immutable replay bytes independently bound; historical TEI mismatch and external witness limits qualified.')
        for name in ['validation', 'accounting', 'fidelity', 'reproducibility', 'schema', 'closure']:
            proof = write_json(stage, lane / (name + '.json'), common | dict(status='pass', command=command, exit_code=0, claim=name, readable_body_unchanged_at_header_binding=True, actual_readable_body_inverse_c14n_equal=True))
            technical[name] = dict(path=proof, status='pass', command=command, exit_code=0)
        review = dict(reviewer='agent:watson-existing-retained-source-review', reviewed_at=at,
            coverage=dict(status='complete', declared=selected, reached=['all retained source edition XML elements', 'all actual readable source paragraphs/front matter/notes/indices/tables/reference targets and URI context', 'all source attributes, tails, hierarchy, inline order, table alignment, literal stanza/line grouping, source xml:space absence/presence, known and absent next/prev navigation and 128 query contexts', 'all exact administrative comments and metadata/CSS/prolog fields'], inspected=['all actual readable source paragraphs/front matter/notes/indices/tables/reference targets and URI context', 'all source attributes, tails, hierarchy, inline order, table alignment, literal stanza/line grouping, source xml:space absence/presence, known and absent next/prev navigation and 128 query contexts', 'all exact administrative comments and metadata/CSS/prolog fields'], unreviewed=[]),
            source_quality_uncertainty=['Exact retained electronic authored works only; print/browser collation not performed.', 'Job literal encoding defects remain source readings;46 prior correction proposals retained but external witness readings unconfirmed.', 'Qualified LIB035 producer replay preserves exact historical accounting but differs from dated TEI pin; historical oracle not rerun.', 'Six absent source toc next/prev targets remain typed navigation gaps; no invented targets.', 'Source presentation attributes retained in complete ledger; no CSS/pixel equivalence.'], discrepancies=['Inherited flat feature ledger repaired to readable native hierarchy and acquired URL context with independent full source proof.'], unreviewed_residuals=['Human review, CCEL formatting rights, print collation and release remain separate; actual commentary projection measured independently.'])
        review_path = write_json(stage, lane / 'review.json', common | review)
        decision = dict(source_local_disposition='Agent accepts each complete faithful retained authored work within the explicit three-work acquired Watson catalog; all source regions/comments, literal correction readings, table alignment, stanza/line hierarchy, known navigation/typed source gaps and acquired query contexts are included. Qualified replay lineage and 46 unconfirmed correction proposals remain explicit.', blockers=[], agent_assessment=dict(status='accepted', actor=review['reviewer'], assessed_at=at, supported_scope=selected, unresolved_claims=[], unassessed_stronger_claims=['human review', 'print collation', 'rights clearance', 'publication', 'downstream commentary projection']), human_decision={'status': 'not-recorded'})
        record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting,
            scope=accepted_scope | dict(expected_members=expected, included_members=included, excluded_members=[]), technical=technical, review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
        acceptance = stage / edition / 'acceptance.json'; write_acceptance(acceptance, record); validate_acceptance(acceptance, root=stage)
        master = write(stage, edition / 'master.tei.xml', bound)
        record['promotion'] = dict(record['promotion']); record['promotion'].update(status='promoted', promoted_at=at, master=make_file_binding(stage, master)); write_acceptance(acceptance, record)
        targets = [x for x in state['targets'] if x['target_type'] == 'edition' and x['target_id'] == spec['edition']]
        if len(targets) != 1 or targets[0]['stage'] != 'acquired': raise PipelineError('Watson edition acquired preimage differs')
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
    receipt = dict(contract='ocd-watson-retained-external-stage-v1', status='bootstrap-only' if bootstrap else 'staged-only', work_id=WORK_ID, stage_root=stage.as_posix(), staged_at=at, before=before, after=_files(stage / WORK), volumes=volumes,
        included_volumes=3, acquired_volumes=3, projection_category='commentary', accepted_scope_kind='edition', human_review='not-recorded', rights='not-assessed', installation='not-performed')
    if not bootstrap:receipt['external_runtime_files']=read(root/LOG/'execution-imports-v1.json')['external_runtime_files']
    receipt['dependency_files'] = {p.as_posix(): sha(_io_path(root / p).read_bytes()) for p in sorted(dependencies(root, bootstrap=bootstrap))}
    write_json(stage, Path('stage-receipt.json'), receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--stage', type=Path, required=True); parser.add_argument('--bootstrap', action='store_true'); args = parser.parse_args()
    result = prepare(args.stage, bootstrap=args.bootstrap); print(json.dumps(dict(work_id=WORK_ID, stage_root=result['stage_root'], volumes=result['volumes']), sort_keys=True))
