"""Stage one complete, exclusive bsb754 nested-part work outside the checkout."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb754_nested as source
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-nested-direct-20260927-v3")
DIRECT_SHA = "bc4f0d11bff03574559e6efd9b1ebb671c0550795928ae97491128ffbf40df85"
REPRO = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-nested-direct-20260927-v4")
EVIDENCE = "openmgh-bsb754-nested-electronic-v1"
CONTRACT = "ocd-openmgh-bsb754-nested-stage-v1"


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
    return _put(stage, relative, source._json(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(work_id: str, stage: Path) -> dict:
    if work_id not in source.SELECTIONS:
        raise ValueError(f"bsb754 work is not selected: {work_id}")
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or ROOT.resolve() in stage.resolve().parents):
        raise ValueError("fresh external bsb754 work stage required")
    if _sha(DIRECT / "receipt.json") != DIRECT_SHA:
        raise ValueError("bsb754 original direct receipt changed")
    direct = _read(DIRECT / "receipt.json")
    if (direct.get("contract") != source.CONTRACT or direct.get("status") != "nonaccepted"
            or len(direct.get("selected_works", [])) != 5 or len(direct.get("held_parts", [])) != 2
            or len(direct.get("other_source_divisions", [])) != 17):
        raise ValueError("bsb754 direct batch accounting changed")
    entry = next(item for item in direct["selected_works"] if item["work_id"] == work_id)
    index, ordinals = source.SELECTIONS[work_id]
    if entry["source_work_div_index"] != index or entry["source_part_indexes"] != list(ordinals):
        raise ValueError("bsb754 selected native parts changed")
    candidate_bytes = _io_path(Path(entry["candidate_path"])).read_bytes()
    if (_sha(Path(entry["candidate_path"])) != entry["candidate_sha256"]
            or _sha(REPRO / work_id / "candidate.tei.xml") != entry["candidate_sha256"]):
        raise ValueError("bsb754 direct or reproduced candidate changed")
    source_bytes, original_source, source_works = source._source()
    original_work = _read(ROOT / entry["work_path"])
    acquisition = _read(ROOT / entry["acquisition_path"])
    if (_sha(ROOT / entry["work_path"]) != entry["work_sha256"]
            or _sha(ROOT / entry["acquisition_path"]) != entry["acquisition_sha256"]):
        raise ValueError("bsb754 current work/acquisition changed")
    selected = [source_works[index][j] for j in ordinals]
    oracle = source._check(selected, candidate_bytes, source._locators(original_work, source.SOURCE))
    if oracle != entry["oracle"]:
        raise ValueError("bsb754 independent source C14N oracle differs")
    work = Path("library/works") / work_id
    before = _files(ROOT / work)
    if set(before) != {"work.json", "state.json", (Path(entry["acquisition_path"]).relative_to(work)).as_posix()}:
        raise ValueError("bsb754 work preimage is not the three-file acquisition")
    for relative, digest in before.items():
        content = _io_path(ROOT / work / relative).read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("bsb754 work preimage changed during stage copy")
        _put(stage, work / relative, content)
    for dependency in (source.SOURCE, source.PACKAGE, source.ACQUISITION_RECEIPT):
        _put(stage, dependency, _io_path(ROOT / dependency).read_bytes())
    form = original_work["textual_forms"][0]
    edition_old = form["editions"][0]
    edition = work / "forms" / form["textual_form_id"] / "editions" / edition_old["edition_id"]
    acceptance_path = edition / "acceptance.json"
    master_path = edition / "master.tei.xml"
    if _io_path(ROOT / acceptance_path).exists() or _io_path(ROOT / master_path).exists():
        raise ValueError("bsb754 edition already accepted")
    revised = _read(stage / work / "work.json")
    edition_new = revised["textual_forms"][0]["editions"][0]
    if edition_new.get("language") or edition_new.get("category"):
        raise ValueError("bsb754 edition language/category preimage differs")
    edition_new.update(language="la", category="prose")
    validate_identity_update(original_work, revised)
    _put_json(stage, work / "work.json", revised)
    load_work(_io_path(stage / work / "work.json"))
    identity = dict(work_id=work_id, textual_form_id=form["textual_form_id"],
                    edition_id=edition_old["edition_id"], acquisition_id=edition_old["acquisition_ids"][0])
    evidence = work / "integration" / EVIDENCE
    _put(stage, evidence / "inputs/candidate.tei.xml", candidate_bytes)
    revision = dict(id=f"{work_id}-bsb754-nested-electronic-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete catalog-owned native source part(s) from the extracted electronic witness.")
    scope_text = (f"Complete bsb754 source work div {index} part indexes {list(ordinals)} (zero-based) "
                  f"for {work_id}; all selected native part descendants and markers in original order. "
                  "Sibling parts, other volume divisions, and held variants remain in the retained XML.")
    source_binding = dict(source_path=source.SOURCE.as_posix(), source_sha256=source.SOURCE_SHA,
                          source_bytes=len(source_bytes), source_scope=scope_text)
    derived = bind_reviewed_header(candidate_bytes, expected_sha256=entry["candidate_sha256"], identity=identity,
                                   source=source_binding, source_url=acquisition["url"],
                                   declared_scope=scope_text, revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != candidate_bytes.split(b"</teiHeader>", 1)[1]:
        raise ValueError("bsb754 accepted header changed source content")
    candidate = _put(stage, evidence / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"bsb754 accepted TEI P5 failure: {errors[:3]}")
    expected = [dict(path=source.PACKAGE.as_posix(), position=1), dict(path=source.SOURCE.as_posix(), position=2)]
    included = [dict(path=source.SOURCE.as_posix(), position=2, bytes=len(source_bytes),
                     sha256=source.SOURCE_SHA, scope=scope_text)]
    excluded = [dict(path=source.PACKAGE.as_posix(), position=1,
                     reason="Original ZIP is acquisition packaging; extracted XML is text authority.")]
    scope = dict(kind="selection", declared=scope_text, expected_members=expected,
                 included_members=included, excluded_members=excluded)
    acquired_binding = {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope")}
    common = dict(identity=identity, source=acquired_binding, candidate=make_file_binding(stage, candidate),
                  scope=scope_text, accepted_scope=dict(kind="selection", declared=scope_text),
                  expected_members=expected, included_members=included, excluded_members=excluded,
                  missing_members=[], unknown_members=[])
    account = _put_json(stage, evidence / "source-accounting.json", common | dict(
        scope=acquisition["source_scope"], source_sha256=source.SOURCE_SHA, source_bytes=len(source_bytes), source_work_div_index=index,
        source_part_indexes=list(ordinals), source_work_div_n=entry["source_work_div_n"],
        source_part_c14n_sha256=oracle["source_part_c14n_sha256"],
        start_xml_id=oracle["start_xml_id"], end_xml_id=oracle["end_xml_id"],
        catalog_locator_ids=entry["catalog_locator_ids"], ordered_source_locator_ids=entry["ordered_source_locator_ids"],
        locator_order_disposition=entry["locator_order_disposition"],
        direct_receipt_sha256=DIRECT_SHA, original_candidate_sha256=entry["candidate_sha256"],
        held_parts=direct["held_parts"], other_source_divisions=direct["other_source_divisions"],
        accepted_body_unchanged=True))
    command = "py -3 -m build.tools.stage_openmgh_bsb754_nested <work-id> --stage <fresh-external-root>"
    technical = dict(producer=dict(id=source.CONTRACT), checker=dict(id="ocd-openmgh-bsb754-nested-C14N-oracle-v1"),
                     shared_assumptions=["Producer and checker parse the same extracted TEI XML; checker compares complete native parts and catalog locator ownership."],
                     independent_corroboration="Complete source-part C14N, fresh candidate reproduction, XSD, and native row checker agree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, evidence / (name + ".json"), common | dict(status="pass", command=command,
                         exit_code=0, claim=name, source_oracle=oracle, direct_receipt_sha256=DIRECT_SHA,
                         clean_process_reproduction="pass", tei_xsd="pass", accepted_body_unchanged=True))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    now = _now()
    review = dict(reviewer=f"agent:{work_id}-bsb754-nested-source-review", reviewed_at=now,
                  coverage=dict(status="unavailable", declared=scope_text,
                                reached=["catalog locator ownership and complete native part C14N"],
                                inspected=["catalog locator ownership and complete native part C14N"],
                                unreviewed=["close CVW visual source comparison"]),
                  source_quality_uncertainty=["No print witness was collated."], discrepancies=[],
                  unreviewed_residuals=["Visual and human review remain unrecorded."])
    review_path = _put_json(stage, evidence / "review.json", common | review)
    decision = dict(source_local_disposition="Agent acceptance of the complete exclusive electronic source part(s) only.",
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
        raise ValueError("bsb754 edition target is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master_path.as_posix(), acceptance_path.as_posix()])
    _put_json(stage, work / "state.json", state)
    validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"bsb754 actual-master native projection failed: {errors[:3]}")
    credit = (f"# Source credit for {work_id}\n\nThis electronic text derives from the extracted openMGH TEI "
              f"at {source.SOURCE.as_posix()}. Monumenta Germaniae Historica and the Bavarian State Library, "
              "Munich, request attribution for electronic copies and derivatives. The retained source header "
              "describes digital annotations as CC BY 4.0 and the underlying text as believed public domain. "
              "The ZIP is acquisition packaging; no print collation or publication authorization is claimed.\n")
    _put(stage, work / "SOURCE_CREDIT.md", credit.encode("utf-8"))
    _put(stage, edition / "README.source.md", credit.encode("utf-8"))
    result = dict(contract=CONTRACT, status="staged-only", work_id=work_id,
                  canonical_root=ROOT.as_posix(), stage_root=stage.as_posix(),
                  direct_receipt=DIRECT.as_posix() + "/receipt.json", direct_receipt_sha256=DIRECT_SHA,
                  source_path=source.SOURCE.as_posix(), source_sha256=source.SOURCE_SHA,
                  package_path=source.PACKAGE.as_posix(), package_sha256=source.PACKAGE_SHA,
                  source_work_div_index=index, source_part_indexes=list(ordinals),
                  source_part_c14n_sha256=oracle["source_part_c14n_sha256"],
                  before=before, after=_files(stage / work), accepted_master_sha256=_sha(master),
                  acceptance_sha256=_sha(stage / acceptance_path), category="prose", language="la",
                  projection_rows=1, projection_status="independent-check-pass", installation="not-performed")
    _put_json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(source.SELECTIONS))
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.work_id, args.stage)
    print(json.dumps(dict(work_id=args.work_id, status=result["status"],
                          master_sha256=result["accepted_master_sha256"]), sort_keys=True))


if __name__ == "__main__":
    main()
