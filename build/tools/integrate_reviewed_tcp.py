"""Integrate the two explicitly reviewed, byte-preserving TCP editions.

This is a closed admission list, not a generic inference of source fidelity.
Historical visual coverage remains bounded; no publication is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lxml import etree
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, promote_accepted_master, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import install_accepted_work
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

CASES = {
    "occom-moses-paul-execution-sermon": dict(code="N09814", ticket="31", short="occom", category="sermons", sha="56d612750fed73102ec0daa1afbbd9182cfe3660275f957fb535fd86d11a3d1a", review="31-occom-visual-continuation-20260906.md", validation="e1231039df406309b55a276c81035a00005a5aa72699577341d7dfaf40ad3942"),
    "baxter-christian-directory": dict(code="A26892", ticket="29", short="baxter", category="prose", sha="1b90e060921164cb2486d938c653640537cb710e8b1889c48a0e10f5e515035e", review="29-baxter-visual-continuation-20260906.md", validation="a9f30e770917c30fd128d5b1d87ebdc6b3aca757340590c3624dfeb70d404637"),
}
CAMPAIGN = Path("plans/2026-08-31-sample-first-library-verification")
REVISION = dict(id="reviewed-tcp-integration-v1", date="2026-09-10", note="Added library identity and acceptance bindings; every retained original byte is preserved and original revision history is unchanged.")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def prepare(root: Path, work: str, stage: Path) -> Path:
    case = CASES[work]
    if stage.exists():
        raise PipelineError("staging root must be fresh")
    source_dir = root / "sources/structured-text" / work
    manifest_path = source_dir / (work + ".source-manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    primary = [a for a in manifest["authorities"] if a["role"] == "primary-source"]
    if len(primary) != 1:
        raise PipelineError("TCP integration requires one complete TEI source member")
    retained = primary[0]
    source_bytes = resolve_repo_path(root, retained["path"]).read_bytes()
    if digest(source_bytes) != case["sha"] or len(source_bytes) != retained["bytes"] or retained["sha256"] != case["sha"]:
        raise PipelineError("retained source no longer matches exact reviewed edition")
    authorities = {}
    for item in manifest["authorities"]:
        content = resolve_repo_path(root, item["path"]).read_bytes()
        if digest(content) != item["sha256"] or len(content) != item["bytes"]:
            raise PipelineError("source authority changed: " + item["path"])
        authorities[item["path"]] = dict(bytes=len(content), sha256=digest(content), role=item["role"])
    package_root = Path(f'C:/tmp/ocd-ticket{case["ticket"]}-{case["short"]}-current-20260906-01/run-a')
    original = (package_root / "package/content.tei.xml").read_bytes()
    if original != source_bytes:
        raise PipelineError("reviewed TEI must equal complete retained source bytes")
    package_manifest = json.loads((package_root / "package/manifest.json").read_text(encoding="utf-8"))
    if package_manifest["source_manifest"]["sha256"] != digest(manifest_path.read_bytes()):
        raise PipelineError("reviewed package source manifest changed")
    for item in package_manifest["members"]:
        if Path(item["name"]).name != item["name"]:
            raise PipelineError("nonlocal package member")
        content = (package_root / "package" / item["name"]).read_bytes()
        if len(content) != item["bytes"] or digest(content) != item["sha256"]:
            raise PipelineError("reviewed package member changed")
        if content != (package_root.parent / "run-b/package" / item["name"]).read_bytes():
            raise PipelineError("historical independent runs differ")
    validation_bytes = (package_root / "validation.json").read_bytes()
    if digest(validation_bytes) != case["validation"] or json.loads(validation_bytes)["status"] != "pass":
        raise PipelineError("historical validation binding changed")
    review_path = root / CAMPAIGN / case["review"]
    review_text = review_path.read_text(encoding="utf-8")
    if case["sha"] not in review_text:
        raise PipelineError("visual review does not bind candidate")
    image_dir = root / CAMPAIGN / "artifacts" / (case["short"] + "-20260906")
    screenshots = {}
    for name, checksum in re.findall(r"\| `([^`]+\.jpg)` \|[^\n]*?`([0-9a-f]{64})`", review_text):
        image_path = image_dir / name
        if digest(image_path.read_bytes()) != checksum:
            raise PipelineError("historical visual evidence changed: " + name)
        screenshots[image_path.relative_to(root).as_posix()] = checksum
    if not screenshots:
        raise PipelineError("no bound historical visual evidence")
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    tree = etree.fromstring(original)
    title = "".join(tree.find("t:teiHeader/t:fileDesc/t:titleStmt/t:title", ns).itertext()).strip()
    author = "".join(tree.find("t:teiHeader/t:fileDesc/t:titleStmt/t:author", ns).itertext()).strip()
    readme = (source_dir / "README.md").read_bytes()
    url = re.search(r"- Pinned XML: (https://\S+)", readme.decode("utf-8")).group(1)
    identity = dict(work_id=work, textual_form_id="tcp-english", edition_id=case["code"].lower(), acquisition_id=case["code"].lower() + "-tei")
    work_rel = Path("library/works") / work
    edition = work_rel / "forms/tcp-english/editions" / identity["edition_id"]
    evidence = stage / work_rel / "integration/reviewed-tcp-v1"
    declared = f'Complete retained TCP {case["code"]} TEI edition, including its header, front matter, body, back matter and explicit gaps where present; no page-image reconstruction.'
    member = dict(path=retained["path"], bytes=len(original), sha256=case["sha"], media_type="application/tei+xml", scope=declared)
    source = dict(source_path=member["path"], source_bytes=member["bytes"], source_sha256=member["sha256"], source_scope=declared)
    args = dict(expected_sha256=case["sha"], identity=identity, source=source, source_url=url, declared_scope=declared, revision=REVISION)
    derived = bind_reviewed_header(original, **args)
    evidence.mkdir(parents=True)
    shutil.copytree(package_root / "package", evidence / "original-package")
    (evidence / "historical-validation.json").write_bytes(validation_bytes)
    (evidence / "historical-review.md").write_bytes(review_path.read_bytes())
    (stage / work_rel / "README.source.md").write_bytes(readme)
    target_source = stage / member["path"]
    target_source.parent.mkdir(parents=True, exist_ok=True)
    target_source.write_bytes(source_bytes)
    write(evidence / "derivation-arguments.json", args)
    worker = "from pathlib import Path; import json,sys; from ocd_kernel.tei.reviewed_integration import bind_reviewed_header; p=Path(sys.argv[1]); sys.stdout.buffer.write(bind_reviewed_header((p/'original-package/content.tei.xml').read_bytes(),**json.loads((p/'derivation-arguments.json').read_text(encoding='utf-8'))))"
    reproduced = subprocess.run([sys.executable, "-c", worker, str(evidence)], cwd=root, check=True, capture_output=True).stdout
    if derived != reproduced or original.split(b"</teiHeader>", 1)[1] != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("integration reproduction or original text preservation failed")
    candidate = evidence / "candidate.tei.xml"
    candidate.write_bytes(derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError("derived TEI schema errors: " + str(errors[:5]))
    counts = dict(Counter(etree.QName(n).localname for n in tree.iter() if isinstance(n.tag, str)))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    write(stage / work_rel / "work.json", dict(schema_version="2.0", work_id=work, title=title, evidence=[member["path"]], creators=[dict(name=author, role="author", evidence=[member["path"] + "#teiHeader/fileDesc/titleStmt/author"])], textual_forms=[dict(textual_form_id=identity["textual_form_id"], language="en", editions=[dict(edition_id=identity["edition_id"], title="TCP " + case["code"] + " retained TEI edition", language="en", category=case["category"], acquisition_ids=[identity["acquisition_id"]])])]))
    write(stage / edition / "acquisitions" / (identity["acquisition_id"] + ".json"), dict(schema_version="2.0", acquisition_id=identity["acquisition_id"], edition_id=identity["edition_id"], provider="Text Creation Partnership", url=url, route="born-digital", retained_files=[member], warnings=["Retained transcription gaps remain explicit. Source attribution is in README.source.md; image rights are not included."]))
    binding = make_file_binding(stage, candidate)
    scope = dict(kind="edition", declared=declared, expected_members=[dict(path=member["path"], position=1)], included_members=[{k: member[k] for k in ("path", "bytes", "sha256", "scope")} | dict(position=1)], excluded_members=[])
    common = dict(identity=identity, source=source, candidate=binding, scope=declared, accepted_scope=dict(kind="edition", declared=declared), **{k: scope[k] for k in ("expected_members", "included_members", "excluded_members")}, missing_members=[], unknown_members=[])
    observations = dict(validation="Exact historical package and current source authority bindings pass; derived TEI P5 XSD passes.", accounting="Complete primary TEI member byte equality; supporting manifest authorities separately hash-verified, not mislabeled literary content.", fidelity="Every original byte is preserved; original source-native tree, attributes, order, notes and gaps remain unchanged. Historical bounded visual observations retained, not expanded.", reproducibility="Header derivation independently repeated in a second Python process with identical bytes; historical run-a/run-b member equality also verified.", schema="Derived document passes current vendored TEI P5 XSD.", closure="Current integration, acceptance and schema implementation hashes recorded; historical converter attestation is retained, not relabeled as a new run.")
    implementation = {p.relative_to(root).as_posix(): digest(p.read_bytes()) for folder in (root / "ocd_kernel/tei", root / "ocd_kernel/library") for p in sorted(folder.rglob("*")) if p.is_file() and p.suffix in {".py", ".xsd"}}
    implementation[Path(__file__).relative_to(root).as_posix()] = digest(Path(__file__).read_bytes())
    command = subprocess.list2cmdline([sys.executable, str(Path(__file__)), "--work", work, "--stage", str(stage)])
    technical = dict(producer=dict(id="reviewed-tcp-header-adapter-v1"), checker=dict(id="complete-retained-byte-comparison-and-tei-xsd"), shared_assumptions=["XML parser and schema validator share lxml; original-byte equality independently proves preserved source structure."], independent_corroboration="Complete binary equality before header derivation, reversible insertions, untouched text suffix, historical supported visual review with screenshot hashes.")
    for name, observation in observations.items():
        path = evidence / (name + ".json")
        write(path, common | dict(status="pass", command=command, exit_code=0, checked_at=now, observation=observation, source_element_counts=counts, authorities=authorities, historical_screenshots=screenshots, implementation=implementation if name == "closure" else {}))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    account = evidence / "source-accounting.json"
    write(account, common | dict(source_sha256=member["sha256"], source_bytes=member["bytes"]))
    review = dict(reviewer="agent:reviewed-tcp-integration", reviewed_at=now, coverage=dict(status="partial", declared=declared, reached=["complete-retained-tei"], inspected=["complete-retained-tei"], unreviewed=[]), source_quality_uncertainty=["Source transcription gaps and errors remain; no adjudication against page images."], discrepancies=[], unreviewed_residuals=["Fresh inspection is mechanical preservation of the full TEI tree. Visual inspection remains the bounded historical coverage in historical-review.md; no exhaustive proofreading."])
    write(evidence / "review.json", common | review)
    decision = dict(source_local_disposition="Complete reviewed retained TEI integrated with reversible header additions.", blockers=[], agent_assessment=dict(status="accepted", actor="agent:reviewed-tcp-integration", assessed_at=now, supported_scope=declared, unassessed_stronger_claims=["human acceptance", "page-image fidelity", "rights clearance", "public release", "category projection compatibility"], unresolved_claims=[]), human_decision=dict(status="not-recorded"))
    write(stage / work_rel / "state.json", dict(schema_version="2.0", work_id=work, targets=[dict(target_id=identity["edition_id"], target_type="edition", stage="review", updated_at=now, reason="Complete reviewed TEI integrated with source structure unchanged.", evidence=[binding["path"]])]))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=account, scope=scope, technical=technical, review=review | dict(report_path=evidence / "review.json"), representation_revision=REVISION, decision=decision)
    acceptance = stage / edition / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", choices=CASES, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--promoted", type=Path)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.install and (not args.promoted or not args.receipt):
        parser.error("installation requires promoted destination and receipt")
    acceptance = prepare(ROOT, args.work, args.stage.resolve())
    result = dict(status="validated-pending", acceptance=str(acceptance))
    if args.promoted:
        promoted = promote_accepted_master(args.stage, acceptance_path=acceptance, destination=args.promoted)
        result = promoted.as_dict()
        if args.install:
            result = install_accepted_work(ROOT, args.promoted, work_id=args.work)
    if args.receipt:
        write(args.receipt, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
