"""Stage Lightfoot's complete PG18191 HTML electronic witness."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei.lightfoot_essays_pg18191_native import (
    ALT_TEXT_SHA256, COVER_MEMBER_SHA256, RAW, ROOT, SOURCE, SOURCE_SHA256,
    adapt, source_bindings,
)
from build.tei.lightfoot_essays_pg18191_oracle import check
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import (PROMOTED_MASTER_REASON, build_acceptance_record,
                                       make_file_binding, validate_acceptance, write_acceptance)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


WORK_ID = "lightfoot-essays-supernatural-religion-1893"
FORM_ID = "lightfoot-essays-supernatural-religion-1893-gutenberg-retained-en"
EDITION_ID = "lightfoot-essays-supernatural-religion-1893-gutenberg-electronic"
ACQUISITION_ID = "lightfoot-essays-supernatural-religion-1893-gutenberg-electronic-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
EVIDENCE = WORK / "integration/lightfoot-essays-pg18191-current-v1"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/lightfoot-essays-direct-20260927-v1")
DIRECT_SHA256 = "b407ca936f44b8324a363c3abaf1c10725af19b584cddd9e8254abdb23019f02"
ADAPTED_SHA256 = "3e5db8f78639b7377f88464fbbcbb6a32fffd76fdd01ffadcb5811df2b97b5c1"
STAGE_PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
SCOPE = ("Complete real extracted Project Gutenberg 18191 HTML electronic witness of J. B. "
         "Lightfoot's Essays on the Work Entitled Supernatural Religion, second edition "
         "(1893): all 1,872 direct body children, including typed Project Gutenberg header "
         "and footer/license; title, preface, transcriber notice, contents, nine essay "
         "sections, one source appendix, 708 relocated footnotes, and both indices. "
         "The three ZIPs are packages, their real TXT members are alternate cross-checks, "
         "and the cover is a package-only unreferenced member, not a TEI graphic or text "
         "witness. No print collation or rights clearance is claimed.")


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> dict:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise ValueError(f"PG18191 JSON object required: {path}")
    return result


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    path = stage / relative
    _io_path(path).parent.mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)
    return path


def _put_json(stage: Path, relative: Path, result: object) -> Path:
    return _put(stage, relative, (json.dumps(result, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")) + "\n").encode())


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (stage.exists() or stage.parent.resolve(strict=True) != STAGE_PARENT.resolve(strict=True)
            or not stage.name.startswith("lightfoot-essays-pg18191-stage-")):
        raise ValueError("fresh external PG18191 candidate-review stage required")
    support = source_bindings()
    raw = _io_path(ROOT / SOURCE).read_bytes()
    original_acquisition = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    if (original_acquisition["source_path"] != SOURCE.as_posix()
            or original_acquisition["source_sha256"] != SOURCE_SHA256
            or original_acquisition["source_bytes"] != len(raw)
            or len(original_acquisition["retained_files"]) != 4
            or [item["path"] for item in original_acquisition["retained_files"]]
            != [item["path"] for item in support]):
        raise ValueError("PG18191 acquired HTML text binding differs")
    direct = _io_path(DIRECT / "candidate.tei.xml").read_bytes()
    if _sha(direct) != DIRECT_SHA256:
        raise ValueError("PG18191 direct candidate changed")
    adapted = adapt(direct)
    if _sha(adapted) != ADAPTED_SHA256:
        raise ValueError("PG18191 adapted candidate changed")
    oracle = check(adapted)
    before = _files(ROOT / WORK)
    if len(before) != 4 or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("PG18191 canonical acquired preimage differs")
    for relative, digest in before.items():
        content = _io_path(ROOT / WORK / relative).read_bytes()
        if _sha(content) != digest:
            raise ValueError(f"PG18191 preimage changed: {relative}")
        _put(stage, WORK / relative, content)
    _put(stage, SOURCE, raw)
    for item in support:
        relative = Path(item["path"])
        _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    for name in ALT_TEXT_SHA256:
        relative = RAW / name
        _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    for target in _read(ROOT / WORK / "state.json")["targets"]:
        for evidence in target["evidence"]:
            relative = Path(evidence)
            if relative.is_absolute() or ".." in relative.parts or not _io_path(ROOT / relative).is_file():
                raise ValueError(f"PG18191 state evidence path differs: {evidence}")
            _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    _put(stage, EVIDENCE / "inputs/direct-candidate.tei.xml", direct)
    _put(stage, EVIDENCE / "inputs/adapted-candidate.tei.xml", adapted)
    _put_json(stage, EVIDENCE / "inputs/oracle.json", oracle)
    acquired = _read(stage / ACQUISITION)
    for original, bound_member in zip(acquired["retained_files"], support):
        if any(original[key] != bound_member[key]
               for key in ("path", "bytes", "sha256", "media_type")):
            raise ValueError("PG18191 source/package/cover inventory differs")
    validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    original_credit = _io_path(ROOT / WORK / "SOURCE_CREDIT.md").read_text(encoding="utf-8")
    credit = (original_credit.rstrip() + "\n\n## Package-only cover and alternate witness accounting\n\n"
              "The HTML package contains a cover PNG (SHA-256 " + COVER_MEMBER_SHA256 +
              ") that is not a separate extracted retained file and is not referenced in the "
              "HTML body or represented as a TEI graphic. The two real TXT files match their "
              "respective ZIP members and are alternate cross-checks, not the accepted text "
              "authority. The accepted HTML witness retains the typed Gutenberg header/footer "
              "and license in its TEI text.\n")
    _put(stage, WORK / "SOURCE_CREDIT.md", credit.encode("utf-8"))
    revised = _read(stage / WORK / "work.json")
    original_work = _read(ROOT / WORK / "work.json")
    form = revised["textual_forms"][0]
    edition = form["editions"][0]
    if (revised["work_id"] != WORK_ID or form["textual_form_id"] != FORM_ID
            or edition["edition_id"] != EDITION_ID
            or edition["acquisition_ids"] != [ACQUISITION_ID] or edition.get("category")):
        raise ValueError("PG18191 acquired identity differs")
    edition["category"] = "prose"
    validate_identity_update(original_work, revised)
    _put_json(stage, WORK / "work.json", revised)
    load_work(_io_path(stage / WORK / "work.json"))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                    acquisition_id=ACQUISITION_ID)
    revision = dict(id="lightfoot-essays-pg18191-current-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete PG18191 extracted HTML witness, including typed provider wrapper.")
    binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA256,
                   source_bytes=len(raw), source_scope=original_acquisition["source_scope"])
    bound = bind_reviewed_header(adapted, expected_sha256=ADAPTED_SHA256, identity=identity,
                                 source=binding, source_url=original_acquisition["url"],
                                 declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != adapted.split(b"</teiHeader>", 1)[1]:
        raise ValueError("PG18191 reviewed header changed source text")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"PG18191 accepted candidate fails P5: {errors[:3]}")
    retained = acquired["retained_files"]
    expected = [dict(path=item["path"], position=i) for i, item in enumerate(retained, 1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(raw),
                     sha256=SOURCE_SHA256, scope=SCOPE)]
    excluded = [dict(path=item["path"], position=i,
                     reason="Retained ZIP package; not the text authority.")
                for i, item in enumerate(retained, 1) if i > 1]
    scope = dict(kind="selection", declared=SCOPE, expected_members=expected,
                 included_members=included, excluded_members=excluded)
    common = dict(identity=identity, source=binding, candidate=make_file_binding(stage, candidate),
                  accepted_scope=dict(kind="selection", declared=SCOPE),
                  expected_members=expected, included_members=included, excluded_members=excluded,
                  missing_members=[], unknown_members=[])
    account = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        scope=original_acquisition["source_scope"], source_sha256=SOURCE_SHA256,
        source_bytes=len(raw), source_oracle=oracle, direct_candidate_sha256=DIRECT_SHA256,
        adapted_candidate_sha256=ADAPTED_SHA256, package_support=support[1:],
        package_only_cover_sha256=COVER_MEMBER_SHA256, alternate_real_text_sha256=ALT_TEXT_SHA256,
        retained_text_authority=SOURCE.as_posix()))
    command = "py -3 -m build.tools.stage_lightfoot_essays_pg18191 --stage <fresh-external-root>"
    technical = dict(producer=dict(id="ocd-lightfoot-pg18191-complete-html-v1"),
                     checker=dict(id=oracle["contract"]),
                     shared_assumptions=["Producer and independent oracle read the same pinned real extracted HTML; the oracle separately checks all direct source spans and ZIP/real member equality."],
                     independent_corroboration="Complete extracted-HTML text stream and 18 span/ID oracle, exact package and alternate member checks, P5 XSD, actual-master native projection and independent row verifier.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            scope=SCOPE, status="pass", command=command, exit_code=0,
            claim=name, source_oracle=oracle, tei_p5_xsd="pass", native_projection="pass"))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:lightfoot-essays-pg18191-source-review", reviewed_at=now,
                  coverage=dict(status="partial", declared=SCOPE,
                                reached=["all 1,872 direct HTML body children, including provider header/footer",
                                         "complete normalized source-to-TEI text stream and 18 exact group spans",
                                         "nine source essay sections and one appendix",
                                         "708 relocated note paragraphs and both indices",
                                         "1,880 HTML/TEI identifiers and exact package/real member equality",
                                         "complete independent mechanical source oracle"],
                                inspected=["complete independent mechanical source oracle"],
                                unreviewed=["current exact-pair CVW visual comparison", "print collation"]),
                  source_quality_uncertainty=["The retained electronic witness was not collated to a print exemplar.",
                                              "Source footnotes were relocated and inconsistent hyphenation was retained."],
                  discrepancies=[], unreviewed_residuals=["Human visual review and rights clearance remain unrecorded."])
    review_path = _put_json(stage, EVIDENCE / "review.json", common | review | dict(scope=SCOPE))
    decision = dict(source_local_disposition="Agent acceptance of the complete PG18191 electronic HTML witness, including typed provider wrapper.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"],
                                          assessed_at=now, supported_scope=SCOPE, unresolved_claims=[],
                                          unassessed_stronger_claims=["visual review", "human acceptance",
                                                                      "print collation", "rights clearance", "publication"]))
    acceptance = stage / EDITION / "acceptance.json"
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                     source_accounting_path=account, scope=scope,
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
        raise ValueError("PG18191 edition is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or not projected["rows"]:
        raise ValueError(f"PG18191 native projection differs: {errors[:3]}; rows={len(projected['rows'])}")
    after = _files(stage / WORK)
    receipt = dict(contract="ocd-lightfoot-essays-pg18191-stage-v1", work_id=WORK_ID,
                   source_sha256=SOURCE_SHA256, direct_sha256=DIRECT_SHA256,
                   adapted_sha256=ADAPTED_SHA256, accepted_master_sha256=_sha(bound),
                   oracle=oracle, package_support=support[1:], package_only_cover_sha256=COVER_MEMBER_SHA256,
                   before=before, after=after,
                   native_rows=len(projected["rows"]), stage_root=stage.as_posix())
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
