"""Close the two accepted American Missionary volumes as one private offline release."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path

from build.tools.check_release_reader import check_reader
from build.tools.complete_puritan_private_release import read, save, sha
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection import native_content
from ocd_kernel.projection.categories import prose, sermons
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.install_accepted import _files

ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/american-missionary")
BASE = WORK / "forms/american-missionary-gutenberg-retained-en/editions"
LOG = ROOT / "reports/_logs/american-missionary-private-release-20261003-v1"
EDITIONS = {
    "american-missionary-volume-36-1882-gutenberg-electronic": (
        "23ba8c41c30e31a2c49f17ad3e9c2a2355fd955ca618242314c284ad305c80d4",
        "939a002f4c69d3ae5ab84f6c74d451c6269dcc36f7710dd6e0487828ae91cf1c",
        1506280,
    ),
    "american-missionary-volume-37-1883-gutenberg-electronic": (
        "3191c74c88e41515cf60f936c5b0d9fef8a9e2e8b6b37789fbfffe7dc60f72df",
        "a83d91f4a091c66679fd672a29a1f4ff36f76b3da9d1d737a19da09aa0dd15da",
        1483486,
    ),
}
SOURCE_NOTE = Path("sources/structured-text/american-missionary/README.source.md")
DATA_NOTE = Path("data/structured-text/american-missionary/README.md")
SOURCE_NOTE_SHA = "ece116c6bce8a644ac36d9489717541923dde08b0eec13713909cefc50b5ffcc"
DATA_NOTE_SHA = "7b437e3bb273419e4fde350977fa27090ebe98043153e308d91ae5810351e5d3"
JOURNAL = Path(".tmp_audit/accepted-install-c9343bfd28cc48e1/operation.json")


def _clean(path: Path) -> Path:
    return Path(str(path).removeprefix("\\\\?\\"))


@contextmanager
def exact_windows_context():
    """Normalize only these two accepted paths in this process; restore unconditionally."""
    original = sermons._accepted_context
    expected = {ROOT / BASE / name / "acceptance.json" for name in EDITIONS}

    def context(root, acceptance_path, *, expected_category="sermons"):
        target = _clean(acceptance_path)
        if _clean(root) == ROOT and target in expected and expected_category == "prose":
            return original(ROOT, target, expected_category=expected_category)
        return original(root, acceptance_path, expected_category=expected_category)

    sermons._accepted_context = context
    try:
        yield
    finally:
        sermons._accepted_context = original


def _check(bindings: dict[str, str]) -> None:
    for relative, digest in bindings.items():
        if sha(ROOT / relative) != digest:
            raise PipelineError(f"Frozen input changed: {relative}")


def _preflight() -> tuple[dict[str, str], dict[str, str]]:
    if io_path(LOG).exists() or io_path(ROOT / WORK / "publication").exists():
        raise PipelineError("Fresh American Missionary release location required")
    installed = _files(ROOT / WORK)
    journal = read(ROOT / JOURNAL)
    expected_installed = dict(journal["after"])
    expected_installed["work.json"] = "be9bacb1de38d731795586a2a5e4b357235832fc59ca43b7b98adb1fe56d8d28"
    if len(installed) != 346 or journal["phase"] != "complete" or installed != expected_installed:
        raise PipelineError("Installed work differs beyond reviewed form-category metadata delta")
    if sha(ROOT / SOURCE_NOTE) != SOURCE_NOTE_SHA or sha(ROOT / DATA_NOTE) != DATA_NOTE_SHA:
        raise PipelineError("Paired visible source and license notices changed")
    review = read(ROOT / "reports/_logs/american-missionary-coordinator-installed-review-20261002-v1/review.json")
    if review["status"] != "pass" or review["installed_files"] != 346:
        raise PipelineError("Installed review differs")
    bindings = {(WORK / relative).as_posix(): digest for relative, digest in installed.items()}
    for relative in (JOURNAL, SOURCE_NOTE, DATA_NOTE,
                     Path("reports/_logs/american-missionary-coordinator-installed-review-20261002-v1/review.json")):
        bindings[relative.as_posix()] = sha(ROOT / relative)
    source_members = 0
    for name, (master_hash, acceptance_hash, _) in EDITIONS.items():
        edition = BASE / name
        if sha(ROOT / edition / "master.tei.xml") != master_hash or sha(ROOT / edition / "acceptance.json") != acceptance_hash:
            raise PipelineError(f"Accepted master or acceptance changed: {name}")
        acceptance = read(ROOT / edition / "acceptance.json")
        if acceptance["identity"] != {
            "work_id": "american-missionary",
            "textual_form_id": "american-missionary-gutenberg-retained-en",
            "edition_id": name,
            "acquisition_id": name + "-acquired",
        }:
            raise PipelineError(f"Accepted identity changed: {name}")
        members = acceptance["scope"]["included_members"]
        if len(members) != 12:
            raise PipelineError(f"Issue inventory changed: {name}")
        for position, member in enumerate(members, 1):
            if member["position"] != position or sha(ROOT / member["path"]) != member["sha256"]:
                raise PipelineError(f"Retained TXT member changed: {member['path']}")
            bindings[member["path"]] = member["sha256"]
            source_members += 1
    if source_members != 24:
        raise PipelineError("Expected 24 retained TXT issue members")
    for folder in ("ocd_kernel/release", "ocd_kernel/projection", "ocd_kernel/library", "ocd_kernel/tei"):
        for path in (ROOT / folder).rglob("*.py"):
            bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (ROOT / "schemas/v2").rglob("*.json"):
        bindings[path.relative_to(ROOT).as_posix()] = sha(path)
    for relative in ("build/tools/report_release_stats.py", "build/tools/check_release_reader.py",
                     "build/tools/complete_puritan_private_release.py", "build/tools/complete_american_missionary_private_release.py",
                     "tests/test_american_missionary_release_profile.py"):
        bindings[relative] = sha(ROOT / relative)
    _check(bindings)
    return installed, bindings


def main() -> None:
    installed, bindings = _preflight()
    notices = [{"source_path": SOURCE_NOTE.as_posix(), "source_sha256": SOURCE_NOTE_SHA,
                "notice_path": DATA_NOTE.as_posix(), "notice_sha256": DATA_NOTE_SHA}]
    selection = {"schema_version": "2.0", "release_id": "american-missionary-private-offline-20261003-v1",
                 "items": [{"item_id": f"american-missionary-v{volume}", "category": "prose",
                            "acceptance_path": (BASE / name / "acceptance.json").as_posix(),
                            "public_notices": notices}
                           for volume, name in zip((36, 37), EDITIONS, strict=True)]}
    for item in selection["items"]:
        visible = notice_texts_for_item(ROOT, item, ROOT / item["acceptance_path"])
        if len(visible) != 1 or visible[0] != io_path(ROOT / DATA_NOTE).read_text(encoding="utf-8"):
            raise PipelineError("Full visible notice differs from retained public text")
    save(LOG / "selection.json", selection)
    total_rows = 0
    total_chars = 0
    with exact_windows_context(), cached_edition_lookups():
        for name, (_, _, expected_chars) in EDITIONS.items():
            acceptance_path = ROOT / BASE / name / "acceptance.json"
            print(f"{name}: actual-master projection START", flush=True)
            projected = prose.project_accepted_prose(ROOT, acceptance_path=acceptance_path)
            save(LOG / name / "projection.json", projected)
            original = native_content.project_content

            def disabled(*args, **kwargs):
                raise AssertionError("Producer called from independent checker")

            native_content.project_content = disabled
            try:
                errors = prose.verify_accepted_prose(ROOT, acceptance_path=acceptance_path,
                    rows=projected["rows"], receipt=projected["receipt"])
            finally:
                native_content.project_content = original
            count = len(projected["rows"])
            chars = sum(len(row["text"]) for row in projected["rows"])
            if errors or count != 12 or chars != expected_chars:
                raise PipelineError(f"Independent actual-master check differs: {name}: {errors[:3]}")
            save(LOG / name / "independent-projection.json", {"status": "pass", "producer_disabled": True,
                "issue_rows": count, "text_characters": chars, "errors": errors,
                "mapping_version": projected["receipt"]["mapping_version"],
                "master_sha256": EDITIONS[name][0], "projection_sha256": sha(LOG / name / "projection.json")})
            bindings[(LOG / name / "projection.json").relative_to(ROOT).as_posix()] = sha(LOG / name / "projection.json")
            bindings[(LOG / name / "independent-projection.json").relative_to(ROOT).as_posix()] = sha(LOG / name / "independent-projection.json")
            total_rows += count
            total_chars += chars
            print(f"{name}: independent checker PASS, {count} rows, {chars} chars", flush=True)
        if total_rows != 24 or total_chars != 2989766:
            raise PipelineError("Two-volume projection totals differ")
        bindings[(LOG / "selection.json").relative_to(ROOT).as_posix()] = sha(LOG / "selection.json")
        save(LOG / "input-bindings.json", bindings)
        _check(bindings)
        if _files(ROOT / WORK) != installed:
            raise PipelineError("Installed work changed before assembly")
        destination = (LOG / "release").resolve()
        if destination.exists():
            raise PipelineError("Release destination already exists")
        gates = {}
        for label, operation in (
            ("assembly", lambda: assemble_release_v2(ROOT, destination, selection=selection)),
            ("independent-verification", lambda: verify_release_v2(ROOT, destination, selection=selection)),
            ("statistics", lambda: release_statistics(ROOT, destination, selection)),
            ("readers", lambda: check_reader(ROOT, destination, selection)),
        ):
            print(f"{label}: START", flush=True)
            result = operation()
            save(LOG / f"{label}.json", result)
            if result["status"] != "pass":
                raise PipelineError(f"{label} failed: {result}")
            gates[label] = {"status": "pass", "path": (LOG / f"{label}.json").relative_to(ROOT).as_posix(),
                            "sha256": sha(LOG / f"{label}.json")}
            print(f"{label}: PASS", flush=True)
    stats = read(LOG / "statistics.json")
    if stats["total"]["records"] != total_rows or stats["total"]["text_characters"] != total_chars:
        raise PipelineError("Saved release counts differ from accepted-master projections")
    release_files = _files(destination)
    card = (destination / "public/README.md").read_text(encoding="utf-8")
    if len(release_files) != 7 or io_path(ROOT / DATA_NOTE).read_text(encoding="utf-8").rstrip() not in card:
        raise PipelineError("Seven-file release or complete visible source license differs")
    _check(bindings)
    if _files(ROOT / WORK) != installed:
        raise PipelineError("Installed work changed before canonical completion")
    completion = {"contract": "ocd-american-missionary-private-offline-completion-v1", "status": "pass",
                  "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": "american-missionary",
                  "editions": {name: {"master_sha256": values[0], "acceptance_sha256": values[1],
                                      "issue_rows": 12, "text_characters": values[2]} for name, values in EDITIONS.items()},
                  "retained_txt_issues": 24, "rows": total_rows, "text_characters": total_chars,
                  "uncompressed_bytes": stats["total"]["uncompressed_bytes"], "preserved_work_files": installed,
                  "input_bindings": bindings, "release_file_bindings": release_files, "gates": gates,
                  "public_notices": notices, "selection_path": (LOG / "selection.json").relative_to(ROOT).as_posix(),
                  "selection_sha256": sha(LOG / "selection.json"), "release_path": str(destination),
                  "private_offline": True, "human_acceptance": "not-recorded", "print_collation": "not-performed",
                  "rights_clearance": "unresolved", "publication_performed": False,
                  "reconstruction_performed": False, "reinstall_performed": False, "accepted_generation_unchanged": True}
    save(LOG / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", io_path(LOG / "completion.json").read_bytes())
    save(ROOT / WORK / "publication/selection.json", io_path(LOG / "selection.json").read_bytes())
    save(ROOT / WORK / "publication/README.md", (
        "# The American Missionary: private offline completion\n\n"
        "The unchanged accepted electronic volumes 36 (1882) and 37 (1883) contain 12 monthly issue rows each: "
        f"{total_rows} rows and {total_chars:,} text characters in this private offline release. The `prose` route is "
        "a transport category for this mixed-genre monthly periodical; tables and figure references remain in the "
        "structured text, while image files remain retained media rather than embedded release images. "
        "All 24 TXT source issues, complete visible Gutenberg terms, and credits are bound into the release card.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind both exact accepted editions. Detailed "
        "evidence is at `reports/_logs/american-missionary-private-release-20261003-v1/`. "
        "Human acceptance, print collation, broader rights clearance, and public publication remain unrecorded "
        "or unperformed.\n").encode())
    canonical = _files(ROOT / WORK)
    expected = dict(installed)
    expected.update({"publication/" + name: sha(ROOT / WORK / "publication" / name)
                     for name in ("completion.json", "selection.json", "README.md")})
    if canonical != expected or _files(destination) != release_files:
        raise PipelineError("Final canonical or release file binding differs")
    _check(bindings)
    save(LOG / "final-audit.json", {"status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
        "input_binding_count": len(bindings), "all_input_bindings_match": True, "preserved_installed_files": 346,
        "canonical_files": canonical, "release_files": release_files, "gates": gates,
        "completion_sha256": sha(LOG / "completion.json"), "selection_sha256": sha(LOG / "selection.json"),
        "rows": total_rows, "text_characters": total_chars, "publication_performed": False})
    print(json.dumps({"status": "pass", "rows": total_rows, "text_characters": total_chars,
                      "completion_sha256": sha(LOG / "completion.json"),
                      "final_audit_sha256": sha(LOG / "final-audit.json")}), flush=True)


if __name__ == "__main__":
    main()
