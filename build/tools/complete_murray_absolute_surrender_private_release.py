"""Prepare the complete accepted native Murray whole collection privately."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from ocd_kernel.library._common import io_path, io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.tei.acceptance import _validate_acceptance_for_work
from ocd_kernel.projection.categories.prose import project_accepted_prose, _prose_validator
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2

WORK = 'murray-absolute-surrender'
BASE = ROOT / 'library/works' / WORK
PUB = BASE / 'publication'
CURRENT = PUB / 'private-offline-20261001'
LOG = ROOT / 'reports/_logs/murray-absolute-surrender-offline-release-20261001-v1'
RELEASE = LOG / 'release'
SCHEMAS = ['schemas/v2/' + name + '.schema.json' for name in (
    'work', 'state', 'acquisition', 'acceptance', 'agent-assessment', 'projection-receipt',
    'release-selection', 'release-report', 'public-row', 'native-content', 'categories/prose')]


def digest(path):
    return sha256(io_path(path).read_bytes()).hexdigest()


def save(name, value):
    path = LOG / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


def process(name, argv):
    try:
        result = subprocess.run(argv, cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8')
    except subprocess.CalledProcessError as exc:
        save(name + '.command.json', {'argv': argv, 'exit_code': exc.returncode, 'stdout': exc.stdout, 'stderr': exc.stderr})
        raise
    save(name + '.command.json', {'argv': argv, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
    return result


def command(name, module, args):
    wrapper = ('import sys; sys.dont_write_bytecode=True\n'
               'from ocd_kernel.library.identities import cached_edition_lookups\n'
               f'from {module} import main\n'
               'with cached_edition_lookups():\n raise SystemExit(main())')
    result = process(name, [sys.executable, '-c', wrapper, *args])
    if name != 'assembly':
        parsed = json.loads(result.stdout)
        save(name + '.json', parsed)
        if parsed.get('status') != 'pass':
            raise ValueError(parsed)


def main():
    # A coordinator-approved stable shared implementation is required before execution.
    freeze_path = PUB / 'runtime-freeze.json'
    freeze = json.loads(freeze_path.read_bytes())
    for rel, expected in freeze.items():
        if digest(ROOT / rel) != expected:
            raise ValueError('Shared freeze mismatch: ' + rel)
    LOG.mkdir(parents=True, exist_ok=False)
    CURRENT.mkdir(parents=True, exist_ok=False)
    bound = {p.relative_to(ROOT).as_posix(): digest(p) for p in io_glob(BASE, '**/*')
             if io_path(p).is_file() and PUB not in p.parents}
    bound.update(freeze)
    for rel in ['docs/sources/ccel-permission.md',
                'build/tools/complete_murray_absolute_surrender_private_release.py',
                'library/works/murray-absolute-surrender/publication/runtime-freeze.json',
                'library/works/murray-absolute-surrender/publication/selection-draft.json']:
        bound[rel] = digest(ROOT / rel)
    for dirname in ['murray-absolute-surrender-reconciliation-20261001-v1']:
        for p in io_glob(ROOT / 'reports/_logs' / dirname, '**/*.json'):
            bound[p.relative_to(ROOT).as_posix()] = digest(p)
    for pattern in ['build/tei/murray_absolute_surrender_current*.py','build/tools/*murray_absolute_surrender_current.py']:
        for p in ROOT.glob(pattern):bound[p.relative_to(ROOT).as_posix()]=digest(p)
    for p in (ROOT/'sources/ccel-murray-surrender-current/murray-absolute-surrender').glob('*'):
        if p.is_file():bound[p.relative_to(ROOT).as_posix()]=digest(p)
    for rel in ['ocd_kernel/reconstruction/contract.py','build/tei/murray_absolute_surrender_reconstruction.py','build/tei/murray_absolute_surrender_oracle.py','sources/structured-text/murray-absolute-surrender/config.json']:
        bound[rel]=digest(ROOT/rel)
    schemas = {rel: digest(ROOT / rel) for rel in SCHEMAS}
    save('schemas-before.json', schemas)
    selection = json.loads((PUB / 'selection-draft.json').read_bytes())
    assert len(selection['items']) == 1
    acceptances = sorted(io_glob(BASE, '**/acceptance.json'))
    assert len(acceptances) == 1
    selected_paths = {item['acceptance_path'] for item in selection['items']}
    assert selected_paths == {p.relative_to(ROOT).as_posix() for p in acceptances}
    projections = []
    primary = []
    with cached_edition_lookups():
        for path in acceptances:
            a = _validate_acceptance_for_work(path, root=ROOT, work_id=WORK)
            edition = a['identity']['edition_id']
            master = ROOT / a['promotion']['master']['path']
            source = ROOT / a['source']['source_path']
            assert digest(source) == a['source']['source_sha256']
            assert io_path(source).stat().st_size == a['source']['source_bytes']
            bound[source.relative_to(ROOT).as_posix()] = digest(source)
            for member in a['scope']['included_members']:
                p = ROOT / member['path']
                assert digest(p) == member['sha256'] and io_path(p).stat().st_size == member['bytes']
                bound[member['path']] = digest(p)
            # Preserve separately declared retained support bindings without acquiring images.
            if a['source'].get('source_kind') == 'retained-member-set':
                member_set = json.loads(io_path(source).read_bytes())
                def bind_members(value):
                    if isinstance(value, dict):
                        if isinstance(value.get('path'), str) and value.get('sha256') and value['path'].startswith('raw/'):
                            p = ROOT / value['path']
                            assert digest(p) == value['sha256']
                            bound[value['path']] = digest(p)
                        for child in value.values():
                            bind_members(child)
                    elif isinstance(value, list):
                        for child in value:
                            bind_members(child)
                bind_members(member_set)
            projection = project_accepted_prose(ROOT, acceptance_path=path)
            save(edition + '/actual-master-projection.json', projection)
            assert projection['receipt']['master_sha256'] == digest(master)
            errors = [str(e) for row in projection['rows'] for e in _prose_validator().iter_errors(row)]
            save(edition + '/public-validation.json', {'status': 'fail' if errors else 'pass', 'errors': errors, 'rows': len(projection['rows'])})
            if errors:
                raise ValueError(errors)
            save(edition + '/projection-master-hash-scope.json', {
                'status': 'pass', 'accepted_master_sha256': digest(master),
                'projection_document_sha256': projection['receipt']['master_sha256'],
                'qualification': 'Full accepted master projected; no synthetic source-selected projection document.'})
            projections.append((path, master, edition, projection))
            primary.append({'edition_id': edition, 'acceptance_path': path.relative_to(ROOT).as_posix(),
                'acceptance_sha256': digest(path), 'master_sha256': digest(master),
                'source_sha256': digest(source), 'accepted_scope': a['scope']['declared'],
                'accepted_review': a['review'], 'reconstruction_performed': True})
            print('Projected complete accepted edition ' + edition, flush=True)
    save('accepted-editions.json', primary)
    independent = '''import sys,json,hashlib,os
from pathlib import Path
sys.dont_write_bytecode=True
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import verify_accepted_prose
import ocd_kernel.projection.native_content as producer
def unavailable(*args,**kwargs): raise AssertionError('producer/renderer invoked by checker')
producer.project_content=unavailable
producer.readable_content=unavailable
root,acceptance,projected=map(Path,sys.argv[1:])
raw=projected.read_bytes();p=json.loads(raw)
with cached_edition_lookups():
 errors=verify_accepted_prose(root,acceptance_path=acceptance,rows=p['rows'],receipt=p['receipt'])
print(json.dumps({'status':'fail' if errors else 'pass','errors':errors,'pid':os.getpid(),'projection_sha256':hashlib.sha256(raw).hexdigest(),'producer_disabled':True}))
raise SystemExit(bool(errors))
'''
    summaries = []
    for path, master, edition, projection in projections:
        projected = LOG / edition / 'actual-master-projection.json'
        result = process(edition + '/independent-projection', [sys.executable, '-c', independent, str(ROOT), str(path), str(projected)])
        checked = json.loads(result.stdout)
        assert checked['status'] == 'pass' and checked['projection_sha256'] == digest(projected)
        checked.update({'edition_id': edition, 'acceptance_sha256': digest(path), 'master_sha256': digest(master), 'schemas': schemas})
        save(edition + '/independent-projection-linkage.json', checked)
        summaries.append({'edition_id': edition, 'acceptance_sha256': digest(path), 'master_sha256': digest(master),
            'saved_projection_sha256': digest(projected), 'independent_linkage_sha256': digest(LOG / edition / 'independent-projection-linkage.json'),
            'rows': len(projection['rows']), 'characters': sum(len(r['text']) for r in projection['rows'])})
    notice_results = []
    for item in selection['items']:
        texts = notice_texts_for_item(ROOT, item, ROOT / item['acceptance_path'])
        notice_results.append({'item_id': item['item_id'], 'bound_notice_count': len(texts)})
        for notice in item['public_notices']:
            for key in ['source_path', 'notice_path']:
                bound[notice[key]] = digest(ROOT / notice[key])
    save('notice-preflight.json', {'status': 'pass', 'items': notice_results})
    selected_path = CURRENT / 'selection.json'
    selected_path.write_text(json.dumps(selection, indent=2) + '\n', encoding='utf-8')
    save('selection.json', selection)
    bound[selected_path.relative_to(ROOT).as_posix()] = digest(selected_path)
    save('authority-before.json', bound)
    common = ['--root', str(ROOT), '--selection', str(selected_path)]
    print('Assembling the complete retained work in one private release', flush=True)
    command('assembly', 'build.scripts.export_huggingface', [*common, '--output', str(RELEASE)])
    save('assembly.json', json.loads((RELEASE / 'internal/release-report.json').read_bytes()))
    with cached_edition_lookups():
        checked = verify_release_v2(ROOT, RELEASE, selection=selection)
    save('independent-verification.json', checked)
    if checked['status'] != 'pass':
        raise ValueError(checked)
    args = [*common, '--release', str(RELEASE)]
    command('separate-process-verification', 'build.tools.check_hf_release', args)
    command('statistics', 'build.tools.report_release_stats', args)
    command('readers', 'build.tools.check_release_reader', [*args, '--output', str(LOG / 'readers.json')])
    after = {rel: digest(ROOT / rel) for rel in bound}
    schema_after = {rel: digest(ROOT / rel) for rel in SCHEMAS}
    save('authority-after.json', after)
    save('schema-stability.json', {'status': 'pass' if schema_after == schemas else 'fail', 'before': schemas, 'after': schema_after})
    if after != bound or schemas != schema_after:
        raise ValueError('Authority or schema drift during release')
    release_files = {p.relative_to(RELEASE).as_posix(): digest(p) for p in RELEASE.rglob('*') if p.is_file()}
    save('release-file-hashes.json', release_files)
    completion = {'status': 'technical-private-offline-release-pass', 'checked_at': datetime.now(timezone.utc).isoformat(),
        'work_id': WORK, 'editions': summaries, 'edition_count': 1,
        'rows': sum(e['rows'] for e in summaries), 'characters': sum(e['characters'] for e in summaries),
        'statistics': json.loads((LOG / 'statistics.json').read_bytes())['total'],
        'authority_unchanged': True, 'bound_schemas_stable': True, 'authority_binding_count': len(bound),
        'schema_binding_count': len(schemas), 'release_file_count': len(release_files),
        'evidence_physical': str(LOG.resolve()), 'publication_performed': False, 'reconstruction_performed': True,
        'remaining': ['human acceptance', 'exhaustive visual/proofreading review', 'print witness/collation',
                      'rights clearance', 'global release selection', 'publication authorization']}
    save('completion.json', completion)
    (CURRENT / 'completion.json').write_text(json.dumps(completion, indent=2) + '\n', encoding='utf-8')
    readme=(f"# Absolute Surrender: private preparation complete\n\n"
        f"The accepted complete retained electronic collection produces {completion['rows']} records, "
        f"{completion['characters']:,} text characters and {completion['statistics']['uncompressed_bytes']:,} uncompressed bytes. "
        "Actual-master public validation, saved producer-disabled independent projection verification, canonical private assembly, "
        "both release verifiers, statistics and normal/streaming readers pass. Current authority and eleven schema hashes stay unchanged.\n\n"
        "The entire existing work includes own title page, nine source-defined addresses and integral scripture index. "
        "Native historical TEI and complete954source-accountability were reproduced unchanged, with renewed bound scope and current evidence. "
        "Andrew Murray is the own author; Claude King scanned/corrected/transcribed the electronic witness. Tim Perrine is credited only for its staff description. "
        "Own Moody Press - Chicago/1895 and first-published statement remain literal qualified source claims. The source explicitly attests light language edits and added scripture references. "
        "Inherited Marshall Brothers London metadata is retained as conflicting historical evidence, not current factual print credit. "
        "Provider Public Domain statement and CCEL files/formatting-sale restriction are visible; independent rights clearance is unclaimed.\n\n"
        "Accepted master and projection-document hashes match; exact saved projection bytes are independently SHA-bound. "
        "No source/body repair, new work IDs, acquisition, shared runtime change or public publication was performed. "
        "Human acceptance, current visual proofreading, exact print equivalence, rights clearance, final global selection and publication remain separate.\n")
    (LOG / 'README.md').write_text(readme, encoding='utf-8', newline='\n')
    (CURRENT / 'README.md').write_text(readme, encoding='utf-8', newline='\n')
    for p in [CURRENT / 'completion.json', CURRENT / 'README.md']:
        after[p.relative_to(ROOT).as_posix()] = digest(p)
    save('friction-notes.json', {'work_id': WORK, 'root_docs_owner': True, 'no_shared_gap': True,
        'observations': ['Durable exact candidate nested candidate/package found; two recorded temporary successor homes absent, not a reconstruction gap.',
                         'Native historical complete TEI and954source-accountability reproduced unchanged, renewed work-bound proofs and whole electronic collection scope.',
                         'Source light language editing/scripture additions distinguish this electronic witness from unassessed print equivalence; nine addresses remain within one existing work.',
                         'Supported single scoped retained-member source binding avoids acquisition summary mutation.',
                         'Own Moody Press Chicago source claim does not substantiate inherited Marshall Brothers London config; historical conflict retained, not adopted.',
                         'Current runtime files/schema bound directly after coordinator stable correction-choice policy freeze; no sibling authority or mutable explanatory receipt pins.']})
    names = ['completion.json', 'accepted-editions.json', 'selection.json', 'notice-preflight.json', 'assembly.json',
             'independent-verification.json', 'separate-process-verification.json', 'statistics.json', 'readers.json',
             'authority-before.json', 'authority-after.json', 'schema-stability.json', 'release-file-hashes.json', 'README.md', 'friction-notes.json']
    for _, _, edition, _ in projections:
        names.extend(edition + '/' + name for name in ['actual-master-projection.json', 'public-validation.json',
                     'projection-master-hash-scope.json', 'independent-projection-linkage.json'])
    save('final-delivery.json', {'status': 'pass', 'checked_at': datetime.now(timezone.utc).isoformat(),
        'authority': after, 'schemas': schema_after, 'release': release_files,
        'evidence': {name: digest(LOG / name) for name in names}})
    print(json.dumps(completion, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
