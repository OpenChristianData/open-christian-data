"""Complete one installed Green witness through the maintained private pipeline."""

from datetime import datetime, timezone
import json
from pathlib import Path

from build.tools.prepare_green_current import ROOT, LOG, WORK_ID, digest, save, json_bytes
from build.tools.stage_green_current_acceptance import WORK, EDITION, SOURCE_SHA
from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _files


OUT = ROOT / "reports/_logs/elisha-w-green-life-1888-private-release-20261002-v1"
DATA_NOTICE = Path("data/prose") / WORK_ID / "README.md"
SOURCE_NOTICE = Path("sources/prose") / WORK_ID / "README.source.md"
SOURCE = ROOT / "raw/docsouth/l763-greenew-exact-1888/greenew.xml"


def hash_path(path):
    return digest(io_path(path).read_bytes())


def main() -> None:
    if OUT.exists() or (ROOT / WORK / "publication/completion.json").exists():
        raise FileExistsError("Private output/completion exists; inspect rather than repeat gates")
    installed_path = LOG / "canonical-install/installed-generation.json"
    installed = json.loads(installed_path.read_bytes())
    if installed["status"] != "pass" or _files(ROOT / WORK) != installed["installed_files"]:
        raise ValueError("Current installed generation differs")
    acceptance = ROOT / EDITION / "acceptance.json"
    master = ROOT / EDITION / "master.tei.xml"
    if hash_path(master) != installed["master_sha256"] or hash_path(SOURCE) != SOURCE_SHA:
        raise ValueError("Installed master/source/runtime drifted")
    notice = (ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    notice_binding = {"source_path": SOURCE_NOTICE.as_posix(), "source_sha256": hash_path(ROOT / SOURCE_NOTICE), "notice_path": DATA_NOTICE.as_posix(), "notice_sha256": hash_path(ROOT / DATA_NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "elisha-w-green-life-1888-private-offline-20261002-v1", "items": [{"item_id": WORK_ID, "category": "prose", "acceptance_path": (EDITION / "acceptance.json").as_posix(), "public_notices": [notice_binding]}]}
    if notice_texts_for_item(io_path(ROOT), selection["items"][0], io_path(acceptance)) != [notice]:
        raise ValueError("Maintained notice preflight differs")
    OUT.mkdir(parents=True)
    save(OUT / "selection.json", json_bytes(selection))
    save(ROOT / WORK / "publication/selection.json", json_bytes(selection))
    before = {WORK.as_posix() + "/" + path: value for path, value in installed["installed_files"].items()}
    direct_inputs = [SOURCE, ROOT / DATA_NOTICE, ROOT / SOURCE_NOTICE, installed_path, LOG / "coordinator-install-clearance.json", LOG / "install-rollback-proof.json", LOG / "repaired-handoff-proof.json", LOG / "source-relationship-review.json", ROOT / "build/tools/check_green_relationships.py", ROOT / WORK / "publication/selection.json", Path(__file__)]
    direct_inputs += [ROOT / path for path in ("ocd_kernel/projection/categories/prose.py", "ocd_kernel/projection/categories/native_documents.py", "ocd_kernel/projection/categories/sermons.py", "ocd_kernel/projection/native_content.py", "ocd_kernel/projection/native_content_check.py", "ocd_kernel/tei/acceptance.py", "ocd_kernel/library/identities.py", "ocd_kernel/library/acquisitions.py", "ocd_kernel/library/state.py", "ocd_kernel/library/_common.py", "ocd_kernel/lib/storage_topology.py", "ocd_kernel/release/assemble.py", "ocd_kernel/release/verify.py", "ocd_kernel/release/notices.py", "ocd_kernel/release/selection.py", "ocd_kernel/release/typed_rows.py", "build/tools/check_release_reader.py", "build/tools/report_release_stats.py", "schemas/v2/native-content.schema.json", "schemas/v2/categories/prose.schema.json", "schemas/v2/public-row.schema.json", "schemas/v2/release-selection.schema.json", "schemas/v2/release-report.schema.json", "build/tei/green_header_archive.py", "build/tools/install_green_current.py", "build/tools/stage_green_current_acceptance.py")]
    direct_inputs += list(LOG.glob("coordinator-*.json"))
    direct_inputs.append(LOG / "active-header-source-field-review.json")
    direct_inputs += [LOG / "current-checker-refresh/current-candidate-proof-v3.json", LOG / "final-preinstall-manifest.json", ROOT / "build/tools/refresh_green_preinstall_proof.py"]
    direct_inputs += list((ROOT / "reports/_logs/green-coordinator-source-review-20261002-v1").glob("*.json"))
    direct_inputs += list((ROOT / "sources/manifest-acquisitions/docsouth-l763-greenew-exact-1888").glob("*"))
    for path in direct_inputs:
        if path.is_dir(): continue
        before[path.relative_to(ROOT).as_posix()] = hash_path(path)
    save(OUT / "authority-before.json", json_bytes(before))
    save(OUT / "notice-gate.json", json_bytes({"status": "pass", "binding": notice_binding, "structured_source_rights": "unresolved", "public_publication_authorized": False}))
    with cached_edition_lookups():
        actual = project_accepted_prose(io_path(ROOT), acceptance_path=io_path(acceptance))
        errors = verify_accepted_prose(io_path(ROOT), acceptance_path=io_path(acceptance), rows=actual["rows"], receipt=actual["receipt"])
        if errors or len(actual["rows"]) != 13 or sum(len(row["text"]) for row in actual["rows"]) != 155586:
            raise ValueError(f"Actual installed-master linkage failed: {errors}")
        saved_projection = json.loads(io_path(ROOT / WORK / "integration/green-accepted-v1/stage-projection.json").read_bytes())
        if actual != saved_projection:
            raise ValueError("Canonical projection differs from exact reviewed staged projection")
        save(OUT / "actual-master-projection.json", json_bytes(actual))
        save(OUT / "actual-master-linkage.json", json_bytes({"status": "pass", "canonical_projection_equals_staged": True, "master_sha256": hash_path(master), "acceptance_sha256": hash_path(acceptance), "rows": 13, "text_characters": 155586, "authority": actual["receipt"]["authority"]}))
        print("actual-master projection and independent linkage: PASS", flush=True)
        release = OUT / "release"
        assembled = assemble_release_v2(io_path(ROOT), release, selection=selection)
        save(OUT / "assembly.json", json_bytes(assembled))
        if assembled["status"] != "pass": raise ValueError(assembled)
        print("assembly: PASS", flush=True)
        for name, operation in (("independent-verification", lambda: verify_release_v2(io_path(ROOT), release, selection=selection)), ("statistics", lambda: release_statistics(io_path(ROOT), release, selection)), ("readers", lambda: check_reader(io_path(ROOT), release, selection))):
            result = operation()
            save(OUT / (name + ".json"), json_bytes(result))
            if result["status"] != "pass": raise ValueError(f"{name}: {result}")
            print(name + ": PASS", flush=True)
    public_readme = (release / "public/README.md").read_text(encoding="utf-8")
    if notice.rstrip() not in public_readme:
        raise ValueError("Released visible credit/rights wording missing")
    save(OUT / "released-notice-check.json", json_bytes({"status": "pass", "notice_sha256": hash_path(ROOT / DATA_NOTICE), "public_readme_sha256": hash_path(release / "public/README.md")}))
    for path, expected in before.items():
        if hash_path(ROOT / path) != expected: raise ValueError("Release input drifted: " + path)
    release_files = {path.relative_to(release).as_posix(): hash_path(path) for path in release.rglob("*") if path.is_file()}
    stats = json.loads((OUT / "statistics.json").read_bytes())
    if stats["total"]["text_characters"] != 155586:
        raise ValueError("Whole retained-volume character count differs")
    completion = {"status": "pass", "contract": "ocd-green-private-offline-completion-v1", "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": WORK_ID, "source_sha256": SOURCE_SHA, "accepted_master_sha256": hash_path(master), "acceptance_sha256": hash_path(acceptance), "rows": 13, "text_characters": 155586, "text_characters": 155586, "release_path": release.as_posix(), "private_offline": True, "rights_clearance": "unresolved", "human_decision": "not-recorded", "publication_performed": False, "input_bindings": before, "release_file_bindings": release_files}
    save(OUT / "release-file-hashes.json", json_bytes(release_files))
    save(OUT / "completion.json", json_bytes(completion))
    save(ROOT / WORK / "publication/completion.json", json_bytes(completion))
    save(OUT / "README.md", ("# Green retained electronic volume: private offline completion\n\n"
        "The complete already-retained electronic volume passes canonical accepted-master projection, independent linkage, offline assembly, independent verification, statistics, and normal and streaming readers. Its 13 rows contain 155,586 text characters.\n\n"
        "The historical 570-node text tree is conserved by the exact 21-alias inverse. The 99-element historical header is archived in a canonical annotated representation with exact inverse serialization; the active header independently binds the literal source roles and current acquisition. Three source image URLs remain represented, with binaries unretained.\n\n"
        "Human acceptance, worldwide rights clearance, source-described print collation, image verification and public publication remain unresolved or unperformed. The paired visible source/data notice reproduces the provider's U.S.-law rights statement and distinguishes the author, funder, transcription, scanning, encoding and electronic publisher.\n\n"
        "Read completion.json and final-current-binding-audit.json for exact current authority and release-file hashes. Source proofs, installation clearance, isolated rollback and coordinator installed-generation review are bound there. No new acquisition or source conversion was performed.\n").encode())
    evidence_files = {path.relative_to(OUT).as_posix(): hash_path(path) for path in OUT.rglob("*") if path.is_file() and path.name not in {"release.stdout.log", "release.stdout.log.exit"}}
    final = {"status": "pass", "root_bindings": before, "release_base": release.as_posix(), "release_bindings": release_files, "output_base": OUT.as_posix(), "output_bindings": evidence_files, "canonical_completion_path": (WORK / "publication/completion.json").as_posix(), "canonical_completion_sha256": hash_path(ROOT / WORK / "publication/completion.json"), "release_gates_complete": True, "stdout_log_excluded_from_input_bindings": True}
    save(OUT / "final-current-binding-audit.json", json_bytes(final))
    print(json.dumps({"status": "pass", "rows": 13, "characters": 155586, "input_bindings": len(before), "release_files": len(release_files), "output_bindings": len(evidence_files), "completion_sha256": digest(json_bytes(completion))}), flush=True)


if __name__ == "__main__":
    main()
