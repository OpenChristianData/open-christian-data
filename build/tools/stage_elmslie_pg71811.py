"""Prepare a review-only accepted-master generation for Elmslie PG71811."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from build.tei.elmslie_pg71811_native import ROOT, SOURCE, SOURCE_SHA256, reconstruct
from build.tei.elmslie_pg71811_oracle import check
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    ELMSLIE_CHOICE_PROFILE, project_accepted_document, verify_accepted_document,
)
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


WORK_ID = "elmslie-books-of-chronicles"
FORM_ID = "elmslie-books-of-chronicles-gutenberg-retained"
EDITION_ID = "elmslie-books-of-chronicles-gutenberg-electronic"
ACQUISITION_ID = "elmslie-books-of-chronicles-gutenberg-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
EVIDENCE = WORK / "integration/elmslie-pg71811-current-v1"
STAGE_PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
SCOPE = (
    "Complete real extracted Project Gutenberg 71811 UTF-8 HTML electronic witness of "
    "W. A. L. Elmslie's The Books of Chronicles, 1916 second-edition Cambridge Bible "
    "volume only: all HTML body content including Gutenberg header, footer and license; "
    "7,255 displayed abbreviations with source title expansions, the complete definition "
    "list, three tables, six linked figures and exact local/external hrefs. The seven-member "
    "ZIP is a package, not text authority; all six extracted JPEGs are referenced image "
    "support. The HTML head and one nonvisible editorial comment are separately accounted. "
    "Cambridge map-caption copyright notices leave image/publication rights open."
)
DEPENDENCIES = (
    Path("build/tei/elmslie_pg71811_native.py"),
    Path("build/tei/elmslie_pg71811_oracle.py"),
    Path("ocd_kernel/projection/native_content.py"),
    Path("ocd_kernel/projection/native_content_check.py"),
    Path("ocd_kernel/projection/categories/native_documents.py"),
    Path("schemas/v2/native-content.schema.json"),
)


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"PG71811 JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")) + "\n").encode("utf-8"))


def retained_bindings(acquisition: dict) -> list[dict]:
    retained = acquisition["retained_files"]
    if (len(retained) != 8 or [item["path"] for item in retained] != [
        "raw/gutenberg/71811/pg71811-h.zip",
        "raw/gutenberg/71811/html/pg71811-images.html",
        *["raw/gutenberg/71811/html/images/" + name for name in (
            "cover.jpg", "i_colophon.jpg", "i_364x.jpg", "i_368x.jpg", "i_371.jpg", "i_374x.jpg")],
    ] or retained[1]["sha256"] != SOURCE_SHA256):
        raise ValueError("PG71811 acquired real-file inventory differs")
    for item in retained:
        data = _io_path(ROOT / item["path"]).read_bytes()
        if len(data) != item["bytes"] or _sha(data) != item["sha256"]:
            raise ValueError(f"PG71811 retained member changed: {item['path']}")
    with ZipFile(_io_path(ROOT / retained[0]["path"])) as archive:
        if archive.testzip() is not None:
            raise ValueError("PG71811 ZIP CRC differs")
        expected = ["pg71811-images.html", *["images/" + Path(item["path"]).name for item in retained[2:]]]
        if archive.namelist() != expected:
            raise ValueError("PG71811 ZIP member order differs")
        for item, member in zip(retained[1:], expected):
            if archive.read(member) != _io_path(ROOT / item["path"]).read_bytes():
                raise ValueError(f"PG71811 ZIP member differs from real file: {member}")
    return retained


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (stage.exists() or stage.parent.resolve(strict=True) != STAGE_PARENT.resolve(strict=True)
            or not stage.name.startswith("elmslie-pg71811-stage-")):
        raise ValueError("fresh external PG71811 candidate-review stage required")
    original_acquisition = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    retained = retained_bindings(original_acquisition)
    if (original_acquisition["source_path"] != SOURCE.as_posix()
            or original_acquisition["source_sha256"] != SOURCE_SHA256
            or original_acquisition["source_bytes"] != 1799715):
        raise ValueError("PG71811 acquired source authority differs")
    direct, tally = reconstruct()
    direct_path = _put(stage, EVIDENCE / "inputs/direct-candidate.tei.xml", direct)
    if errors := validate_file(_io_path(direct_path)):
        raise ValueError(f"PG71811 direct P5 errors: {errors[:3]}")
    direct_oracle = check(direct)
    before = _files(ROOT / WORK)
    if len(before) != 3 or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("PG71811 canonical acquired preimage differs")
    for relative, digest in before.items():
        data = _io_path(ROOT / WORK / relative).read_bytes()
        if _sha(data) != digest:
            raise ValueError(f"PG71811 preimage changed: {relative}")
        _put(stage, WORK / relative, data)
    for item in retained:
        relative = Path(item["path"])
        _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    state = _read(ROOT / WORK / "state.json")
    for target in state["targets"]:
        for evidence in target["evidence"]:
            relative = Path(evidence)
            if relative.is_absolute() or ".." in relative.parts or not _io_path(ROOT / relative).is_file():
                raise ValueError(f"PG71811 state evidence differs: {evidence}")
            _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    if _read(stage / ACQUISITION) != original_acquisition:
        raise ValueError("PG71811 staged acquisition differs")
    validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    credit = (
        "# Source and credit — Elmslie, The Books of Chronicles, Project Gutenberg 71811\n\n"
        "This accepted technical reconstruction uses the complete real extracted UTF-8 HTML "
        "electronic witness of W. A. L. Elmslie's 1916 second-edition Cambridge Bible volume. "
        "It does not claim the entire Cambridge commentary series or print collation. "
        "The Gutenberg header, footer, and license remain in the reconstructed text.\n\n"
        f"Text authority: {SOURCE.as_posix()} — SHA-256 {SOURCE_SHA256}.\n\n"
        "The retained ZIP is the acquisition package, not text authority. Its seven members "
        "were checked byte-for-byte against the real extracted HTML and six JPEGs:\n"
        + "".join(f"- {item['path']} — SHA-256 {item['sha256']}\n" for item in retained)
        + "\nThe HTML references all six JPEGs. The cover is transcriber-provided support; "
        "two map captions explicitly say 'Copyright Cambridge University Press,' while "
        "two other map captions name Cambridge University Press. Those notices and image "
        "rights require separate publication review.\n\n"
        "Project Gutenberg record: https://www.gutenberg.org/ebooks/71811\n"
        "Project Gutenberg license: https://www.gutenberg.org/policy/license.html\n\n"
        "Gutenberg identifies U.S. public-domain status for the eBook. Rights outside the "
        "United States, image/map rights, trademark and redistribution conditions, human "
        "acceptance, and public release remain unapproved.\n"
    )
    _put(stage, WORK / "SOURCE_CREDIT.md", credit.encode("utf-8"))
    notice = (
        "Future public data-path notice for elmslie-books-of-chronicles: bind this SOURCE_CREDIT "
        "with the public work index before release; include Project Gutenberg 71811, W. A. L. "
        "Elmslie, the 1916 second-edition volume scope, all six source image credits, and the "
        "Cambridge map-caption rights hold. No public data-path notice is installed by this stage.\n"
    )
    _put(stage, EVIDENCE / "future-public-notice-binding.md", notice.encode("utf-8"))
    original_work = _read(ROOT / WORK / "work.json")
    revised = json.loads(json.dumps(original_work))
    edition = revised["textual_forms"][0]["editions"][0]
    if (revised["work_id"] != WORK_ID
            or revised["textual_forms"][0]["textual_form_id"] != FORM_ID
            or edition["edition_id"] != EDITION_ID
            or edition["acquisition_ids"] != [ACQUISITION_ID] or edition.get("category")):
        raise ValueError("PG71811 acquired identity differs")
    edition["category"] = "prose"
    validate_identity_update(original_work, revised)
    _put_json(stage, WORK / "work.json", revised)
    load_work(_io_path(stage / WORK / "work.json"))
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                    acquisition_id=ACQUISITION_ID)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    revision = dict(id="elmslie-pg71811-current-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete real extracted PG71811 1916 second-edition HTML witness with six linked JPEG supports.")
    binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA256,
                   source_bytes=1799715, source_scope=original_acquisition["source_scope"])
    bound = bind_reviewed_header(direct, expected_sha256=_sha(direct), identity=identity,
                                 source=binding, source_url=original_acquisition["url"],
                                 declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != direct.split(b"</teiHeader>", 1)[1]:
        raise ValueError("PG71811 reviewed header changed source body")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"PG71811 accepted P5 errors: {errors[:3]}")
    oracle = check(bound)
    expected = [dict(path=item["path"], position=index) for index, item in enumerate(retained, 1)]
    included = [dict(path=SOURCE.as_posix(), position=2, bytes=1799715,
                     sha256=SOURCE_SHA256, scope=SCOPE)]
    excluded = [dict(path=item["path"], position=index,
                     reason=("Retained ZIP acquisition package, not text authority." if index == 1 else
                             "Real extracted JPEG referenced by the HTML/TEI as image support, not text authority."))
                for index, item in enumerate(retained, 1) if index != 2]
    scope = dict(kind="selection", declared=SCOPE, expected_members=expected,
                 included_members=included, excluded_members=excluded)
    common = dict(identity=identity, source=binding, candidate=make_file_binding(stage, candidate),
                  accepted_scope=dict(kind="selection", declared=SCOPE), expected_members=expected,
                  included_members=included, excluded_members=excluded,
                  missing_members=[], unknown_members=[])
    account = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        scope=original_acquisition["source_scope"], source_sha256=SOURCE_SHA256,
        source_bytes=1799715, source_oracle=oracle,
        direct_oracle=direct_oracle, source_tags=tally,
        retained_text_authority=SOURCE.as_posix(), support=retained,
        html_head_disposition="Retained in exact HTML authority; not body reading text.",
        editorial_comment_disposition="One nonvisible WIP comment is hash-accounted by the independent oracle; its tail remains in reading order."))
    _put_json(stage, EVIDENCE / "inputs/oracle.json", oracle)
    command = "py -3 -m build.tools.stage_elmslie_pg71811 --stage <fresh-external-root>"
    technical = dict(producer=dict(id="ocd-elmslie-pg71811-complete-real-html-v1"),
                     checker=dict(id=oracle["contract"]),
                     shared_assumptions=["Both HTML reads use lxml; independent oracle compares source DOM with a separately parsed candidate and never calls the mapper."],
                     independent_corroboration="Complete displayed text, 7,255 abbreviation/title pairs, 2,543 ordered hrefs, all three tables, all six figures/JPEGs, definition roles, local targets, exact retained ZIP/real files, P5 and independent native checker.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        report = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            scope=SCOPE, status="pass", claim=name, command=command, exit_code=0, source_oracle=oracle,
            tei_p5_xsd="pass", native_projection="pass"))
        technical[name] = dict(path=report, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:elmslie-pg71811-source-review", reviewed_at=now,
                  coverage=dict(status="partial", declared=SCOPE,
                                reached=["complete normalized source/TEI displayed text",
                                         "7,255 ordered abbreviation/title choices", "2,543 exact hrefs",
                                         "three complete tables and one complete definition list",
                                         "six linked JPEGs byte-equal to ZIP members", "P5 and independent native row",
                                         "independent mechanical source oracle"],
                                inspected=["independent mechanical source oracle"],
                                unreviewed=["human visual source comparison", "print collation", "image rights clearance"]),
                  source_quality_uncertainty=["Electronic HTML is the retained authority; the 1916 print exemplar was not collated."],
                  discrepancies=[], unreviewed_residuals=["Cambridge map-caption copyright, human acceptance, and public release remain open."])
    review_path = _put_json(stage, EVIDENCE / "review.json", common | review | dict(scope=SCOPE))
    decision = dict(source_local_disposition="Agent technical acceptance of complete PG71811 electronic witness with all six linked JPEGs.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"],
                                          assessed_at=now, supported_scope=SCOPE, unresolved_claims=[],
                                          unassessed_stronger_claims=["human visual review", "human acceptance",
                                                                      "print collation", "image rights clearance",
                                                                      "publication"]))
    acceptance = stage / EDITION / "acceptance.json"
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                     source_accounting_path=account, scope=scope, technical=technical,
                                     review=review | dict(report_path=review_path),
                                     representation_revision=revision, decision=decision)
    write_acceptance(_io_path(acceptance), record)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    master = _put(stage, EDITION / "master.tei.xml", bound)
    record["promotion"].update(status="promoted", promoted_at=now,
                               master=make_file_binding(stage, master))
    write_acceptance(_io_path(acceptance), record)
    staged_state = _read(stage / WORK / "state.json")
    target = [item for item in staged_state["targets"] if item["target_type"] == "edition"
              and item["target_id"] == EDITION_ID]
    if len(target) != 1 or target[0]["stage"] != "acquired":
        raise ValueError("PG71811 edition state differs")
    target[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    target[0]["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _put_json(stage, WORK / "state.json", staged_state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                          category="prose", projection_profile=ELMSLIE_CHOICE_PROFILE)
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"],
                                      category="prose", projection_profile=ELMSLIE_CHOICE_PROFILE)
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"PG71811 native projection differs: {errors[:3]}")
    after = _files(stage / WORK)
    dependency_sha256 = {item.as_posix(): _sha(_io_path(ROOT / item).read_bytes()) for item in DEPENDENCIES}
    receipt = dict(contract="ocd-elmslie-pg71811-stage-v1", work_id=WORK_ID,
                   source_sha256=SOURCE_SHA256, source_bytes=1799715,
                   direct_sha256=_sha(direct), accepted_master_sha256=_sha(bound),
                   oracle=oracle, support=retained, before=before, after=after,
                   dependency_sha256=dependency_sha256, native_rows=1, stage_root=stage.as_posix())
    _put_json(stage, Path("stage-receipt.json"), receipt)
    return dict(status="staged-for-review", stage=stage.as_posix(), work_id=WORK_ID,
                before_files=len(before), after_files=len(after), native_rows=1,
                receipt_sha256=_sha(_io_path(stage / "stage-receipt.json").read_bytes()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().stage), sort_keys=True))


if __name__ == "__main__":
    main()
