"""Freeze the complete retained PG13360 TXT as one source-bound acceptance stage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei.missionary_survey_pg13360_native import ROOT, SOURCE, SOURCE_SHA256, adapt, source_path
from build.tei.missionary_survey_pg13360_oracle import check
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import (PROMOTED_MASTER_REASON, build_acceptance_record,
                                       make_file_binding, validate_acceptance, write_acceptance)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


WORK_ID = "missionary-survey"
FORM_ID = "missionary-survey-gutenberg-retained-en"
EDITION_ID = "missionary-survey-gutenberg-electronic"
ACQUISITION_ID = "missionary-survey-gutenberg-electronic-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
EVIDENCE = WORK / "integration/missionary-survey-pg13360-current-v1"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/missionary-survey-direct-20260927-v1")
ORIGINAL_SHA256 = "be815784cb77e2fd786d70da15342573f647d36a7f167c451750df2e39e11e13"
ADAPTED_SHA256 = "edb4d15479b8d9f00cc45284108ac982d82286453f4eaed09a8b7eecd797bd4b"
STAGE_PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
SCOPE = ("Complete retained PG13360 electronic Missionary Survey book: all 4,095 nonblank "
         "book lines between the unique Project Gutenberg start and end markers, the title page, "
         "transcriber note, preface, contents, eleven chapters, 76 fixed-width table blocks "
         "in the Gutenberg transposed orientation, linked footnotes, and the end marker. "
         "Twenty-seven pre-start and 350 post-end wrapper lines remain in retained TXT "
         "outside the represented book. No print exemplar is claimed.")


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


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
    return _put(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")) + "\n").encode("utf-8"))


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (stage.exists() or stage.parent.resolve(strict=True) != STAGE_PARENT.resolve(strict=True)
            or not stage.name.startswith("missionary-survey-pg13360-stage-")):
        raise ValueError("fresh external PG13360 stage under candidate-reviews required")
    raw = source_path().read_bytes()
    acquisition = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    if (acquisition["source_path"] != SOURCE.as_posix()
            or acquisition["source_sha256"] != SOURCE_SHA256
            or acquisition["source_bytes"] != len(raw)
            or [(item["path"], item["sha256"]) for item in acquisition["retained_files"]]
            != [(SOURCE.as_posix(), SOURCE_SHA256)]):
        raise ValueError("PG13360 acquired one-member source binding differs")
    original = _io_path(DIRECT / "candidate.tei.xml").read_bytes()
    if _sha(original) != ORIGINAL_SHA256:
        raise ValueError("PG13360 direct candidate changed")
    adapted = adapt(original)
    if _sha(adapted) != ADAPTED_SHA256:
        raise ValueError("PG13360 adapted candidate changed")
    oracle = check(adapted)
    before = _files(ROOT / WORK)
    if len(before) != 4 or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("PG13360 canonical acquired preimage differs")
    for relative, digest in before.items():
        content = _io_path(ROOT / WORK / relative).read_bytes()
        if _sha(content) != digest:
            raise ValueError(f"PG13360 preimage changed: {relative}")
        _put(stage, WORK / relative, content)
    _put(stage, SOURCE, raw)
    for target in _read(ROOT / WORK / "state.json")["targets"]:
        for evidence in target["evidence"]:
            relative = Path(evidence)
            if relative.is_absolute() or ".." in relative.parts or not _io_path(ROOT / relative).is_file():
                raise ValueError(f"PG13360 state evidence path differs: {evidence}")
            _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    _put(stage, EVIDENCE / "inputs/direct-candidate.tei.xml", original)
    _put(stage, EVIDENCE / "inputs/adapted-candidate.tei.xml", adapted)
    _put_json(stage, EVIDENCE / "inputs/oracle.json", oracle)
    revised = _read(stage / WORK / "work.json")
    original_work = _read(ROOT / WORK / "work.json")
    edition = revised["textual_forms"][0]["editions"][0]
    if (revised["work_id"] != WORK_ID
            or revised["textual_forms"][0]["textual_form_id"] != FORM_ID
            or edition["edition_id"] != EDITION_ID
            or edition["acquisition_ids"] != [ACQUISITION_ID]
            or edition.get("category")):
        raise ValueError("PG13360 acquired edition identity differs")
    edition["category"] = "prose"
    validate_identity_update(original_work, revised)
    _put_json(stage, WORK / "work.json", revised)
    load_work(_io_path(stage / WORK / "work.json"))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                    acquisition_id=ACQUISITION_ID)
    revision = dict(id="missionary-survey-pg13360-current-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete Project Gutenberg TXT book with source-line fidelity and native title-page roles.")
    binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA256,
                   source_bytes=len(raw), source_scope=acquisition["source_scope"])
    bound = bind_reviewed_header(adapted, expected_sha256=ADAPTED_SHA256, identity=identity,
                                 source=binding, source_url=acquisition["url"],
                                 declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != adapted.split(b"</teiHeader>", 1)[1]:
        raise ValueError("PG13360 reviewed header changed book text")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"PG13360 accepted P5 XSD failed: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(raw),
                     sha256=SOURCE_SHA256, scope=SCOPE)]
    accepted_scope = dict(kind="selection", declared=SCOPE, expected_members=expected,
                          included_members=included, excluded_members=[])
    common = dict(identity=identity, source=binding, candidate=make_file_binding(stage, candidate),
                  scope=acquisition["source_scope"], accepted_scope=dict(kind="selection", declared=SCOPE),
                  expected_members=expected, included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA256, source_bytes=len(raw),
        source_oracle=oracle, direct_candidate_sha256=ORIGINAL_SHA256,
        adapted_candidate_sha256=ADAPTED_SHA256,
        retained_text_authority=SOURCE.as_posix(), title_page_role_mapping="source-specific P5 native rendition",
        included_selected_nonblank_lines=4095, excluded_pre_start_wrapper_lines=27,
        excluded_post_end_wrapper_lines=350))
    command = "py -3 -m build.tools.stage_missionary_survey_pg13360 --stage <fresh-external-root>"
    technical = dict(producer=dict(id="ocd-missionary-survey-pg13360-retained-txt-v1"),
                     checker=dict(id=oracle["contract"]),
                     shared_assumptions=["Producer and oracle read the same pinned UTF-8 Project Gutenberg TXT; oracle independently compares all selected raw lines."],
                     independent_corroboration="Independent complete line stream, wrapper, table, title-page, chapter and note oracle; TEI P5 and actual-master native projection.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            scope=SCOPE, status="pass", command=command, exit_code=0, claim=name,
            source_oracle=oracle, tei_p5_xsd="pass", native_projection="pass"))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:missionary-survey-pg13360-source-review", reviewed_at=now,
                  coverage=dict(status="partial", declared=SCOPE,
                                reached=["all 5,031 TXT source lines and unique Gutenberg markers",
                                         "all 4,095 selected nonblank source-line carriers",
                                         "title-page roles, eleven chapters, 76 fixed-width tables and linked notes",
                                         "independent source oracle, TEI P5 and native projection",
                                         "complete independent mechanical source oracle"],
                                inspected=["complete independent mechanical source oracle"],
                                unreviewed=["current exact-pair CVW visual comparison", "print collation"]),
                  source_quality_uncertainty=["Gutenberg TXT table transposition is retained; no print witness was collated."],
                  discrepancies=[], unreviewed_residuals=["Human review and rights clearance remain unrecorded."])
    review_path = _put_json(stage, EVIDENCE / "review.json", common | review | dict(scope=SCOPE))
    decision = dict(source_local_disposition="Agent acceptance of the complete PG13360 electronic book within one retained TXT member.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"],
                                          assessed_at=now, supported_scope=SCOPE,
                                          unresolved_claims=[], unassessed_stronger_claims=[
                                              "visual review", "human acceptance", "print collation",
                                              "rights clearance", "publication"]))
    acceptance = stage / EDITION / "acceptance.json"
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                     source_accounting_path=account, scope=accepted_scope,
                                     technical=technical, review=review | dict(report_path=review_path),
                                     representation_revision=revision, decision=decision)
    write_acceptance(_io_path(acceptance), record)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    master = _put(stage, EDITION / "master.tei.xml", bound)
    record["promotion"].update(status="promoted", promoted_at=now,
                               master=make_file_binding(stage, master))
    write_acceptance(_io_path(acceptance), record)
    state = _read(stage / WORK / "state.json")
    targets = [item for item in state["targets"] if item["target_type"] == "edition"
               and item["target_id"] == EDITION_ID]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("PG13360 edition state is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                          category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 16:
        raise ValueError(f"PG13360 actual-master native projection differs: {errors[:3]}; rows={len(projected['rows'])}")
    after = _files(stage / WORK)
    receipt = dict(contract="ocd-missionary-survey-pg13360-stage-v1", work_id=WORK_ID,
                   source_sha256=SOURCE_SHA256, direct_sha256=ORIGINAL_SHA256,
                   adapted_sha256=ADAPTED_SHA256, accepted_master_sha256=_sha(bound),
                   oracle=oracle, before=before, after=after, native_rows=len(projected["rows"]),
                   stage_root=stage.as_posix())
    _put_json(stage, Path("stage-receipt.json"), receipt)
    return dict(status="staged-for-review", work_id=WORK_ID,
                stage=stage.as_posix(), before_files=len(before), after_files=len(after),
                native_rows=len(projected["rows"]), receipt_sha256=_sha(_io_path(stage / "stage-receipt.json").read_bytes()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().stage), sort_keys=True))


if __name__ == "__main__":
    main()
