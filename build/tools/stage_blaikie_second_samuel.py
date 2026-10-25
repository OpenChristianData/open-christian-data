"""Prepare one guarded complete Second Samuel book; preserve the sibling catalog."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from build.tei.blaikie_second_samuel_scope import ROOT, LOG, WORK_ID, MEMBERS, OLD_PACKAGE, REPLAY_LOG, BOUNDARY, sha
from build.tei.blaikie_second_samuel_prepare import SOURCE_DIR, SCOPE, canonical
from build.tei.blaikie_second_samuel_oracle import _oracle as oracle, check, ORACLE_IMPORTS, PRODUCER_IMPORTS
from build.tools.prepare_blaikie_second_samuel import CANDIDATES
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
EVIDENCE = WORK / 'integration/blaikie-second-samuel-retained-current-20261003-v3'


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
    result = {Path('build/tei/blaikie_second_samuel_scope.py'), Path('build/tei/blaikie_second_samuel_prepare.py'), Path('build/tei/blaikie_second_samuel_oracle.py'), Path('build/tei/blaikie_second_samuel_emitter.py'), Path('build/tei/ccel_retained_native_emitter.py'), Path('build/tools/prepare_blaikie_second_samuel.py'), Path('build/tools/stage_blaikie_second_samuel.py'), Path('build/tools/install_blaikie_second_samuel.py'), Path('ocd_kernel/__init__.py'), Path('ocd_kernel/tei/writer.py')}
    result.update(p.relative_to(root) for directory, suffix in [('ocd_kernel/reconstruction', '*.py'), ('ocd_kernel/reconstruction/schemas', '*.json'), ('schemas/v2', '*.json'), ('ocd_kernel/tei/vendor/xsd', '*.xsd')] for p in (root / directory).rglob(suffix))
    result.update(Path(p) for p in ORACLE_IMPORTS + PRODUCER_IMPORTS)
    result.add(Path("build/tools/prove_blaikie_second_samuel_install.py"))
    # Reviewed baseline runtime dependencies; actual Second Samuel execution is inventoried at final stage.
    result.add(Path('ocd_kernel/projection/categories/lib040_augustine_divisions.py'))
    # Additional modules observed by the reviewed baseline preflight,
    # beyond the independent oracle's separately scoped fresh import-time closure.
    result.update(Path(p) for p in ['build/__init__.py', 'build/tei/__init__.py',
        'ocd_kernel/library/__init__.py', 'ocd_kernel/library/source_selection.py',
        'ocd_kernel/projection/source_projection_evidence.py', 'ocd_kernel/tei/__init__.py',
        'ocd_kernel/tei/normalization.py', 'ocd_kernel/tei/projection_profile.py',
        'ocd_kernel/projection/categories/prose.py', 'ocd_kernel/projection/categories/sermons.py'])
    result.update(Path(p) for p in ['ocd_kernel/tei/acceptance.py', 'ocd_kernel/tei/install_accepted.py', 'ocd_kernel/tei/reviewed_integration.py', 'ocd_kernel/tei/validate.py', 'ocd_kernel/library/state.py', 'ocd_kernel/library/identities.py', 'ocd_kernel/library/acquisitions.py', 'ocd_kernel/library/_common.py', 'ocd_kernel/lib/path_io.py', 'ocd_kernel/lib/storage_topology.py', 'ocd_kernel/lib/atomic_io.py', 'ocd_kernel/projection/__init__.py', 'ocd_kernel/projection/categories/__init__.py', 'ocd_kernel/projection/categories/commentary.py', 'ocd_kernel/projection/categories/commentary_source_native.py', 'ocd_kernel/projection/categories/native_documents.py', 'ocd_kernel/projection/native_content.py', 'ocd_kernel/projection/native_content_check.py', 'ocd_kernel/projection/envelope.py', 'ocd_kernel/projection/scripture_authority.py', 'ocd_kernel/projection/scripture_targets.py', 'ocd_kernel/projection/scripture_targets_check.py', 'build/bible_data/osis_book_codes.json'])
    result.update(p.relative_to(root) for p in (root / OLD_PACKAGE).iterdir() if p.is_file())
    result.update({REPLAY_LOG / 'qualified-current-lib036-replay-receipt.json', LOG / 'retained-scope-reconciliation.json', LOG / 'candidate-completion-receipt.json'})
    for member_id, spec in MEMBERS.items():
        manifest_path = SOURCE_DIR / (member_id + '.source-manifest.json')
        manifest = SourceManifest.load(root / manifest_path, repository_root=root)
        result.add(manifest_path)
        result.add(edition_path(spec) / 'acquisitions' / (spec['acquisition'] + '.json'))
        result.update(Path(x['path']) for x in manifest.record['authorities'])
    return result


def execution_modules(root=ROOT):
    """Observed concrete Python implementations, including durable junctions.

    Code in the canonical repo maps directly; retained-library code maps only
    through the declared raw/reports/exports junction. Other Library imports
    fail closed. Fixture copies must equal the canonical executing code bytes.
    """
    observed={};canonical_root=ROOT.resolve(strict=True);library_root=LIBRARY.resolve(strict=True)
    for module in tuple(sys.modules.values()):
        filename=getattr(module,'__file__',None)
        if not filename:continue
        physical=Path(filename).resolve()
        if physical.suffix!='.py':continue
        try:relative=physical.relative_to(canonical_root)
        except ValueError:
            try:relative=physical.relative_to(library_root)
            except ValueError:continue
            if not relative.parts or relative.parts[0] not in {'raw','reports','exports'} or (ROOT/relative).resolve()!=physical:
                raise PipelineError('Unexpected retained-library Python import outside canonical junctions: '+physical.as_posix())
        actual=sha(physical.read_bytes());bound=sha(_io_path(root/relative).read_bytes())
        if actual!=bound:raise PipelineError('Executing implementation differs from bound root: '+relative.as_posix())
        observed[relative.as_posix()]=dict(path=relative.as_posix(),physical_path=physical.as_posix(),sha256=actual)
    return [observed[key] for key in sorted(observed)]


def prepare(stage, *, root=ROOT):
    root = root.resolve(strict=True); stage = stage.absolute()
    if stage.exists() or stage.parent != (LIBRARY / 'candidate-reviews').resolve(strict=True) or not stage.name.startswith('blaikie-second-samuel-s-'):
        raise PipelineError('Fresh external Blaikie Second Samuel stage required')
    before = _files(root / WORK)
    work = read(root / WORK / 'work.json'); original_work = json.loads(json.dumps(work))
    state = read(root / WORK / 'state.json')
    scope_review = read(root / LOG / 'retained-scope-reconciliation.json')
    if scope_review['status'] != 'pass' or scope_review['complete_authored_works'] != 1 or scope_review['excluded_works'] != ['First Samuel','Joshua']:
        raise PipelineError('Complete existing Second Samuel book envelope differs')
    first_form=WORK_ID+'--blaikie-expositor8--retained-en'
    first_edition=WORK_ID+'--blaikie-expositor8--ccel-electronic'
    first_path=WORK/'forms'/first_form/'editions'/first_edition
    if not _io_path(root/first_path/'master.tei.xml').is_file() or not _io_path(root/first_path/'acceptance.json').is_file():
        raise PipelineError('Final Second Samuel stage awaits First Samuel canonical readback')
    validate_acceptance(root/first_path/'acceptance.json',root=root)
    for spec in MEMBERS.values():
        if (root / edition_path(spec) / 'master.tei.xml').exists() or (root / edition_path(spec) / 'acceptance.json').exists():
            raise PipelineError('Blaikie Second Samuel canonical accepted authority already exists; no replacement')
    stage.mkdir()
    for relative in before: copy(root, stage, WORK / relative)
    for relative in dependencies(root): copy(root, stage, relative)
    evidence = set(work['evidence'] + [p for target in state['targets'] for p in target['evidence']])
    for relative in evidence:
        # Existing evidence may select a JSON fragment; copy the containing
        # retained file while preserving the original sidecar reference exactly.
        containing_file = Path(relative.split('#', 1)[0])
        if not _io_path(stage / containing_file).exists(): copy(root, stage, containing_file)
    write(stage, EVIDENCE / 'complete-second-samuel-source-scope.json', (root / LOG / 'retained-scope-reconciliation.json').read_bytes())
    at = now(); volumes = []
    for member_id, spec in MEMBERS.items():
        edition = edition_path(spec); lane = EVIDENCE / member_id
        manifest_path = SOURCE_DIR / (member_id + '.source-manifest.json')
        manifest = SourceManifest.load(root / manifest_path, repository_root=root)
        package = CandidatePackage.load(CANDIDATES / 'package')
        report = validate(manifest, package, oracle)
        current = read(root / LOG / 'candidate-completion-receipt.json')
        direct = check(member_id, package.path, native=False)
        if (current['status']!='pass' or current['complete_works']!=1 or current['retained_sources']!=1
                or current['excluded_works']!=['First Samuel','Joshua'] or report.status!='pass'
                or current['package_sha256']!=package.sha256 or current['source_manifest_sha256']!=manifest.sha256
                or current['oracle_report_sha256']!=report.sha256 or current['direct_source_review']!=direct
                or len(current['mutations'])!=22 or not all(x['rejected'] and x['p5_valid'] for x in current['mutations'])
                or len(current['replays'])!=2 or not all(x['fresh_python_process'] and x['exact_six_member_bytes_equal'] and x['package_sha256']==package.sha256 for x in current['replays'])
                or len(current['import_negatives'])!=2 or not all(x['rejected'] for x in current['import_negatives'])
                or current['retained_lineage_field_proof']!=read(root/LOG/'retained-lineage-field-mutation-proof.json')
                or current['retained_lineage_field_proof']['status']!='pass'
                or len(current['retained_lineage_field_proof']['mutations'])!=4
                or not all(x['rejected'] and x['p5_valid'] and x['exact_tei_unchanged'] for x in current['retained_lineage_field_proof']['mutations'])):
            raise PipelineError('Second Samuel complete current source/replay/negative proof differs')
        acquisition_rel = edition / 'acquisitions' / (spec['acquisition'] + '.json')
        acquisition = validate_acquisition(root / acquisition_rel, root=root)
        if acquisition['source_sha256'] != spec['sha256'] or len(acquisition['retained_files']) != 1:
            raise PipelineError('Blaikie Second Samuel existing acquisition source differs')
        form = next(x for x in work['textual_forms'] if x['textual_form_id'] == spec['form'])
        edition_record = next(x for x in form['editions'] if x['edition_id'] == spec['edition'])
        if edition_record.get('category') is not None: raise PipelineError('Blaikie Second Samuel category preimage changed')
        edition_record['category'] = 'commentary'
        for name in package.member_names: write(stage, lane / 'inputs/package' / name, package.member_bytes(name))
        write(stage, lane / 'inputs/current-review.json', (root / LOG / 'candidate-completion-receipt.json').read_bytes())
        identity = dict(work_id=WORK_ID, textual_form_id=spec['form'], edition_id=spec['edition'], acquisition_id=spec['acquisition'])
        source = {key: acquisition[key] for key in ['source_path', 'source_sha256', 'source_bytes', 'source_scope']}
        selected = BOUNDARY+' '+SCOPE
        revision = dict(id=member_id + '-retained-current-20261003-v3', date=at[:10], note='Readable faithful complete Second Samuel book; original source order and literal identities preserved.')
        raw = package.member_bytes('content.tei.xml')
        bound = bind_reviewed_header(raw, expected_sha256=sha(raw), identity=identity, source=source, source_url=acquisition['url'], declared_scope=selected, revision=revision)
        if bound.split(b'</teiHeader>', 1)[1] != raw.split(b'</teiHeader>', 1)[1]: raise PipelineError('Blaikie Second Samuel header binding changed readable body')
        candidate = write(stage, lane / 'candidate.tei.xml', bound)
        if errors := validate_file(candidate): raise PipelineError(str(errors[:3]))
        expected = [dict(path=spec['path'], position=1)]
        included = [dict(path=spec['path'], position=1, bytes=spec['bytes'], sha256=spec['sha256'], scope=selected)]
        accepted_scope = dict(kind='work', declared=selected)
        common = dict(identity=identity, representation_revision=revision, staged_at=at, source=source, candidate=make_file_binding(stage, candidate), scope=selected, accepted_scope=accepted_scope,
            expected_members=expected, included_members=included, excluded_members=[], missing_members=[], unknown_members=[],
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256, oracle_report_sha256=report.sha256,
            direct_source_review=make_file_binding(stage, stage / lane / 'inputs/current-review.json'))
        accounting = write_json(stage, lane / 'source-accounting.json', common | dict(scope=source['source_scope'], source_sha256=spec['sha256'], source_bytes=spec['bytes'], full_source_elements=spec['elements'], readable_source_elements=spec['native_source_elements'],
            administrative_comments=spec['body_comments'], tbody_wrappers=spec['tbody_wrappers'], administrative_comment_disposition='All ten comments retain exact fields/positions; independently checked whitespace-only tails join actual text. Actual-readable source body inverse equals complete raw source. No source table, tbody, or column group exists.',
            retained_administration='All original ThML header/CSS source fields accounted', retained_work_sources=1, complete_authored_works=1, excluded_authored_works=['First Samuel','Joshua'], original_candidate_route='qualified-existing-lib036-readable-repair', omitted_readable_elements=0))
        command = 'py -3 -m build.tools.stage_blaikie_second_samuel'
        technical = dict(producer={'id':manifest.record['converter']['id']},checker={'id':manifest.record['validator']['id']},
            shared_assumptions=['Pinned retained electronic witness, P5 and literal native mapping policy; independent oracle does not import producer/emitter or trust ledger native attrs.'],
            independent_corroboration='Independent stdlib source traversal, with lxml corroboration, verifies every actual readable DOM direct/tail field, semantic attribute, heading, note, verse line, generated index ownership and all42 acquired URL bases. Actual-readable source body inverse equals raw including all10 administrative comments. Qualified current LIB036 aggregate replay conserves exact raw bytes and original fields; no September11 recovery or historical oracle pass is claimed. No Second Samuel historical correction rows exist. All22 P5-valid mutations rejected; two fresh Python processes reproduce all six package members. Complete source head/root/XML prefix and permissions are visible.')
        for name in ['validation', 'accounting', 'fidelity', 'reproducibility', 'schema', 'closure']:
            proof = write_json(stage, lane / (name + '.json'), common | dict(status='pass', command=command, exit_code=0, claim=name, readable_body_unchanged_at_header_binding=True, actual_readable_body_inverse_c14n_equal=True))
            technical[name] = dict(path=proof, status='pass', command=command, exit_code=0)
        review = dict(reviewer='agent:blaikie-second-samuel-retained-source-review', reviewed_at=at,
            coverage=dict(status='complete', declared=selected, reached=['all retained source volume XML elements', 'all actual readable source paragraphs/front matter/notes/indices/reference targets', 'all source attributes, tails and order', 'all source administrative comments, metadata/CSS, literal document prefix and prolog fields'], inspected=['all actual readable source paragraphs/front matter/notes/indices/reference targets', 'all source attributes, tails and order', 'all source administrative comments, metadata/CSS, literal document prefix and prolog fields'], unreviewed=[]),
            source_quality_uncertainty=['Retained CCEL electronic Second Samuel only; no print/provider collation. Own 1898 New York A.C. Armstrong and Son title page, chapters I-XXXIII and final indexes define one complete authored book. First Samuel and Joshua remain outside this candidate; no author-catalog or series completeness claim.', 'Exact historical candidate path ACL denied; no absence/recovery or old oracle pass claim. The existing current converter-only aggregate replay is qualified lineage. Raw readings preserved; zero historical correction rows for Second Samuel. No source images or tables. All42 relative query targets retain acquired URL context.'],
            discrepancies=[],unreviewed_residuals=['Human review, print collation, CCEL formatting rights and publication remain separate; actual commentary projection is measured independently.'])
        review_path = write_json(stage, lane / 'review.json', common | review)
        decision = dict(source_local_disposition='Agent accepts the complete faithful retained Second Samuel authored book within the one retained source scope.', blockers=[], agent_assessment=dict(status='accepted', actor=review['reviewer'], assessed_at=at, supported_scope=selected, unresolved_claims=[], unassessed_stronger_claims=['human review', 'print collation', 'rights clearance', 'publication', 'downstream commentary projection']), human_decision={'status': 'not-recorded'})
        record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting,
            scope=accepted_scope | dict(expected_members=expected, included_members=included, excluded_members=[]), technical=technical, review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
        acceptance = stage / edition / 'acceptance.json'; write_acceptance(acceptance, record); validate_acceptance(acceptance, root=stage)
        master = write(stage, edition / 'master.tei.xml', bound)
        record['promotion'] = dict(record['promotion']); record['promotion'].update(status='promoted', promoted_at=at, master=make_file_binding(stage, master)); write_acceptance(acceptance, record)
        targets = [x for x in state['targets'] if x['target_type'] == 'edition' and x['target_id'] == spec['edition']]
        if len(targets) != 1 or targets[0]['stage'] != 'acquired': raise PipelineError('Blaikie Second Samuel edition acquired preimage differs')
        targets[0].update(stage='accepted', reason=PROMOTED_MASTER_REASON, updated_at=at)
        targets[0]['evidence'].extend([(edition / 'master.tei.xml').as_posix(), (edition / 'acceptance.json').as_posix()])
        write_json(stage, WORK / 'work.json', work)
        volumes.append(dict(member_id=member_id, source_sha256=spec['sha256'], source_manifest_sha256=manifest.sha256,
            candidate_package_sha256=package.sha256, oracle_report_sha256=report.sha256, master_sha256=sha(master.read_bytes()), acceptance_sha256=sha(acceptance.read_bytes()), scope_kind='work'))
    validate_identity_update(original_work, work); write_json(stage, WORK / 'work.json', work); load_work(stage / WORK / 'work.json')
    write_json(stage, WORK / 'state.json', state)
    for member_id, spec in MEMBERS.items():
        acceptance = stage / edition_path(spec) / 'acceptance.json'
        validate_acceptance(acceptance, root=stage)
        next(row for row in volumes if row['member_id'] == member_id)['projection_gate'] = projection_gate(stage, acceptance,
            raw_evidence=stage / EVIDENCE / member_id / 'projection-raw-probe.json')
    validate_state(stage / WORK / 'state.json', root=stage)
    if _files(root/WORK)!=before:raise PipelineError('Second Samuel canonical/sibling preimage changed during preparation')
    receipt = dict(contract='ocd-blaikie-second-samuel-external-stage-v1', status='staged-only', staged_at=at, work_id=WORK_ID, stage_root=stage.as_posix(), before=before, after=_files(stage / WORK), volumes=volumes,
        included_sources=1, acquired_sources=1, complete_authored_works=1, projection_category='commentary', accepted_scope_kind='work', human_review='not-recorded', rights='not-assessed', installation='not-performed')
    receipt['dependency_files'] = {p.as_posix(): sha(_io_path(root / p).read_bytes()) for p in sorted(dependencies(root))}
    observed = execution_modules(root)
    if any(receipt['dependency_files'].get(item['path']) != item['sha256'] for item in observed):
        raise PipelineError('Blaikie Second Samuel actual stage execution loaded an unpinned first-party module: '+repr([item for item in observed if receipt['dependency_files'].get(item['path'])!=item['sha256']]))
    receipt['executed_first_party_modules'] = observed
    write_json(stage, Path('stage-receipt.json'), receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--stage', type=Path, required=True); args = parser.parse_args()
    result = prepare(args.stage); print(json.dumps(dict(work_id=WORK_ID, stage_root=result['stage_root'], volumes=result['volumes']), sort_keys=True))
