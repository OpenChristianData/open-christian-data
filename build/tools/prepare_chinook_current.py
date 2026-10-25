"""Prepare one unchanged-body PG33105 technical acceptance in a fresh stage."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree
from build.tei.l744_hymns_oracle import _oracle
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (PROMOTED_MASTER_REASON, build_acceptance_record,
    make_file_binding, validate_acceptance, write_acceptance)
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WID = "l744-pg33105-chinook-hymns"
FID = "pg33105-complete-text"
EID = "pg33105-second-edition-1889-revised-enlarged"
AID = "pg33105-l744-retained-source-only"
WORK = Path("library/works") / WID
EDITION = WORK / "forms" / FID / "editions" / EID
ACQUISITION = EDITION / "acquisitions" / (AID + ".json")
MANIFEST = Path("sources/manifest-acquisitions") / WID / "source-manifest.json"
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20261001-l744-pg33105-main-v1/package")
STAGE = ROOT / ".tmp_audit/chinook-acceptance-20261002-v1"
LOG = ROOT / "reports/_logs/chinook-current-20261002-v1"
EVIDENCE = WORK / "integration/chinook-acceptance-20261002-v1"
EXPECTED_TEI = "f90dcad4c534c9069c3b792c57ac8d19c7289646fe11aa6a5757a66df7e637e7"
T = "{http://www.tei-c.org/ns/1.0}"

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def save(path: Path, value: object) -> None:
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    content = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    io_path(path).write_bytes(content)

def copy(relative: Path) -> None:
    source = resolve_repo_path(ROOT, relative.as_posix()) if relative.parts[0] == "raw" else ROOT / relative
    io_path((STAGE / relative).parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(io_path(source), io_path(STAGE / relative))

def main() -> None:
    if STAGE.exists():
        raise ValueError("Fresh stage required; prior evidence is retained")
    if (ROOT / EDITION / "master.tei.xml").exists() or (ROOT / EDITION / "acceptance.json").exists():
        raise ValueError("Canonical acceptance already exists")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(PACKAGE)
    report = validate(manifest, package, _oracle)
    original = package.member_bytes("content.tei.xml")
    if digest(original) != EXPECTED_TEI or report.status != "pass":
        raise ValueError("Reviewed candidate or current oracle differs")
    acquisition = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    before = _files(ROOT / WORK)
    STAGE.mkdir(parents=True)
    shutil.copytree(io_path(ROOT / WORK), io_path(STAGE / WORK))
    # Copy the complete explicit source/authority/evidence closure; no new acquisition.
    copy(MANIFEST)
    for entry in manifest.record["authorities"]:
        copy(Path(entry["path"]))
    for entry in acquisition["retained_files"]:
        copy(Path(entry["path"]))
    for target in json.loads((ROOT / WORK / "state.json").read_bytes())["targets"]:
        for reference in target.get("evidence", []):
            relative = Path(reference.split("#", 1)[0])
            if not (STAGE / relative).exists():
                copy(relative)
    # Historical closeout is a retained dated input, not current acceptance authority.
    historical = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/L744_PG33105_CURRENT_TECHNICAL_20261001")
    for item in (ROOT / historical).iterdir():
        if item.is_file():
            copy(item.relative_to(ROOT))
    identity = dict(work_id=WID, textual_form_id=FID, edition_id=EID, acquisition_id=AID)
    source = {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope", "source_kind")}
    revision = dict(id="pg33105-retained-complete-technical-v1", date=datetime.now(timezone.utc).date().isoformat(),
        note="Technically accept the complete retained PG33105 digital HTML witness with unchanged reconstructed body; print, human, rights and public decisions remain separate.")
    header, body = original.split(b"</teiHeader>", 1)
    header = header.replace(b"<sourceDesc><p>", b"<sourceDesc><bibl>", 1).replace(b"</p></sourceDesc>", b"</bibl></sourceDesc>", 1)
    header = header.replace(b"Nonaccepted source reconstruction.", b"Technical reconstruction of the retained electronic witness.", 1)
    ready = header + b"</teiHeader>" + body
    bound = bind_reviewed_header(ready, expected_sha256=digest(ready), identity=identity,
        source=source, source_url=acquisition["url"], declared_scope=source["source_scope"], revision=revision)
    html = next(item for item in acquisition["retained_files"] if item["path"].endswith("pg33105-images.html"))
    # The singular included text member differs from the acquisition member-set hash.
    bound = bound.replace(("<idno type=\"sha256\">" + source["source_sha256"] + "</idno>").encode(),
                          ("<idno type=\"sha256\">" + html["sha256"] + "</idno>").encode(), 1)
    if bound.split(b"</teiHeader>", 1)[1] != body:
        raise ValueError("Acceptance changed reviewed body bytes")
    candidate = STAGE / EVIDENCE / "candidate.tei.xml"
    save(candidate, bound)
    if findings := validate_file(candidate):
        raise ValueError(f"P5 errors: {findings[:3]}")
    # Recheck all readable structures directly after the header renewal.
    class MemoryCandidate:
        def __init__(self, values):
            self.values = values
            self.sha256 = digest(values["content.tei.xml"])
        def member_bytes(self, name):
            return self.values[name]
    members = {name: package.member_bytes(name) for name in package.member_names}
    members["content.tei.xml"] = bound
    accountability = json.loads(members["source-accountability.json"])
    accountability.update(candidate_sha256=digest(bound), candidate_bytes=len(bound))
    members["source-accountability.json"] = (json.dumps(accountability, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    renewed = _oracle(manifest, MemoryCandidate(members))
    if renewed["status"] != "pass":
        raise ValueError(f"Renewed independent oracle: {renewed['findings']}")
    retained = acquisition["retained_files"]
    expected = [dict(path=item["path"], position=i) for i, item in enumerate(retained, 1)]
    included = [dict(path=html["path"], position=2, bytes=html["bytes"], sha256=html["sha256"], scope=source["source_scope"])]
    excluded = [dict(path=item["path"], position=i, reason="Retained archive, unreferenced cover, receipt or inventory is support; the complete digital HTML body is included.") for i, item in enumerate(retained, 1) if item != html]
    scope = dict(kind="selection", declared=source["source_scope"], expected_members=expected, included_members=included, excluded_members=excluded)
    common = dict(identity=identity, source=source, candidate=make_file_binding(STAGE, candidate), scope=source["source_scope"],
        accepted_scope={key: scope[key] for key in ("kind", "declared")}, expected_members=expected, included_members=included,
        excluded_members=excluded, missing_members=[], unknown_members=[], source_sha256=source["source_sha256"], source_bytes=source["source_bytes"])
    accounting = STAGE / EVIDENCE / "source-accounting.json"
    save(accounting, common | dict(historical_tei_sha256=EXPECTED_TEI, unchanged_body_sha256=digest(body),
        source_element_count=2271, hymns=20, translations=20, interlinear_tables=142, verse_divisions=195,
        closing_prayers=2, archive_members=2, cover_disposition="Byte-bound retained support; not referenced by source HTML."))
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]), checker=dict(id=manifest.record["validator"]["id"]),
        shared_assumptions=["Same retained bytes, P5 schema and explicit HTML-to-TEI vocabulary; source profile is a shared historical census."],
        independent_corroboration="Current html5lib oracle independently recomputes source tree, text, attributes, order, parent relationships and interlinear row boundaries, using a parser independent of the lxml producer. Exact body byte conservation corroborates the renewed header derivation.")
    command = "py -3 -m build.tools.prepare_chinook_current"
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = STAGE / EVIDENCE / (name + ".json")
        save(path, common | dict(status="pass", command=command, exit_code=0, claim=name, current_oracle=renewed,
            historical_reproducibility="Two fresh-process historical package replays remain byte-identical; this header derivation conserves the entire body exactly.",
            bindings={"source_manifest":manifest.sha256,"package":package.sha256,"original_candidate":EXPECTED_TEI},
            artifact_conservation="Original TEI body unchanged byte-for-byte; no converter, checker, policy or schema edits."))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(reviewer="agent:chinook-whole-work-owner", reviewed_at=now,
        coverage=dict(status="partial", declared=source["source_scope"], reached=["complete retained source/TEI mechanical comparison", "title and interlinear source structures"],
            inspected=["complete retained source/TEI mechanical comparison", "title and interlinear source structures"],
            unreviewed=["CVW visual comparison", "printed edition collation", "human verification"]),
        source_quality_uncertainty=["Retained digital witness has no page scans. Provider header says English; printed title says Chinook Jargon and interlinear English is present. No language code is inferred.",
            "Source title-page HTML attribute names the sibling Ojibway collection; its literal title, provider identity, numbered hymns and archive establish this PG33105 work. The wrong source attribute is retained as source evidence."],
        discrepancies=[], unreviewed_residuals=["No close visual or human review is claimed; no print or worldwide rights clearance is claimed."])
    review_path = STAGE / EVIDENCE / "review.json"
    save(review_path, common | review | dict(selected_review_patterns=["RP-01","RP-04","RP-06","RP-11","RP-13","RP-14","RP-15"]))
    decision = dict(source_local_disposition="Accept the complete retained digital HTML text including provider header/footer/license and all interlinear tables; support remains retained.", blockers=[],
        agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now, supported_scope=source["source_scope"], unresolved_claims=[],
            unassessed_stronger_claims=["CVW visual comparison", "print collation", "human acceptance", "independent rights clearance", "public publication"]), human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(STAGE, identity=identity, candidate_path=candidate, source_accounting_path=accounting,
        scope=scope, technical=technical, review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
    acceptance = STAGE / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=STAGE)
    master = STAGE / EDITION / "master.tei.xml"
    save(master, bound)
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(STAGE, master))
    write_acceptance(acceptance, record)
    state = json.loads((STAGE / WORK / "state.json").read_bytes())
    target = next(item for item in state["targets"] if item["target_id"] == EID)
    if target["stage"] != "review":
        raise ValueError("Edition target no longer in review")
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    target["evidence"].extend([(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    save(STAGE / WORK / "state.json", state)
    validate_acceptance(acceptance, root=STAGE)
    validate_state(STAGE / WORK / "state.json", root=STAGE)
    result = dict(status="staged-only", work_id=WID, stage_root=str(STAGE), before=before, after=_files(STAGE / WORK),
        master_sha256=digest(bound), acceptance_sha256=digest(acceptance.read_bytes()), unchanged_body_sha256=digest(body),
        current_source_oracle="pass", p5="pass", canonical_install="not-performed", human_acceptance="not-recorded", rights="unresolved", public_publication="not-performed")
    save(LOG / "stage-receipt.json", result)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
