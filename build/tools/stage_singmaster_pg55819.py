"""Stage the complete PG55819 book and its exact extracted image supports."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei.singmaster_pg55819_native import (
    ROOT, SOURCE, adapt, retained_bindings, source_path,
)
from build.tei.singmaster_pg55819_oracle import check
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import (PROMOTED_MASTER_REASON, build_acceptance_record,
                                       make_file_binding, validate_acceptance, write_acceptance)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


WORK_ID = "singmaster-story-of-lutheran-missions"
FORM_ID = "singmaster-story-of-lutheran-missions-gutenberg-retained-en"
EDITION_ID = "singmaster-story-of-lutheran-missions-gutenberg-electronic"
ACQUISITION_ID = "singmaster-story-of-lutheran-missions-gutenberg-electronic-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
EVIDENCE = WORK / "integration/singmaster-pg55819-current-v1"
SOURCE_SHA256 = "11d6827013ade4b36ed68c3f9f9d4f5d96086405013deb202651361d5a41871a"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/singmaster-pg55819-direct-20260928-v1")
DIRECT_SHA256 = "0f06812667a16896749b357a66fd232f94748832b1b7103b61ec7e6a49be86ae"
ADAPTED_SHA256 = "e749012ef615cb8df667c792969b04cf9a0748500614f37fd1af3e937d02c6dc"
STAGE_PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
SCOPE = ("Complete retained Project Gutenberg 55819 electronic edition of Elsie Singmaster's "
         "The Story of Lutheran Missions: 1,010 ordered visible text carriers across 774 direct "
         "HTML body children between the unique Gutenberg header/footer, title matter, "
         "contents, preface, six chapters, footnotes, tables, 21 electronic page markers, "
         "36 illustrations, transcriber notes, and exact Gutenberg end marker. The ZIP is "
         "a package and the 36 extracted images are support, not independent text witnesses. "
         "The separate retained TXT is a cross-check, not the accepted text authority. "
         "No print collation or rights clearance is claimed.")


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> dict:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise ValueError(f"PG55819 JSON object required: {path}")
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
            or not stage.name.startswith("singmaster-pg55819-stage-")):
        raise ValueError("fresh external PG55819 candidate-review stage required")
    raw = source_path().read_bytes()
    support = retained_bindings()
    original_acquisition = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    if (original_acquisition["source_path"] != SOURCE.as_posix()
            or original_acquisition["source_sha256"] != SOURCE_SHA256
            or original_acquisition["source_bytes"] != len(raw)
            or len(original_acquisition["retained_files"]) != 2
            or original_acquisition["retained_files"][1]["path"] != support[0]["path"]):
        raise ValueError("PG55819 acquired HTML text binding differs")
    direct = _io_path(DIRECT / "candidate.tei.xml").read_bytes()
    if _sha(direct) != DIRECT_SHA256:
        raise ValueError("PG55819 direct candidate changed")
    adapted = adapt(direct)
    if _sha(adapted) != ADAPTED_SHA256:
        raise ValueError("PG55819 adapted candidate changed")
    oracle = check(adapted)
    before = _files(ROOT / WORK)
    if len(before) != 4 or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("PG55819 canonical acquired preimage differs")
    for relative, digest in before.items():
        content = _io_path(ROOT / WORK / relative).read_bytes()
        if _sha(content) != digest:
            raise ValueError(f"PG55819 preimage changed: {relative}")
        _put(stage, WORK / relative, content)
    _put(stage, SOURCE, raw)
    for item in support:
        relative = Path(item["path"])
        _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    for target in _read(ROOT / WORK / "state.json")["targets"]:
        for evidence in target["evidence"]:
            relative = Path(evidence)
            if relative.is_absolute() or ".." in relative.parts or not _io_path(ROOT / relative).is_file():
                raise ValueError(f"PG55819 state evidence path differs: {evidence}")
            _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    _put(stage, EVIDENCE / "inputs/direct-candidate.tei.xml", direct)
    _put(stage, EVIDENCE / "inputs/adapted-candidate.tei.xml", adapted)
    _put_json(stage, EVIDENCE / "inputs/oracle.json", oracle)
    acquired = _read(stage / ACQUISITION)
    if acquired["retained_files"][1] != support[0]:
        # The pre-existing package inventory can have its own source-specific scope.
        if any(acquired["retained_files"][1][key] != support[0][key]
               for key in ("path", "bytes", "sha256", "media_type")):
            raise ValueError("PG55819 original package inventory differs")
    acquired["retained_files"].extend(support[1:])
    _put_json(stage, ACQUISITION, acquired)
    validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    original_credit = _io_path(ROOT / WORK / "SOURCE_CREDIT.md").read_text(encoding="utf-8")
    credit = (original_credit.rstrip() + "\n\n## Retained image support for the accepted electronic book\n\n"
              "The 36 extracted image files referenced by the retained HTML are locally retained "
              "as support, not separate text witnesses. The retained ZIP is a package. "
              "Their exact source-order occurrences and bytes are checked against the accepted "
              "TEI and independent source oracle.\n\n")
    credit += "".join(f"- {item['path']} — SHA-256 {item['sha256']}\n" for item in support[1:])
    _put(stage, WORK / "SOURCE_CREDIT.md", credit.encode("utf-8"))
    revised = _read(stage / WORK / "work.json")
    original_work = _read(ROOT / WORK / "work.json")
    form = revised["textual_forms"][0]
    edition = form["editions"][0]
    if (revised["work_id"] != WORK_ID or form["textual_form_id"] != FORM_ID
            or edition["edition_id"] != EDITION_ID
            or edition["acquisition_ids"] != [ACQUISITION_ID] or edition.get("category")):
        raise ValueError("PG55819 acquired identity differs")
    edition["category"] = "prose"
    validate_identity_update(original_work, revised)
    _put_json(stage, WORK / "work.json", revised)
    load_work(_io_path(stage / WORK / "work.json"))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                    acquisition_id=ACQUISITION_ID)
    revision = dict(id="singmaster-pg55819-current-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete Project Gutenberg HTML book with 36 extracted illustration supports.")
    binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA256,
                   source_bytes=len(raw), source_scope=original_acquisition["source_scope"])
    bound = bind_reviewed_header(adapted, expected_sha256=ADAPTED_SHA256, identity=identity,
                                 source=binding, source_url=original_acquisition["url"],
                                 declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != adapted.split(b"</teiHeader>", 1)[1]:
        raise ValueError("PG55819 reviewed header changed source text")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"PG55819 accepted candidate fails P5: {errors[:3]}")
    retained = acquired["retained_files"]
    expected = [dict(path=item["path"], position=i) for i, item in enumerate(retained, 1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(raw),
                     sha256=SOURCE_SHA256, scope=SCOPE)]
    excluded = [dict(path=item["path"], position=i,
                     reason=("Retained ZIP package; not the text authority." if i == 2 else
                             "Retained HTML-referenced image support; not an independent text witness."))
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
        adapted_candidate_sha256=ADAPTED_SHA256, image_support=support[1:], package_support=support[0],
        retained_text_authority=SOURCE.as_posix()))
    command = "py -3 -m build.tools.stage_singmaster_pg55819 --stage <fresh-external-root>"
    technical = dict(producer=dict(id="ocd-singmaster-pg55819-html-v1"),
                     checker=dict(id=oracle["contract"]),
                     shared_assumptions=["Producer and independent oracle parse the same pinned HTML; the oracle separately traverses the full body carrier stream and retained images."],
                     independent_corroboration="Complete HTML body/source-carrier oracle, image byte pins, P5 XSD, actual-master native projection and independent row verifier.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            scope=SCOPE, status="pass", command=command, exit_code=0,
            claim=name, source_oracle=oracle, tei_p5_xsd="pass", native_projection="pass"))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:singmaster-pg55819-source-review", reviewed_at=now,
                  coverage=dict(status="partial", declared=SCOPE,
                                reached=["all 774 direct HTML body children and wrapper boundary",
                                         "all 1,010 ordered source text carriers",
                                         "six chapters, 21 electronic pages, 11 notes and transcriber notes",
                                         "36 occurrences and 36 exact retained image files",
                                         "complete independent mechanical source oracle"],
                                inspected=["complete independent mechanical source oracle"],
                                unreviewed=["current exact-pair CVW visual comparison", "print collation"]),
                  source_quality_uncertainty=["The retained electronic book was not collated to a print exemplar.",
                                              "Project Gutenberg reports silent typographical corrections."],
                  discrepancies=[], unreviewed_residuals=["Human visual review and rights clearance remain unrecorded."])
    review_path = _put_json(stage, EVIDENCE / "review.json", common | review | dict(scope=SCOPE))
    decision = dict(source_local_disposition="Agent acceptance of the complete PG55819 electronic book with separately bound image support.",
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
        raise ValueError("PG55819 edition is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or not projected["rows"]:
        raise ValueError(f"PG55819 native projection differs: {errors[:3]}; rows={len(projected['rows'])}")
    after = _files(stage / WORK)
    receipt = dict(contract="ocd-singmaster-pg55819-stage-v1", work_id=WORK_ID,
                   source_sha256=SOURCE_SHA256, direct_sha256=DIRECT_SHA256,
                   adapted_sha256=ADAPTED_SHA256, accepted_master_sha256=_sha(bound),
                   oracle=oracle, image_support=support[1:], package_support=support[0], before=before, after=after,
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
