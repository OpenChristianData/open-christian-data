"""Complete Apostolic Tradition's accepted electronic text as a private offline release."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library.state import validate_state
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/apostolic-tradition")
EDITION = WORK / "forms/apostolic-tradition-gutenberg-retained/editions/apostolic-tradition-gutenberg-electronic"
OUT = ROOT / "reports/_logs/apostolic-tradition-private-release-20261002-v1"
LOG = Path("reports/_logs/apostolic-tradition-current-reconciliation-20261002-v1")
SOURCE = Path("raw/gutenberg/61614/html/pg61614-images.html")
SOURCE_MANIFEST = Path("sources/apostolic-tradition/apostolic-tradition.source-manifest.json")
DATA_NOTICE = Path("data/prose/apostolic-tradition/README.md")
SOURCE_NOTICE = Path("sources/prose/apostolic-tradition/README.source.md")
SOURCE_CREDIT = WORK / "SOURCE_CREDIT.md"
SOURCE_SHA = "820d396c5f69ff601cf2264cb8ed352765c49809a69fda8f616b746e07b9cd05"
SOURCE_MANIFEST_SHA = "2d4f58910dc1152bedabbca6a17d19044f0806636c30bdcf488920ac23e98576"
MASTER_SHA = "89d3ac7c301c7fe62dd465327830b206b697e8cb42d963ce697ca5c449664d5a"
ACCEPTANCE_SHA = "d7b2bfa02b5a1ff4f5f3f34babdc459f0acbad091cf7eee435390a49d6922151"
WORK_SHA = "dddd0755a5adea52112c04e9ea353074af2aac68dc627f82c326efa92dbc4fd8"
SOURCE_CREDIT_SHA = "5751cd335bafe91af16536b28f51b288023576a5726c312a24cf2a0566a604ea"
SOURCE_NOTICE_SHA = "dac9d445cf9aecca2582b82a07ea7a541bb0ec3e212017abd21b4d71a2b1e236"
DATA_NOTICE_SHA = "baf8013271b8e184a5382246d35130ad48908a103b6b025cd8bd2f1f149ad9e7"
STAGE_MAP_SHA = "4521b10f26a6ed95720a0f25558b941fa20cf094e1cde8d52897d1fd1f9eaba4"
STAGE_RECEIPT_SHA = "f2611afafd2bdc80a59907dcc1dfcc65ff243e2d90a29531753cc5514b020dad"
INSTALLED_SHA = "5061217ab3c6eeffb1b161a27eed1eaf291efc1218854bef66d18d7427390e5d"
DATA_NOTICE_INSTALL_SHA = "23f47b4d5c155ef5617469da7bc3d04e1d457346c23d202325d87de2aa8b96ac"
V6_FREEZE_SHA = "39ccc693ad3b83018de6f43f3e8daee0c00a681bc5ab1de2c51ab823d1c314da"
NOTICE_REVISION_FREEZE_SHA = "dc9e46adff6c41a36cf60ebb3c670b80d8b6d0129a774e4a6ef6e620f45498d9"
NOTICE_PROBE_SHA = "75c44f4f46a2167eb74d87e98b52a569fa5e415dd148f1909d58c29fa235cc84"
RELEASE_FREEZE = LOG / "proposal/release-freeze-v5.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    if (OUT.exists() or (ROOT / WORK / "publication/selection.json").exists()
            or (ROOT / WORK / "publication/completion.json").exists()):
        raise FileExistsError("Apostolic private release or completion exists; inspect before rerun")
    authority = {
        ROOT / SOURCE: SOURCE_SHA,
        ROOT / SOURCE_MANIFEST: SOURCE_MANIFEST_SHA,
        ROOT / EDITION / "master.tei.xml": MASTER_SHA,
        ROOT / EDITION / "acceptance.json": ACCEPTANCE_SHA,
        ROOT / WORK / "work.json": WORK_SHA,
        ROOT / SOURCE_CREDIT: SOURCE_CREDIT_SHA,
        ROOT / SOURCE_NOTICE: SOURCE_NOTICE_SHA,
        ROOT / DATA_NOTICE: DATA_NOTICE_SHA,
        ROOT / LOG / "stage-v3-map.json": STAGE_MAP_SHA,
        ROOT / LOG / "stage-receipt-v3.json": STAGE_RECEIPT_SHA,
        ROOT / LOG / "installed-generation-v1.json": INSTALLED_SHA,
        ROOT / LOG / "data-notice-install-result.json": DATA_NOTICE_INSTALL_SHA,
        ROOT / LOG / "proposal/stage-evidence-freeze-v6.json": V6_FREEZE_SHA,
        ROOT / LOG / "rights-notice-revision-v3.json": NOTICE_REVISION_FREEZE_SHA,
        ROOT / LOG / "notice-contract-probe-v3.json": NOTICE_PROBE_SHA,
    }
    for path, expected in authority.items():
        if digest(path) != expected:
            raise ValueError(f"Apostolic private release authority drifted: {path}")
    freeze = json.loads((ROOT / RELEASE_FREEZE).read_text(encoding="utf-8"))
    if (freeze["status"] != "review-ready-release-not-started"
            or freeze["driver_sha256"] != digest(Path(__file__))
            or freeze["expected_source_notice_sha256"] != SOURCE_NOTICE_SHA
            or freeze["expected_data_notice_sha256"] != DATA_NOTICE_SHA):
        raise ValueError("reviewed one-work release freeze differs")
    data_revision = json.loads((ROOT / LOG / "data-notice-revision-v3-result.json").read_text(encoding="utf-8"))
    source_notice_install = json.loads((ROOT / LOG / "source-notice-install-v3-result.json").read_text(encoding="utf-8"))
    if (data_revision["status"] != "applied-and-readback"
            or data_revision["successor_sha256"] != DATA_NOTICE_SHA
            or source_notice_install["status"] != "installed-and-readback"
            or source_notice_install["sha256"] != SOURCE_NOTICE_SHA
            or source_notice_install["paired_data_notice_sha256"] != DATA_NOTICE_SHA):
        raise ValueError("paired notice revision receipts differ")
    acceptance = ROOT / EDITION / "acceptance.json"
    validate_acceptance(acceptance, root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    notice = (ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    notice_binding = {"source_path": SOURCE_NOTICE.as_posix(),
                      "source_sha256": SOURCE_NOTICE_SHA,
                      "notice_path": DATA_NOTICE.as_posix(),
                      "notice_sha256": DATA_NOTICE_SHA}
    selection = {"schema_version": "2.0",
                 "release_id": "apostolic-tradition-private-offline-20261002-v1",
                 "items": [{"item_id": "apostolic-tradition", "category": "prose",
                            "acceptance_path": (EDITION / "acceptance.json").as_posix(),
                            "public_notices": [notice_binding]}]}
    if notice_texts_for_item(ROOT, selection["items"][0], acceptance) != [notice]:
        raise ValueError("Apostolic visible rights/attribution notice differs")
    OUT.mkdir(parents=True, exist_ok=True)
    save(OUT / "selection.json", selection)
    save(ROOT / WORK / "publication/selection.json", selection)
    if (OUT / "selection.json").read_bytes() != (ROOT / WORK / "publication/selection.json").read_bytes():
        raise ValueError("Apostolic canonical release selection differs from report copy")
    save(OUT / "notice-gate.json", {"status": "pass", "binding": notice_binding,
                                    "title_page_1934_1962_notices": "retained",
                                    "provider_us_public_domain_label": "retained",
                                    "rights_unresolved": ["underlying work", "Easton translation",
                                                          "Easton introduction, notes, and other editorial matter",
                                                          "exact edition and printing", "retained electronic transcription",
                                                          "cover image", "reuse in intended territory"],
                                    "human_decision": "not-recorded",
                                    "public_publication_authorized": False})
    before = {WORK.as_posix() + "/" + path: sha for path, sha in _files(ROOT / WORK).items()
              if path != "publication/selection.json"}
    extra = [SOURCE, SOURCE_MANIFEST, DATA_NOTICE, SOURCE_NOTICE, SOURCE_CREDIT,
             Path("ocd_kernel/projection/categories/apostolic_tradition.py"),
             Path("ocd_kernel/projection/categories/apostolic_tradition_check.py"),
             Path("ocd_kernel/projection/categories/prose.py"),
             Path("ocd_kernel/projection/categories/native_documents.py"),
             Path("ocd_kernel/release/assemble.py"), Path("ocd_kernel/release/verify.py"),
             Path("ocd_kernel/release/notices.py"),
             Path("schemas/v2/categories/prose.schema.json"),
             Path("schemas/v2/public-row.schema.json"),
             Path("schemas/v2/native-content.schema.json"),
             Path("build/tools/report_release_stats.py"),
             Path("build/tools/check_release_reader.py"),
             Path("build/tools/complete_apostolic_tradition_private_release.py")]
    before.update({path.as_posix(): digest(ROOT / path) for path in extra})
    before.update({relative.as_posix(): digest(ROOT / relative) for relative in (
        LOG / "stage-v3-map.json", LOG / "stage-receipt-v3.json",
        LOG / "installed-generation-v1.json", LOG / "data-notice-install-result.json",
        LOG / "proposal/stage-evidence-freeze-v6.json",
        LOG / "rights-notice-revision-v3.json",
        LOG / "notice-contract-probe-v3.json",
        LOG / "data-notice-revision-v3-result.json",
        LOG / "source-notice-install-v3-result.json", RELEASE_FREEZE)})
    save(OUT / "authority-before.json", before)
    release = OUT / "release"
    assembled = assemble_release_v2(ROOT, release, selection=selection)
    save(OUT / "assembly.json", assembled)
    if assembled["status"] != "pass":
        raise ValueError(f"Apostolic private assembly failed: {assembled}")
    print("assembly: PASS", flush=True)
    for name, operation in (("independent-verification", lambda: verify_release_v2(ROOT, release, selection=selection)),
                            ("statistics", lambda: release_statistics(ROOT, release, selection)),
                            ("readers", lambda: check_reader(ROOT, release, selection))):
        result = operation()
        save(OUT / f"{name}.json", result)
        if result["status"] != "pass":
            raise ValueError(f"Apostolic private release {name} failed: {result}")
        print(f"{name}: PASS", flush=True)
    if notice.rstrip() not in (release / "public/README.md").read_text(encoding="utf-8"):
        raise ValueError("Apostolic release omits visible rights/attribution notice")
    save(OUT / "released-notice-check.json", {"status": "pass",
                                               "notice_sha256": DATA_NOTICE_SHA,
                                               "public_readme_sha256": digest(release / "public/README.md"),
                                               "exact_notice_included": True})
    for label, expected in before.items():
        if digest(ROOT / label) != expected:
            raise ValueError(f"Apostolic release input drifted: {label}")
    release_files = {path.relative_to(release).as_posix(): digest(path)
                     for path in release.rglob("*") if path.is_file()}
    save(OUT / "release-file-hashes.json", release_files)
    stats = json.loads((OUT / "statistics.json").read_text(encoding="utf-8"))
    if stats["total"]["records"] != 11 or stats["total"]["text_characters"] != 207491:
        raise ValueError("Apostolic private statistics differ from approved eleven-span projection")
    completion = {"contract": "ocd-apostolic-tradition-private-offline-completion-v1",
                  "status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
                  "work_id": "apostolic-tradition", "source_sha256": SOURCE_SHA,
                  "accepted_master_sha256": MASTER_SHA,
                  "acceptance_sha256": ACCEPTANCE_SHA,
                  "selection_sha256": digest(OUT / "selection.json"),
                  "rows": 11, "text_characters": stats["total"]["text_characters"],
                  "release_path": str(release), "private_offline": True,
                  "publication_performed": False, "human_decision": "not-recorded",
                  "rights_context": "1934 Cambridge copyright and 1962 reprint notices; Project Gutenberg US public-domain label; underlying work, Easton translation/introduction/notes/editorial matter, exact edition/printing, electronic transcription, image, and territory rights unresolved",
                  "reference_navigation_limit": "Source ref targets and private ID-to-row/path accounting retained; public rows do not provide clickable same-document anchor navigation",
                  "input_bindings": before, "release_file_bindings": release_files,
                  "notice_sha256": DATA_NOTICE_SHA,
                  "installed_generation_sha256": INSTALLED_SHA,
                  "v6_stage_freeze_sha256": V6_FREEZE_SHA,
                  "notice_revision_freeze_sha256": NOTICE_REVISION_FREEZE_SHA,
                  "release_freeze_sha256": digest(ROOT / RELEASE_FREEZE)}
    save(OUT / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", completion)
    if (OUT / "completion.json").read_bytes() != (ROOT / WORK / "publication/completion.json").read_bytes():
        raise ValueError("Apostolic canonical completion differs from report copy")
    print(json.dumps({"status": "pass", "completion_sha256": digest(OUT / "completion.json"),
                      "rows": 11, "release_file_count": len(release_files)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
