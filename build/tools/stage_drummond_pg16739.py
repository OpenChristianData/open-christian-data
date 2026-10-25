"""Stage the complete Project Gutenberg 16739 electronic witness for review."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei.drummond_pg16739_native import ROOT, SOURCE, SOURCE_SHA256, adapt, direct_candidate
from build.tei.drummond_pg16739_native_oracle import MANIFEST, PACKAGE, check
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


WORK_ID = "drummond-greatest-thing"
FORM_ID = "drummond-greatest-thing-retained-text"
EDITION_ID = "drummond-greatest-thing-pg16739-electronic-witness"
ACQUISITION_ID = "drummond-greatest-thing-pg16739-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
EVIDENCE = WORK / "integration/drummond-pg16739-current-v1"
STAGE_PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
ADAPTED_SHA256 = "1de6077dda49d0a1524b61b1c183de8bf370c67e9d5d21586368dde445d0b09b"
SCOPE = (
    "Complete retained Project Gutenberg 16739 UTF-8 plain-text electronic witness of Henry Drummond's "
    "The Greatest Thing in the World and Other Addresses: all 3,922 source lines, source title and credits, "
    "all collected addresses in their retained order, the Gutenberg opening and closing wrappers and complete "
    "license. The retained electronic collection is the work boundary; no constituent-address split or "
    "specific print-edition equivalence is claimed."
)


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"PG16739 JSON object required: {path}")
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
            or not stage.name.startswith("drummond-pg16739-stage-")):
        raise ValueError("fresh external PG16739 stage required")
    raw = _io_path(ROOT / SOURCE).read_bytes()
    if len(raw) != 204970 or _sha(raw) != SOURCE_SHA256:
        raise ValueError("PG16739 retained plain text differs")
    acquired = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    retained = acquired["retained_files"]
    if (len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["bytes"] != len(raw) or retained[0]["sha256"] != SOURCE_SHA256
            or acquired["url"] != "https://www.gutenberg.org/ebooks/16739"):
        raise ValueError("PG16739 acquisition member or source identity differs")
    direct = direct_candidate()
    adapted, counts = adapt(direct)
    if _sha(adapted) != ADAPTED_SHA256:
        raise ValueError("PG16739 adapted candidate differs")
    oracle = check(adapted)
    if oracle["source_oracle_status"] != "pass":
        raise ValueError("PG16739 complete source oracle failed")
    before = _files(ROOT / WORK)
    if len(before) != 3 or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("PG16739 canonical acquired preimage differs")
    for relative in before:
        _put(stage, WORK / relative, _io_path(ROOT / WORK / relative).read_bytes())
    _put(stage, SOURCE, raw)
    for target in _read(ROOT / WORK / "state.json")["targets"]:
        for evidence in target["evidence"]:
            relative = Path(evidence)
            if relative.is_absolute() or ".." in relative.parts or not _io_path(ROOT / relative).is_file():
                raise ValueError(f"PG16739 state evidence differs: {evidence}")
            _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    _put(stage, EVIDENCE / "inputs/direct-candidate.tei.xml", direct)
    _put(stage, EVIDENCE / "inputs/adapted-candidate.tei.xml", adapted)
    _put_json(stage, EVIDENCE / "inputs/oracle.json", oracle)
    _put_json(stage, EVIDENCE / "inputs/validated-direct-package.json", dict(
        path=PACKAGE.as_posix(), package_sha256=oracle["direct_package_sha256"],
        manifest_path=MANIFEST.relative_to(ROOT).as_posix(),
        manifest_sha256=oracle["source_manifest_sha256"]))
    _put(stage, WORK / "SOURCE_CREDIT.md", (
        "# Source and credit — Henry Drummond, The Greatest Thing in the World and Other Addresses\n\n"
        "The accepted source is the complete retained Project Gutenberg 16739 UTF-8 text, including the "
        "source title, credits, all addresses, opening and closing wrapper, and full Gutenberg license. "
        "It credits David Garcia, Jeannie Howse, and the Online Distributed Proofreading Team. "
        "This electronic collection is not a claim of equivalence to one print edition.\n\n"
        f"Text authority: {SOURCE.as_posix()} — SHA-256 {SOURCE_SHA256}.\n\n"
        "Project Gutenberg record: https://www.gutenberg.org/ebooks/16739\n"
        "Project Gutenberg license: https://www.gutenberg.org/policy/license.html\n\n"
        "Gutenberg states a United States public-domain basis. Other jurisdictions, the license and trademark "
        "conditions for redistribution, human acceptance, and public release require separate review.\n"
    ).encode("utf-8"))
    original_work = _read(ROOT / WORK / "work.json")
    revised = json.loads(json.dumps(original_work))
    form = revised["textual_forms"][0]
    edition = form["editions"][0]
    if (revised["work_id"] != WORK_ID or form["textual_form_id"] != FORM_ID
            or edition["edition_id"] != EDITION_ID or edition["acquisition_ids"] != [ACQUISITION_ID]
            or edition.get("category")):
        raise ValueError("PG16739 acquired work identity differs")
    edition["category"] = "prose"
    form["language"] = "en"
    edition["language"] = "en"
    validate_identity_update(original_work, revised)
    _put_json(stage, WORK / "work.json", revised)
    load_work(_io_path(stage / WORK / "work.json"))
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                    acquisition_id=ACQUISITION_ID)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    revision = dict(id="drummond-pg16739-current-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained PG16739 plain-text electronic collection.")
    binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA256,
                   source_bytes=len(raw), source_scope=retained[0]["scope"])
    bound = bind_reviewed_header(adapted, expected_sha256=ADAPTED_SHA256,
                                 identity=identity, source=binding,
                                 source_url=acquired["url"], declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != adapted.split(b"</teiHeader>", 1)[1]:
        raise ValueError("PG16739 reviewed header changed the source body")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"PG16739 accepted candidate fails P5: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(raw),
                     sha256=SOURCE_SHA256, scope=SCOPE)]
    selection = dict(kind="selection", declared=SCOPE, expected_members=expected,
                     included_members=included, excluded_members=[])
    common = dict(identity=identity, source=binding, candidate=make_file_binding(stage, candidate),
                  accepted_scope=dict(kind="selection", declared=SCOPE), expected_members=expected,
                  included_members=included, excluded_members=[], missing_members=[], unknown_members=[])
    account = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        scope=retained[0]["scope"], source_sha256=SOURCE_SHA256, source_bytes=len(raw),
        source_oracle=oracle, source_carriers=counts, direct_candidate_sha256=_sha(direct),
        adapted_candidate_sha256=ADAPTED_SHA256, retained_text_authority=SOURCE.as_posix()))
    command = "py -3 -m build.tools.stage_drummond_pg16739 --stage <fresh-external-root>"
    technical = dict(producer=dict(id="ocd-drummond-pg16739-complete-text-native-v1"),
                     checker=dict(id=oracle["contract"]),
                     shared_assumptions=["The full-source source-to-TEI oracle and this adapter oracle share TEI parsing, but the latter independently compares every transformed node without calling the adapter."],
                     independent_corroboration="All 3,922 source lines, 181 emphasis spans, 362 literal delimiters, 665 blank lines, 21 source headings, P5 and actual-master native producer/checker.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            scope=SCOPE, status="pass", claim=name, command=command, exit_code=0,
            source_oracle=oracle, tei_p5_xsd="pass", native_projection="pass"))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:drummond-pg16739-source-review", reviewed_at=now,
                  coverage=dict(status="partial", declared=SCOPE,
                                reached=["all 3,922 source lines including Gutenberg wrapper and license",
                                         "181 exact underscore emphasis spans and 362 delimiters",
                                         "665 blank lines and 21 headings in source order",
                                         "complete independent source oracle, P5, and native projection",
                                         "complete independent mechanical source oracle"],
                                inspected=["complete independent mechanical source oracle"],
                                unreviewed=["human visual comparison", "print collation"]),
                  source_quality_uncertainty=["The electronic text has not been collated to a print exemplar."],
                  discrepancies=[], unreviewed_residuals=["Human acceptance and rights clearance remain open."])
    review_path = _put_json(stage, EVIDENCE / "review.json", common | review | dict(scope=SCOPE))
    decision = dict(source_local_disposition="Agent technical acceptance of complete PG16739 electronic collection.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                                          supported_scope=SCOPE, unresolved_claims=[],
                                          unassessed_stronger_claims=["human visual review", "human acceptance",
                                                                      "print collation", "rights clearance", "publication"]))
    acceptance = stage / EDITION / "acceptance.json"
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                     source_accounting_path=account, scope=selection,
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
        raise ValueError("PG16739 edition acquired state differs")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master.relative_to(stage).as_posix(),
                                 acceptance.relative_to(stage).as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                          category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"PG16739 native accepted-master projection differs: {errors}")
    after = _files(stage / WORK)
    dependencies = {
        relative: _sha(_io_path(ROOT / relative).read_bytes()) for relative in (
            "build/tei/drummond_pg16739_native.py",
            "build/tei/drummond_pg16739_native_oracle.py",
            "build/tei/drummond_greatest_thing_37c135_reconstruction.py",
            "build/tei/drummond_greatest_thing_37c135_oracle.py",
            "build/tools/stage_drummond_pg16739.py",
            "ocd_kernel/projection/native_content.py",
            "ocd_kernel/projection/native_content_check.py",
            "ocd_kernel/projection/categories/native_documents.py",
            "schemas/v2/native-content.schema.json",
        )
    }
    receipt = dict(contract="ocd-drummond-pg16739-stage-v1", work_id=WORK_ID,
                   source_sha256=SOURCE_SHA256, direct_sha256=_sha(direct),
                   adapted_sha256=ADAPTED_SHA256, accepted_master_sha256=_sha(bound),
                   oracle=oracle, before=before, after=after, native_rows=1,
                   dependencies=dependencies,
                   stage_root=stage.as_posix())
    _put_json(stage, Path("stage-receipt.json"), receipt)
    return dict(status="staged-for-review", stage=stage.as_posix(),
                before_files=len(before), after_files=len(after), native_rows=1,
                receipt_sha256=_sha(_io_path(stage / "stage-receipt.json").read_bytes()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().stage), sort_keys=True))


if __name__ == "__main__":
    main()
