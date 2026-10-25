"""Verify one installed A23804 private offline release with maintained gates."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tools.stage_whole_duty_prayer_acceptance import ROOT, WORK, WORK_ID, EDITION, SOURCE, SOURCE_SHA256
from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError, io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prayers import project_accepted_prayers, verify_accepted_prayers
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.install_accepted import _files, _io_path

LOG = ROOT / "reports/_logs/whole-duty-prayer-private-release-20261003-v2"
PUB = WORK / "publication"
NOTICE_SOURCE = Path("sources/structured-text/whole-duty-of-prayer/README.source.md")
NOTICE_DATA = Path("data/prayers/whole-duty-of-prayer/README.md")
EVIDENCE = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence")


def digest(path):
    return sha256(_io_path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(_io_path(path).read_bytes())


def save(path, value):
    target = _io_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@cached_edition_lookups()
def main():
    if _io_path(LOG).exists() or _io_path(ROOT / PUB / "completion.json").exists():
        raise FileExistsError("Reconcile an existing A23804 release before rerunning")
    install = read(ROOT / EVIDENCE / "L788_WHOLE_DUTY_PRAYER_INSTALL_READBACK_20261003.json")
    reproduction = read(ROOT / EVIDENCE / "L788_WHOLE_DUTY_PRAYER_FROZEN_LINKAGE_REPRODUCTION_20261003.json")
    generation = _files(ROOT / WORK)
    if (install["status"] != "pass-installed-agent-electronic-witness"
            or generation != install["installation"]["installed_files"]
            or len(generation) != 35 or reproduction["status"] != "pass"
            or reproduction["source_manifest_sha256"] != "16f7fcb00c2df7d87ce220fb735892b08a9d269c0a5d6e66f539b20f43e9c807"
            or reproduction["source_sha256"] != SOURCE_SHA256
            or reproduction["candidate_package_sha256"] != "cfa8bf2de639834e732447688a6c670c545b409960d1061595a34ac155fe0344"
            or reproduction["replay_package_sha256"] != reproduction["candidate_package_sha256"]
            or reproduction["installed_master_sha256"] != install["master_sha256"]
            or not reproduction["all_seven_files_exact"]
            or not reproduction["all_five_payloads_unchanged"]
            or digest(ROOT / SOURCE) != SOURCE_SHA256):
        raise PipelineError("A23804 current install/reproduction/source authority differs")
    # The source note directs readers to the separately reviewed public-safe credit.
    destination = _io_path(ROOT / NOTICE_DATA)
    if (digest(ROOT / NOTICE_SOURCE) != "166fcb3cebc49c59df29b867870aef4a997023499f3ac4eecb279289e0a9b41a"
            or digest(destination) != "50d860fabaed596567a5fc42ebccd8dcb8dd356d1f3ddc6cf9c343e6983f242b"):
        raise PipelineError("A23804 reviewed source/data notice differs")
    before = {(WORK / path).as_posix(): value for path, value in generation.items()}
    manifest_path = ROOT / "sources/structured-text/whole-duty-of-prayer/whole-duty-of-prayer.source-manifest.frozen-linkage-20261003.json"
    manifest = SourceManifest.load(manifest_path, repository_root=ROOT)
    before[manifest_path.relative_to(ROOT).as_posix()] = manifest.sha256
    for authority in manifest.record["authorities"]:
        before[authority["path"]] = authority["sha256"]
    before[NOTICE_DATA.as_posix()] = digest(ROOT / NOTICE_DATA)
    before[NOTICE_SOURCE.as_posix()] = digest(ROOT / NOTICE_SOURCE)
    for path in (EVIDENCE / "L788_WHOLE_DUTY_PRAYER_INSTALL_READBACK_20261003.json",
                 EVIDENCE / "L788_WHOLE_DUTY_PRAYER_FROZEN_LINKAGE_REPRODUCTION_20261003.json"):
        before[path.as_posix()] = digest(ROOT / path)
    implementation_paths = [
        "build/tools/complete_whole_duty_prayer_private_release.py",
        "build/tools/check_release_reader.py", "build/tools/report_release_stats.py",
        "ocd_kernel/projection/categories/prayers.py", "ocd_kernel/projection/categories/native_documents.py",
        "ocd_kernel/projection/native_content.py", "ocd_kernel/projection/native_content_check.py",
        "ocd_kernel/release/assemble.py", "ocd_kernel/release/verify.py", "ocd_kernel/release/notices.py",
        "ocd_kernel/tei/acceptance.py", "ocd_kernel/library/identities.py", "ocd_kernel/library/state.py",
        "build/tei/whole_duty_prayer_native_adapter.py", "ocd_kernel/tei/reviewed_integration.py",
        "ocd_kernel/__init__.py", "ocd_kernel/reconstruction/__init__.py", "ocd_kernel/reconstruction/contract.py",
    ]
    implementation_paths.extend(manifest.record[role]["implementation_path"] for role in ("converter", "validator"))
    frozen = {path: digest(ROOT / path) for path in implementation_paths}
    for schema in io_glob(ROOT / "schemas/v2", "**/*.json"):
        frozen[schema.relative_to(ROOT).as_posix()] = digest(schema)
    request = dict(schema_version="2.0", release_id="whole-duty-prayer-private-offline-20261003-v2",
        items=[dict(item_id=WORK_ID, category="prayers", acceptance_path=(EDITION / "acceptance.json").as_posix(),
            public_notices=[dict(source_path=NOTICE_SOURCE.as_posix(), source_sha256=digest(ROOT / NOTICE_SOURCE),
                notice_path=NOTICE_DATA.as_posix(), notice_sha256=digest(ROOT / NOTICE_DATA))])])
    save(LOG / "authority-before.json", before)
    save(LOG / "implementation-schema-before.json", frozen)
    save(LOG / "selection.json", request)
    projection = project_accepted_prayers(ROOT, acceptance_path=ROOT / EDITION / "acceptance.json")
    errors = verify_accepted_prayers(ROOT, acceptance_path=ROOT / EDITION / "acceptance.json",
        rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 6:
        raise PipelineError(f"A23804 canonical native projection differs: {errors[:3]}")
    save(LOG / "actual-master-projection.json", projection)
    print("A23804 canonical native projection/checker: pass", flush=True)
    output = LOG / "release"
    for name, operation in (
        ("assembly", lambda: assemble_release_v2(ROOT, output, selection=request)),
        ("independent-verification", lambda: verify_release_v2(ROOT, output, selection=request)),
        ("statistics", lambda: release_statistics(ROOT, output, request)),
        ("readers", lambda: check_reader(ROOT, output, request)),
    ):
        result = operation()
        save(LOG / (name + ".json"), result)
        if result.get("status") != "pass":
            raise PipelineError(f"A23804 {name} failed: {result}")
        print(f"A23804 {name}: pass", flush=True)
    if (any(digest(ROOT / path) != value for path, value in before.items())
            or any(digest(ROOT / path) != value for path, value in frozen.items())
            or _files(ROOT / WORK) != generation):
        raise PipelineError("A23804 inputs or installed generation changed during release")
    completion = dict(status="offline-verified-not-authorized-for-publication", checked_at=datetime.now(timezone.utc).isoformat(),
        work_id=WORK_ID, source_sha256=SOURCE_SHA256, master_sha256=install["master_sha256"],
        acceptance_sha256=install["acceptance_sha256"], projection_rows=6, release=output.as_posix(),
        reader_normal_and_streaming="pass", input_bindings=before, implementation_schema_bindings=frozen,
        release_files=_files(output), human_acceptance="not-recorded", rights_clearance="not-recorded",
        print_collation="not-performed", public_publication=False)
    save(LOG / "completion.json", completion)
    save(ROOT / PUB / "selection.json", request)
    save(ROOT / PUB / "completion.json", completion)
    print(json.dumps({"status": completion["status"], "release": str(output)}))


if __name__ == "__main__":
    main()
