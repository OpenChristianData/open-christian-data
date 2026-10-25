"""Complete the accepted WEB British Edition as a private offline Bible release."""

from datetime import datetime, timezone
import json
from pathlib import Path

from build.tools.complete_puritan_private_release import read, save, sha, check
from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories import bible
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.install_accepted import _files

ROOT = Path(__file__).resolve().parents[2]
WID = "engwebpb"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms/engwebpb-retained-en/editions/engwebpb-electronic-2020"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
SOURCE_NOTE = ROOT / "sources/structured-text/engwebpb/README.source.md"
DATA_NOTE = ROOT / "data/bible/engwebpb/README.md"
LOG = ROOT / "reports/_logs/engwebpb-private-release-20261003-v1"
EXPECTED_MASTER = "701161a141f37d103338b30bbc1399efd212534b7bfeab21ec5fa31c08f37277"
EXPECTED_ACCEPTANCE = "ed04202db9966ff788bc4f8136b5c7575eeb5b0bcab5880ae4b79136b2a88b01"


def main() -> None:
    if LOG.exists() or io_path(WORK / "publication/completion.json").exists():
        raise PipelineError("Fresh engwebpb private release path required")
    if sha(MASTER) != EXPECTED_MASTER or sha(ACCEPTANCE) != EXPECTED_ACCEPTANCE:
        raise PipelineError("Accepted engwebpb source authority changed")
    installed = _files(WORK)
    if len(installed) != 30:
        raise PipelineError("Installed engwebpb file inventory changed")

    item = {
        "item_id": WID,
        "category": "bible",
        "acceptance_path": ACCEPTANCE.relative_to(ROOT).as_posix(),
        "public_notices": [{
            "source_path": SOURCE_NOTE.relative_to(ROOT).as_posix(),
            "source_sha256": sha(SOURCE_NOTE),
            "notice_path": DATA_NOTE.relative_to(ROOT).as_posix(),
            "notice_sha256": sha(DATA_NOTE),
        }],
    }
    selection = {"schema_version": "2.0", "release_id": "engwebpb-private-offline-20261003-v1", "items": [item]}
    notices = notice_texts_for_item(ROOT, item, ACCEPTANCE)
    if len(notices) != 1 or not all(
        phrase in notices[0] for phrase in ("68 extracted USFM", "four nonverse notes", "trademark", "public release")
    ):
        raise PipelineError("Complete visible source/use notice differs")

    bindings = {(Path("library/works") / WID / path).as_posix(): digest for path, digest in installed.items()}
    for path in (SOURCE_NOTE, DATA_NOTE, Path(__file__), ROOT / "build/tools/complete_puritan_private_release.py"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for folder in ("ocd_kernel/projection", "ocd_kernel/release", "ocd_kernel/library", "ocd_kernel/tei"):
        for path in (ROOT / folder).rglob("*.py"):
            bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for folder in ("schemas/v2", "raw/ebible/engwebpb/usfm"):
        for path in (ROOT / folder).rglob("*"):
            if io_path(path).is_file():
                bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for relative in (
        "build/scripts/export_huggingface.py", "build/tools/check_hf_release.py",
        "build/tools/check_release_reader.py", "build/tools/report_release_stats.py",
        "ocd_kernel/lib/storage_topology.py", "ocd_kernel/projection/envelope.py",
    ):
        bindings[relative] = sha(ROOT / relative)
    check(bindings)
    save(LOG / "selection.json", selection)
    save(LOG / "input-bindings-before.json", bindings)
    print("Actual accepted-master projection: START", flush=True)
    with cached_edition_lookups():
        projected = bible.project_accepted_bible(ROOT, acceptance_path=ACCEPTANCE)
        names = ("project_accepted_bible", "project_bible_document", "_projection", "_render")
        originals = {name: getattr(bible, name) for name in names}

        def unavailable(*args, **kwargs):
            raise AssertionError("Independent checker invoked Bible producer")

        try:
            for name in names:
                setattr(bible, name, unavailable)
            errors = bible.verify_accepted_bible(
                ROOT, acceptance_path=ACCEPTANCE, rows=projected["rows"], receipt=projected["receipt"]
            )
        finally:
            for name, original in originals.items():
                setattr(bible, name, original)
    if errors or projected["receipt"]["master_sha256"] != EXPECTED_MASTER:
        raise PipelineError("Independent accepted-master linkage failed: " + str(errors))
    rows = projected["rows"]
    count = len(rows)
    characters = sum(len(row["text"]) for row in rows)
    notes = sum(len(row["notes"]) for row in rows)
    retained_notes = sum(entry["retained_only_counts"].get("note", 0) for entry in projected["inventory"])
    if count != 31103 or notes != 1568 or retained_notes != 4 or len(projected["inventory"]) != 68:
        raise PipelineError("Projected verse/member/note accounting differs")
    if any(row["references"] for row in rows):
        raise PipelineError("Source-native references were asserted as normalized targets")
    save(LOG / "actual-master-projection.json", projected)
    save(LOG / "independent-projection.json", {
        "status": "pass", "errors": [], "producer_disabled": True,
        "rows": count, "text_characters": characters, "projected_notes": notes,
        "retained_only_nonverse_notes": retained_notes, "source_members": 68,
        "master_sha256": sha(MASTER), "acceptance_sha256": sha(ACCEPTANCE),
        "saved_projection_sha256": sha(LOG / "actual-master-projection.json"),
    })
    del projected, rows
    print("Actual accepted-master projection: PASS", flush=True)

    destination = (LOG / "release").resolve()
    gates = {}
    with cached_edition_lookups():
        for name, operation in (
            ("assembly", lambda: assemble_release_v2(ROOT, destination, selection=selection)),
            ("independent-verification", lambda: verify_release_v2(ROOT, destination, selection=selection)),
            ("statistics", lambda: release_statistics(ROOT, destination, selection)),
            ("readers", lambda: check_reader(ROOT, destination, selection)),
        ):
            print(name + ": START", flush=True)
            result = operation()
            save(LOG / (name + ".json"), result)
            if result["status"] != "pass":
                raise PipelineError(name + " failed: " + str(result))
            gates[name] = {
                "status": "pass", "path": (LOG / (name + ".json")).relative_to(ROOT).as_posix(),
                "sha256": sha(LOG / (name + ".json")),
            }
            print(name + ": PASS", flush=True)
    total = read(LOG / "statistics.json")["total"]
    if total["records"] != count or total["text_characters"] != characters:
        raise PipelineError("Release counts differ from accepted-master projection")
    if io_path(DATA_NOTE).read_text(encoding="utf-8").rstrip() not in (destination / "public/README.md").read_text(encoding="utf-8"):
        raise PipelineError("Release omits complete visible source/use notice")
    check(bindings)
    if _files(WORK) != installed:
        raise PipelineError("Installed engwebpb authority changed during release")
    files = _files(destination)
    completion = {
        "status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": WID,
        "rows": count, "text_characters": characters, "projected_notes": notes,
        "retained_only_nonverse_notes": retained_notes, "source_members": 68,
        "accepted_master_sha256": sha(MASTER), "acceptance_sha256": sha(ACCEPTANCE),
        "input_bindings": bindings, "preserved_work_files": installed,
        "release_file_bindings": files, "gates": gates,
        "selection_path": (LOG / "selection.json").relative_to(ROOT).as_posix(),
        "selection_sha256": sha(LOG / "selection.json"), "release_path": str(destination),
        "private_offline": True, "publication_performed": False,
        "human_acceptance": "not-recorded", "print_collation": "not-performed",
        "rights_clearance": "unresolved", "trademark_clearance": "unresolved",
        "final_public_release_selection": "unresolved", "reconstruction_performed": False,
        "reinstall_performed": False,
    }
    save(LOG / "completion.json", completion)
    save(WORK / "publication/selection.json", io_path(LOG / "selection.json").read_bytes())
    save(WORK / "publication/completion.json", io_path(LOG / "completion.json").read_bytes())
    save(WORK / "publication/README.md", (
        "# World English Bible British Edition: private offline preparation complete\n\n"
        f"The accepted 68-member electronic witness passes actual-master verse projection, independent linkage, private assembly, release verification, statistics, and both readers: {count:,} verse rows and {characters:,} text characters. "
        f"Rows carry {notes:,} attached notes; four nonverse notes, FRT/GLO, headings, and markers remain in the accepted master. The full provider and rights qualification accompanies the release data.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind this package. Human review, print collation, rights and trademark clearance, and public publication remain separate.\n"
    ).encode())
    expected = dict(installed)
    for name in ("completion.json", "selection.json", "README.md"):
        expected["publication/" + name] = sha(WORK / "publication" / name)
    if _files(WORK) != expected or _files(destination) != files:
        raise PipelineError("Final engwebpb delivery envelope differs")
    check(bindings)
    save(LOG / "final-audit.json", {
        "status": "pass", "input_binding_count": len(bindings),
        "canonical_files": expected, "release_file_count": len(files),
        "all_release_files_match": True,
        "canonical_completion_byte_identical": sha(WORK / "publication/completion.json") == sha(LOG / "completion.json"),
        "canonical_selection_byte_identical": sha(WORK / "publication/selection.json") == sha(LOG / "selection.json"),
        "rows": count, "text_characters": characters, "publication_performed": False,
    })
    print(json.dumps({"status": "pass", "rows": count, "text_characters": characters, "release_files": len(files)}), flush=True)


if __name__ == "__main__":
    main()
