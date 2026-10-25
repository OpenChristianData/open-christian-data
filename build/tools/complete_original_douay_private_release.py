"""Assemble and verify one private offline release from the installed Douay master."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.bible import _validator, project_accepted_bible
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.install_accepted import _files

from build.tools.stage_original_douay_current import ROOT, WORK, EDITION


LOG = ROOT / "reports/_logs/original-douay-rheims-private-offline-20261002-v1"
INPUT = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"
PUB = ROOT / WORK / "publication/private-offline-20261002"
RELEASE = LOG / "release"
WORK_ID = "original-douay-rheims"
MODULES = [
    "ocd_kernel/projection/categories/bible.py", "ocd_kernel/projection/envelope.py",
    "ocd_kernel/reconstruction/contract.py", "ocd_kernel/release/notices.py",
    "ocd_kernel/release/selection.py", "ocd_kernel/release/assemble.py",
    "ocd_kernel/release/verify.py", "ocd_kernel/release/public_allowlist.py",
    "build/scripts/export_huggingface.py", "build/tools/check_hf_release.py",
    "build/tools/report_release_stats.py", "build/tools/check_release_reader.py",
    "build/tools/complete_original_douay_private_release.py",
]
SCHEMAS = [
    "schemas/v2/categories/bible.schema.json", "schemas/v2/work.schema.json",
    "schemas/v2/release-selection.schema.json", "schemas/v2/release-report.schema.json",
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return sha(path.read_bytes())


def save(path: Path, value: object) -> None:
    if path.exists():
        raise FileExistsError("Fresh private release evidence required: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def process(name: str, args: list[str]) -> dict:
    try:
        result = subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        save(LOG / f"{name}.command.json", {"argv": args, "exit_code": exc.returncode, "stdout": exc.stdout, "stderr": exc.stderr})
        raise
    save(LOG / f"{name}.command.json", {"argv": args, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"stdout": result.stdout}


def module(name: str, implementation: str, args: list[str]) -> dict:
    return process(name, [sys.executable, "-m", implementation, *args])


def main() -> None:
    if LOG.exists() or PUB.exists():
        raise FileExistsError("Fresh exact Douay private release roots required")
    LOG.mkdir(parents=True)
    freeze_bytes = (INPUT / "coordinator-install-freeze.json").read_bytes()
    freeze = json.loads(freeze_bytes)
    installed = json.loads((INPUT / "guarded-install-v1/installed-audit.json").read_bytes())
    final_bytes = (INPUT / "final-private-release-notice-bindings.json").read_bytes()
    final = json.loads(final_bytes)
    acceptance = ROOT / EDITION / "acceptance.json"
    master = ROOT / EDITION / "master.tei.xml"
    if (freeze["status"] != "pass" or installed["status"] != "pass"
            or installed["files"] != freeze["after"] or _files(ROOT / WORK) != freeze["after"]
            or digest(master) != freeze["bound_master_sha256"]
            or final["status"] != "pass" or final["notice_count"] != 170
            or final["frozen_work_sha256"] != freeze["bound_master_sha256"]):
        raise ValueError("Installed Douay authority or final notice set differs")
    runtime = {path: digest(ROOT / path) for path in MODULES}
    schemas = {path: digest(ROOT / path) for path in SCHEMAS}
    if any(digest(ROOT / path) != value for path, value in freeze["runtime_schema_pins"].items()):
        raise ValueError("Current pinned Douay install runtime drifted")
    bindings = final["bindings"]
    item = {
        "item_id": WORK_ID, "category": "bible",
        "acceptance_path": (EDITION / "acceptance.json").as_posix(),
        "public_notices": bindings,
    }
    texts = notice_texts_for_item(ROOT, item, acceptance)
    if len(texts) != 170:
        raise ValueError("Complete canonical Douay source notice set differs")
    selection = {"schema_version": "2.0", "release_id": "original-douay-rheims-private-offline-20261002-v1", "items": [item]}
    save(LOG / "runtime-before.json", runtime)
    save(LOG / "schemas-before.json", schemas)
    save(LOG / "notice-preflight.json", {"status": "pass", "notice_count": len(texts), "final_bindings_sha256": sha(final_bytes), "source_credit_sha256": freeze["full_paired_credit_sha256"]})
    with cached_edition_lookups():
        projection = project_accepted_bible(ROOT, acceptance_path=acceptance)
    save(LOG / "actual-master-projection.json", projection)
    validator = _validator()
    errors = [str(error) for row in projection["rows"] for error in validator.iter_errors(row)]
    empty = [row["locator"] for row in projection["rows"] if not row["text"]]
    if (errors or len(projection["rows"]) != 37181 or empty
            or projection["receipt"]["master_sha256"] != digest(master)):
        raise ValueError("Complete actual Douay Bible projection differs: " + str(errors[:3] or empty[:3]))
    save(LOG / "projection-check.json", {"status": "pass", "rows": len(projection["rows"]), "characters": sum(len(row["text"]) for row in projection["rows"]), "empty_slots": 0, "errors": []})
    code = '''import sys,json,hashlib
from pathlib import Path
from ocd_kernel.library.identities import cached_edition_lookups
import ocd_kernel.projection.categories.bible as bible
def unavailable(*a,**k): raise AssertionError('Bible producer invoked by independent checker')
bible.project_accepted_bible=bible.project_bible_document=bible._projection=bible._render=unavailable
root,acceptance,saved=map(Path,sys.argv[1:]); raw=saved.read_bytes(); doc=json.loads(raw)
with cached_edition_lookups(): errors=bible.verify_accepted_bible(root,acceptance_path=acceptance,rows=doc['rows'],receipt=doc['receipt'])
print(json.dumps(dict(status='fail' if errors else 'pass',errors=errors,producer_disabled=True,saved_projection_sha256=hashlib.sha256(raw).hexdigest())))
raise SystemExit(bool(errors))'''
    linked = process("independent-projection", [sys.executable, "-c", code, str(ROOT), str(acceptance), str(LOG / "actual-master-projection.json")])
    if linked.get("status") != "pass" or linked["saved_projection_sha256"] != digest(LOG / "actual-master-projection.json"):
        raise ValueError("Producer-disabled accepted-master verification differs")
    save(LOG / "independent-projection-linkage.json", linked)
    print("Actual installed Douay projection and independent linkage pass; assembling private release", flush=True)
    PUB.mkdir(parents=True)
    save(PUB / "selection.json", selection)
    save(LOG / "selection.json", selection)
    common = ["--root", str(ROOT), "--selection", str(PUB / "selection.json")]
    module("assembly", "build.scripts.export_huggingface", [*common, "--output", str(RELEASE)])
    report = json.loads((RELEASE / "internal/release-report.json").read_bytes())
    save(LOG / "assembly.json", report)
    with cached_edition_lookups():
        verified = verify_release_v2(ROOT, RELEASE, selection=selection)
    save(LOG / "independent-verification.json", verified)
    if verified["status"] != "pass":
        raise ValueError("Independent private release verifier failed")
    verify_args = [*common, "--release", str(RELEASE)]
    second = module("separate-process-verification", "build.tools.check_hf_release", verify_args)
    if second.get("status") != "pass":
        raise ValueError("Separate-process private release verifier failed")
    stats = module("statistics", "build.tools.report_release_stats", verify_args)
    reader = module("readers", "build.tools.check_release_reader", [*verify_args, "--output", str(LOG / "readers.json")])
    if reader.get("status") != "pass":
        raise ValueError("Private release reader check failed")
    public_readme = (RELEASE / "public/README.md").read_bytes()
    if any((ROOT / item["notice_path"]).read_bytes().rstrip() not in public_readme for item in bindings):
        raise ValueError("Private release dataset card omits selected source-context wording")
    after_runtime = {path: digest(ROOT / path) for path in MODULES}
    after_schemas = {path: digest(ROOT / path) for path in SCHEMAS}
    if after_runtime != runtime or after_schemas != schemas or digest(master) != freeze["bound_master_sha256"]:
        raise ValueError("Runtime, schema, or master changed during Douay release")
    files = {path.relative_to(RELEASE).as_posix(): digest(path) for path in RELEASE.rglob("*") if path.is_file()}
    save(LOG / "release-file-hashes.json", files)
    completion = {
        "status": "technical-private-offline-release-pass",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "work_id": WORK_ID, "rows": len(projection["rows"]),
        "characters": sum(len(row["text"]) for row in projection["rows"]),
        "context_notice_parts": 169, "source_and_context_notices": 170,
        "accepted_master_sha256": digest(master),
        "actual_master_projection_sha256": digest(LOG / "actual-master-projection.json"),
        "producer_disabled_linkage_sha256": digest(LOG / "independent-projection-linkage.json"),
        "final_notice_bindings_sha256": sha(final_bytes),
        "statistics_status": stats.get("status"),
        "reader_status": reader.get("status"),
        "authority_runtime_schema_stable": True,
        "public_publication": False,
        "remaining": ["human acceptance", "printed-witness collation", "rights clearance", "public publication authorization"],
    }
    save(LOG / "completion.json", completion)
    save(PUB / "completion.json", completion)
    readme = (
        "# Original Douay-Rheims: private preparation complete\n\n"
        "All 37,181 source verse occurrences remain in the accepted Bible projection, including both Tobias chapter-zero carriers. "
        "The 169 readable context notices preserve the nonverse source material and pair with the provider/source credit notice in the private release. "
        "Human acceptance, printed-witness collation, rights clearance, and public publication remain separate.\n"
    )
    (PUB / "README.md").write_text(readme, encoding="utf-8")
    (LOG / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps(completion), flush=True)


if __name__ == "__main__":
    main()
