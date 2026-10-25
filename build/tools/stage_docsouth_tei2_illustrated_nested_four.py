"""Stage one of four illustrated nested-quote DocSouth works externally."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree

from build.tools import prepare_docsouth_tei2_illustrated_nested_four as direct_source
from build.tei import docsouth_tei2_illustrated as source
from build.tei.docsouth_tei2_illustrated_oracle import check
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-nested-four-direct-20260927-v1")
DIRECT_SHA = "8c4a103cd26724d73799a8c727a3354911729b00265735fed9fb13fb92af5ec3"
REPRO = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-nested-four-direct-20260927-v2")
EVIDENCE = "docsouth-tei2-illustrated-nested-four-electronic-v1"
CONTRACT = "ocd-docsouth-tei2-illustrated-nested-four-stage-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, direct_source._json(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(work_id: str, stage: Path) -> dict:
    if work_id not in direct_source.SELECTIONS:
        raise ValueError(f"DocSouth simple work is not selected: {work_id}")
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or ROOT.resolve() in stage.resolve().parents):
        raise ValueError("fresh external DocSouth work stage required")
    if _sha(DIRECT / "receipt.json") != DIRECT_SHA:
        raise ValueError("DocSouth direct receipt changed")
    direct = _read(DIRECT / "receipt.json")
    if (direct.get("contract") != direct_source.CONTRACT or direct.get("status") != "nonaccepted"
            or len(direct.get("selected_works", [])) != 4
            or {item["work_id"] for item in direct["selected_works"]} != direct_source.SELECTIONS):
        raise ValueError("DocSouth direct batch scope changed")
    entry = next(item for item in direct["selected_works"] if item["work_id"] == work_id)
    candidate_bytes = _io_path(Path(entry["candidate_path"])).read_bytes()
    if (_sha(Path(entry["candidate_path"])) != entry["candidate_sha256"]
            or _sha(REPRO / work_id / "candidate.tei.xml") != entry["candidate_sha256"]):
        raise ValueError("DocSouth candidate reproduction changed")
    reproduced, producer = source.convert(work_id, selections=direct_source.SELECTIONS)
    if reproduced != candidate_bytes or producer != entry["producer"]:
        raise ValueError("DocSouth source conversion changed")
    oracle = check(ROOT / entry["source_path"], entry["source_sha256"], candidate_bytes,
                   ROOT / entry["acquisition_receipt_path"])
    if oracle != entry["oracle"]:
        raise ValueError("DocSouth independent source oracle changed")
    original_work = _read(ROOT / entry["work_path"])
    acquisition = _read(ROOT / entry["acquisition_path"])
    if (_sha(ROOT / entry["work_path"]) != entry["work_sha256"]
            or _sha(ROOT / entry["state_path"]) != entry["state_sha256"]
            or _sha(ROOT / entry["acquisition_path"]) != entry["acquisition_sha256"]
            or _sha(ROOT / entry["acquisition_receipt_path"]) != entry["acquisition_receipt_sha256"]):
        raise ValueError("DocSouth current sidecar or receipt changed")
    source_bytes = _io_path(ROOT / entry["source_path"]).read_bytes()
    if (sha256(source_bytes).hexdigest() != entry["source_sha256"]
            or len(source_bytes) != entry["source_bytes"]
            or acquisition.get("source_path") != entry["source_path"]
            or acquisition.get("source_sha256") != entry["source_sha256"]
            or len(acquisition.get("retained_files", [])) != entry["producer"]["source_entity_declarations"] + 1):
        raise ValueError("DocSouth retained TEI.2 authority changed")
    work = Path("library/works") / work_id
    before = _files(ROOT / work)
    if set(before) != {"work.json", "state.json", (Path(entry["acquisition_path"]).relative_to(work)).as_posix()}:
        raise ValueError("DocSouth work preimage is not the three-file acquisition")
    for relative, digest in before.items():
        content = _io_path(ROOT / work / relative).read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("DocSouth work preimage changed during copy")
        _put(stage, work / relative, content)
    image_paths = [Path(member["path"]) for member in acquisition["retained_files"][1:]]
    for relative in (Path(entry["source_path"]), *image_paths, Path(entry["acquisition_receipt_path"]),
                     source.INVENTORY.relative_to(ROOT)):
        _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    form = original_work["textual_forms"][0]
    edition_old = form["editions"][0]
    edition = work / "forms" / form["textual_form_id"] / "editions" / edition_old["edition_id"]
    acceptance_path = edition / "acceptance.json"
    master_path = edition / "master.tei.xml"
    if _io_path(ROOT / acceptance_path).exists() or _io_path(ROOT / master_path).exists():
        raise ValueError("DocSouth edition already accepted")
    revised = _read(stage / work / "work.json")
    edition_new = revised["textual_forms"][0]["editions"][0]
    if edition_new.get("language") or edition_new.get("category"):
        raise ValueError("DocSouth edition category/language preimage differs")
    edition_new.update(language="en", category="prose")
    validate_identity_update(original_work, revised)
    _put_json(stage, work / "work.json", revised)
    load_work(_io_path(stage / work / "work.json"))
    identity = dict(work_id=work_id, textual_form_id=form["textual_form_id"],
                    edition_id=edition_old["edition_id"], acquisition_id=edition_old["acquisition_ids"][0])
    evidence = work / "integration" / EVIDENCE
    _put(stage, evidence / "inputs/candidate.tei.xml", candidate_bytes)
    revision = dict(id=f"{work_id}-docsouth-tei2-illustrated-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete source-bound TEI.2 front/body and source-declared figures as P5 with explicit legacy-carrier mapping.")
    scope_text = (f"Complete retained DocSouth TEI.2 XML member {entry['source_path']} for {work_id}; "
                  "one source text with front/body, all original readings, and the exact source-declared figure JPEGs. "
                  "No table or back matter occurs in this selected source.")
    source_binding = dict(source_path=entry["source_path"], source_sha256=entry["source_sha256"],
                          source_bytes=len(source_bytes), source_scope=scope_text)
    derived = bind_reviewed_header(candidate_bytes, expected_sha256=entry["candidate_sha256"], identity=identity,
                                   source=source_binding, source_url=acquisition["url"],
                                   declared_scope=scope_text, revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != candidate_bytes.split(b"</teiHeader>", 1)[1]:
        raise ValueError("DocSouth acceptance header changed source body")
    candidate = _put(stage, evidence / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"DocSouth accepted TEI P5 XSD failed: {errors[:3]}")
    retained = acquisition["retained_files"]
    expected = [dict(path=member["path"], position=index) for index, member in enumerate(retained, 1)]
    included = [dict(path=member["path"], position=index, bytes=member["bytes"],
                     sha256=member["sha256"], scope=member["scope"])
                for index, member in enumerate(retained, 1)]
    scope = dict(kind="selection", declared=scope_text, expected_members=expected,
                 included_members=included, excluded_members=[])
    acquired_binding = {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope")}
    common = dict(identity=identity, source=acquired_binding, candidate=make_file_binding(stage, candidate),
                  scope=scope_text, accepted_scope=dict(kind="selection", declared=scope_text),
                  expected_members=expected, included_members=included, excluded_members=[],
                  missing_members=[], unknown_members=[])
    account = _put_json(stage, evidence / "source-accounting.json", common | dict(
        scope=acquisition["source_scope"], source_sha256=entry["source_sha256"],
        source_bytes=len(source_bytes), source_doctype=entry["producer"]["source_doctype"],
        source_entity_declarations=entry["producer"]["source_entity_declarations"], source_oracle=oracle, source_rights_text_sha256=entry["producer"]["source_rights_text_sha256"],
        direct_receipt_sha256=DIRECT_SHA, original_candidate_sha256=entry["candidate_sha256"],
        accepted_body_unchanged=True))
    command = "py -3 -m build.tools.stage_docsouth_tei2_illustrated_nested_four <work-id> --stage <fresh-external-root>"
    technical = dict(producer=dict(id=source.CONTRACT), checker=dict(id=oracle["contract"]),
                     shared_assumptions=["Producer and checker parse the same retained XML/JPEG envelope; checker independently compares every front/body node, DTD image binding, and source metadata field."],
                     independent_corroboration="Fresh-process byte reproduction, TEI P5 XSD, and native prose projection agree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, evidence / (name + ".json"), common | dict(status="pass", command=command,
                         exit_code=0, claim=name, source_oracle=oracle, direct_receipt_sha256=DIRECT_SHA,
                         clean_process_reproduction="pass", tei_xsd="pass", accepted_body_unchanged=True))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    now = _now()
    review = dict(reviewer=f"agent:{work_id}-docsouth-tei2-source-review", reviewed_at=now,
                  coverage=dict(status="unavailable", declared=scope_text,
                                reached=["complete front/body, figure/JPEG, and rights/credit oracle"],
                                inspected=["complete front/body, figure/JPEG, and rights/credit oracle"],
                                unreviewed=["close CVW visual source comparison"]),
                  source_quality_uncertainty=["No print witness was independently collated."], discrepancies=[],
                  unreviewed_residuals=["Visual and human review remain unrecorded."])
    review_path = _put_json(stage, evidence / "review.json", common | review)
    decision = dict(source_local_disposition="Agent acceptance of the exact electronic text and mapped P5 carriers only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                                          supported_scope=scope_text, unresolved_claims=[],
                    unassessed_stronger_claims=["visual review", "human acceptance", "print collation", "rights clearance", "publication"]))
    acceptance = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                         source_accounting_path=account, scope=scope, technical=technical,
                                         review=review | dict(report_path=review_path),
                                         representation_revision=revision, decision=decision)
    write_acceptance(_io_path(stage / acceptance_path), acceptance)
    validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
    master = _put(stage, master_path, derived)
    acceptance["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, master))
    write_acceptance(_io_path(stage / acceptance_path), acceptance)
    state = _read(stage / work / "state.json")
    targets = [t for t in state["targets"] if t["target_type"] == "edition" and t["target_id"] == edition_old["edition_id"]]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("DocSouth edition target is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master_path.as_posix(), acceptance_path.as_posix()])
    _put_json(stage, work / "state.json", state)
    validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != entry["native_projection_rows"]:
        raise ValueError(f"DocSouth actual-master native projection failed: {errors[:3]}")
    source_tree = etree.fromstring(source_bytes)
    availability_nodes = source_tree.findall("teiHeader/fileDesc/publicationStmt/availability")
    if len(availability_nodes) != 1:
        raise ValueError("DocSouth source availability differs")
    availability = " ".join("".join(availability_nodes[0].itertext()).split())
    source_responsibilities = source_tree.findall("teiHeader/fileDesc/titleStmt/respStmt")
    if not source_responsibilities:
        raise ValueError("DocSouth source responsibility statements missing")
    credit_roles = []
    for statement in source_responsibilities:
        role = statement.find("resp")
        name = statement.find("name")
        if role is None or name is None:
            raise ValueError("DocSouth source responsibility statement differs")
        role_text = " ".join("".join(role.itertext()).split())
        name_text = " ".join("".join(name.itertext()).split())
        if not role_text or not name_text:
            raise ValueError("DocSouth source responsibility wording missing")
        credit_roles.append(f"- {role_text}: {name_text}\n")
    funder = source_tree.find("teiHeader/fileDesc/titleStmt/funder")
    if funder is None or not " ".join("".join(funder.itertext()).split()):
        raise ValueError("DocSouth source funding credit missing")
    funder_text = " ".join("".join(funder.itertext()).split())
    credit = (f"# Electronic source credit for {work_id}\n\n"
              f"This reconstructed electronic text derives from the retained DocSouth TEI.2 witness at {entry['source_path']}. "
              "Credit Documenting the American South and the University of North Carolina at Chapel Hill.\n\n"
              "The retained electronic header credits:\n\n"
              + "".join(credit_roles) + f"- Funding: {funder_text}\n\n"
              f"The source availability states: {availability} This stage does not establish worldwide rights clearance, "
              "print collation, or public release.\n")
    _put(stage, work / "SOURCE_CREDIT.md", credit.encode("utf-8"))
    _put(stage, edition / "README.source.md", credit.encode("utf-8"))
    result = dict(contract=CONTRACT, status="staged-only", work_id=work_id,
                  canonical_root=ROOT.as_posix(), stage_root=stage.as_posix(),
                  direct_receipt=(DIRECT / "receipt.json").as_posix(), direct_receipt_sha256=DIRECT_SHA,
                  source_path=entry["source_path"], source_sha256=entry["source_sha256"],
                  source_bytes=len(source_bytes), source_doctype=entry["producer"]["source_doctype"],
                  source_entity_declarations=entry["producer"]["source_entity_declarations"], source_rights_text_sha256=entry["producer"]["source_rights_text_sha256"],
                  source_oracle=oracle, before=before, after=_files(stage / work),
                  accepted_master_sha256=_sha(master), acceptance_sha256=_sha(stage / acceptance_path),
                  category="prose", language="en", projection_rows=len(projected["rows"]),
                  projection_status="independent-check-pass", installation="not-performed")
    _put_json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(direct_source.SELECTIONS))
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.work_id, args.stage)
    print(json.dumps(dict(work_id=args.work_id, status=result["status"],
                          master_sha256=result["accepted_master_sha256"]), sort_keys=True))


if __name__ == "__main__":
    main()
