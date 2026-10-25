"""Finish the interrupted Aquinas private release after saved projection linkage."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

from build.tools import complete_aquinas_four_private_release as original
from ocd_kernel.library._common import io_glob, io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2


ROOT = original.ROOT
OUT = original.OUT
PUB = original.PUB
RELEASE = original.RELEASE


def digest(path: Path) -> str:
    result = sha256()
    with io_path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def load(path: Path):
    return json.loads(io_path(path).read_bytes())


def save(path: Path, value):
    original.save(path, value)


def require_pass(path: Path):
    value = load(path)
    if value.get("status") != "pass":
        raise ValueError(f"Failed checkpoint: {path}")
    return value


def require_command_pass(name: str):
    value = load(OUT / (name + ".command.json"))
    if value.get("exit_code") != 0:
        raise ValueError(f"Failed command checkpoint: {name}")


def check_bound_inputs() -> tuple[dict, dict]:
    before = load(OUT / "authority-before.json")
    schemas = load(OUT / "schemas-before.json")
    changed = [path for path, expected in before.items()
               if digest(ROOT / path) != expected]
    changed_schemas = [path for path, expected in schemas.items()
                       if digest(ROOT / path) != expected]
    if changed or changed_schemas:
        raise ValueError(f"Bound inputs drifted: authority={changed}, schemas={changed_schemas}")
    installed_review = ROOT / "reports/_logs/aquinas-four-current-reconciliation-20261002-v1/coordinator-installed-generation-review.json"
    installed_sha256 = "5087b8d304799b2a0356d428ef94a9ba166541f5f152d70b13b364eeaeefff22"
    if digest(installed_review) != installed_sha256:
        raise ValueError("Installed generation review changed")
    review = load(installed_review)
    if review.get("status") != "pass" or review.get("installed_count") != 29:
        raise ValueError("Installed generation review incomplete")
    master = ROOT / original.EDITION / "master.tei.xml"
    if digest(master) != "8afc726956294b98055dd5dbd154df84e61a75597d9ffe77629ef891b226104b":
        raise ValueError("Accepted master changed")
    projection = OUT / "actual-master-projection.json"
    linkage = load(OUT / "independent-projection-linkage.json")
    if linkage.get("status") != "pass" or not linkage.get("producer_disabled") or not linkage.get("full_accepted_master"):
        raise ValueError("Saved independent linkage incomplete")
    if digest(projection) != linkage["saved_projection_sha256"]:
        raise ValueError("Saved projection changed")
    if linkage.get("accepted_master_sha256") != digest(master):
        raise ValueError("Linkage master differs")
    return before, schemas


def assemble_from_saved_rows(selection):
    if RELEASE.exists() or (OUT / "assembly.command.json").exists():
        raise FileExistsError("Release or assembly command already exists; inspect before resuming")
    code = '''import json,sys
from pathlib import Path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories import prose
from build.scripts.export_huggingface import main
saved = json.loads(Path(sys.argv[1]).read_bytes())
def retained_rows(*args, **kwargs):
    return saved
prose.project_accepted_prose = retained_rows
with cached_edition_lookups():
    raise SystemExit(main(sys.argv[2:]))'''
    args = ["--root", str(ROOT), "--selection", str(PUB / "selection.json"),
            "--output", str(RELEASE)]
    result = original.process("assembly", [sys.executable, "-c", code,
                                            str(OUT / "actual-master-projection.json"), *args])
    command_result = json.loads(result.stdout)
    if command_result.get("assembly") != "pass" or command_result.get("verification") != "pass":
        raise ValueError(command_result)
    report = load(RELEASE / "internal/release-report.json")
    if report.get("status") != "pass":
        raise ValueError(report)
    save(OUT / "assembly.json", report)


def main():
    before, schemas = check_bound_inputs()
    selection = load(PUB / "selection.json")
    if selection != load(OUT / "selection.json") or len(selection["items"]) != 1:
        raise ValueError("Private selection changed")
    item = selection["items"][0]
    if item["item_id"] != original.WORK_ID or len(item["public_notices"]) != 4:
        raise ValueError("Four-component selection changed")
    acceptance = ROOT / original.EDITION / "acceptance.json"
    texts = notice_texts_for_item(ROOT, item, acceptance)
    if len(texts) != 4:
        raise ValueError("Four source/data notices required")
    if not RELEASE.exists():
        print("Assembling Aquinas release from independently linked saved rows", flush=True)
        assemble_from_saved_rows(selection)
    elif not (OUT / "assembly.json").exists():
        raise FileExistsError("Existing release lacks assembly receipt; inspect it manually")
    if (OUT / "independent-verification.json").exists():
        require_pass(OUT / "independent-verification.json")
    else:
        with cached_edition_lookups():
            verified = verify_release_v2(ROOT, RELEASE, selection=selection)
        save(OUT / "independent-verification.json", verified)
        if verified.get("status") != "pass":
            raise ValueError(verified)
    common = ["--root", str(ROOT), "--selection", str(PUB / "selection.json"),
              "--release", str(RELEASE)]
    if (OUT / "separate-process-verification.json").exists():
        require_command_pass("separate-process-verification")
        require_pass(OUT / "separate-process-verification.json")
    else:
        original.command("separate-process-verification", "build.tools.check_hf_release", common)
    if (OUT / "statistics.json").exists():
        require_command_pass("statistics")
        require_pass(OUT / "statistics.json")
    else:
        original.command("statistics", "build.tools.report_release_stats", common)
    if (OUT / "readers.json").exists():
        require_command_pass("readers")
        reader = require_pass(OUT / "readers.json")
        if not reader.get("offline") or reader.get("publication_performed"):
            raise ValueError("Reader checkpoint has wrong publication scope")
        if any(config.get("normal_and_streaming") != "pass" or not config.get("all_original_values_and_order_preserved")
               for config in reader.get("configurations", [])):
            raise ValueError("Reader checkpoint incomplete")
    else:
        original.command("readers", "build.tools.check_release_reader",
                         [*common, "--output", str(OUT / "readers.json")])
    released = (RELEASE / "public/README.md").read_bytes()
    if any(text.encode().rstrip() not in released for text in texts):
        raise ValueError("Release omits a complete source/data license or credit")
    save(OUT / "released-notice-check.json",
         dict(status="pass", complete_notices=4, complete_licenses_embedded=True))
    after = {path: digest(ROOT / path) for path in before}
    schema_after = {path: digest(ROOT / path) for path in schemas}
    if after != before or schema_after != schemas:
        raise ValueError("Bound input or schema changed during release")
    save(OUT / "authority-after.json", after)
    save(OUT / "schema-stability.json", dict(status="pass", before=schemas, after=schema_after))
    files = {path.relative_to(RELEASE).as_posix(): digest(path)
             for path in io_glob(RELEASE, "**/*") if io_path(path).is_file()}
    save(OUT / "release-file-hashes.json", files)
    statistics = require_pass(OUT / "statistics.json")["total"]
    if statistics["records"] != 4 or statistics["text_characters"] != 12452726:
        raise ValueError("Four-row statistics changed")
    completion = dict(status="pass", private_offline=True, publication_performed=False,
                      checked_at=datetime.now(timezone.utc).isoformat(), work_id=original.WORK_ID,
                      rows=4, source_units=35488, semantic_questions=512, semantic_articles=2669,
                      text_characters=statistics["text_characters"],
                      statistics=statistics,
                      accepted_master_sha256=digest(ROOT / original.EDITION / "master.tei.xml"),
                      acceptance_sha256=digest(acceptance),
                      saved_projection_sha256=digest(OUT / "actual-master-projection.json"),
                      independent_linkage_sha256=digest(OUT / "independent-projection-linkage.json"),
                      installed_generation_review_sha256="5087b8d304799b2a0356d428ef94a9ba166541f5f152d70b13b364eeaeefff22",
                      resume_script_sha256=digest(ROOT / "build/tools/resume_aquinas_four_private_release.py"),
                      authority_unchanged_during_release=True, bound_schemas_stable=True,
                      complete_own_source_data_credit_and_licenses_visible=True,
                      release_path=str(RELEASE), remaining=[
                          "Human acceptance and exhaustive visual proofreading",
                          "Four retained components only; traditional Supplement absent",
                          "Print equivalence and independent rights clearance",
                          "Public publication authorization"])
    save(OUT / "completion.json", completion)
    save(PUB / "completion.json", completion)
    readme = ("# Summa Theologica: four-component private readiness\n\n"
              "One accepted TEI preserves the four retained English electronic components I, I-II, II-II and III: "
              "35,488 source units, 512 semantic question boundaries and 2,669 semantic articles. "
              "The traditional Supplement is absent. Native source numbering anomalies, own dedication/notes/contents/prologues, "
              "editorial insertion, italics and breaks remain literal; generated ownership/taxonomy are reconstruction analysis.\n\n"
              "Full actual-master public projection and saved producer-disabled independent linkage, private assembly, "
              "both release verifiers, statistics and normal/streaming readers pass. Four paired human-visible "
              "source/data notices preserve primary translator and electronic contributor statements and each complete own "
              "Gutenberg license. Current dated runtime/schema and installed generation are bound. Human acceptance, visual "
              "proofreading, print equivalence, rights clearance and public publication remain separate.\n")
    for path in (OUT / "README.md", PUB / "README.md"):
        path.write_text(readme, encoding="utf-8", newline="\n")
    for path in io_glob(PUB, "**/*"):
        if io_path(path).is_file():
            after[path.relative_to(ROOT).as_posix()] = digest(path)
    evidence = {path.relative_to(OUT).as_posix(): digest(path)
                for path in io_glob(OUT, "**/*")
                if io_path(path).is_file() and RELEASE not in path.parents}
    save(OUT / "final-delivery.json",
         dict(status="pass", map_bases=dict(authority=str(ROOT), schemas=str(ROOT),
                                            release=str(RELEASE), evidence=str(OUT)),
              authority=after, schemas=schema_after, release=files, evidence=evidence))
    print(json.dumps(completion), flush=True)


if __name__ == "__main__":
    main()
