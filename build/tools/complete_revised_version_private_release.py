"""Finish the installed Revised Version witness with the maintained offline gates."""
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
WID = "revised-version-with-apocrypha"
WORK = ROOT / "library/works" / WID
OLD = ROOT / "reports/_logs/revised-version-with-apocrypha-private-release-20261002-v1"
LOG = ROOT / "reports/_logs/revised-version-with-apocrypha-private-release-20261003-v6"


def main():
    if LOG.exists() or io_path(WORK / "publication/completion.json").exists():
        raise PipelineError("Fresh work-local completion required")
    selection = read(OLD / "private-offline-v1-selection.json")
    acceptance = ROOT / selection["items"][0]["acceptance_path"]
    master = acceptance.with_name("master.tei.xml")
    bindings = read(OLD / "private-offline-v1-authority-before.json")
    transitions = []
    # Preserve historical receipts; only executable runtime pins can change here.
    for path, previous in list(bindings.items()):
        current = sha(ROOT / path)
        if current != previous:
            if not path.startswith(("ocd_kernel/", "build/scripts/", "build/tools/")) or not path.endswith(".py"):
                raise PipelineError("Retained authority changed: " + path)
            transitions.append(dict(path=path, historical_sha256=previous, current_sha256=current))
            bindings[path] = current
    installed = _files(WORK)
    bindings.update({(Path("library/works") / WID / p).as_posix():h for p,h in installed.items()})
    for folder in ("ocd_kernel/projection", "ocd_kernel/release", "ocd_kernel/library", "ocd_kernel/tei"):
        for path in (ROOT / folder).rglob("*.py"):
            bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    schemas = {p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT / "schemas/v2").rglob("*.json")}
    bindings.update(schemas)
    for path in (Path(__file__), ROOT / "build/tools/complete_puritan_private_release.py"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    check(bindings)
    notices = notice_texts_for_item(ROOT, selection["items"][0], acceptance)
    if len(notices) != 1 or "80 extracted USFM book files" not in notices[0]:
        raise PipelineError("Complete existing visible source notice differs")
    save(LOG / "selection.json", selection)
    save(LOG / "input-bindings-before.json", bindings)
    save(LOG / "runtime-transition.json", dict(status="historical-runtime-preserved-current-runtime-bound", transitions=transitions))
    save(LOG / "verse-label-policy.json", dict(
        status="current-projection-format", locator_verse_type="string",
        mapping_version=bible.MAPPING_VERSION, corpus_mapping_version=bible.CORPUS_MAPPING_VERSION,
        reason="Native numeric and range labels share one Arrow field for combined Bible releases",
        source_native_ranges_preserved=True, historical_dated_numeric_releases_unchanged=True,
        reference_normalization="uses the source label without inventing verse endpoints",
        public_retained_member_set_namespace="edition and representation revision identity, without source digest",
        private_source_binding="exact retained member-set digest remains in acceptance and projection receipt"))
    print("Actual installed master projection: START", flush=True)
    with cached_edition_lookups():
        projected = bible.project_accepted_bible(ROOT, acceptance_path=acceptance)
        # Disable producer entry points while the independent traversal runs.
        names = ("project_accepted_bible", "project_bible_document", "_projection", "_render")
        originals = {n:getattr(bible,n) for n in names}
        def unavailable(*args, **kwargs):
            raise AssertionError("Independent checker invoked the producer")
        try:
            for n in names:
                setattr(bible,n,unavailable)
            errors = bible.verify_accepted_bible(ROOT, acceptance_path=acceptance,
                rows=projected["rows"], receipt=projected["receipt"])
        finally:
            for n,v in originals.items():
                setattr(bible,n,v)
    if errors or projected["receipt"]["master_sha256"] != sha(master):
        raise PipelineError("Independent actual-master projection failed: " + str(errors))
    save(LOG / "actual-master-projection.json", projected)
    rows = len(projected["rows"])
    if rows != 36878:
        raise PipelineError("Projection differs from all 36,878 retained verse carriers")
    if any(not isinstance(row["locator"]["verse"], str) for row in projected["rows"]):
        raise PipelineError("Current Bible source labels are not uniformly strings")
    if sum("-" in row["locator"]["verse"] for row in projected["rows"]) != 5:
        raise PipelineError("Projection differs from five retained native range labels")
    if any("\\+w" in row["text"] or "|strong=" in row["text"] for row in projected["rows"]):
        raise PipelineError("Public verse text retains machine word annotations")
    if sum(warning["reason"] == "source-usfm-word-annotation-rendered-to-surface" for warning in projected["receipt"]["warnings"]) != 17:
        raise PipelineError("Projection differs from 17 retained word annotations")
    if sum(row["text"] == "" for row in projected["rows"]) != 42:
        raise PipelineError("Projection differs from the 42 source-defined empty carriers")
    characters = sum(len(row["text"]) for row in projected["rows"])
    save(LOG / "independent-projection.json", dict(status="pass", errors=[], producer_disabled=True,
        rows=rows, text_characters=characters, source_empty_carriers=42, native_range_labels=5,
        word_annotation_surface_warnings=17, machine_word_annotations_in_public_text=0,
        master_sha256=sha(master), acceptance_sha256=sha(acceptance),
        saved_projection_sha256=sha(LOG / "actual-master-projection.json")))
    del projected
    print("Actual installed master projection: PASS", flush=True)
    destination = (LOG / "release").resolve()
    gates = {}
    with cached_edition_lookups():
        for name, operation in (
            ("assembly", lambda:assemble_release_v2(ROOT,destination,selection=selection)),
            ("independent-verification", lambda:verify_release_v2(ROOT,destination,selection=selection)),
            ("statistics", lambda:release_statistics(ROOT,destination,selection)),
            ("readers", lambda:check_reader(ROOT,destination,selection)),
        ):
            print(name + ": START", flush=True)
            result = operation()
            save(LOG / (name + ".json"), result)
            if result["status"] != "pass":
                raise PipelineError(name + " failed: " + str(result))
            gates[name] = dict(status="pass", path=(LOG/(name+".json")).relative_to(ROOT).as_posix(), sha256=sha(LOG/(name+".json")))
            print(name + ": PASS", flush=True)
    total = read(LOG / "statistics.json")["total"]
    if total["records"] != rows or total["text_characters"] != characters:
        raise PipelineError("Released counts differ from full accepted-master projection")
    notice = ROOT / selection["items"][0]["public_notices"][0]["notice_path"]
    if io_path(notice).read_text(encoding="utf-8").rstrip() not in (destination/"public/README.md").read_text(encoding="utf-8"):
        raise PipelineError("Release omits complete visible source notice")
    check(bindings)
    if _files(WORK) != installed:
        raise PipelineError("Installed generation changed during release")
    files = _files(destination)
    completion = dict(status="pass", checked_at=datetime.now(timezone.utc).isoformat(), work_id=WID,
        rows=rows, text_characters=characters, accepted_master_sha256=sha(master), acceptance_sha256=sha(acceptance),
        input_bindings=bindings, preserved_work_files=installed, release_file_bindings=files, gates=gates,
        selection_path=(LOG/"selection.json").relative_to(ROOT).as_posix(), selection_sha256=sha(LOG/"selection.json"),
        release_path=str(destination), private_offline=True, publication_performed=False,
        human_acceptance="not-recorded", print_collation="not-performed", rights_clearance="unresolved",
        final_public_release_selection="unresolved", reconstruction_performed=False, reinstall_performed=False)
    save(LOG / "completion.json", completion)
    # Reuse the already installed exact selection; the fresh report binds current code.
    canonical_selection = WORK / "publication/selection.json"
    if read(canonical_selection) != read(OLD / "private-offline-v1-selection.json"):
        raise PipelineError("Canonical selection changed")
    save(WORK / "publication/completion.json", io_path(LOG/"completion.json").read_bytes())
    save(WORK / "publication/README.md", (
        "# Revised Version: private offline preparation complete\n\n"
        f"The installed 80-member electronic witness passes actual-master projection, independent linkage, assembly, verification, statistics and both readers: {rows:,} rows and {characters:,} text characters. The complete source notice is included.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind this release. Human review, print collation, rights clearance and public publication remain separate. No source was acquired or reconstructed.\n").encode())
    expected = dict(installed)
    for name in ("completion.json", "selection.json", "README.md"):
        expected["publication/"+name] = sha(WORK/"publication"/name)
    if _files(WORK) != expected or _files(destination) != files:
        raise PipelineError("Final delivery envelope differs")
    check(bindings)
    save(LOG / "final-audit.json", dict(status="pass", input_binding_count=len(bindings),
        canonical_files=expected, release_file_count=len(files), all_release_files_match=True,
        canonical_completion_byte_identical=sha(WORK/"publication/completion.json")==sha(LOG/"completion.json"),
        canonical_selection_byte_identical=sha(canonical_selection)==sha(LOG/"selection.json"),
        rows=rows, text_characters=characters, publication_performed=False))
    print(json.dumps(dict(status="pass",rows=rows,text_characters=characters,release_files=len(files))),flush=True)


if __name__ == "__main__":
    main()
