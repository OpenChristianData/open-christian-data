"""Prepare a guarded, external four-unit Maclaren accepted-library generation."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from build.tei.maclaren_retained_native_prepare import ROOT, LOG, WORK_ID, SPECS as MEMBERS, OLD_PACKAGE, sha
from build.tei.maclaren_retained_native_prepare import SOURCE_DIR, canonical
from build.tei.maclaren_retained_native_oracle import _oracle as oracle, check, ORACLE_IMPORTS
from build.tools.prepare_maclaren_retained_candidates import CANDIDATES, EXPECTED_MUTATIONS
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
EVIDENCE = WORK / 'integration/maclaren-retained-current-20261003-v1'


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
        return dict(status='pass' if not errors else 'held', rows=len(result['rows']), errors=errors)
    except PipelineError as error:
        # The same held authority-path failure contains the caller's root. Keep
        # the exact error and relative locus comparable across stage/fixture/live.
        detail = str(error)
        for prefix in sorted({str(root), root.as_posix(), str(_io_path(root))}, key=len, reverse=True):
            detail = detail.replace(prefix, '<reviewed-root>')
        return dict(status='held', rows=0, errors=[detail])


def dependencies(root, *, bootstrap=False):
    result = {Path('build/tei/maclaren_retained_native_prepare.py'), Path('build/tei/maclaren_retained_native_prepare.py'), Path('build/tei/maclaren_retained_native_oracle.py'), Path('build/tei/maclaren_retained_native_emitter.py'), Path('build/tools/prepare_maclaren_retained_candidates.py'), Path('build/tools/stage_maclaren_retained_acceptance.py'), Path('build/tools/install_maclaren_retained_acceptance.py'), Path('ocd_kernel/__init__.py'), Path('ocd_kernel/tei/writer.py')}
    result.update(p.relative_to(root) for directory, suffix in [('ocd_kernel/reconstruction', '*.py'), ('ocd_kernel/reconstruction/schemas', '*.json'), ('schemas/v2', '*.json'), ('ocd_kernel/tei/vendor/xsd', '*.xsd')] for p in (root / directory).rglob(suffix))
    result.update(Path(p) for p in ORACLE_IMPORTS)
    result.add(Path('build/tools/prove_maclaren_retained_install.py'))
    result.add(LOG / 'execution_import_probe.py')
    result.add(LOG / 'late_import_fixture_worker.py')
    if not bootstrap:
        result.add(LOG / 'execution-imports.json')
        execution = read(root / LOG / 'execution-imports.json')
        if execution.get('status') != 'pass' or execution.get('work_id') != WORK_ID:
            raise PipelineError('Maclaren execution evidence differs')
        for item in execution['first_party_files']:
            if sha(_io_path(root / item['path']).read_bytes()) != item['sha256']:
                raise PipelineError('Maclaren actual execution dependency drifted: ' + item['path'])
        result.update(Path(item['path']) for item in execution['first_party_files'])
    result.update(Path(p) for p in ['ocd_kernel/tei/acceptance.py', 'ocd_kernel/tei/install_accepted.py', 'ocd_kernel/tei/reviewed_integration.py', 'ocd_kernel/tei/validate.py', 'ocd_kernel/library/state.py', 'ocd_kernel/library/identities.py', 'ocd_kernel/library/acquisitions.py', 'ocd_kernel/library/_common.py', 'ocd_kernel/lib/path_io.py', 'ocd_kernel/lib/storage_topology.py', 'ocd_kernel/lib/atomic_io.py', 'ocd_kernel/projection/__init__.py', 'ocd_kernel/projection/categories/__init__.py', 'ocd_kernel/projection/categories/commentary.py', 'ocd_kernel/projection/categories/commentary_source_native.py', 'ocd_kernel/projection/categories/native_documents.py', 'ocd_kernel/projection/native_content.py', 'ocd_kernel/projection/native_content_check.py', 'ocd_kernel/projection/envelope.py', 'ocd_kernel/projection/scripture_authority.py', 'ocd_kernel/projection/scripture_targets.py', 'ocd_kernel/projection/scripture_targets_check.py', 'build/bible_data/osis_book_codes.json'])
    result.update(p.relative_to(root) for p in (root / OLD_PACKAGE).iterdir() if p.is_file())
    result.update({LOG / 'source_inventory.py', LOG / 'source-inventory.json', LOG / 'candidate-completion-receipt-v2.json', Path('build/tools/prepare_maclaren_stage_code.py'), Path('build/tools/prepare_maclaren_code.py')})
    for member_id, spec in MEMBERS.items():
        manifest_path = SOURCE_DIR / (member_id + '.source-manifest.json')
        manifest = SourceManifest.load(root / manifest_path, repository_root=root)
        result.add(manifest_path); result.add(LOG / (member_id + '-current-review-v2.json'))
        result.add(edition_path(spec) / 'acquisitions' / (spec['acquisition'] + '.json'))
        result.update(Path(x['path']) for x in manifest.record['authorities'])
    return result


REVISION_NOTE='Readable faithful retained volume; original source order and literal identities preserved.'
def declared_scope(edition_record, member_id):
    ranges={'maclaren-expositorpsalms1':'Psalms I-XXXVIII (1-38), volume I','maclaren-expositorpsalms2':'Psalms XXXIX-LXXXIX (39-89), volume II','maclaren-expositorpsalms3':'Psalms XC-CL (90-150), volume III','maclaren-expositorcolphm':'Colossians and Philemon, the complete acquired combined volume'}
    return f"Complete retained CCEL electronic volume unit: {edition_record['title']}; {ranges[member_id]}. All source front matter, ordered commentary, printed and generated indices, notes, tables, verse/line and source span/br carriers, navigation and literal references are retained. All ten administrative comments per source remain exact ledger fields with independently checked whitespace joins; both PsalmsII tbody wrappers retain intact owning rows and exact inverse fields. Table summaries/spans and six Colossians/Philemon source th roles preserved. Relative hrefs (38/51/61/33 by acquired unit) retain literal targets and exact corresponding acquisition-URL context; known next/prev source IDs map locally, missing toc remains literal annotation. Entire source body independently restored from actual native payload and source-derived original attributes; complete source head/prolog/CSS/copyright human-visible. All four acquired units accounted (4/4) under unchanged existing author catalog, not complete author or series. Three Psalms volumes jointly cover the retained Psalm ranges1-150, without claiming any one is the whole Psalms work. No print, universal layout or invented verse-target claim. These four XML witnesses contain no image elements or U+FFFD."
def recompute_header(raw, *, identity, source, source_url, declared, revision):
    bound=bind_reviewed_header(raw,expected_sha256=sha(raw),identity=identity,source=source,source_url=source_url,declared_scope=declared,revision=revision)
    old=b'Reconstruction candidate of an existing acquired electronic witness. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
    new=b'Agent-accepted faithful retained electronic volume. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
    if bound.count(old)!=1:raise PipelineError('Maclaren ordered header publication preimage differs')
    bound=bound.replace(old,new,1)
    if bound.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise PipelineError('Maclaren ordered header binding changed body bytes')
    return bound

def prepare(stage, *, root=ROOT, bootstrap=False):
    root = root.resolve(strict=True); stage = stage.absolute()
    if stage.exists() or stage.parent != (LIBRARY / 'candidate-reviews').resolve(strict=True) or not stage.name.startswith('maclaren-s-'):
        raise PipelineError('Fresh external Maclaren stage required')
    before = _files(root / WORK)
    work = read(root / WORK / 'work.json'); original_work = json.loads(json.dumps(work))
    state = read(root / WORK / 'state.json')
    scope_review = read(root / LOG / 'source-inventory.json')
    if scope_review['status'] != 'pass' or scope_review['acquired_denominator'] != 4 or len(work['textual_forms']) != 4:
        raise PipelineError('Complete existing four-unit Maclaren envelope differs')
    for spec in MEMBERS.values():
        if (root / edition_path(spec) / 'master.tei.xml').exists() or (root / edition_path(spec) / 'acceptance.json').exists():
            raise PipelineError('Maclaren canonical accepted authority already exists; no replacement')
    stage.mkdir()
    for relative in before: copy(root, stage, WORK / relative)
    for relative in dependencies(root, bootstrap=bootstrap): copy(root, stage, relative)
    evidence = set(work['evidence'] + [p for target in state['targets'] for p in target['evidence']])
    for relative in evidence:
        physical = Path(relative.split('#', 1)[0])
        if not _io_path(stage / physical).exists(): copy(root, stage, physical)
    write(stage, EVIDENCE / 'four-unit-source-scope.json', (root / LOG / 'source-inventory.json').read_bytes())
    at = now(); volumes = []
    for member_id, spec in MEMBERS.items():
        edition = edition_path(spec); lane = EVIDENCE / member_id
        manifest_path = SOURCE_DIR / (member_id + '.source-manifest.json')
        manifest = SourceManifest.load(root / manifest_path, repository_root=root)
        package = CandidatePackage.load(CANDIDATES / member_id / 'package')
        report = validate(manifest, package, oracle)
        current = read(root / LOG / (member_id + '-current-review-v2.json'))
        direct = check(member_id, package.path)
        if report.status != 'pass' or current['package_sha256'] != package.sha256 or current['oracle_report_sha256'] != report.sha256 or current['direct_source_review']['tei_sha256'] != direct['tei_sha256'] or not current['reproducibility']['exact_six_member_bytes_equal'] or len(current['reproducibility']['replays']) != 2 or not current['closure_negative']['rejected'] or not current['closure_negative']['producer_rejected'] or len(current['direct_source_review']['mutations']) != EXPECTED_MUTATIONS[member_id] or not all(x['rejected'] for x in current['direct_source_review']['mutations']):
            raise PipelineError('Maclaren current source/replay/negative proof differs')
        acquisition_rel = edition / 'acquisitions' / (spec['acquisition'] + '.json')
        acquisition = validate_acquisition(root / acquisition_rel, root=root)
        if acquisition['source_sha256'] != spec['sha256'] or len(acquisition['retained_files']) != 1:
            raise PipelineError('Maclaren existing acquisition source differs')
        form = next(x for x in work['textual_forms'] if x['textual_form_id'] == spec['form'])
        edition_record = next(x for x in form['editions'] if x['edition_id'] == spec['edition'])
        if edition_record.get('category') is not None: raise PipelineError('Maclaren category preimage changed')
        edition_record['category'] = 'commentary'
        for name in package.member_names: write(stage, lane / 'inputs/package' / name, package.member_bytes(name))
        write(stage, lane / 'inputs/current-review.json', (root / LOG / (member_id + '-current-review-v2.json')).read_bytes())
        identity = dict(work_id=WORK_ID, textual_form_id=spec['form'], edition_id=spec['edition'], acquisition_id=spec['acquisition'])
        source = {key: acquisition[key] for key in ['source_path', 'source_sha256', 'source_bytes', 'source_scope']}
        selected = declared_scope(edition_record, member_id)
        revision = dict(id=member_id + '-retained-current-20261003-v1', date=datetime.now(timezone.utc).date().isoformat(), note=REVISION_NOTE)
        raw = package.member_bytes('content.tei.xml')
        bound = recompute_header(raw, identity=identity, source=source, source_url=acquisition['url'], declared=selected, revision=revision)
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
            administrative_comments=spec['comments'], administrative_comment_disposition='Exact ledger fields; actual readable source independently compared after bounded whitespace joins; inverse entire source body C14N equal',
            retained_administration='All original ThML header/CSS source fields accounted', complete_acquired_work_volumes=4, original_candidate_route='Existing final LIB033 flat source graphs and encoded witnesses independently reconciled; readable source hierarchy repaired from the four already acquired raw sources', relative_uri_context=direct['relative_uri_context'], table_count=direct['table_count'], table_header_cell_count=direct['table_header_cell_count'], omitted_readable_elements=0))
        command = 'py -3 -m build.tools.stage_maclaren_retained_acceptance'
        technical = dict(producer={'id': manifest.record['converter']['id']}, checker={'id': manifest.record['validator']['id']}, shared_assumptions=['Pinned XML, P5 and declared native mapping; prior producer/mapping exposure declared. Independent stdlib raw source traversal with secondary lxml corroboration; oracle imports no producer/emitter or projection code.'], independent_corroboration='Complete actual root/text/front/body/back fields, semantic attributes, paragraph/heading/verse and source span/br ownership, note attachment, table summaries/spans/header roles, exact next/prev or missing toc annotations and all relative URI contexts independently compared against raw. All ten administrative comments per source and two tbody wrappers in PsalmsII independently reconciled with exact joins before entire actual-backed source-body inverse. All original head/prolog/CSS/copyright human-visible. Schema-valid 15/19/15/20 mutations including same-text wrong attachment and extra outer body payload reject. Two fresh Python six-member equality replays each pass. Complete original flat graphs/encoded witnesses independently reconciled before repair; not a readable-native equality claim. No image elements or source U+FFFD occur.')
        for name in ['validation', 'accounting', 'fidelity', 'reproducibility', 'schema', 'closure']:
            proof = write_json(stage, lane / (name + '.json'), common | dict(status='pass', command=command, exit_code=0, claim=name, readable_body_unchanged_at_header_binding=True, actual_readable_body_inverse_c14n_equal=True))
            technical[name] = dict(path=proof, status='pass', command=command, exit_code=0)
        review = dict(reviewer='agent:maclaren-existing-retained-source-review', reviewed_at=at,
            coverage=dict(status='complete', declared=selected, reached=['all retained source edition XML elements', 'all actual readable source paragraphs/front matter/notes/indices/tables/reference targets and URI context', 'all source attributes, tails and order', 'all ten administrative comments per volume and metadata/CSS fields'], inspected=['all actual readable source paragraphs/front matter/notes/indices/tables/reference targets and URI context', 'all source attributes, tails and order', 'all ten administrative comments per volume and metadata/CSS fields'], unreviewed=[]),
            source_quality_uncertainty=['Exact retained CCEL electronic witnesses only; no print or independent provider collation.', 'Psalms I1-38 /II39-89 /III90-150 retained as three volume units. Colossians/Philemon remains its acquired combined volume. Source-specific span/br versus verse/l arrangements retained, with no invented verse targets or typography equivalence.', 'Missing source navigation toc references remain literal typed annotations; no source images or U+FFFD in these four XML witnesses.'], discrepancies=[], unreviewed_residuals=['Human review, CCEL formatting rights, print collation and release remain separate; actual commentary projection measured independently.'])
        review_path = write_json(stage, lane / 'review.json', common | review)
        decision = dict(source_local_disposition='Agent accepts the complete faithful retained electronic volume within the explicit four-unit acquired author catalog work.', blockers=[], agent_assessment=dict(status='accepted', actor=review['reviewer'], assessed_at=at, supported_scope=selected, unresolved_claims=[], unassessed_stronger_claims=['human review', 'print collation', 'rights clearance', 'publication', 'downstream commentary projection']), human_decision={'status': 'not-recorded'})
        record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting,
            scope=accepted_scope | dict(expected_members=expected, included_members=included, excluded_members=[]), technical=technical, review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
        acceptance = stage / edition / 'acceptance.json'; write_acceptance(acceptance, record); validate_acceptance(acceptance, root=stage)
        master = write(stage, edition / 'master.tei.xml', bound)
        record['promotion'] = dict(record['promotion']); record['promotion'].update(status='promoted', promoted_at=at, master=make_file_binding(stage, master)); write_acceptance(acceptance, record)
        targets = [x for x in state['targets'] if x['target_type'] == 'edition' and x['target_id'] == spec['edition']]
        if len(targets) != 1 or targets[0]['stage'] != 'acquired': raise PipelineError('Maclaren edition acquired preimage differs')
        targets[0].update(stage='accepted', reason=PROMOTED_MASTER_REASON, updated_at=at)
        targets[0]['evidence'].extend([(edition / 'master.tei.xml').as_posix(), (edition / 'acceptance.json').as_posix()])
        write_json(stage, WORK / 'work.json', work)
        write_json(stage, WORK / 'state.json', state)
        volumes.append(dict(member_id=member_id, source_sha256=spec['sha256'], source_manifest_sha256=manifest.sha256,
            candidate_package_sha256=package.sha256, oracle_report_sha256=report.sha256, master_sha256=sha(master.read_bytes()), acceptance_sha256=sha(acceptance.read_bytes()), projection_gate=projection_gate(stage, acceptance), scope_kind='volume'))
    validate_identity_update(original_work, work); write_json(stage, WORK / 'work.json', work); load_work(stage / WORK / 'work.json')
    write_json(stage, WORK / 'state.json', state)
    for spec in MEMBERS.values(): validate_acceptance(stage / edition_path(spec) / 'acceptance.json', root=stage)
    validate_state(stage / WORK / 'state.json', root=stage)
    receipt = dict(contract='ocd-maclaren-retained-external-stage-v1', status='bootstrap-only' if bootstrap else 'staged-only', work_id=WORK_ID, stage_root=stage.as_posix(), before=before, after=_files(stage / WORK), volumes=volumes,
        included_volumes=4, acquired_volumes=4, projection_category='commentary', accepted_scope_kind='volume', human_review='not-recorded', rights='not-assessed', installation='not-performed', staged_at=at)
    receipt['dependency_files'] = {p.as_posix(): sha(_io_path(root / p).read_bytes()) for p in sorted(dependencies(root, bootstrap=bootstrap))}
    write_json(stage, Path('stage-receipt.json'), receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--stage', type=Path, required=True); parser.add_argument('--bootstrap', action='store_true'); args = parser.parse_args()
    result = prepare(args.stage, bootstrap=args.bootstrap); print(json.dumps(dict(work_id=WORK_ID, stage_root=result['stage_root'], volumes=result['volumes']), sort_keys=True))
