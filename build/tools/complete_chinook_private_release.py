"""Prepare and verify one PG33105 private offline hymn snapshot; no upload."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path

from build.tools.prepare_chinook_current import ROOT,LOG,WORK,EDITION,WID,digest,save
from build.tools.prepare_chinook_notices import SOURCE_NOTICE,DATA_NOTICE
from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.hymns import project_accepted_hymns,verify_accepted_hymns
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files

OUT=LOG/"private-offline-release-v1"

def main() -> None:
    if OUT.exists() or (ROOT/WORK/"publication/completion.json").exists():
        raise ValueError("Chinook release already exists; reconcile prior results before rerunning")
    installation=json.loads((LOG/"canonical-install/installed-generation.json").read_bytes())
    if installation["status"] != "pass" or _files(ROOT/WORK) != installation["installed_files"]:
        raise ValueError("Exact installed Chinook generation differs")
    accepted=validate_acceptance(ROOT/EDITION/"acceptance.json",root=ROOT)
    validate_state(ROOT/WORK/"state.json",root=ROOT)
    output=project_accepted_hymns(ROOT,acceptance_path=ROOT/EDITION/"acceptance.json")
    errors=verify_accepted_hymns(ROOT,acceptance_path=ROOT/EDITION/"acceptance.json",rows=output["rows"],receipt=output["receipt"])
    if errors or len(output["rows"]) != 20:
        raise ValueError(f"Chinook actual-master projection differs: {errors}")
    notices=dict(source_path=SOURCE_NOTICE.as_posix(),source_sha256=digest((ROOT/SOURCE_NOTICE).read_bytes()),
        notice_path=DATA_NOTICE.as_posix(),notice_sha256=digest((ROOT/DATA_NOTICE).read_bytes()))
    selection=dict(schema_version="2.0",release_id="pg33105-chinook-private-offline-20261002-v1",
        items=[dict(item_id=WID,category="hymns",acceptance_path=(EDITION/"acceptance.json").as_posix(),public_notices=[notices])])
    if notice_texts_for_item(ROOT,selection["items"][0],ROOT/EDITION/"acceptance.json") != [(ROOT/DATA_NOTICE).read_text(encoding="utf-8")]:
        raise ValueError("Chinook paired notice differs")
    relative_inputs=[*[(WORK/Path(path)).as_posix() for path in installation["installed_files"]],
        SOURCE_NOTICE.as_posix(),DATA_NOTICE.as_posix(),
        "sources/manifest-acquisitions/l744-pg33105-chinook-hymns/source-manifest.json",
        "sources/manifest-acquisitions/l744-pg33105-chinook-hymns/policy.json",
        "sources/manifest-acquisitions/l744-pg33105-chinook-hymns/profile.json",
        "raw/gutenberg/33105/pg33105-h.zip","raw/gutenberg/33105/html/pg33105-images.html",
        "raw/gutenberg/33105/html/33105-cover.png","raw/gutenberg/33105/acquisition-receipt.json","raw/gutenberg/33105/member-inventory.tsv",
        "build/tools/complete_chinook_private_release.py","build/tools/check_release_reader.py","build/tools/report_release_stats.py",
        "build/tei/l744_hymns.py","build/tei/l744_hymns_oracle.py",
        "ocd_kernel/projection/categories/chinook_hymns.py","ocd_kernel/projection/categories/hymns.py",
        "ocd_kernel/release/assemble.py","ocd_kernel/release/verify.py","ocd_kernel/release/notices.py",
        "ocd_kernel/release/selection.py","ocd_kernel/release/public_allowlist.py","ocd_kernel/release/typed_rows.py","ocd_kernel/release/features.py",
        "ocd_kernel/tei/acceptance.py","ocd_kernel/tei/install_accepted.py",
        "schemas/v2/categories/hymns.schema.json","schemas/v2/public-row.schema.json","schemas/v2/release-selection.schema.json"]
    # Resolve runtime filenames from the installed source tree; reject missing inputs explicitly.
    for relative in relative_inputs:
        if not (ROOT/relative).is_file():
            raise ValueError(f"Required Chinook release input missing: {relative}")
    inputs={relative:digest((ROOT/relative).read_bytes()) for relative in relative_inputs}
    OUT.mkdir(parents=True)
    save(OUT/"selection.json",selection)
    save(OUT/"input-bindings-before.json",inputs)
    save(OUT/"projection.json",output)
    release=OUT/"release"
    assembly=assemble_release_v2(ROOT,release,selection=selection)
    save(OUT/"assembly.json",assembly)
    if assembly["status"] != "pass" or assembly["items"][0]["row_count"] != 20:
        raise ValueError("Chinook 20-row assembly failed")
    print("assembly: pass",flush=True)
    for name,operation in (("independent-verification",lambda:verify_release_v2(ROOT,release,selection=selection)),
            ("statistics",lambda:release_statistics(ROOT,release,selection)),("readers",lambda:check_reader(ROOT,release,selection))):
        result=operation()
        save(OUT/(name+".json"),result)
        if result["status"] != "pass":
            raise ValueError(f"Chinook release {name} failed: {result}")
        print(name+": pass",flush=True)
    for relative,expected in inputs.items():
        if digest((ROOT/relative).read_bytes()) != expected:
            raise ValueError(f"Chinook release input drifted: {relative}")
    files={path.relative_to(release).as_posix():digest(path.read_bytes()) for path in release.rglob("*") if path.is_file()}
    save(OUT/"release-file-bindings.json",files)
    stats=json.loads((OUT/"statistics.json").read_bytes())
    completion=dict(contract="ocd-pg33105-chinook-private-offline-completion-v1",status="pass",work_id=WID,
        checked_at=datetime.now(timezone.utc).isoformat(),accepted_master_sha256=accepted["promotion"]["master"]["sha256"],
        acceptance_sha256=digest((ROOT/EDITION/"acceptance.json").read_bytes()),selection_sha256=digest((OUT/"selection.json").read_bytes()),
        rows=20,sections=40,source_verse_stanzas=195,text_characters=stats["total"]["text_characters"],release_path=str(release),
        private_offline=True,publication_performed=False,human_decision="not-recorded",rights_clearance="unresolved",
        print_collation="unverified; no retained page scans",row_scope="20 numbered hymn/translation pairs; all non-hymn matter and interlinear prayers retained in full master outside these rows",
        source_notice_sha256=notices["source_sha256"],public_notice_sha256=notices["notice_sha256"],
        input_bindings=inputs,release_file_bindings=files,
        gate_bindings={name:digest((OUT/(name+".json")).read_bytes()) for name in ("assembly","independent-verification","statistics","readers")})
    save(OUT/"completion.json",completion)
    save(ROOT/WORK/"publication/completion.json",completion)
    print(json.dumps(dict(status="pass",rows=20,text_characters=completion["text_characters"],release_files=len(files),completion_sha256=digest((OUT/"completion.json").read_bytes())),indent=2),flush=True)

if __name__ == "__main__":
    main()
