"""Resume only the affected public projection of the already-complete private Select Sermons stage."""
import argparse,json
from pathlib import Path
from hashlib import sha256
from copy import deepcopy
from build.tools.prepare_edwards_select_sermons_current import ROOT,WORK_ID,WORK,EDITION,ACQUISITION,BASE,SOURCE_SHA
from build.tools.stage_edwards_select_sermons_current import EVIDENCE,put_json
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.native_documents import project_accepted_document,verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--promoted',type=Path,required=True);args=p.parse_args()
    promoted_root=args.promoted.absolute()
    if promoted_root!=Path('D:/Library/Open Christian Data/candidate-reviews/edwards-select-sermons-promoted-20261001-v2'):raise ValueError('exact failed stage resume root required')
    if (promoted_root/'stage-receipt.json').exists():raise FileExistsError('already-complete receipt')
    stage=Path('D:/Library/Open Christian Data/candidate-reviews/edwards-select-sermons-stage-20261001-v2')
    failure=json.loads((ROOT/'reports/_logs/edwards-select-sermons-reconciliation-20261001-v1/processes/stage-v2.json').read_bytes())
    if failure['exit_code']!=1 or 'source-projection mapped target tag differs' not in failure['stderr']:raise ValueError('located old public failure differs')
    before=json.loads((ROOT/'reports/_logs/edwards-select-sermons-reconciliation-20261001-v1/preflight.json').read_bytes())['before']
    if _files(ROOT/WORK)!=before:raise ValueError('canonical preimage changed')
    manifest=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);manifest.verify()
    package=CandidatePackage.load(Path('D:/Library/Open Christian Data/candidate-reviews/edwards-select-sermons-current-20261001-v2/package'));package.verify_integrity()
    if package.sha256!='03f3c7fc4a70d9fb1bac1a5333b061b45a21e9a530d17171df32f9e995050ad2' or sha256(package.member_bytes('content.tei.xml')).hexdigest()!='b68c425e0323d66f6ab439a2684dd429c3d72f3421e06674f341eec1bea7afb9':raise ValueError('frozen reviewed candidate differs')
    promoted_acceptance=promoted_root/EDITION/'acceptance.json'
    acceptance=validate_acceptance(promoted_acceptance,root=promoted_root)
    bound=io_path(promoted_root/EDITION/'master.tei.xml').read_bytes()
    if bound.split(b'</teiHeader>',1)[1]!=package.member_bytes('content.tei.xml').split(b'</teiHeader>',1)[1]:raise ValueError('reviewed body/standOff changed')
    for name in package.member_names:
        if io_path(promoted_root/EVIDENCE/'original-package'/name).read_bytes()!=package.member_bytes(name):raise ValueError('staged original member differs')
    accounting_path=promoted_root/EVIDENCE/'source-accounting.json';accounting=json.loads(io_path(accounting_path).read_bytes());source_facts=accounting['source_facts'];source=acceptance['source']
    mutations=json.loads(io_path(promoted_root/EVIDENCE/'mutations.json').read_bytes())
    if source_facts!=mutations['baseline'] or len(mutations['cases'])!=32 or mutations['status']!='pass' or source_facts['source_elements']!=3618 or source_facts['body_roots']!=21:raise ValueError('existing private gates differ')
    if source['source_sha256']!=SOURCE_SHA:raise ValueError('source binding differs')
    schema_paths=sorted(p.relative_to(ROOT) for p in (ROOT/'schemas/v2').rglob('*.json'));schema_pins={p.as_posix():sha256((ROOT/p).read_bytes()).hexdigest() for p in schema_paths}
    runtime_paths=[Path(p) for p in ['ocd_kernel/projection/source_projection_evidence.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/categories/native_documents.py']]
    runtime_pins={p.as_posix():sha256((ROOT/p).read_bytes()).hexdigest() for p in runtime_paths}
    if runtime_pins['ocd_kernel/projection/source_projection_evidence.py']!='d749eb107efc8e762642a05dc35c7ebcd7789b37459851f74d9faf14c7c1c013':raise ValueError('reviewed helper freeze differs')
    freeze=json.loads((ROOT/'reports/_logs/edwards-select-sermons-helper-support-20261001-v1/patch-binding.json').read_bytes())
    if any(sha256(io_path(ROOT/p).read_bytes()).hexdigest()!=value for p,value in freeze['untouched'].items()):raise ValueError('untouched runtime changed')
    put_json(promoted_root,EVIDENCE/'resume-binding.json',dict(status='private-stage-reused',source_accounting_sha256=sha256(io_path(accounting_path).read_bytes()).hexdigest(),reviewed_original_tei_sha256='b68c425e0323d66f6ab439a2684dd429c3d72f3421e06674f341eec1bea7afb9',private_oracle_replay_32mutations_not_rerun=True,original_failure_preserved=True,old_helper_sha256=freeze['before_sha256'],new_helper_sha256=freeze['after_sha256']))
    with cached_edition_lookups():
        validate_acceptance(promoted_acceptance,root=promoted_root)
        projection = project_accepted_document(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance),category="sermons",collection=True)
        errors = verify_accepted_document(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance),rows=projection["rows"],receipt=projection["receipt"],category="sermons",collection=True)
    if errors or len(projection["rows"]) != 21:
        raise ValueError(f"actual-master projection differs: {errors}; rows={len(projection['rows'])}")
    # Independent source oracle covers exact media/marker URIs and attachment.
    # Prove actual public structure keeps them, with producer-disabled verifier sensitivity.
    def nodes(value):
        result=[]
        if isinstance(value,dict):
            if "kind" in value:result.append(value)
            for child in value.values():result.extend(nodes(child))
        elif isinstance(value,list):
            for child in value:result.extend(nodes(child))
        return result
    projected_nodes=nodes(projection["rows"])
    icons=[n for n in projected_nodes if n.get("kind")=="image-reference"]
    if len(icons)!=17 or any(n.get("attributes",{}).get("source_target")!="http://static.ccel.org/pix/mp3.png" or n.get("attributes",{}).get("number")!="mp3" for n in icons):raise ValueError("public exact source icon target/alt differs")
    public_mutations=[]
    for kind in ("icon-target-loss","icon-target-change","icon-alt-change","audio-target-change","marker-label-change","anchor-label-change"):
        rows=deepcopy(projection["rows"]);ns=nodes(rows)
        if kind.startswith("icon"):
            node=next(n for n in ns if n.get("kind")=="image-reference")
            if kind=="icon-target-loss":node["attributes"].pop("source_target")
            elif kind=="icon-target-change":node["attributes"]["source_target"]="https://example.invalid/invented.png"
            else:node["attributes"]["number"]="invented"
        elif kind=="audio-target-change":
            node=next(n for n in ns if n.get("attributes",{}).get("source_target","").endswith(".mp3"));node["attributes"]["source_target"]="https://example.invalid/audio.mp3"
        elif kind=="marker-label-change":
            node=next(n for n in ns if n.get("attributes",{}).get("type")=="ThML-scripCom");node["attributes"]["number"]="Invented"
        else:
            node=next(n for n in ns if n.get("attributes",{}).get("type")=="ThML-anchor" and n.get("content"));node["content"][0]["text"]="Invented"
        failures=verify_accepted_document(io_path(promoted_root),acceptance_path=io_path(promoted_acceptance),rows=rows,receipt=projection["receipt"],category="sermons",collection=True)
        if not failures:raise ValueError("public source mutation escaped "+kind)
        public_mutations.append(dict(mutation=kind,status="rejected",errors=failures))
    put_json(promoted_root,EVIDENCE/"source-public-proof.json",dict(status="pass",icon_count=17,exact_external_targets_and_alt=True,unretained_payloads=True,independent_mutation_checks=public_mutations))
    if {p.as_posix(): sha256((ROOT / p).read_bytes()).hexdigest() for p in schema_paths} != schema_pins:
        raise ValueError("shared schema changed during staged projection")
    put_json(promoted_root,EVIDENCE/"stage-projection.json",projection)
    if {p.as_posix():sha256((ROOT/p).read_bytes()).hexdigest() for p in runtime_paths} != runtime_pins: raise ValueError("shared runtime changed during staged checks")
    receipt = dict(runtime_pins=runtime_pins,status="pass",work_id=WORK_ID,source_sha256=source["source_sha256"],category="sermons",language="en",
                   source_facts=source_facts,before=before,master_sha256=sha256(bound).hexdigest(),rows=len(projection["rows"]),
                   projection_errors=errors,stage_root=stage.as_posix(),promoted_root=promoted_root.as_posix(),
                   schema_pins=schema_pins,
                   promotion_route="work-specific long-path staged promotion; shared record/binding validators and guarded canonical installer")
    receipt["after"] = _files(promoted_root/WORK)
    put_json(promoted_root,Path("stage-receipt.json"),receipt)
    print(json.dumps(receipt))


if __name__=="__main__":main()
