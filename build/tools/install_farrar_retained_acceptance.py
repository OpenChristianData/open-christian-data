"""Pinned read-only preflight or atomic guarded installation for Farrar only."""
from __future__ import annotations

import argparse
import json
from contextlib import ExitStack
from datetime import datetime
import sys
from pathlib import Path

from build.tools.stage_farrar_retained_acceptance import ROOT, LOG, LIBRARY, WORK, WORK_ID, EVIDENCE, MEMBERS, SOURCE_DIR, CANDIDATES, edition_path, dependencies, projection_gate, read, sha, bind_master, declared_scope, projection_signature
from build.tei.farrar_retained_native_oracle import _oracle as oracle
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.path_io import resolve_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage, validate
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON
from ocd_kernel.tei.install_accepted import _files, _io_path, _commit_generation


def digest(path):
    return sha(_io_path(path).read_bytes())


def preflight(stage, receipt_sha256, *, root=ROOT):
    root = root.resolve(strict=True); stage = stage.resolve(strict=True)
    fixture = root != ROOT.resolve(strict=True)
    if fixture:
        expected_fixture=(ROOT/'.tmp_audit/farrar-retained-install-fixture-20261003-v2').resolve(strict=True)
        if root!=expected_fixture:raise PipelineError('Farrar fixture root exceeds exact task boundary')
        marker = root / '.ocd-farrar-retained-install-fixture'
        if not marker.is_file() or marker.read_text() != 'fixture-only\n': raise PipelineError('Farrar root override requires exact fixture marker')
    if root == stage or root in stage.parents or stage in root.parents:raise PipelineError('Farrar stage/root containment is forbidden in both directions')
    if stage.parent != (LIBRARY / 'candidate-reviews').resolve(strict=True) or not stage.name.startswith('farrar-s-') or root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError('Farrar stage/root boundary differs')
    if len(receipt_sha256) != 64 or any(c not in '0123456789abcdef' for c in receipt_sha256) or digest(stage / 'stage-receipt.json') != receipt_sha256:
        raise PipelineError('Farrar caller receipt pin differs')
    receipt = read(stage / 'stage-receipt.json')
    if receipt.get('contract') != 'ocd-farrar-retained-external-stage-v1' or receipt.get('work_id') != WORK_ID or receipt.get('status') != 'staged-only' or receipt.get('stage_root') != stage.as_posix() or receipt.get('included_volumes') != 3 or receipt.get('acquired_volumes') != 3 or receipt.get('accepted_scope_kind') != 'edition' or receipt.get('projection_category') != 'commentary' or receipt.get('installation') != 'not-performed':
        raise PipelineError('Farrar receipt identity or finite three-edition scope differs')
    for item in receipt['external_runtime_files']:
        path=Path(item['path'])
        if not path.is_absolute() or _io_path(path).stat().st_size!=item['bytes'] or digest(path)!=item['sha256']:raise PipelineError('Farrar observed external runtime bytes drifted: '+str(path))
    before = _files(root / WORK); after = _files(stage / WORK)
    if before != receipt['before'] or after != receipt['after']:
        raise PipelineError('Farrar complete canonical preimage or frozen stage generation changed')
    for relative in before:
        if relative not in {'work.json', 'state.json'} and after.get(relative) != before[relative]: raise PipelineError('Farrar retained authority changed: ' + relative)
    expected_work = read(root / WORK / 'work.json')
    expected_state = read(root / WORK / 'state.json'); staged_state = read(stage / WORK / 'state.json')
    allowed_additions = set()
    for spec in MEMBERS.values():
        edition = edition_path(spec)
        if _io_path(root / edition / 'master.tei.xml').exists() or _io_path(root / edition / 'acceptance.json').exists(): raise PipelineError('Farrar canonical accepted authority already exists; no replacement')
        form = next(x for x in expected_work['textual_forms'] if x['textual_form_id'] == spec['form'])
        entry = next(x for x in form['editions'] if x['edition_id'] == spec['edition'])
        if entry.get('category') is not None: raise PipelineError('Farrar work metadata preimage differs')
        entry['category'] = 'commentary'
        old = next(x for x in expected_state['targets'] if x['target_type'] == 'edition' and x['target_id'] == spec['edition'])
        new = next(x for x in staged_state['targets'] if x['target_type'] == 'edition' and x['target_id'] == spec['edition'])
        if old['stage'] != 'acquired' or new['stage'] != 'accepted' or new['reason']!=PROMOTED_MASTER_REASON or new['evidence'] != old['evidence'] + [(edition / 'master.tei.xml').as_posix(), (edition / 'acceptance.json').as_posix()]: raise PipelineError('Farrar acquired-to-accepted edition transition differs')
        old.update(stage=new['stage'], reason=new['reason'], updated_at=new['updated_at'], evidence=new['evidence'])
        allowed_additions.update({(edition / name).relative_to(WORK).as_posix() for name in ['master.tei.xml', 'acceptance.json']})
    if expected_work != read(stage / WORK / 'work.json') or expected_state != staged_state:
        raise PipelineError('Farrar canonical delta exceeds genre and three accepted editions')
    prefix = EVIDENCE.relative_to(WORK).as_posix() + '/'
    if any(path not in allowed_additions and not path.startswith(prefix) for path in set(after) - set(before)):
        raise PipelineError('Farrar staged work additions exceed declared boundary')
    dep = dependencies(root)
    observed = {path.as_posix(): digest(root / path) for path in sorted(dep)}
    if observed != receipt.get('dependency_files'): raise PipelineError('Farrar pinned dependency set/code/source/schema/proofs changed')
    for path in dep:
        if digest(stage / path) != observed[path.as_posix()]: raise PipelineError('Farrar staged dependency differs: ' + str(path))
    if [x['member_id'] for x in receipt['volumes']] != list(MEMBERS): raise PipelineError('Farrar ordered three-edition receipt differs')
    for member_id, spec in MEMBERS.items():
        row = next(x for x in receipt['volumes'] if x['member_id'] == member_id)
        edition = edition_path(spec); lane = EVIDENCE / member_id
        authority_root = ROOT if fixture else root
        manifest = SourceManifest.load(authority_root / SOURCE_DIR / (member_id + '.source-manifest.json'), repository_root=authority_root)
        package = CandidatePackage.load(stage / lane / 'inputs/package')
        package.verify_integrity()
        if package.sha256 != CandidatePackage.load(CANDIDATES / member_id / 'package').sha256 or package.sha256 != row['candidate_package_sha256'] or manifest.sha256 != row['source_manifest_sha256'] or row['source_sha256'] != spec['sha256']:
            raise PipelineError('Farrar source/candidate receipt bindings differ')
        report = validate(manifest, package, oracle)
        if report.status != 'pass' or report.sha256 != row['oracle_report_sha256']: raise PipelineError('Farrar fresh complete raw-source oracle differs')
        original = package.member_bytes('content.tei.xml'); master = _io_path(stage / edition / 'master.tei.xml').read_bytes()
        if original.split(b'</teiHeader>', 1)[1] != master.split(b'</teiHeader>', 1)[1] or digest(stage / edition / 'master.tei.xml') != row['master_sha256'] or digest(stage / edition / 'acceptance.json') != row['acceptance_sha256']:
            raise PipelineError('Farrar reviewed readable body or acceptance changed')
        canonical_work=read(root/WORK/'work.json');form=next(f for f in canonical_work['textual_forms'] if f['textual_form_id']==spec['form']);entry=next(e for e in form['editions'] if e['edition_id']==spec['edition'])
        acquisition=read(root/edition/'acquisitions'/(spec['acquisition']+'.json'))
        expected_identity=dict(work_id=WORK_ID,textual_form_id=spec['form'],edition_id=spec['edition'],acquisition_id=spec['acquisition'])
        expected_source={key:acquisition[key] for key in ('source_path','source_sha256','source_bytes','source_scope')}
        revision=row['representation_revision'];expected_revision=dict(id=member_id+'-retained-current-20261003-v1',date=datetime.fromisoformat(receipt['staged_at'].replace('Z','+00:00')).date().isoformat(),note='Readable faithful retained volume; original source order and literal identities preserved.')
        if revision!=expected_revision or validate_acceptance(stage/edition/'acceptance.json',root=stage)['representation_revision']!=expected_revision:raise PipelineError('Farrar exact representation revision differs')
        if master!=_io_path(stage/lane/'candidate.tei.xml').read_bytes() or master!=bind_master(original,identity=expected_identity,source=expected_source,source_url=acquisition['url'],declared_scope=declared_scope(entry),revision=expected_revision):raise PipelineError('Farrar exact ordered reviewed header recomputation differs')
        accounting = read(stage / lane / 'source-accounting.json')
        if accounting['full_source_elements'] != spec['elements'] or accounting['readable_source_elements'] != spec['body_elements'] - 1 or accounting['accepted_scope']['kind'] != 'edition' or accounting['source_sha256'] != spec['sha256'] or accounting['expected_members'] != [dict(path=spec['path'], position=1)] or accounting['excluded_members'] or accounting['missing_members'] or accounting['unknown_members'] or accounting['complete_acquired_work_volumes'] != 3:
            raise PipelineError('Farrar explicit full volume and acquired work accounting differs')
        acceptance = stage / edition / 'acceptance.json'; accepted = validate_acceptance(acceptance, root=stage)
        if accepted['promotion']['status'] != 'promoted' or accepted['identity']['work_id'] != WORK_ID or accepted['identity']['edition_id'] != spec['edition']: raise PipelineError('Farrar accepted authority identity differs')
        if projection_signature(projection_gate(stage, acceptance)) != projection_signature(row['projection_gate']): raise PipelineError('Farrar separate actual commentary projection gate changed')
    validate_state(stage / WORK / 'state.json', root=stage)
    return dict(status='ready-for-parent-review', work_id=WORK_ID, receipt_sha256=receipt_sha256, before_files=len(before), after_files=len(after), included_volumes=3, scope_kind='edition', dependency_files=len(dep), projection_gate={x['member_id']: x['projection_gate'] for x in receipt['volumes']})


def loaded_code_pins(receipt):
    observed={}
    bound_paths={resolve_path(ROOT/relative,strict=True):(relative,pin) for relative,pin in receipt['dependency_files'].items()}
    for module in sys.modules.copy().values():
        filename=getattr(module,'__file__',None)
        if not filename:continue
        path=resolve_path(Path(filename),strict=True)
        if path.is_relative_to(resolve_path(ROOT,strict=True)) or path.is_relative_to(resolve_path(LIBRARY,strict=True)):
            binding=bound_paths.get(path)
            if binding is None:raise PipelineError('Farrar unexpected executed first-party dependency: '+path.as_posix())
            relative,pin=binding
            if digest(path)!=pin:raise PipelineError('Farrar executed code drifted: '+relative)
            observed[relative]=pin
    for item in receipt['external_runtime_files']:
        if _io_path(Path(item['path'])).stat().st_size!=item['bytes'] or digest(Path(item['path']))!=item['sha256']:raise PipelineError('Farrar late external runtime bytes drifted: '+item['path'])
    if not observed:raise PipelineError('Farrar actual loaded execution code census absent')
    return observed


def install(stage, receipt_sha256, *, root=ROOT, fail_at=None):
    root = root.resolve(strict=True); stage = stage.resolve(strict=True); target = root / WORK; source = stage / WORK
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda x: x.as_posix()): locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(stage, receipt_sha256, root=root); receipt = read(stage / 'stage-receipt.json')
        runtime_pins={};projection_readbacks={}
        def checkpoint(point):
            if point == 'after-validated':
                if _files(target) != receipt['after']: raise PipelineError('Farrar installed generation differs')
                for member_id, spec in MEMBERS.items():
                    acceptance = root / edition_path(spec) / 'acceptance.json'; validate_acceptance(acceptance, root=root)
                    row = next(x for x in receipt['volumes'] if x['member_id'] == member_id)
                    gate=projection_gate(root, acceptance)
                    projection_readbacks[member_id]=gate
                    if projection_signature(gate) != projection_signature(row['projection_gate']): raise PipelineError('Farrar installed projection gate differs')
                validate_state(target / 'state.json', root=root)
                runtime_pins.update(loaded_code_pins(receipt))
            if fail_at is not None: fail_at(point)
        result = _commit_generation(root, target, source, work_id=WORK_ID, before=receipt['before'], after=receipt['after'], existed=True, replacement=False,
            operation_kind='farrar-existing-three-edition-completion-install', result_status='installed-and-validated', accepted_editions=3, fail_at=checkpoint)
    result['after_validated_loaded_code_pins']=runtime_pins
    result['actual_commentary_projection_readback']=projection_readbacks
    result['late_execution_dependency_gate']='pass'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('stage', type=Path); parser.add_argument('--expected-sha256', required=True); parser.add_argument('--apply', action='store_true'); args = parser.parse_args()
    result = preflight(args.stage, args.expected_sha256)
    if args.apply: result['installation'] = install(args.stage, args.expected_sha256)
    print(json.dumps(result, sort_keys=True))
