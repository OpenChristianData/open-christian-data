"""Prepare, but never install, a source-bound L741 acceptance fixture."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
PORTABLE_STAGE = ROOT / ".tmp_audit/l741-portable-v1-20261001"
STAGE = ROOT / ".tmp_audit/c"
WORK = Path("library/works/evangelische-gezangen-1806")
EDITION = WORK / "forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic"
ACQUISITION = EDITION / "acquisitions/evangelische-gezangen-1806-dbnl-acquired.json"
CANDIDATE = EDITION / "acceptance-candidate.tei.xml"
EVIDENCE = WORK / "integration/l741-dbnl-electronic-v1"
SOURCE = Path("raw/dbnl/evangelische-gezangen-1806/evangelische-gezangen-1806.xml")
SOURCE_SHA = "d8132943dd20b1053d1d77bda57cab2b69c9dc567e38ea4450baab914925abb9"
PORTABLE_SHA = "67b87d5cb2694ce033d6d03f28eacc26ede61cd03c4c2dc9163d93d82b21aab0"
WORK_SHA = "a2cf66e3e7c5c7916669fd6c098f21d448a63029de311f55ff580b604d2d8e13"
STATE_SHA = "6b27f9758a52831cfb4b44d349f9fd6b2c6ab991f4e1571e92ddb06a1c109c32"
ACQUISITION_SHA = "b694e97b4560799b8e8027e5d53ed7dee9341e01319f20ac5f3a72f90a634e29"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return path


def _copy(relative: Path) -> None:
    source = ROOT / relative
    target = STAGE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
    except OSError as exc:
        raise OSError(f"cannot stage {relative.as_posix()} from {source} to {target}") from exc


def stage() -> dict[str, object]:
    before = {"work": WORK_SHA, "state": STATE_SHA, "acquisition": ACQUISITION_SHA}
    for name, relative in (("work", WORK / "work.json"), ("state", WORK / "state.json"),
                           ("acquisition", ACQUISITION)):
        if _sha(ROOT / relative) != before[name]:
            raise ValueError(f"L741 {name} preimage changed")
    if _sha(PORTABLE_STAGE / CANDIDATE) != PORTABLE_SHA or _sha(ROOT / SOURCE) != SOURCE_SHA:
        raise ValueError("L741 portable candidate or retained source changed")
    if (ROOT / EDITION / "master.tei.xml").exists() or (ROOT / EDITION / "acceptance.json").exists():
        raise ValueError("L741 canonical acceptance preimage changed")
    if STAGE.exists():
        raise ValueError("L741 stage already promoted")
    STAGE.mkdir(parents=True)
    staged_candidate = STAGE / CANDIDATE
    staged_candidate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PORTABLE_STAGE / CANDIDATE, staged_candidate)
    _copy(SOURCE)
    source_manifest = json.loads((ROOT / "sources/manifest-acquisitions/l741-evangelische-gezangen-1806/source-manifest.json").read_text(encoding="utf-8"))
    resources = [Path(item["path"]) for item in source_manifest["authorities"] if item["role"] == "source-resource"]
    if len(resources) != 68:
        raise ValueError("L741 score resource count changed")
    for relative in resources:
        _copy(relative)
    for relative in (WORK / "work.json", WORK / "state.json", ACQUISITION,
                     Path("raw/dbnl/evangelische-gezangen-1806/acquisition-receipt.json"),
                     Path("raw/dbnl/evangelische-gezangen-1806/score-image-acquisition-receipt.json"),
                     Path("sources/manifest-acquisitions/l741-evangelische-gezangen-1806/source-manifest.json"),
                     Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/L741_EVANGELISCHE_GEZANGEN_V14_TECHNICAL_CLOSEOUT_20261001.json"),
                     Path("sources/dbnl/evangelische-gezangen-1806/README.source.md"),
                     Path("data/hymns/evangelische-gezangen-1806/README.md")):
        _copy(relative)
    work_path = STAGE / WORK / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if form["textual_form_id"] != "evangelische-gezangen-1806-dbnl-retained" or edition["edition_id"] != "evangelische-gezangen-1806-dbnl-electronic":
        raise ValueError("L741 identity changed")
    form["category"] = "hymns"
    form["language"] = "nl"
    _write_json(work_path, work)
    load_work(work_path)
    acquisition = json.loads((STAGE / ACQUISITION).read_text(encoding="utf-8"))
    identity = dict(work_id="evangelische-gezangen-1806",
                    textual_form_id=form["textual_form_id"], edition_id=edition["edition_id"],
                    acquisition_id=acquisition["acquisition_id"])
    revision = dict(id="l741-dbnl-electronic-accepted-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Bind the complete retained DBNL electronic witness as a TEI master; public rows select only the 192 hymn texts.")
    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=acquisition["source_bytes"], source_scope=acquisition["source_scope"])
    original = (STAGE / CANDIDATE).read_bytes()
    bound = bind_reviewed_header(original, expected_sha256=PORTABLE_SHA, identity=identity,
                                 source=source, source_url=acquisition["url"],
                                 declared_scope=acquisition["source_scope"], revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise ValueError("L741 acceptance altered the source-bound TEI body")
    bound_path = STAGE / EVIDENCE / "candidate.tei.xml"
    bound_path.parent.mkdir(parents=True, exist_ok=True)
    bound_path.write_bytes(bound)
    if errors := validate_file(bound_path):
        raise ValueError(f"L741 bound TEI P5 failure: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=acquisition["source_bytes"],
                     sha256=SOURCE_SHA, scope=acquisition["source_scope"])]
    scope = dict(kind="selection", declared=acquisition["source_scope"], expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=identity, source=source, candidate=make_file_binding(STAGE, bound_path),
                  scope=acquisition["source_scope"], accepted_scope=dict(kind="selection", declared=acquisition["source_scope"]),
                  expected_members=expected, included_members=included, excluded_members=[],
                  missing_members=[], unknown_members=[])
    accounting = _write_json(STAGE / EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=acquisition["source_bytes"],
        retained_member_count=1, retained_score_resource_count=68,
        source_manifest_sha256=_sha(STAGE / "sources/manifest-acquisitions/l741-evangelische-gezangen-1806/source-manifest.json"),
        normalized_uri_count=68, portable_candidate_sha256=PORTABLE_SHA,
        source_hymn_divisions=192, source_hymn_poem_groups=197, source_score_gifs=68,
        publication_selection="192 hymn texts only; source master remains complete"))
    command = "py -3 -m pytest -p no:cacheprovider tests/test_l741_evangelische_gezangen_1806.py tests/test_projection_l741_gezangen.py -q"
    technical = dict(producer=dict(id="l741-dbnl-retained-source-to-tei"),
                     checker=dict(id="l741-dbnl-source-oracle-and-projection-verifier"),
                     shared_assumptions=["Both producer and checker use the retained DBNL XML and exact L741 work boundary."],
                     independent_corroboration="Source oracle and P5 checks pass; two package replays agree. The public-row verifier rereads retained TEI.2 but shares row and stanza mapping helpers with its producer. A separate independent reviewer compared all 192 source heading/order/section boundaries, 1,292 stanzas and 8,873 lines, candidate/master text C14N, score targets, and a changed-XLVI-section rejection.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _write_json(STAGE / EVIDENCE / f"{name}.json", common | dict(
            claim=name, status="pass", command=command, exit_code=0,
            v14_closeout_sha256=_sha(STAGE / "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/L741_EVANGELISCHE_GEZANGEN_V14_TECHNICAL_CLOSEOUT_20261001.json"),
            portable_candidate_sha256=PORTABLE_SHA, exact_score_uri_normalization_count=68,
            source_oracle="pass", tei_p5="pass", package_replay_count=2,
            projection_rows=192, projection_hymn_xlvi_sections=6))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(reviewer="agent:l741-dbnl-electronic-technical-acceptance", reviewed_at=now,
                  coverage=dict(status="partial", declared=acquisition["source_scope"],
                                reached=["complete retained electronic XML", "192 hymn divisions", "68 retained score resources",
                                         "source-to-TEI oracle", "68 URI/hash bindings", "192 source hymn rows and six XLVI sections"],
                                inspected=["source-to-TEI oracle", "68 URI/hash bindings", "192 source hymn rows and six XLVI sections"],
                                unreviewed=["print page scans", "DBNL interventions at pages 151, 352, 386", "human acceptance"]),
                  source_quality_uncertainty=["No print page scans were retained for visual print collation."],
                  discrepancies=[], unreviewed_residuals=["Print collation and human review remain open.",
                                                        "Rights clearance and public publication authorization remain open."])
    review_path = _write_json(STAGE / EVIDENCE / "review.json", common | review)
    decision = dict(source_local_disposition="Technically accept the complete retained DBNL electronic witness as one TEI master; public text rows select only its 192 body hymns.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                        supported_scope=acquisition["source_scope"], unresolved_claims=[],
                        unassessed_stronger_claims=["print collation", "human acceptance", "broader rights clearance", "public publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(STAGE, identity=identity, candidate_path=bound_path,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
    acceptance = STAGE / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    master = STAGE / EDITION / "master.tei.xml"
    master.write_bytes(bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(STAGE, master))
    write_acceptance(acceptance, record)
    state_path = STAGE / WORK / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    target = next(item for item in state["targets"] if item["target_id"] == identity["edition_id"])
    if target["stage"] != "review":
        raise ValueError("L741 state review preimage changed")
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    target["evidence"].extend([(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    _write_json(state_path, state)
    validate_acceptance(acceptance, root=STAGE)
    validate_state(state_path, root=STAGE)
    result = dict(stage=str(STAGE), status="staged-only", preimage=before,
                  portable_candidate_sha256=PORTABLE_SHA, master_sha256=_sha(master),
                  acceptance_sha256=_sha(acceptance), work_sha256=_sha(work_path),
                  state_sha256=_sha(state_path), human_acceptance="not-recorded",
                  rights_clearance="not-determined", canonical_install="not-performed")
    _write_json(STAGE / "l741-acceptance-stage-receipt.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(stage(), sort_keys=True))
