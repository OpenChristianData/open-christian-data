"""Derive additive title guards from the immutable reviewed compatibility guards."""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / 'reports/_logs/blaikie-first-samuel-existing-install-20261003-v1'


def load(relative, pin):
    raw = (ROOT / relative).read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError('Reviewed compatibility authority changed: ' + relative)
    return raw.decode('utf-8')


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError('Bounded derivation anchor differs: ' + old[:90])
    return text.replace(old, new)


def write(relative, text):
    path = ROOT / relative
    if path.exists():
        raise FileExistsError('Preserve prior title guard: ' + relative)
    path.write_bytes(text.encode('utf-8'))


def main():
    stage = load('build/tools/stage_blaikie_first_samuel_acceptance.py', 'f81bb2d446e5bc5343e83ed3696886d55dcf352c7736f3ceb869d837c32d93bc')
    stage = replace(stage, 'WORK as WORK_ID,SPECS', 'WORK as SOURCE_WORK_ID,SPECS')
    stage = replace(stage, 'LIBRARY=Path', "from build.tools.propose_blaikie_first_samuel_title_identity import WORK as WORK_ID,FORM,EDITION,ACQUISITION,OLD_WORK\nfrom ocd_kernel.library.identities import validate_record\n\nORIGINAL=Path('library/works')/OLD_WORK\nPROPOSAL=LOG/'title-specific-identity-proposal-v1'\nLIBRARY=Path")
    stage = replace(stage, "EVIDENCE=WORK/'integration/blaikie-first-samuel-complete-current-20261003-v1'", "EVIDENCE=WORK/'integration/blaikie-first-samuel-title-current-20261003-v1'")
    start = stage.index('def specs():')
    end = stage.index('\nMEMBERS=specs()', start)
    stage = stage[:start] + "def specs():\n return {'blaikie-expositor8':dict(form=FORM,edition=EDITION,acquisition=ACQUISITION,members=['blaikie-expositor8'])}\n" + stage[end:]
    start = stage.index('def expected_work(root):')
    end = stage.index('\ndef projection_gate(', start)
    stage = stage[:start] + '''def assert_original(root):
 crosswalk=read(root/PROPOSAL/'old-to-new-identity-crosswalk.json')
 if _files(root/ORIGINAL)!=crosswalk['original_author_container_preimages']:raise PipelineError('Original Blaikie author-container preimages differ')
 return crosswalk

def expected_work(root):
 assert_original(root)
 if _io_path(root/WORK).exists():raise PipelineError('Title-specific First Samuel canonical home already exists')
 work=read(root/PROPOSAL/'work.json')
 if work['work_id']!=WORK_ID or work['title']!='The First Book of Samuel':raise PipelineError('Title-specific First Samuel primary identity differs')
 work['evidence']+=[(EVIDENCE/'identity-crosswalk.json').as_posix()]
 validate_record('work',work,context='Title-specific First Samuel')
 return work

def expected_state(root,at):
 state=read(root/PROPOSAL/'state.json');spec=MEMBERS['blaikie-expositor8']
 targets=[t for t in state['targets'] if t['target_type']=='edition' and t['target_id']==spec['edition']]
 acquired=[t for t in state['targets'] if t['target_type']=='acquisition' and t['target_id']==spec['acquisition']]
 if len(state['targets'])!=2 or len(targets)!=1 or targets[0]['stage']!='acquired' or len(acquired)!=1 or acquired[0]['stage']!='acquired':raise PipelineError('First Samuel inherited acquired state differs')
 targets[0].update(stage='accepted',reason=PROMOTED_MASTER_REASON,updated_at=at)
 targets[0]['evidence']+=[(edition_path(spec)/'master.tei.xml').as_posix(),(edition_path(spec)/'acceptance.json').as_posix(),(EVIDENCE/'identity-crosswalk.json').as_posix()]
 return state

def expected_acquisition(root):
 crosswalk=assert_original(root);old=read(root/Path(crosswalk['original_acquisition']['path']))
 if sha(_io_path(root/Path(crosswalk['original_acquisition']['path'])).read_bytes())!=crosswalk['original_acquisition']['sha256']:raise PipelineError('Original First Samuel acquisition changed')
 expected=deepcopy(old);expected['acquisition_id']=ACQUISITION;expected['edition_id']=EDITION
 if expected!=read(root/PROPOSAL/'acquisition.json'):raise PipelineError('Title acquisition changed original nonidentity fields or absences')
 return expected

def source_credit(root):
 package=CandidatePackage.load(CANDIDATES/'package')
 prefix=('The First Book of Samuel - title-specific retained work identity\\n\\n'
  'This additive record reuses the already retained CCEL First Samuel XML. No new acquisition occurred. '
  'The original Blaikie author-container records remain unchanged; integration/identity-crosswalk.json records both identity sets. '
  'Primary work title: The First Book of Samuel. Source title page: Toronto, Willard Tract Depository and Bible Depot, 1888; '
  'the literal primary title page and electronic Williard spelling remain preserved in the TEI and source notes. '
  'Original acquisition has no access date or rights field. Human review: not-recorded; rights: unresolved; publication: not-ready.\\n\\n').encode('utf-8')
 return prefix+package.member_bytes('README.source.md')
''' + stage[end:]
    stage = replace(stage, "result={Path(p) for p in ORACLE_IMPORTS+PRODUCER_IMPORTS}", "result={Path(p) for p in ORACLE_IMPORTS+PRODUCER_IMPORTS}\n result.update(PROPOSAL/n for n in ('work.json','state.json','acquisition.json','old-to-new-identity-crosswalk.json','proposal-receipt.json'))\n result.update(Path('build/tools')/(n+'.py') for n in ('propose_blaikie_first_samuel_title_identity','derive_blaikie_first_samuel_title_install','stage_blaikie_first_samuel_title_acceptance','install_blaikie_first_samuel_title_acceptance','prove_blaikie_first_samuel_title_install'))")
    stage = stage.replace("'execution_import_probe.py','late_import_fixture_worker.py'", "'title_execution_import_probe.py','title_late_import_fixture_worker.py'")
    stage = stage.replace("LOG/'execution-imports.json'", "LOG/'title-execution-imports-v1.json'")
    stage = replace(stage, "within the preserved author catalog", "under the primary title-specific work identity; the original author catalog remains historical acquisition lineage")
    stage = stage.replace("'blaikie-first-samuel-s-'", "'blaikie-first-samuel-title-s-'")
    stage = replace(stage, "before=_files(root/WORK);old=read(root/WORK/'work.json');work=expected_work(root)", "before=_files(root/WORK);old=read(root/ORIGINAL/'work.json');work=expected_work(root)")
    stage = replace(stage, "for relative in before:copy(root,stage,WORK/relative)", "for relative in _files(root/ORIGINAL):copy(root,stage,ORIGINAL/relative)")
    stage = replace(stage, "read(root/WORK/'state.json')['targets']", "read(root/ORIGINAL/'state.json')['targets']")
    stage = replace(stage, "write_json(stage,WORK/'work.json',work)", "write_json(stage,WORK/'work.json',work)\n write_json(stage,acquisition_path(MEMBERS['blaikie-expositor8']),expected_acquisition(root))\n write(stage,WORK/'SOURCE_CREDIT.md',source_credit(root))\n copy(root,stage,PROPOSAL/'old-to-new-identity-crosswalk.json')\n write(stage,EVIDENCE/'identity-crosswalk.json',_io_path(root/PROPOSAL/'old-to-new-identity-crosswalk.json').read_bytes())")
    stage = stage.replace('build.tools.stage_blaikie_first_samuel_acceptance', 'build.tools.stage_blaikie_first_samuel_title_acceptance')
    stage = stage.replace('ocd-blaikie-first-samuel-complete-external-stage-v1', 'ocd-blaikie-first-samuel-title-external-stage-v1')
    stage = replace(stage, "before=before,after=_files(stage/WORK)", "before=before,original_author_container_preimages=_files(root/ORIGINAL),original_author_container_unchanged=True,new_title_home_previously_absent=True,after=_files(stage/WORK)")
    write('build/tools/stage_blaikie_first_samuel_title_acceptance.py', stage)

    installer = load('build/tools/install_blaikie_first_samuel_acceptance.py', '53531bf7e25384cd32d36642be551c74804ba5cadb1a72a250246eeac223e643')
    installer = installer.replace('stage_blaikie_first_samuel_acceptance', 'stage_blaikie_first_samuel_title_acceptance')
    installer = replace(installer, ',component_artifacts\r\n', ',component_artifacts,ORIGINAL,PROPOSAL,assert_original,expected_acquisition,source_credit\r\n') if '\r\n' in installer else replace(installer, ',component_artifacts\n', ',component_artifacts,ORIGINAL,PROPOSAL,assert_original,expected_acquisition,source_credit\n')
    installer = installer.replace('blaikie-first-samuel-install-fixture-20261003-v1', 'blaikie-first-samuel-title-install-fixture-20261003-v1')
    installer = installer.replace("'blaikie-first-samuel-s-'", "'blaikie-first-samuel-title-s-'")
    installer = installer.replace('ocd-blaikie-first-samuel-complete-external-stage-v1', 'ocd-blaikie-first-samuel-title-external-stage-v1')
    installer = replace(installer, "before=_files(root/WORK);after=_files(stage/WORK)", "before=_files(root/WORK);after=_files(stage/WORK)\n if before or _io_path(root/WORK).exists() or receipt.get('new_title_home_previously_absent') is not True:raise PipelineError('Title-specific First Samuel home is not absent')\n if assert_original(root)['original_author_container_preimages']!=receipt.get('original_author_container_preimages') or _files(stage/ORIGINAL)!=receipt['original_author_container_preimages'] or receipt.get('original_author_container_unchanged') is not True:raise PipelineError('Original Blaikie author container changed')")
    installer = replace(installer, "allowed=set()", "allowed={'work.json','state.json','SOURCE_CREDIT.md'}\n allowed.add(acquisition_path(MEMBERS['blaikie-expositor8']).relative_to(WORK).as_posix())\n if read(stage/acquisition_path(MEMBERS['blaikie-expositor8']))!=expected_acquisition(root) or _io_path(stage/WORK/'SOURCE_CREDIT.md').read_bytes()!=source_credit(root):raise PipelineError('Title-specific acquisition or visible source credit differs')\n if _io_path(stage/EVIDENCE/'identity-crosswalk.json').read_bytes()!=_io_path(root/PROPOSAL/'old-to-new-identity-crosswalk.json').read_bytes():raise PipelineError('Title-specific durable identity crosswalk differs')")
    installer = replace(installer, "sorted((target,source)", "sorted((target,source,root/ORIGINAL)")
    installer = replace(installer, "if point=='after-validated':", "if point=='after-validated':\n    if _files(root/ORIGINAL)!=receipt['original_author_container_preimages'] or _files(stage/ORIGINAL)!=receipt['original_author_container_preimages']:raise PipelineError('Original Blaikie container changed during installation')")
    installer = replace(installer, 'existed=True,replacement=False', 'existed=False,replacement=False')
    installer = installer.replace('blaikie-first-samuel-existing-complete-work-install', 'blaikie-first-samuel-additive-title-work-install')
    write('build/tools/install_blaikie_first_samuel_title_acceptance.py', installer)

    proof = load('build/tools/prove_blaikie_first_samuel_install.py', 'a963b3aab0d5b482b3e9e26cefaf9668b8cf872ea46cdb95eafc7b64c7d45aa1')
    proof = proof.replace('install_blaikie_first_samuel_acceptance', 'install_blaikie_first_samuel_title_acceptance')
    proof = replace(proof, 'read, digest', 'read, digest, ORIGINAL')
    proof = proof.replace('blaikie-first-samuel-install-fixture-20261003-v1', 'blaikie-first-samuel-title-install-fixture-20261003-v1')
    proof = proof.replace('blaikie-first-samuel-install-wrong-root-20261003-v1', 'blaikie-first-samuel-title-install-wrong-root-20261003-v1')
    proof = replace(proof, "before=_files(ROOT/WORK)", "before=_files(ROOT/WORK);original=_files(ROOT/ORIGINAL)\n if _io_path(ROOT/WORK).exists() or before or original!=receipt['original_author_container_preimages']:raise PipelineError('Title home absence or original author preimage differs')")
    proof = replace(proof, "for relative in before:", "for relative in original:")
    proof = replace(proof, "fixture/WORK/relative", "fixture/ORIGINAL/relative")
    proof = replace(proof, "ROOT/WORK/relative", "ROOT/ORIGINAL/relative")
    proof = proof.replace("'late_import_fixture_worker.py'", "'title_late_import_fixture_worker.py'")
    proof = proof.replace("'fixture-operation-journals-v1'", "'title-fixture-operation-journals-v1'")
    proof = proof.replace("'guarded-install-fixture-proof-v1.json'", "'title-guarded-install-fixture-proof-v1.json'")
    proof = replace(proof, "durable_journals=[];journal_root", "if _files(ROOT/ORIGINAL)!=original or _files(fixture/ORIGINAL)!=original or _files(stage/ORIGINAL)!=original or _io_path(ROOT/WORK).exists():raise ValueError('Title fixture mutated canonical absence or original author container')\n durable_journals=[];journal_root")
    proof = replace(proof, "proof=dict(durable_terminal_operation_journals", "proof=dict(original_author_container_unchanged=True,canonical_title_home_absent=True,durable_terminal_operation_journals")
    write('build/tools/prove_blaikie_first_samuel_title_install.py', proof)

    probe = load('reports/_logs/blaikie-first-samuel-existing-install-20261003-v1/execution_import_probe.py', 'cdae894e069999f17ec70a27439df12292baf07185010412aa0c275b004c7836')
    probe = replace(probe, 'SOURCE_DIR,WORK as WORK_ID,_convert', 'SOURCE_DIR,_convert')
    probe = probe.replace('stage_blaikie_first_samuel_acceptance', 'stage_blaikie_first_samuel_title_acceptance').replace('install_blaikie_first_samuel_acceptance', 'install_blaikie_first_samuel_title_acceptance')
    probe = replace(probe, 'MEMBERS,WORK,WORKS', 'MEMBERS,WORK,WORKS,WORK_ID,ORIGINAL')
    probe = probe.replace("LOG/'execution-imports.json'", "LOG/'title-execution-imports-v1.json'")
    write('reports/_logs/blaikie-first-samuel-existing-install-20261003-v1/title_execution_import_probe.py', probe)
    worker = load('reports/_logs/blaikie-first-samuel-existing-install-20261003-v1/late_import_fixture_worker.py', '831921b0ccee5a2f8bf93e0ca1800c687cd5d35dbb565ece8f3444819d148c17')
    worker = worker.replace('install_blaikie_first_samuel_acceptance', 'install_blaikie_first_samuel_title_acceptance')
    worker = worker.replace('blaikie-first-samuel-install-fixture-20261003-v1', 'blaikie-first-samuel-title-install-fixture-20261003-v1')
    write('reports/_logs/blaikie-first-samuel-existing-install-20261003-v1/title_late_import_fixture_worker.py', worker)


if __name__ == '__main__':
    main()
