"""Stage or guarded-install only the existing Charnock Volume 1 status header repair."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree
from build.tools.stage_charnock_vol1_current_acceptance import (
    ROOT, LIBRARY, WORK, WORK_ID, EDITION, EDITION_ID, SOURCE, SOURCE_SHA, MANIFEST, ACQUISITION,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import (
    _files, _commit_generation, _replacement_changes_are_scoped,
    _validate_promoted_tree, _validate_state_transition,
)
from ocd_kernel.tei.validate import validate_file

EVIDENCE = WORK / 'acceptance/charnock-vol1-header-status-20261003-v1'
LOG = ROOT / 'reports/_logs/charnock-vol1-current-20261003-v1'
OLD_MASTER = 'a08001efad6351b3ef175e84f341fdf6a59fa97917456f0b3121a57b8208cc50'
OLD_ACCEPTANCE = '65d985cdc989b783eec8ee13010d258bcf0632485198a79dde84e5c201de0f1c'
OLD_REVISION = 'charnock-vol1-native-v2-current-20261003-v1'
REVISION = dict(id='charnock-vol1-header-status-20261003-v1', date='2026-10-03',
    note='Correct the stale producer candidate-status publication statement after agent acceptance; preserve the complete accepted text, retained source bindings, prior revision, human-review qualifications, and publication hold.')
OLD_STATUS = b'Nonaccepted reconstruction candidate; publication:not_ready.'
NEW_STATUS = b'Agent-accepted retained electronic witness; human verification and rights clearance remain unrecorded; publication:not_ready.'
FIXTURE_MARKER = '.ocd-charnock-vol1-header-repair-fixture'
COMMAND = 'py -3 -m build.tools.repair_charnock_vol1_publication_header'


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def read(path):
    return json.loads(io_path(path).read_bytes())


def digest(path):
    return sha256(io_path(path).read_bytes()).hexdigest()


def put(root, relative, content):
    path = root / relative
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    io_path(path).write_bytes(content)
    return path


def save(root, relative, value):
    return put(root, relative, canonical(value))


def repaired(original):
    if sha256(original).hexdigest() != OLD_MASTER:
        raise PipelineError('Exact Charnock Volume 1 installed master preimage required')
    status_before = b'<publicationStmt><p>' + OLD_STATUS + b'</p></publicationStmt>'
    status_after = b'<publicationStmt><p>' + NEW_STATUS + b'</p></publicationStmt>'
    binding_before = b'<idno type="representation_revision">' + OLD_REVISION.encode() + b'</idno>'
    binding_after = b'<idno type="representation_revision">' + REVISION['id'].encode() + b'</idno>'
    change = ('<change xml:id="' + REVISION['id'] + '" when="' + REVISION['date'] + '">' + REVISION['note'] + '</change>').encode()
    for token in (status_before, binding_before, b'</revisionDesc>'):
        if original.count(token) != 1:
            raise PipelineError('Exact singleton old header token required')
    result = original.replace(status_before, status_after, 1).replace(binding_before, binding_after, 1).replace(b'</revisionDesc>', change + b'</revisionDesc>', 1)
    inverse = result.replace(change + b'</revisionDesc>', b'</revisionDesc>', 1).replace(binding_after, binding_before, 1).replace(status_after, status_before, 1)
    if inverse != original or original.split(b'</teiHeader>', 1)[1] != result.split(b'</teiHeader>', 1)[1]:
        raise PipelineError('Header-only repair exact inverse/body proof failed')
    old_tree, new_tree = etree.fromstring(original), etree.fromstring(result)
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    old_text, new_text = old_tree.find('t:text', ns), new_tree.find('t:text', ns)
    old_c14n = etree.tostring(old_text, method='c14n')
    if old_c14n != etree.tostring(new_text, method='c14n'):
        raise PipelineError('Complete text C14N differs')
    ids = new_tree.xpath('//@xml:id', namespaces={'xml': 'http://www.w3.org/XML/1998/namespace'})
    id_set = set(ids)
    if len(ids) != len(id_set):
        raise PipelineError('Duplicate local identities')
    references = [part for node in new_tree.iter() for name, value in node.attrib.items()
                  if name in {'target', 'corresp', 'sameAs', 'next', 'prev', 'spanTo', 'from', 'to'}
                  for part in value.split() if part.startswith('#')]
    if any(part[1:] not in id_set for part in references):
        raise PipelineError('Broken local reference')
    return result, dict(text_body_byte_identical=True, complete_text_c14n_sha256=sha256(old_c14n).hexdigest(),
        complete_inverse_byte_identical=True, inverse_master_sha256=sha256(inverse).hexdigest(),
        unchanged_after_header_sha256=sha256(original.split(b'</teiHeader>', 1)[1]).hexdigest(),
        local_ids=len(ids), local_references=len(references), local_closure_errors=[],
        exact_header_changes=['publicationStmt/p status text', 'representation_revision idno', 'one appended revisionDesc/change'],
        original_revision_preserved=True)


def dependencies():
    manifest = read(ROOT / MANIFEST)
    paths = {SOURCE, MANIFEST, ACQUISITION,
        Path('sources/structured-text/charnock-existence-attributes-vol-1/charnock-existence-attributes-vol-1.source-manifest.json')}
    paths.update(Path(item['path']) for item in manifest['authorities'])
    paths.update(Path(manifest[name]['implementation_path']) for name in ('converter', 'validator'))
    state = read(ROOT / WORK / 'state.json')
    paths.update(Path(path) for target in state['targets'] for path in target['evidence'])
    return paths


def runtime_bindings():
    # Freeze the imported kernel surface and schema closure without changing it.
    paths = {Path(__file__).resolve().relative_to(ROOT), Path('build/tools/stage_charnock_vol1_current_acceptance.py'),
             Path('build/bible_data/osis_book_codes.json')}
    for directory in ('ocd_kernel/tei', 'ocd_kernel/library', 'ocd_kernel/lib', 'ocd_kernel/projection'):
        paths.update(path.relative_to(ROOT) for path in (ROOT / directory).rglob('*.py'))
    for directory in ('ocd_kernel/schemas', 'schemas'):
        paths.update(path.relative_to(ROOT) for path in (ROOT / directory).rglob('*.json'))
    paths.update(path.relative_to(ROOT) for path in (ROOT / 'ocd_kernel/tei/vendor/xsd').rglob('*.xsd'))
    return {path.as_posix(): digest(ROOT / path) for path in sorted(paths)}


def projection(root):
    acceptance = root / EDITION / 'acceptance.json'
    with cached_edition_lookups():
        value = project_accepted_document(root, acceptance_path=acceptance, category='prose')
        errors = verify_accepted_document(root, acceptance_path=acceptance, rows=value['rows'], receipt=value['receipt'], category='prose')
    if errors or len(value['rows']) != 2:
        raise PipelineError(f'Charnock actual-master projection differs: {errors}')
    return value


def require_conserved_rows(previous, current):
    if len(previous) != len(current) or len(previous) != 2:
        raise PipelineError('Accepted native row count changed')
    for old_row, new_row in zip(previous, current, strict=True):
        expected = dict(old_row)
        if expected.get('representation_revision') != OLD_REVISION or new_row.get('representation_revision') != REVISION['id']:
            raise PipelineError('Native row revision bindings differ')
        expected['representation_revision'] = REVISION['id']
        if expected != new_row:
            raise PipelineError('Header repair changes native row content outside revision binding')


def prepare(stage):
    stage = stage.absolute()
    if stage.exists() or stage.parent.resolve(strict=True) != (LIBRARY / 'candidate-reviews').resolve(strict=True) or not stage.name.startswith('c1-h'):
        raise PipelineError('Fresh bounded Charnock header stage required')
    before = _files(ROOT / WORK)
    if len(before) != 23 or digest(ROOT / EDITION / 'acceptance.json') != OLD_ACCEPTANCE:
        raise PipelineError('Installed Charnock 23-file preimage differs')
    old = validate_acceptance(ROOT / EDITION / 'acceptance.json', root=ROOT)
    validate_state(ROOT / WORK / 'state.json', root=ROOT)
    if old['promotion']['master']['sha256'] != OLD_MASTER or old['decision']['agent_assessment']['status'] != 'accepted' or old['decision']['human_decision']['status'] != 'not-recorded':
        raise PipelineError('Old acceptance or human qualifications differ')
    source_bindings = {path.as_posix(): digest(ROOT / path) for path in dependencies()}
    if source_bindings[SOURCE.as_posix()] != SOURCE_SHA:
        raise PipelineError('Retained source changed')
    for relative in before:
        put(stage, WORK / relative, io_path(ROOT / WORK / relative).read_bytes())
    for relative in source_bindings:
        put(stage, Path(relative), io_path(ROOT / relative).read_bytes())
    original = io_path(ROOT / EDITION / 'master.tei.xml').read_bytes()
    bound, proof = repaired(original)
    # Preserve the exact superseded accepted artifacts in the new acceptance evidence.
    put(stage, EVIDENCE / 'superseded-master.tei.xml', original)
    put(stage, EVIDENCE / 'superseded-record.json', io_path(ROOT / EDITION / 'acceptance.json').read_bytes())
    candidate = put(stage, EVIDENCE / 'candidate.tei.xml', bound)
    errors = validate_file(io_path(candidate))
    if errors:
        raise PipelineError(f'Header repair P5 errors: {errors[:3]}')
    mutations = [dict(case=name, rejected=payload != bound) for name, payload in (
        ('stale-status', bound.replace(NEW_STATUS, OLD_STATUS, 1)),
        ('premature-publication', bound.replace(b'publication:not_ready.', b'publication:ready.', 1)),
        ('wrong-revision-binding', bound.replace(REVISION['id'].encode(), b'wrong-revision', 1)),
        ('changed-body', bound.replace(b'</text>', b'changed</text>', 1)))]
    if not all(row['rejected'] for row in mutations):
        raise PipelineError('Exact allowed-delta mutation rejection failed')
    proof.update(status='pass', superseded_master_sha256=OLD_MASTER, superseded_acceptance_sha256=OLD_ACCEPTANCE,
        successor_candidate_sha256=digest(candidate), tei_p5_errors=errors, mutations=mutations,
        replay_byte_identical=repaired(original)[0] == bound,
        source_reconstruction_rerun=False,
        mutation_scope='Exact allowed-byte-delta comparator challenges only; not independently executed source oracle challenges.',
        basis='Current source authority hashes and every original source/body proof remain unchanged. Complete accepted text bytes and C14N match; inverse restores every original master byte. Original dated proof is inherited only for unchanged body/source, not relabeled as a new source reconstruction.')
    proof_path = save(stage, EVIDENCE / 'header-body-equivalence.json', proof)
    old_account = read(ROOT / old['source']['accounting']['path'])
    common = {key: old_account[key] for key in ('identity', 'source', 'accepted_scope', 'expected_members', 'included_members', 'excluded_members', 'missing_members', 'unknown_members')}
    common.update(candidate=make_file_binding(stage, candidate), header_body_equivalence=make_file_binding(stage, proof_path),
        superseded_acceptance=make_file_binding(stage, stage / EVIDENCE / 'superseded-record.json'),
        dated_source_accounting=old['source']['accounting'], inherited_original_decision=old['decision'])
    account = dict(old_account)
    account.update(common)
    account['current_header_repair'] = proof
    account_path = save(stage, EVIDENCE / 'source-accounting.json', account)
    technical = {key: old['technical'][key] for key in ('producer', 'checker', 'shared_assumptions')}
    technical['independent_corroboration'] = proof['basis'] + ' Fresh P5, complete local ID closure, exact allowed-delta mutation challenges, acceptance/state validation and native actual-master verification are required for this successor.'
    for name in ('validation', 'accounting', 'fidelity', 'reproducibility', 'schema', 'closure'):
        path = save(stage, EVIDENCE / (name + '.json'), common | dict(status='pass', claim=name, command=COMMAND, exit_code=0,
            scope=old['scope']['declared'], dated_original_proof=old['technical'][name], current_header_checks=proof))
        technical[name] = dict(path=path, status='pass', command=COMMAND, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    review = {key: old['review'][key] for key in ('coverage', 'source_quality_uncertainty', 'discrepancies', 'unreviewed_residuals')}
    review.update(reviewer='agent:charnock-vol1-header-status-review', reviewed_at=now)
    review_path = save(stage, EVIDENCE / 'review.json', common | review | dict(scope=old['scope']['declared'],
        review_basis='Original dated source review retained unchanged. Current review covers exact status correction, complete body equivalence, retained source/identity/scope conservation, explicit successor revision and unchanged human/rights/publication qualifications.',
        dated_original_review=old['review']['report']))
    decision = json.loads(canonical(old['decision']))
    decision['agent_assessment'].update(actor=review['reviewer'], assessed_at=now)
    record = build_acceptance_record(stage, identity=old['identity'], candidate_path=candidate,
        source_accounting_path=account_path, scope=old['scope'], technical=technical,
        review=review | dict(report_path=review_path), representation_revision=REVISION, decision=decision)
    acceptance = stage / EDITION / 'acceptance.json'
    write_acceptance(io_path(acceptance), record)
    validate_acceptance(acceptance, root=stage)
    master = put(stage, EDITION / 'master.tei.xml', bound)
    record['promotion'].update(status='promoted', promoted_at=now, master=make_file_binding(stage, master))
    write_acceptance(io_path(acceptance), record)
    state = read(stage / WORK / 'state.json')
    target = next(item for item in state['targets'] if item['target_type'] == 'edition' and item['target_id'] == EDITION_ID)
    if target['stage'] != 'accepted':
        raise PipelineError('Existing accepted state required')
    target['updated_at'] = now
    save(stage, WORK / 'state.json', state)
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / 'state.json', root=stage)
    previous_projection = projection(ROOT)
    current_projection = projection(stage)
    require_conserved_rows(previous_projection['rows'], current_projection['rows'])
    save(stage, EVIDENCE / 'superseded-actual-master-projection.json', previous_projection)
    save(stage, EVIDENCE / 'actual-master-projection.json', current_projection)
    after = _files(stage / WORK)
    _replacement_changes_are_scoped(before, after)
    receipt = dict(contract='ocd-charnock-vol1-header-repair-stage-v1', status='staged-only',
        work_id=WORK_ID, stage_root=stage.as_posix(), before=before, after=after,
        source_bindings=source_bindings, runtime_bindings=runtime_bindings(), source_sha256=SOURCE_SHA,
        old_master_sha256=OLD_MASTER, old_acceptance_sha256=OLD_ACCEPTANCE,
        master_sha256=digest(master), acceptance_sha256=digest(acceptance), representation_revision=REVISION,
        body_proof=proof, original_decision=old['decision'], original_scope=old['scope'],
        projection_rows=2, projection_body_rows_unchanged=True,
        projection_row_changes=['representation_revision only'], independent_verifier_errors=[],
        convenience_dispatcher='Shared prose convenience wrapper is not claimed; supported native_documents seam used.',
        installation='not-performed')
    save(stage, Path('stage-receipt.json'), receipt)
    if _files(ROOT / WORK) != before:
        raise PipelineError('Canonical preimages changed during preparation')
    return receipt


def preflight(stage, pin, *, root=ROOT):
    stage, root = stage.resolve(strict=True), root.resolve(strict=True)
    if root != ROOT.resolve(strict=True):
        if not root.name.startswith('c1-h-fixture') or (root / '.git').exists() or (root / '.ocd-storage.json').exists() or (root / FIXTURE_MARKER).read_text(encoding='utf-8') != 'fixture-only\n':
            raise PipelineError('Bounded explicit Charnock header fixture required')
    if stage.parent != (LIBRARY / 'candidate-reviews').resolve(strict=True) or not stage.name.startswith('c1-h') or root == stage:
        raise PipelineError('Bounded Charnock header stage required')
    if digest(stage / 'stage-receipt.json') != pin:
        raise PipelineError('Header stage receipt differs')
    receipt = read(stage / 'stage-receipt.json')
    if receipt['contract'] != 'ocd-charnock-vol1-header-repair-stage-v1' or receipt['status'] != 'staged-only' or receipt['stage_root'] != stage.as_posix() or receipt['work_id'] != WORK_ID or receipt['representation_revision'] != REVISION or receipt['installation'] != 'not-performed':
        raise PipelineError('Header receipt identity/route differs')
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != receipt['before'] or len(before) != 23 or after != receipt['after']:
        raise PipelineError('All23 canonical preimages or complete successor changed')
    if receipt['runtime_bindings'] != runtime_bindings():
        raise PipelineError('Complete current runtime/schema/scripture authority freeze differs')
    for relative, pin_value in receipt['runtime_bindings'].items():
        if digest(ROOT / relative) != pin_value:
            raise PipelineError('Runtime/schema changed: ' + relative)
    for relative, pin_value in receipt['source_bindings'].items():
        if digest(root / relative) != pin_value:
            raise PipelineError('Source/current authority changed: ' + relative)
        # Acceptance/master/state are intentionally superseded; every other authority is identical in stage.
        if Path(relative).name not in {'master.tei.xml', 'acceptance.json', 'state.json'} and digest(stage / relative) != pin_value:
            raise PipelineError('Staged source authority differs: ' + relative)
    _replacement_changes_are_scoped(before, after)
    mutable = {(EDITION / name).relative_to(WORK).as_posix() for name in ('master.tei.xml', 'acceptance.json')} | {'state.json'}
    if set(before) - set(after) or any(after[path] != before[path] for path in before if path not in mutable):
        raise PipelineError('Replacement changes existing metadata/source/evidence')
    if any(not path.startswith(EVIDENCE.relative_to(WORK).as_posix() + '/') for path in set(after) - set(before)):
        raise PipelineError('Undeclared evidence addition')
    old = validate_acceptance(root / EDITION / 'acceptance.json', root=root)
    new = validate_acceptance(stage / EDITION / 'acceptance.json', root=stage)
    validate_state(stage / WORK / 'state.json', root=stage)
    if digest(root / EDITION / 'master.tei.xml') != OLD_MASTER or digest(root / EDITION / 'acceptance.json') != OLD_ACCEPTANCE:
        raise PipelineError('Pinned superseded accepted artifacts differ')
    if new['identity'] != old['identity'] or new['scope'] != old['scope'] or old['scope'] != receipt['original_scope'] or old['decision'] != receipt['original_decision']:
        raise PipelineError('Acceptance identities, source scope, or original decision differ')
    expected_decision = json.loads(canonical(old['decision']))
    expected_decision['agent_assessment'].update(actor=new['review']['reviewer'], assessed_at=new['review']['reviewed_at'])
    if new['decision'] != expected_decision or new['representation_revision'] != REVISION:
        raise PipelineError('Successor changes decision qualifications')
    original = io_path(root / EDITION / 'master.tei.xml').read_bytes()
    expected, proof = repaired(original)
    if io_path(stage / EDITION / 'master.tei.xml').read_bytes() != expected or digest(stage / EDITION / 'master.tei.xml') != receipt['master_sha256'] or digest(stage / EDITION / 'acceptance.json') != receipt['acceptance_sha256']:
        raise PipelineError('Exact header-only derivative/bindings differ')
    if validate_file(io_path(stage / EDITION / 'master.tei.xml')):
        raise PipelineError('Successor P5 failure')
    _validate_promoted_tree(root, root / WORK, work_id=WORK_ID)
    _validate_promoted_tree(stage, stage / WORK, work_id=WORK_ID)
    _validate_state_transition(root / WORK, stage / WORK, existed=True, replacement=True,
        accepted_evidence_by_edition={EDITION_ID: ((EDITION / 'master.tei.xml').as_posix(), (EDITION / 'acceptance.json').as_posix())})
    current = projection(stage)
    require_conserved_rows(read(stage / EVIDENCE / 'superseded-actual-master-projection.json')['rows'], current['rows'])
    if current != read(stage / EVIDENCE / 'actual-master-projection.json'):
        raise PipelineError('Exact actual-master projection differs')
    return dict(status='ready-for-review', work_id=WORK_ID, before_files=len(before), after_files=len(after),
        receipt_sha256=pin, projection_rows=2, text_body_byte_identical=proof['text_body_byte_identical'])


def install(stage, pin, *, root=ROOT, fail_at=None):
    stage, root = stage.resolve(strict=True), root.resolve(strict=True)
    target, source = root / WORK, stage / WORK
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda value: value.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(stage, pin, root=root)
        receipt = read(stage / 'stage-receipt.json')
        def checkpoint(phase):
            if phase == 'after-validated':
                if _files(target) != receipt['after']:
                    raise PipelineError('Installed complete header successor differs')
                validate_acceptance(root / EDITION / 'acceptance.json', root=root)
                validate_state(root / WORK / 'state.json', root=root)
                if projection(root) != read(stage / EVIDENCE / 'actual-master-projection.json'):
                    raise PipelineError('Canonical accepted master projection differs')
            if fail_at is not None:
                fail_at(phase)
        return _commit_generation(root, target, source, work_id=WORK_ID, before=receipt['before'], after=receipt['after'],
            existed=True, replacement=True, operation_kind='charnock-vol1-publication-status-header-repair',
            result_status='replaced-and-validated', accepted_editions=1, fail_at=checkpoint)


def rollback_proof(stage, pin, fixture):
    if fixture.exists() or fixture.parent.resolve(strict=True) != (LIBRARY / 'candidate-reviews').resolve(strict=True) or not fixture.name.startswith('c1-h-fixture'):
        raise PipelineError('Fresh bounded fixture required')
    receipt = read(stage / 'stage-receipt.json')
    fixture.mkdir()
    put(fixture, Path(FIXTURE_MARKER), b'fixture-only\n')
    for relative in receipt['source_bindings']:
        put(fixture, Path(relative), io_path(ROOT / relative).read_bytes())
    for relative in receipt['before']:
        put(fixture, WORK / relative, io_path(ROOT / WORK / relative).read_bytes())
    try:
        preflight(stage, '0' * 64, root=fixture)
    except PipelineError as error:
        if str(error) != 'Header stage receipt differs':
            raise
    else:
        raise PipelineError('Wrong receipt accepted')
    def fail(phase):
        if phase == 'after-new-live':
            if _files(fixture / WORK) != receipt['after']:
                raise PipelineError('Injected live successor differs')
            raise RuntimeError('Charnock header rollback injected after-new-live')
    try:
        install(stage, pin, root=fixture, fail_at=fail)
    except RuntimeError as error:
        if str(error) != 'Charnock header rollback injected after-new-live':
            raise
    else:
        raise PipelineError('Rollback injection not reached')
    if _files(fixture / WORK) != receipt['before'] or _files(ROOT / WORK) != receipt['before']:
        raise PipelineError('Complete fixture rollback/canonical preimages differ')
    result = install(stage, pin, root=fixture)
    if _files(fixture / WORK) != receipt['after'] or _files(ROOT / WORK) != receipt['before']:
        raise PipelineError('Successful fixture/canonical conservation differs')
    journals = {path.as_posix(): dict(sha256=digest(path), phase=read(path)['phase']) for path in (fixture / '.tmp_audit').glob('accepted-install-*/operation.json')}
    if sorted(value['phase'] for value in journals.values()) != ['complete', 'rolled-back']:
        raise PipelineError('Fixture journals differ')
    value = dict(status='pass', stage=stage.as_posix(), stage_receipt_sha256=pin, fixture=fixture.as_posix(),
        wrong_receipt_rejected=True, after_new_live_complete_successor_observed=True, exact23_preimage_rollback=True,
        successful_fixture_install=result, complete_successor_matches=True, journals=journals, canonical_install=False)
    save(LOG, Path('header-repair-rollback-proof.json'), value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--expected-sha256')
    parser.add_argument('--rollback-fixture', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        if args.apply or args.rollback_fixture or args.expected_sha256:
            raise PipelineError('Prepare cannot apply or replace an existing stage')
        value = prepare(args.stage)
        print(json.dumps(dict(status=value['status'], receipt_sha256=digest(args.stage / 'stage-receipt.json'), master_sha256=value['master_sha256'], after_files=len(value['after']))))
        return
    if not args.expected_sha256:
        raise PipelineError('Frozen stage receipt pin required')
    value = preflight(args.stage, args.expected_sha256)
    if args.rollback_fixture:
        value['rollback'] = rollback_proof(args.stage, args.expected_sha256, args.rollback_fixture)
    if args.apply:
        value['installation'] = install(args.stage, args.expected_sha256)
    print(json.dumps(value))


if __name__ == '__main__':
    main()
