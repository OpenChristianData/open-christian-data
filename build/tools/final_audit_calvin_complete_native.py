"""Read-only final pin checks and one append-only work-local closeout receipt."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json
from build.tools.prepare_calvin_complete_native import ROOT,WORK,EDITION,LOGS,canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.tei.install_accepted import _files
PUB=WORK/'publication'
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def read(p):return json.loads(io_path(p).read_bytes())
def main():
    target=ROOT/PUB/'final-delivery-audit.json'
    if io_path(target).exists():raise FileExistsError('preserve prior final audit')
    completion=ROOT/PUB/'completion.json';record=read(completion)
    if record['status']!='pass' or record['rows']!=16 or record['text_characters']!=3739015:raise ValueError('completed one-work release differs')
    checked={}
    for field in ('authority_bindings','schema_implementation_bindings','independent_corroboration_bindings'):
        for name,h in record[field].items():
            p=Path(name);p=p if p.is_absolute() else ROOT/p
            if digest(p)!=h:raise ValueError('current bound input differs '+name)
            checked[p.as_posix()]=h
    out=Path(record['evidence_path']);release=Path(record['release_path'])
    for name,h in record['release_evidence_bindings'].items():
        if digest(out/name)!=h:raise ValueError('release proof differs '+name)
        checked[(out/name).as_posix()]=h
    for name,h in record['release_file_bindings'].items():
        if digest(release/name)!=h:raise ValueError('actual private release file differs '+name)
        checked[(release/name).as_posix()]=h
    install=read(ROOT/'reports/_logs/calvin-institutes-install-20261001-v1/canonical/installation.json')
    if {p:h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')}!=install['installed_files']:raise ValueError('canonical nonpublication generation differs')
    journal=Path(install['operation'])/'operation.json';operation=read(journal)
    if operation['phase']!='complete' or operation['after']!=install['installed_files']:raise ValueError('guarded canonical operation not complete')
    coordinator=ROOT/'reports/_logs/calvin-institutes-install-20261001-v1/canonical/coordinator-installed-and-prerequisite-review.json'
    coordinator_record=read(coordinator)
    if coordinator_record['status']!='pass' or coordinator_record['checked_installed_files']!=25:raise ValueError('coordinator corroboration differs')
    original=read(ROOT/LOGS/'association-proposal.json')
    if original['before_sha256']!=digest(ROOT/LOGS/'acquisition-before.json'):raise ValueError('original partial association preimage missing')
    checked[coordinator.as_posix()]=digest(coordinator);checked[journal.as_posix()]=digest(journal)
    # The first maintained notice pair remains sealed history even though a
    # separate release-only pair satisfies the stricter one-LF card renderer.
    old_source=ROOT/'sources/private-pg-allen-calvin/calvins-institutes/README.source.md'
    old_data=ROOT/'data/prose/calvins-institutes/README.md'
    old_notice_sha=read(ROOT/LOGS/'notice-v2-repair.json')['original_bound_notice_sha256']
    if digest(old_source)!=old_notice_sha or digest(old_data)!=old_notice_sha:raise ValueError('original bound notice pair changed')
    checked[old_source.as_posix()]=old_notice_sha;checked[old_data.as_posix()]=old_notice_sha
    result=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),completion_path=completion.as_posix(),completion_sha256=digest(completion),current_checked_pins=checked,checked_pins=len(checked),installed_generation_files=25,coordinator_current_installed_and_prerequisite_review=dict(path=coordinator.as_posix(),sha256=digest(coordinator)),full_master_sha256=record['accepted_master_sha256'],rows=16,text_characters=3739015,private_offline=True,publication_performed=False,rights_human_print_decisions_separate=True,friction_observations=['Existing complete retained mapper body was reusable; old profile import closure was stale. Fresh work-local bindings retained the mapper and unchanged independent source oracle.','Generic public route rejects grouped text envelope and generated table dimensions/row roles/c delimiters. Reversible work-local teiCorpus aliases preserved every source line/blank payload/volume-part/table cell/note/index; no shared policy repair.','The source sidecar was legitimately partial VolII. Guarded as-found association adds already-retained VolI with an explicit physical ordered member manifest; no synthetic digest passed off as an original file and no download history invented.','Maintained header binder accepts one TEI, so a supported isolated outer-header shell plus exact corpus-header-only byte splice preserves both whole member documents; actual full corpus acceptance/P5/public checks and fresh byte replay establish the final artifact.','Cheap notice gate accepts trailing blank lines while dataset-card renderer requires exactly one terminal LF. The actual first private assembly exposed this; a separate notice pair changes only its directed data path and terminal padding, with original bound notices and failed release preserved. Previewing the maintained card would locate this earlier.','Local caller errors (validation receipt serialization, mappingproxy serialization, attestation kwargs, header idno dictionary order and license sentinel containing trademark symbol) were corrected with failures and superseded artifacts retained; no shared contract changes.'])
    io_path(target).write_bytes(canonical(result));print(json.dumps(dict(status='pass',path=(PUB/'final-delivery-audit.json').as_posix(),checked_pins=len(checked),completion_sha256=result['completion_sha256'])))
if __name__=='__main__':main()
