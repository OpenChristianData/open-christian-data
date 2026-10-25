"""Resume saved PG33105 release after a resolved unrelated catalog gate."""
from __future__ import annotations
from datetime import datetime, timezone
import json

from build.tools.prepare_chinook_current import ROOT,LOG,WORK,EDITION,WID,digest,save
from build.tools.complete_chinook_private_release import OUT
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files

def main():
    installation=json.loads((LOG/"canonical-install/installed-generation.json").read_bytes())
    inputs=json.loads((OUT/"input-bindings-before.json").read_bytes())
    saved_failure=json.loads((OUT/"statistics-guard-failure.json").read_bytes())
    release=OUT/"release"
    for name in ("statistics","readers","completion"):
        if (OUT/(name+".json")).exists():
            raise ValueError(f"Resume output already exists: {name}")
    if (ROOT/WORK/"publication/completion.json").exists() or _files(ROOT/WORK)!=installation["installed_files"]:
        raise ValueError("Installed generation changed or completion already exists")
    for relative,expected in inputs.items():
        if digest((ROOT/relative).read_bytes())!=expected:
            raise ValueError(f"Preserved input changed: {relative}")
    for name in ("assembly","independent-verification"):
        if digest((OUT/(name+".json")).read_bytes())!=saved_failure["gate_bindings"][name]:
            raise ValueError(f"Preserved passed gate changed: {name}")
    selection=json.loads((OUT/"selection.json").read_bytes())
    notices=selection["items"][0]["public_notices"][0]
    files_before={path.relative_to(release).as_posix():digest(path.read_bytes()) for path in release.rglob("*") if path.is_file()}
    resume_binding=dict(path="build/tools/resume_chinook_private_release.py",sha256=digest(__import__("pathlib").Path(__file__).read_bytes()),
        prior_failure_sha256=digest((OUT/"statistics-guard-failure.json").read_bytes()),
        scope="Resume saved release only: retry failed statistics/fresh verification once, first normal/streaming readers, then completion; no assembly or standalone verification rerun.")
    save(OUT/"resume-input-bindings.json",dict(installed_files=installation["installed_files"],original_inputs=inputs,release_files=files_before,resume=resume_binding))
    for name,operation in (("statistics",lambda:release_statistics(ROOT,release,selection)),("readers",lambda:check_reader(ROOT,release,selection))):
        try:
            result=operation()
            if result["status"]!="pass":
                raise PipelineError(f"{name} returned a failing report: {result}")
        except (PipelineError,OSError,ValueError,ImportError) as exc:
            save(OUT/"resume-guard-failure.json",dict(status="fail",gate=name,error=str(exc),publication_performed=False))
            raise
        save(OUT/(name+".json"),result)
        print(name+": pass",flush=True)
    for relative,expected in inputs.items():
        if digest((ROOT/relative).read_bytes())!=expected:
            raise ValueError(f"Preserved input drifted: {relative}")
    if _files(ROOT/WORK)!=installation["installed_files"]:
        raise ValueError("Installed generation drifted during resumed checks")
    files={path.relative_to(release).as_posix():digest(path.read_bytes()) for path in release.rglob("*") if path.is_file()}
    if files!=files_before:
        raise ValueError("Saved release bytes changed during resumed checks")
    save(OUT/"release-file-bindings.json",files)
    accepted=json.loads((ROOT/EDITION/"acceptance.json").read_bytes())
    stats=json.loads((OUT/"statistics.json").read_bytes())
    if stats["total"]["records"]!=20 or stats["total"]["text_characters"]!=13932:
        raise ValueError("Original Chinook row or text counts differ")
    completion=dict(contract="ocd-pg33105-chinook-private-offline-completion-v1",status="pass",work_id=WID,
        checked_at=datetime.now(timezone.utc).isoformat(),accepted_master_sha256=accepted["promotion"]["master"]["sha256"],
        acceptance_sha256=digest((ROOT/EDITION/"acceptance.json").read_bytes()),selection_sha256=digest((OUT/"selection.json").read_bytes()),
        rows=20,sections=40,source_verse_stanzas=195,text_characters=stats["total"]["text_characters"],release_path=str(release),
        private_offline=True,publication_performed=False,human_decision="not-recorded",rights_clearance="unresolved",
        print_collation="unverified; no retained page scans",row_scope="20 numbered hymn/translation pairs; all non-hymn matter and interlinear prayers retained in full master outside these rows",
        source_notice_sha256=notices["source_sha256"],public_notice_sha256=notices["notice_sha256"],
        input_bindings=inputs,installed_generation=installation["installed_files"],release_file_bindings=files,resume=resume_binding,
        gate_bindings={name:digest((OUT/(name+".json")).read_bytes()) for name in ("assembly","independent-verification","statistics","readers")})
    save(OUT/"completion.json",completion)
    save(ROOT/WORK/"publication/completion.json",completion)
    print(json.dumps(dict(status="pass",rows=20,text_characters=13932,release_files=len(files),completion_sha256=digest((OUT/"completion.json").read_bytes())),indent=2),flush=True)

if __name__=="__main__":
    main()
