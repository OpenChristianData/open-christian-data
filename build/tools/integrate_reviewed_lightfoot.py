"""Connect the exact reviewed Lightfoot TEI in a fresh bounded staging tree.

No source reconstruction or live installation is performed by this command.
The historical package is retained unchanged beside its derived representation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lxml import etree
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, promote_accepted_master, validate_acceptance, write_acceptance
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

WORK = "lightfoot-colossians-philemon"
WORK_PATH = Path("library/works") / WORK
EDITION = WORK_PATH / "forms/lightfoot-english/editions/pg50857"
IDENTITY = dict(work_id=WORK, textual_form_id="lightfoot-english", edition_id="pg50857", acquisition_id="pg50857-text")
ORIGINAL_SHA = "08373ba46f8e1a281f379c4b5b67e24d2305509575de602618131017beabb717"
REVIEW = Path("plans/2026-08-31-sample-first-library-verification/11-lightfoot-whole-candidate-review.md")
REVISION = dict(id="reviewed-integration-v1", date="2026-09-10", note="Acceptance identity and source bindings added to the exact reviewed representation; all original bytes retained.")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def prepare(root: Path, package_root: Path, stage: Path) -> Path:
    raise PipelineError(
        "Lightfoot structural fidelity is blocked: Ticket 11 is reopened. "
        "The retained-line candidate must not be promoted by this historical adapter."
    )


def _historical_prepare(root: Path, package_root: Path, stage: Path) -> Path:
    """Retained for evidence of the superseded integration; not a CLI entry point."""
    if stage.exists():
        raise PipelineError("integration staging root must be fresh")
    original = (package_root / "package/content.tei.xml").read_bytes()
    if digest(original) != ORIGINAL_SHA:
        raise PipelineError("original differs from the reviewed Lightfoot TEI")
    review_text = (root / REVIEW).read_text(encoding="utf-8")
    if ORIGINAL_SHA not in review_text:
        raise PipelineError("review report does not bind selected TEI")
    manifest = json.loads((package_root / "package/manifest.json").read_text(encoding="utf-8"))
    for member in manifest["members"]:
        if Path(member["name"]).name != member["name"]:
            raise PipelineError("package member must be a flat filename")
        content = (package_root / "package" / member["name"]).read_bytes()
        if len(content) != member["bytes"] or digest(content) != member["sha256"]:
            raise PipelineError("historical package member changed: " + member["name"])
    acquisition_rel = EDITION / "acquisitions/pg50857-text.json"
    acquisition = json.loads((root / acquisition_rel).read_text(encoding="utf-8"))
    retained = acquisition["retained_files"][0]
    source_bytes = resolve_repo_path(root, retained["path"]).read_bytes()
    if digest(source_bytes) != retained["sha256"] or len(source_bytes) != retained["bytes"]:
        raise PipelineError("retained source differs from acquisition")
    # Independently traverse source bytes; do not invoke the converter.
    rows = []
    offset = 0
    for number, raw in enumerate(source_bytes.splitlines(keepends=True), 1):
        payload = raw[:-1] if raw.endswith(b"\n") else raw
        payload = payload[:-1] if payload.endswith(b"\r") else payload
        rows.append(dict(line=number, byte_start=offset, byte_end=offset + len(raw),
                         source_sha256=digest(raw), tei_id=f"lightfoot-line-{number:06d}", text=payload.decode("utf-8")))
        offset += len(raw)
    account = json.loads((package_root / "package/source-accountability.json").read_text(encoding="utf-8"))
    if account["crosswalk"] != rows:
        raise PipelineError("historical source accounting does not match retained bytes")
    # This superseded adapter requires its historical oracle, not the current one.
    from build.tei.lightfoot_colossians_philemon_oracle import _assert_header_and_body

    _assert_header_and_body(etree.fromstring(original), rows)
    source = dict(source_path=retained["path"], source_sha256=retained["sha256"],
                  source_bytes=retained["bytes"], source_scope=retained["scope"])
    declared = retained["scope"]
    derived = bind_reviewed_header(original, expected_sha256=ORIGINAL_SHA, identity=IDENTITY,
                                  source=source, source_url=acquisition["url"], declared_scope=declared, revision=REVISION)
    if derived != bind_reviewed_header(original, expected_sha256=ORIGINAL_SHA, identity=IDENTITY,
                                      source=source, source_url=acquisition["url"], declared_scope=declared, revision=REVISION):
        raise PipelineError("header integration is nondeterministic")
    header = etree.fromstring(original).find("{http://www.tei-c.org/ns/1.0}teiHeader")
    header_end = ("</" + (header.prefix + ":" if header.prefix else "") + "teiHeader>").encode("utf-8")
    if derived.split(header_end, 1)[1] != original.split(header_end, 1)[1]:
        raise PipelineError("reviewed text changed")
    shutil.copytree(root / WORK_PATH, stage / WORK_PATH)
    evidence = stage / WORK_PATH / "integration/reviewed-v1"
    shutil.copytree(package_root / "package", evidence / "original-package")
    shutil.copyfile(package_root / "validation.json", evidence / "historical-validation.json")
    shutil.copyfile(root / REVIEW, evidence / "historical-review.md")
    target_source = stage / retained["path"]
    target_source.parent.mkdir(parents=True, exist_ok=True)
    target_source.write_bytes(source_bytes)
    candidate = evidence / "candidate.tei.xml"
    candidate.write_bytes(derived)
    schema_errors = validate_file(candidate)
    if schema_errors:
        raise PipelineError("derived TEI schema validation failed: " + str(schema_errors[:3]))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    scope = dict(kind="edition", declared=declared,
                 expected_members=[dict(path=retained["path"], position=1)],
                 included_members=[{key: retained[key] for key in ("path", "bytes", "sha256", "scope")} | {"position": 1}],
                 excluded_members=[])
    binding = make_file_binding(stage, candidate)
    common = dict(identity=IDENTITY, source=source, candidate=binding, scope=declared,
                  accepted_scope=dict(kind="edition", declared=declared),
                  expected_members=scope["expected_members"], included_members=scope["included_members"],
                  excluded_members=[], missing_members=[], unknown_members=[])
    historical = {name: make_file_binding(stage, evidence / name) for name in
                  ("historical-review.md", "historical-validation.json", "original-package/content.tei.xml", "original-package/source-accountability.json")}
    technical = dict(producer={"id": "reviewed-integration-v1"}, checker={"id": "lightfoot-independent-source-traversal-and-original-oracle"},
                     shared_assumptions=["The original oracle checks the original candidate; the adapter is separately checked for preservation."],
                     independent_corroboration="Direct source-byte line traversal and byte-identical text suffix before and after header integration.")
    observations = {
        "validation": "Original package member hashes, original oracle structure, source traversal, and derived TEI P5 XSD passed.",
        "accounting": f"All {len(rows)} retained source lines match the original crosswalk and readable TEI; no text byte changed during integration.",
        "fidelity": "Existing bounded visual review is retained with its original hash; direct source traversal and original oracle passed now. No new visual review is claimed.",
        "reproducibility": "Two header derivations from the hash-pinned original matched exactly. Original source-to-TEI reproducibility remains historical review evidence.",
        "schema": "The derived representation passes the vendored TEI P5 XSD.",
        "closure": "Current integration implementation and validator inputs are hash-bound below; this does not refresh historical converter closure attestations.",
    }
    implementation = {}
    for folder in (root / "ocd_kernel/tei", root / "ocd_kernel/library"):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".xsd"}:
                implementation[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    for path in (Path(__file__).resolve(), root / "build/tei/lightfoot_colossians_philemon_oracle.py"):
        implementation[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    command = "py -3 build/tools/integrate_reviewed_lightfoot.py " + " ".join(
        f'{flag} "{value}"' for flag, value in
        (("--root", root), ("--package", package_root), ("--stage", stage))
    ) + " (prepare phase; promotion destination recorded by caller)"
    for name, observation in observations.items():
        path = evidence / f"{name}.json"
        write(path, common | dict(contract="ocd-reviewed-integration-proof-v1", status="pass", command=command,
                                 exit_code=0, checked_at=now, observation=observation, historical_evidence=historical,
                                 implementation=implementation if name == "closure" else {}))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    source_account = evidence / "source-accounting.json"
    write(source_account, common | dict(source_sha256=source["source_sha256"], source_bytes=source["source_bytes"]))
    coverage = dict(status="partial", declared=declared, reached=["whole-retained-member"],
                    inspected=["whole-retained-member/source-lines-and-unchanged-text"], unreviewed=[])
    review = dict(reviewer="agent:reviewed-integration", reviewed_at=now, coverage=coverage,
                  source_quality_uncertainty=["Retained transcription and its notices remain authoritative; print-edition adjudication is not claimed."],
                  discrepancies=[], unreviewed_residuals=["No new visual inspection; historical bounded visual coverage is preserved in historical-review.md."])
    write(evidence / "review.json", common | review | dict(historical_evidence=historical))
    decision = dict(source_local_disposition="Existing reviewed retained transcription connected without text changes.", blockers=[],
                    agent_assessment=dict(status="accepted", actor="agent:reviewed-integration", assessed_at=now,
                                          supported_scope=declared, unassessed_stronger_claims=["human textual acceptance", "rights clearance", "public release", "category projection compatibility"], unresolved_claims=[]),
                    human_decision={"status": "not-recorded"})
    state_path = stage / WORK_PATH / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if any(item["target_id"] == "pg50857" for item in state["targets"]):
        raise PipelineError("edition state already exists; reconcile before integration")
    state["targets"].append(dict(target_id="pg50857", target_type="edition", stage="review", updated_at=now,
                                 reason="Exact reviewed TEI connected for technical acceptance.", evidence=[binding["path"]]))
    write(state_path, state)
    acceptance = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
                                         source_accounting_path=source_account, scope=scope, technical=technical,
                                         review=review | {"report_path": evidence / "review.json"}, representation_revision=REVISION, decision=decision)
    acceptance_path = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance_path, acceptance)
    validate_acceptance(acceptance_path, root=stage)
    write(evidence / "run.json", dict(root=str(root), original_package=str(package_root), stage=str(stage),
                                      original_sha256=ORIGINAL_SHA, derived_sha256=digest(derived), source_lines=len(rows), status="validated-pending"))
    return acceptance_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--promoted", type=Path, required=True)
    args = parser.parse_args()
    acceptance = prepare(args.root.resolve(), args.package.resolve(), args.stage.resolve())
    result = promote_accepted_master(args.stage, acceptance_path=acceptance, destination=args.promoted)
    print(json.dumps(result.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
