"""Complete one installed Nave witness through the maintained private pipeline."""

from datetime import datetime, timezone
import json
from pathlib import Path

from build.tools.prepare_nave_current import ROOT, LOG, WORK_ID, digest, save, json_bytes
from build.tools.stage_nave_current_acceptance import WORK, EDITION, ADAPTER_SHA, DISPATCH_SHA, SOURCE_SHA
from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.topical_indexes import project_accepted_topical_indexes, verify_accepted_topical_indexes
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _files


OUT = ROOT / "reports/_logs/naves-topical-bible-private-release-20261002-v1"
DATA_NOTICE = Path("data/topical_indexes") / WORK_ID / "README.md"
SOURCE_NOTICE = Path("sources/topical-indexes") / WORK_ID / "README.source.md"
SOURCE = ROOT / EDITION / "source-member-set.json"


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
    if hash_path(master) != installed["master_sha256"] or hash_path(SOURCE) != SOURCE_SHA or hash_path(ROOT / "ocd_kernel/projection/categories/topical_indexes.py") != DISPATCH_SHA or hash_path(ROOT / "ocd_kernel/projection/categories/topical_nave.py") != ADAPTER_SHA:
        raise ValueError("Installed master/source/runtime drifted")
    notice = (ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    notice_binding = {"source_path": SOURCE_NOTICE.as_posix(), "source_sha256": hash_path(ROOT / SOURCE_NOTICE), "notice_path": DATA_NOTICE.as_posix(), "notice_sha256": hash_path(ROOT / DATA_NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "naves-topical-bible-private-offline-20261002-v1", "items": [{"item_id": WORK_ID, "category": "topical_indexes", "acceptance_path": (EDITION / "acceptance.json").as_posix(), "public_notices": [notice_binding]}]}
    if notice_texts_for_item(io_path(ROOT), selection["items"][0], io_path(acceptance)) != [notice]:
        raise ValueError("Maintained notice preflight differs")
    OUT.mkdir(parents=True)
    save(OUT / "selection.json", json_bytes(selection))
    save(ROOT / WORK / "publication/selection.json", json_bytes(selection))
    before = {WORK.as_posix() + "/" + path: value for path, value in installed["installed_files"].items()}
    direct_inputs = [SOURCE, ROOT / DATA_NOTICE, ROOT / SOURCE_NOTICE, installed_path, LOG / "coordinator-install-clearance.json", LOG / "install-rollback-proof.json", LOG / "native-support-proposal-v2/coordinator-adapter-clearance.json", ROOT / "reports/_logs/nave-coordinator-source-review-20261002-v1/review.json", ROOT / WORK / "publication/selection.json", Path(__file__)]
    direct_inputs += [ROOT / path for path in ("ocd_kernel/projection/categories/topical_indexes.py", "ocd_kernel/projection/categories/topical_nave.py", "ocd_kernel/tei/acceptance.py", "ocd_kernel/library/identities.py", "ocd_kernel/library/acquisitions.py", "ocd_kernel/library/state.py", "ocd_kernel/library/_common.py", "ocd_kernel/lib/storage_topology.py", "ocd_kernel/release/assemble.py", "ocd_kernel/release/verify.py", "ocd_kernel/release/notices.py", "ocd_kernel/release/selection.py", "ocd_kernel/release/typed_rows.py", "build/tools/check_release_reader.py", "build/tools/report_release_stats.py", "schemas/v2/categories/topical-indexes.schema.json", "schemas/v2/public-row.schema.json", "schemas/v2/release-selection.schema.json", "schemas/v2/release-report.schema.json")]
    direct_inputs += sorted((ROOT / "sources" / WORK_ID).glob("*"))
    direct_inputs += sorted((ROOT / "raw/naves_topical/modules/lexdict/zld/nave").glob("*"))
    direct_inputs += [ROOT / "raw/naves_topical/mods.d/nave.conf", ROOT / "raw/naves_topical/Nave.zip", LOG / "category-prerequisite-result.json"] if (LOG / "category-prerequisite-result.json").exists() else [ROOT / "raw/naves_topical/mods.d/nave.conf", ROOT / "raw/naves_topical/Nave.zip"]
    coordinator_install = LOG / "coordinator-installed-generation-review.json"
    if coordinator_install.exists():
        direct_inputs.append(coordinator_install)
    for path in direct_inputs:
        if path.is_dir(): continue
        before[path.relative_to(ROOT).as_posix()] = hash_path(path)
    save(OUT / "authority-before.json", json_bytes(before))
    save(OUT / "notice-gate.json", json_bytes({"status": "pass", "binding": notice_binding, "structured_source_rights": "unresolved", "public_publication_authorized": False}))
    with cached_edition_lookups():
        actual = project_accepted_topical_indexes(io_path(ROOT), acceptance_path=io_path(acceptance))
        errors = verify_accepted_topical_indexes(io_path(ROOT), acceptance_path=io_path(acceptance), rows=actual["rows"], receipt=actual["receipt"])
        if errors or len(actual["rows"]) != 5322 or sum(len(item["references"]) for row in actual["rows"] for item in row["items"]) != 82303:
            raise ValueError(f"Actual installed-master linkage failed: {errors}")
        saved_projection = json.loads(io_path(ROOT / WORK / "integration/nave-accepted-v1/stage-projection.json").read_bytes())
        if actual != saved_projection:
            raise ValueError("Canonical projection differs from exact reviewed staged projection")
        save(OUT / "actual-master-projection.json", json_bytes(actual))
        save(OUT / "actual-master-linkage.json", json_bytes({"status": "pass", "canonical_projection_equals_staged": True, "master_sha256": hash_path(master), "acceptance_sha256": hash_path(acceptance), "rows": 5322, "literal_references": 82303, "authority": actual["receipt"]["authority"]}))
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
    if stats["total"]["text_characters"] != 1410060:
        raise ValueError("Whole definition-character count differs")
    completion = {"status": "pass", "contract": "ocd-nave-private-offline-completion-v1", "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": WORK_ID, "source_sha256": SOURCE_SHA, "accepted_master_sha256": hash_path(master), "acceptance_sha256": hash_path(acceptance), "rows": 5322, "literal_references": 82303, "text_characters": 1410060, "release_path": release.as_posix(), "private_offline": True, "rights_clearance": "unresolved", "human_decision": "not-recorded", "publication_performed": False, "input_bindings": before, "release_file_bindings": release_files}
    save(OUT / "release-file-hashes.json", json_bytes(release_files))
    save(OUT / "completion.json", json_bytes(completion))
    save(ROOT / WORK / "publication/completion.json", json_bytes(completion))
    evidence_files = {path.relative_to(OUT).as_posix(): hash_path(path) for path in OUT.rglob("*") if path.is_file()}
    final = {"status": "pass", "root_bindings": before, "release_base": release.as_posix(), "release_bindings": release_files, "output_base": OUT.as_posix(), "output_bindings": evidence_files, "canonical_completion_path": (WORK / "publication/completion.json").as_posix(), "canonical_completion_sha256": hash_path(ROOT / WORK / "publication/completion.json"), "release_gates_complete": True, "stdout_log_excluded_from_input_bindings": True}
    save(OUT / "final-current-binding-audit.json", json_bytes(final))
    print(json.dumps({"status": "pass", "rows": 5322, "characters": 1410060, "input_bindings": len(before), "release_files": len(release_files), "output_bindings": len(evidence_files), "completion_sha256": digest(json_bytes(completion))}), flush=True)


if __name__ == "__main__":
    main()
