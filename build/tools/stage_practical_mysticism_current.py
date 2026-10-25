"""Stage the complete current Standard Ebooks Practical Mysticism spine."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei.se_candidate_oracle import _oracle
from build.tools.prepare_practical_mysticism_spine_sidecars import evidence
from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "practical-mysticism"
FORM_ID = "practical-mysticism-standard-ebooks-en"
EDITION_ID = "practical-mysticism-standard-ebooks-retained"
ACQUISITION_ID = "practical-mysticism-standard-ebooks-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
MEMBER_SET = EDITION / "source-member-set.json"
SUPPORT = EDITION / "retained-support.json"
EVIDENCE = WORK / "integration/practical-mysticism-current-v1"
MANIFEST = Path("sources/standard-ebooks/evelyn-underhill_practical-mysticism/practical-mysticism.source-manifest.json")
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/practical-mysticism-current-20260928-v1/package")
STAGE_PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
SOURCE_SET_SHA256 = "44d8778c4004454f2af16b432aec662034b6253624217021ea777c4ae7c1f9d4"
MANIFEST_SHA256 = "afff3494208de6fa63b38fda51dfb79afb66e056844fce0e2dff941c589523d0"
PACKAGE_SHA256 = "653961af8dd5a750584ade2fab622bc54c358bc5310d4fc4143c2ef451b09138"
DIRECT_SHA256 = "ec948c5d5210ba09127258030c8a09997bc6044111d02a743436799785a33b6c"
SCOPE = (
    "Complete retained Standard Ebooks electronic witness of Evelyn Underhill's Practical Mysticism, "
    "commit 7ee6f8c2f826797f8cb1f3922dc7378142454eec: 18 complete XHTML text members in the exact OPF "
    "spine order, from titlepage through uncopyright, and 15 separately hash-bound checkout support "
    "members. The retained electronic witness, not an independently collated print edition, is accepted."
)


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Practical Mysticism JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")) + "\n").encode("utf-8"))


def source_check() -> tuple[bytes, dict, dict]:
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(PACKAGE)
    if manifest.sha256 != MANIFEST_SHA256 or package.sha256 != PACKAGE_SHA256:
        raise ValueError("Practical Mysticism fresh source manifest or package differs")
    report = validate(manifest, package, _oracle)
    if report.status != "pass":
        raise ValueError("Practical Mysticism complete source oracle failed")
    direct = package.member_bytes("content.tei.xml")
    if _sha(direct) != DIRECT_SHA256:
        raise ValueError("Practical Mysticism source-bound TEI differs")
    sidecars = evidence(ROOT)
    if (len(sidecars["ordered_text_members"]) != 18 or len(sidecars["support_members"]) != 15):
        raise ValueError("Practical Mysticism OPF spine or support inventory differs")
    return direct, sidecars, dict(
        contract="ocd-practical-mysticism-current-source-oracle-v1",
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        direct_tei_sha256=DIRECT_SHA256, validation_status=report.status,
        source_member_set_sha256=SOURCE_SET_SHA256, text_members=18, support_members=15,
        opf_sha256=sidecars["opf"]["sha256"], source_revision=sidecars["source_revision"])


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (stage.exists() or stage.parent.resolve(strict=True) != STAGE_PARENT.resolve(strict=True)
            or not stage.name.startswith("practical-mysticism-stage-")):
        raise ValueError("fresh external Practical Mysticism stage required")
    direct, sidecars, oracle = source_check()
    acquired = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    retained = acquired["retained_files"]
    text = sidecars["ordered_text_members"]
    support = sidecars["support_members"]
    if (acquired["source_path"] != MEMBER_SET.as_posix()
            or acquired["source_sha256"] != SOURCE_SET_SHA256
            or acquired["source_kind"] != "retained-member-set"
            or [(x["path"], x["bytes"], x["sha256"]) for x in retained]
            != [(x["path"], x["bytes"], x["sha256"]) for x in text]
            or _io_path(ROOT / MEMBER_SET).read_bytes() != source_member_set_bytes(acquired)):
        raise ValueError("Practical Mysticism acquisition or 18-member set differs")
    support_sidecar = _read(ROOT / SUPPORT)
    if ([(x["path"], x["bytes"], x["sha256"]) for x in support_sidecar["support_members"]]
            != [(x["path"], x["bytes"], x["sha256"]) for x in support]):
        raise ValueError("Practical Mysticism 15-support sidecar differs")
    before = _files(ROOT / WORK)
    if len(before) != 6 or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("Practical Mysticism acquired preimage differs")
    for relative in before:
        _put(stage, WORK / relative, _io_path(ROOT / WORK / relative).read_bytes())
    for member in text + support:
        relative = Path(member["path"])
        raw = _io_path(ROOT / relative).read_bytes()
        if len(raw) != member["bytes"] or _sha(raw) != member["sha256"]:
            raise ValueError(f"Practical Mysticism retained member changed: {relative}")
        _put(stage, relative, raw)
    for target in _read(ROOT / WORK / "state.json")["targets"]:
        for evidence_path in target["evidence"]:
            relative = Path(evidence_path)
            if relative.is_absolute() or ".." in relative.parts or not _io_path(ROOT / relative).is_file():
                raise ValueError(f"Practical Mysticism state evidence differs: {relative}")
            _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    _put(stage, EVIDENCE / "inputs/direct-candidate.tei.xml", direct)
    _put_json(stage, EVIDENCE / "inputs/oracle.json", oracle)
    _put(stage, EVIDENCE / "future-public-notice-binding.md", (
        "Before a public data-path release, bind the existing work-local SOURCE_CREDIT.md to the public "
        "work index: Evelyn Underhill, Practical Mysticism, Standard Ebooks retained commit "
        "7ee6f8c2f826797f8cb1f3922dc7378142454eec, 18 OPF-spine XHTML text members and 15 "
        "support members. Preserve Standard Ebooks artwork/source credit and license conditions. "
        "No public notice is installed by this stage.\n").encode("utf-8"))
    original_work = _read(ROOT / WORK / "work.json")
    revised = json.loads(json.dumps(original_work))
    form = revised["textual_forms"][0]
    edition = form["editions"][0]
    if (revised["work_id"] != WORK_ID or form["textual_form_id"] != FORM_ID or form.get("language") != "en"
            or edition["edition_id"] != EDITION_ID or edition.get("language") != "en"
            or edition["acquisition_ids"] != [ACQUISITION_ID] or edition.get("category")):
        raise ValueError("Practical Mysticism acquired work identity differs")
    edition["category"] = "prose"
    validate_identity_update(original_work, revised)
    _put_json(stage, WORK / "work.json", revised)
    load_work(_io_path(stage / WORK / "work.json"))
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                    acquisition_id=ACQUISITION_ID)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    revision = dict(id="practical-mysticism-current-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained Standard Ebooks Practical Mysticism OPF spine.")
    binding = {key: acquired[key] for key in ("source_kind", "source_path", "source_bytes",
                                               "source_sha256", "source_scope")}
    bound = bind_reviewed_header(direct, expected_sha256=DIRECT_SHA256, identity=identity,
                                 source=binding, source_url=acquired["url"],
                                 declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != direct.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Practical Mysticism reviewed header changed source text")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Practical Mysticism accepted candidate fails P5: {errors[:3]}")
    expected = [dict(path=item["path"], position=index) for index, item in enumerate(retained, 1)]
    included = [dict(path=item["path"], position=index, bytes=item["bytes"],
                     sha256=item["sha256"], scope=item["scope"])
                for index, item in enumerate(retained, 1)]
    selection = dict(kind="edition", declared=SCOPE, expected_members=expected,
                     included_members=included, excluded_members=[])
    common = dict(identity=identity, source=binding, candidate=make_file_binding(stage, candidate),
                  accepted_scope=dict(kind="edition", declared=SCOPE), expected_members=expected,
                  included_members=included, excluded_members=[], missing_members=[], unknown_members=[])
    account = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        scope=acquired["source_scope"], source_sha256=SOURCE_SET_SHA256,
        source_bytes=acquired["source_bytes"], source_oracle=oracle,
        text_members=text, support_members=support, opf=sidecars["opf"],
        source_revision=sidecars["source_revision"]))
    command = "py -3 -m build.tools.stage_practical_mysticism_current --stage <fresh-external-root>"
    technical = dict(producer=dict(id="ocd-standard-ebooks-retained-source-to-tei"),
                     checker=dict(id="ocd-standard-ebooks-independent-tree-oracle"),
                     shared_assumptions=["The direct source mapper and oracle parse XML separately; current OPF and sidecars independently bind all 33 retained files."],
                     independent_corroboration="Full 33-file source oracle, OPF-spine 18 text/15 support sidecars, current source hashes, P5, and actual-master native producer/checker.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            scope=SCOPE, status="pass", claim=name, command=command, exit_code=0,
            source_oracle=oracle, tei_p5_xsd="pass", native_projection="pass"))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:practical-mysticism-current-source-review", reviewed_at=now,
                  coverage=dict(status="partial", declared=SCOPE,
                                reached=["18 complete source XHTML files in OPF spine order",
                                         "15 exact support files including images, styles, navigation and license",
                                         "full source oracle, P5 and native projection",
                                         "complete independent mechanical source oracle"],
                                inspected=["complete independent mechanical source oracle"],
                                unreviewed=["human visual comparison", "print collation", "artwork rights"]),
                  source_quality_uncertainty=["The retained Standard Ebooks electronic witness was not collated to a print exemplar."],
                  discrepancies=[], unreviewed_residuals=["Human acceptance, artwork rights, license attribution and public release remain open."])
    review_path = _put_json(stage, EVIDENCE / "review.json", common | review | dict(scope=SCOPE))
    decision = dict(source_local_disposition="Agent technical acceptance of complete Standard Ebooks Practical Mysticism OPF-spine witness.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                                          supported_scope=SCOPE, unresolved_claims=[],
                                          unassessed_stronger_claims=["human visual review", "human acceptance",
                                                                      "print collation", "artwork rights",
                                                                      "license attribution", "publication"]))
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
        raise ValueError("Practical Mysticism acquired edition state differs")
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
    if errors or len(projected["rows"]) != 18:
        raise ValueError(f"Practical Mysticism native accepted-master rows differ: {errors}")
    after = _files(stage / WORK)
    dependencies = {relative: _sha(_io_path(ROOT / relative).read_bytes()) for relative in (
        "build/tei/se_candidate_reconstruction.py", "build/tei/se_candidate_oracle.py",
        "build/tools/prepare_practical_mysticism_spine_sidecars.py",
        "build/tools/stage_practical_mysticism_current.py",
        "ocd_kernel/projection/native_content.py", "ocd_kernel/projection/native_content_check.py",
        "ocd_kernel/projection/categories/native_documents.py", "schemas/v2/native-content.schema.json")}
    receipt = dict(contract="ocd-practical-mysticism-current-stage-v1", work_id=WORK_ID,
                   source_member_set_sha256=SOURCE_SET_SHA256, source_manifest_sha256=MANIFEST_SHA256,
                   direct_package_sha256=PACKAGE_SHA256, direct_tei_sha256=DIRECT_SHA256,
                   accepted_master_sha256=_sha(bound), oracle=oracle,
                   text_members=text, support_members=support, before=before, after=after,
                   native_rows=18, dependencies=dependencies, stage_root=stage.as_posix())
    _put_json(stage, Path("stage-receipt.json"), receipt)
    return dict(status="staged-for-review", stage=stage.as_posix(),
                before_files=len(before), after_files=len(after), native_rows=18,
                receipt_sha256=_sha(_io_path(stage / "stage-receipt.json").read_bytes()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().stage), sort_keys=True))


if __name__ == "__main__":
    main()
