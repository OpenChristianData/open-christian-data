"""Complete one canonical four-component partial Summa witness privately."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from build.tools.prepare_aquinas_four_current import ROOT, WORK, WORK_ID, EDITION, ACQUISITION, BASE, LOG as INSTALL_LOG, canonical
from ocd_kernel.library._common import io_path, io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.native_documents import _validate_rows
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2

OUT = ROOT / 'reports/_logs/aquinas-four-offline-release-20261002-v1'
PUB = ROOT / WORK / 'publication'
RELEASE = OUT / 'release'


def digest(path):
    return sha256(io_path(path).read_bytes()).hexdigest()


def save(path, value):
    path = io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    path.write_bytes(canonical(value))


def process(name, argv):
    try:
        result = subprocess.run(argv, cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8')
    except subprocess.CalledProcessError as exc:
        save(OUT / (name + '.command.json'), dict(argv=argv, exit_code=exc.returncode, stdout=exc.stdout, stderr=exc.stderr))
        raise
    save(OUT / (name + '.command.json'), dict(argv=argv, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
    return result


def command(name, module, args):
    code = 'import sys;sys.dont_write_bytecode=True\nfrom ocd_kernel.library.identities import cached_edition_lookups\nfrom ' + module + ' import main\nwith cached_edition_lookups():\n raise SystemExit(main())'
    result = process(name, [sys.executable, '-c', code, *args])
    if name != 'assembly':
        value = json.loads(result.stdout)
        save(OUT / (name + '.json'), value)
        if value.get('status') != 'pass':
            raise ValueError(value)


def main():
    if OUT.exists() or PUB.exists():
        raise FileExistsError('Fresh whole-work private completion paths required')
    OUT.mkdir(parents=True)
    PUB.mkdir(parents=True)
    log = ROOT / INSTALL_LOG
    pin = json.loads((ROOT / BASE / 'stage-pin.json').read_bytes())
    staged = json.loads(Path(pin['receipt']).read_bytes())
    if digest(Path(pin['receipt'])) != pin['receipt_sha256']:
        raise ValueError('Frozen stage changed')
    master, acceptance = ROOT / EDITION / 'master.tei.xml', ROOT / EDITION / 'acceptance.json'
    if digest(master) != staged['master_sha256']:
        raise ValueError('Installed master differs from cleared stage')
    installed = json.loads((log / 'canonical-install/installed-audit.json').read_bytes())
    if installed['files'] != staged['after'] or installed['status'] != 'pass':
        raise ValueError('Canonical installed audit incomplete')
    bound = {p.relative_to(ROOT).as_posix(): digest(p) for p in io_glob(ROOT / WORK, '**/*') if io_path(p).is_file() and PUB not in p.parents}
    acquisition = json.loads(io_path(ROOT / ACQUISITION).read_bytes())
    for member in acquisition['retained_files']:
        if digest(ROOT / member['path']) != member['sha256']:
            raise ValueError('Retained source changed')
        bound[member['path']] = member['sha256']
    members = json.loads(io_path(ROOT / EDITION / 'source-member-set.json').read_bytes())
    def add_members(value):
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and value['path'].startswith('raw/') and value.get('sha256'):
                if digest(ROOT / value['path']) != value['sha256']:
                    raise ValueError('Retained support/source changed')
                bound[value['path']] = value['sha256']
            for child in value.values():
                add_members(child)
        elif isinstance(value, list):
            for child in value:
                add_members(child)
    add_members(members)
    schemas = {path: digest(ROOT / path) for path in staged['schema_pins']}
    modules = ['ocd_kernel/projection/categories/native_documents.py', 'ocd_kernel/projection/categories/prose.py', 'ocd_kernel/projection/categories/sermons.py', 'ocd_kernel/projection/native_content.py', 'ocd_kernel/projection/native_content_check.py', 'ocd_kernel/projection/source_projection_evidence.py', 'ocd_kernel/projection/envelope.py', 'ocd_kernel/reconstruction/contract.py', 'ocd_kernel/tei/acceptance.py', 'ocd_kernel/library/identities.py', 'ocd_kernel/library/_common.py', 'ocd_kernel/library/acquisitions.py', 'ocd_kernel/library/state.py', 'ocd_kernel/lib/storage_topology.py', 'ocd_kernel/release/selection.py', 'ocd_kernel/release/assemble.py', 'ocd_kernel/release/verify.py', 'ocd_kernel/release/notices.py', 'ocd_kernel/release/typed_rows.py', 'build/scripts/export_huggingface.py', 'build/tools/check_hf_release.py', 'build/tools/report_release_stats.py', 'build/tools/check_release_reader.py', 'build/tools/complete_aquinas_four_private_release.py']
    runtime = {p: digest(ROOT / p) for p in modules}
    for p in ['ocd_kernel/projection/scripture_authority.py', 'ocd_kernel/projection/scripture_targets.py', 'ocd_kernel/projection/scripture_targets_check.py', 'ocd_kernel/release/public_allowlist.py', 'ocd_kernel/release/work_metadata.py', 'ocd_kernel/release/public_rows.py', 'build/bible_data/osis_book_codes.json']:
        runtime[p] = digest(ROOT / p)
    bound.update(runtime)
    for directory in [log, ROOT / BASE]:
        for p in io_glob(directory, '*'):
            if io_path(p).is_file():
                bound[p.relative_to(ROOT).as_posix()] = digest(p)
    for p in io_glob(log / 'canonical-install', '**/*'):
        if io_path(p).is_file():
            bound[p.relative_to(ROOT).as_posix()] = digest(p)
    notices = json.loads((log / 'notice-preflight.json').read_bytes())
    item = notices['item']
    texts = notice_texts_for_item(ROOT, item, acceptance)
    if len(texts) != 4:
        raise ValueError('Four complete own source/data notices required')
    for notice in item['public_notices']:
        for key in ['source_path', 'notice_path']:
            bound[notice[key]] = digest(ROOT / notice[key])
    selection = dict(schema_version='2.0', release_id='aquinas-four-private-offline-20261002-v1', items=[item])
    save(PUB / 'selection.json', selection)
    save(OUT / 'selection.json', selection)
    bound[(PUB / 'selection.json').relative_to(ROOT).as_posix()] = digest(PUB / 'selection.json')
    save(OUT / 'schemas-before.json', schemas)
    save(OUT / 'runtime-freeze.json', runtime)
    save(OUT / 'authority-before.json', bound)
    saved = log / 'current-runtime-projection.json'
    projection = json.loads(saved.read_bytes())
    _validate_rows(projection['rows'], 'prose')
    if len(projection['rows']) != 4 or projection['receipt']['master_sha256'] != digest(master):
        raise ValueError('Full exact installed master linkage differs')
    (OUT / 'actual-master-projection.json').write_bytes(saved.read_bytes())
    save(OUT / 'public-validation.json', dict(status='pass', rows=4, errors=[], supported_stage_projection_reused=True, installed_master_sha256=digest(master)))
    code = '''import sys,json,hashlib
from pathlib import Path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection import native_content
def forbidden(*a,**kw):raise AssertionError('Producer disabled')
native_documents.project_document=native_documents.project_accepted_document=native_content.project_content=native_content.readable_content=forbidden
root,acceptance,saved=map(Path,sys.argv[1:]);raw=saved.read_bytes();p=json.loads(raw)
with cached_edition_lookups():errors=native_documents.verify_accepted_document(root,acceptance_path=acceptance,rows=p['rows'],receipt=p['receipt'],category='prose')
print(json.dumps(dict(status='fail' if errors else 'pass',errors=errors,producer_disabled=True,saved_projection_sha256=hashlib.sha256(raw).hexdigest())))
raise SystemExit(bool(errors))'''
    checked = json.loads(process('independent-projection', [sys.executable, '-c', code, str(ROOT), str(acceptance), str(OUT / 'actual-master-projection.json')]).stdout)
    if checked['status'] != 'pass' or checked['saved_projection_sha256'] != digest(OUT / 'actual-master-projection.json'):
        raise ValueError(checked)
    checked.update(accepted_master_sha256=digest(master), acceptance_sha256=digest(acceptance), full_accepted_master=True, qualification='Exact whole accepted master reused; supported staged rows retained after closed current-runtime renewal and independently compared against actual canonical authority. No source-selected synthetic document.')
    save(OUT / 'independent-projection-linkage.json', checked)
    save(OUT / 'notice-preflight.json', dict(status='pass', notice_count=4, complete_own_license_and_credits=True))
    print('Actual canonical master and saved four rows independently linked; assembling private release', flush=True)
    common = ['--root', str(ROOT), '--selection', str(PUB / 'selection.json')]
    command('assembly', 'build.scripts.export_huggingface', [*common, '--output', str(RELEASE)])
    report = json.loads((RELEASE / 'internal/release-report.json').read_bytes())
    if report['status'] != 'pass':
        raise ValueError(report)
    save(OUT / 'assembly.json', report)
    with cached_edition_lookups():
        verified = verify_release_v2(ROOT, RELEASE, selection=selection)
    save(OUT / 'independent-verification.json', verified)
    if verified['status'] != 'pass':
        raise ValueError(verified)
    args = [*common, '--release', str(RELEASE)]
    command('separate-process-verification', 'build.tools.check_hf_release', args)
    command('statistics', 'build.tools.report_release_stats', args)
    command('readers', 'build.tools.check_release_reader', [*args, '--output', str(OUT / 'readers.json')])
    released = (RELEASE / 'public/README.md').read_bytes()
    if any(text.encode().rstrip() not in released for text in texts):
        raise ValueError('Release omits complete own license/credit notice')
    save(OUT / 'released-notice-check.json', dict(status='pass', complete_notices=4, complete_licenses_embedded=True))
    after = {p: digest(ROOT / p) for p in bound}
    schema_after = {p: digest(ROOT / p) for p in schemas}
    if after != bound or schema_after != schemas:
        raise ValueError('Current bound inputs/schema drift')
    save(OUT / 'authority-after.json', after)
    save(OUT / 'schema-stability.json', dict(status='pass', before=schemas, after=schema_after))
    files = {p.relative_to(RELEASE).as_posix(): digest(p) for p in io_glob(RELEASE, '**/*') if io_path(p).is_file()}
    save(OUT / 'release-file-hashes.json', files)
    completion = dict(status='pass', private_offline=True, publication_performed=False, checked_at=datetime.now(timezone.utc).isoformat(), work_id=WORK_ID, rows=4, source_units=35488, semantic_questions=512, semantic_articles=2669, text_characters=sum(len(r['text']) for r in projection['rows']), statistics=json.loads((OUT / 'statistics.json').read_bytes())['total'], accepted_master_sha256=digest(master), acceptance_sha256=digest(acceptance), saved_projection_sha256=digest(OUT / 'actual-master-projection.json'), independent_linkage_sha256=digest(OUT / 'independent-projection-linkage.json'), authority_unchanged_during_release=True, bound_schemas_stable=True, complete_own_source_data_credit_and_licenses_visible=True, release_path=str(RELEASE), remaining=['Human acceptance and exhaustive visual proofreading', 'Four retained components only; traditional Supplement absent', 'Print equivalence and independent rights clearance', 'Public publication authorization'])
    save(OUT / 'completion.json', completion)
    save(PUB / 'completion.json', completion)
    readme = '# Summa Theologica: four-component private readiness\n\nOne accepted TEI preserves the four retained English electronic components I, I-II, II-II and III: 35,488 source units, 512 semantic question boundaries and 2,669 semantic articles. The traditional Supplement is absent. Native source numbering anomalies, own dedication/notes/contents/prologues, editorial insertion, italics and breaks remain literal; generated ownership/taxonomy are reconstruction analysis.\n\nFull actual-master public projection and saved producer-disabled independent linkage, private assembly, both release verifiers, statistics and normal/streaming readers pass. Four paired human-visible source/data notices preserve primary translator and electronic contributor statements and each complete own Gutenberg license. Current dated runtime/schema and installed generation are bound. Human acceptance, visual proofreading, print equivalence, rights clearance and public publication remain separate.\n'
    for path in [OUT / 'README.md', PUB / 'README.md']:
        path.write_text(readme, encoding='utf-8', newline='\n')
    for p in io_glob(PUB, '**/*'):
        if io_path(p).is_file():
            after[p.relative_to(ROOT).as_posix()] = digest(p)
    evidence = {p.relative_to(OUT).as_posix(): digest(p) for p in io_glob(OUT, '**/*') if io_path(p).is_file() and RELEASE not in p.parents}
    save(OUT / 'final-delivery.json', dict(status='pass', map_bases=dict(authority=str(ROOT), schemas=str(ROOT), release=str(RELEASE), evidence=str(OUT)), authority=after, schemas=schema_after, release=files, evidence=evidence))
    print(json.dumps(completion), flush=True)


if __name__ == '__main__':
    main()
