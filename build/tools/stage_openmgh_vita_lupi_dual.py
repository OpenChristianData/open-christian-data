"""Stage both Vita Lupi electronic editions in one complete external work generation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei import openmgh_vita_lupi_dual as source
from build.tei.openmgh_vita_lupi_dual_oracle import check
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = source.ROOT
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-vita-lupi-dual-direct-20260927-v1")
DIRECT_SHA = "8fa41eadcdfe789125846b92ae6cf51c4d045e4b9299e54613be9ade7da3bc6a"
REPRO = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-vita-lupi-dual-direct-20260927-v2")
EVIDENCE = "openmgh-vita-lupi-dual-electronic-v1"
CONTRACT = "ocd-openmgh-vita-lupi-dual-stage-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, _json(value))


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or ROOT.resolve() in stage.resolve().parents):
        raise ValueError("fresh external Vita Lupi stage required")
    if _sha(DIRECT / "receipt.json") != DIRECT_SHA:
        raise ValueError("Vita Lupi direct receipt changed")
    direct = _read(DIRECT / "receipt.json")
    if (direct.get("contract") != "ocd-openmgh-vita-lupi-dual-direct-v1"
            or direct.get("selected_editions") != 2
            or {item["code"] for item in direct["sources"]} != set(source.WITNESSES)):
        raise ValueError("Vita Lupi direct edition scope changed")
    work = Path("library/works") / source.WORK_ID
    before = _files(ROOT / work)
    original = _read(ROOT / work / "work.json")
    if (len(before) != 4 or original.get("work_id") != source.WORK_ID
            or len(original.get("textual_forms", [])) != 1
            or len(original["textual_forms"][0].get("editions", [])) != 2):
        raise ValueError("Vita Lupi canonical preimage or edition set changed")
    for rel, digest in before.items():
        content = _io_path(ROOT / work / rel).read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError(f"Vita Lupi preimage changed while copying: {rel}")
        _put(stage, work / rel, content)
    revised = _read(stage / work / "work.json")
    old_form = original["textual_forms"][0]
    new_form = revised["textual_forms"][0]
    for edition in new_form["editions"]:
        if edition.get("language") or edition.get("category"):
            raise ValueError("Vita Lupi native fields already assigned")
        edition.update(language="la", category="prose")
    validate_identity_update(original, revised)
    _put_json(stage, work / "work.json", revised)
    load_work(_io_path(stage / work / "work.json"))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    state = _read(stage / work / "state.json")
    results = []
    credit_lines = []
    for item in direct["sources"]:
        code = item["code"]
        spec = source.WITNESSES[code]
        old_edition = next(e for e in old_form["editions"] if e["edition_id"].endswith(f"{code}-electronic"))
        edition = work / "forms" / old_form["textual_form_id"] / "editions" / old_edition["edition_id"]
        acquisition_path = edition / "acquisitions" / (old_edition["acquisition_ids"][0] + ".json")
        acquisition = _read(ROOT / acquisition_path)
        source_path, package_path, receipt_path = source.paths(code)
        for rel, digest in ((source_path, spec["source_sha256"]), (package_path, spec["package_sha256"]),
                            (receipt_path, spec["receipt_sha256"])):
            if _sha(ROOT / rel) != digest:
                raise ValueError(f"{code} source dependency changed: {rel}")
            _put(stage, rel, _io_path(ROOT / rel).read_bytes())
        raw = _io_path(ROOT / source_path).read_bytes()
        if (acquisition.get("source_path") != source_path.as_posix()
                or acquisition.get("source_sha256") != spec["source_sha256"]
                or {entry["path"]: entry["sha256"] for entry in acquisition.get("retained_files", [])}
                != {source_path.as_posix(): spec["source_sha256"], package_path.as_posix(): spec["package_sha256"]}):
            raise ValueError(f"{code} acquisition does not bind extracted XML and package")
        candidate_bytes = _io_path(Path(item["candidate_path"])).read_bytes()
        reproduced, producer = source.convert(code)
        oracle = check(code, candidate_bytes)
        if (sha256(candidate_bytes).hexdigest() != item["candidate_sha256"]
                or _sha(REPRO / code / "candidate.tei.xml") != item["candidate_sha256"]
                or reproduced != candidate_bytes or producer != item["producer"] or oracle != item["oracle"]):
            raise ValueError(f"{code} source candidate, reproduction, or oracle changed")
        identity = dict(work_id=source.WORK_ID, textual_form_id=old_form["textual_form_id"],
                        edition_id=old_edition["edition_id"], acquisition_id=old_edition["acquisition_ids"][0])
        scope = (f"Complete direct Vita Lupi work division {spec['work_div_index']} (zero-based) of "
                 f"{spec['volume_work_count']} in extracted {source_path.as_posix()}, from source XML ID "
                 f"{spec['first_id']} through {spec['last_id']}, including every selected node, attribute, "
                 "line, page, word fragment, and text tail. The volume shell and sibling work divisions "
                 "remain retained outside this edition. The other acquired Vita Lupi edition is separately staged.")
        evidence = work / "integration" / EVIDENCE / code
        _put(stage, evidence / "inputs/candidate.tei.xml", candidate_bytes)
        revision = dict(id=f"{source.WORK_ID}-{code}-exact-v1", date=datetime.now(timezone.utc).date().isoformat(),
                        note="Accept the complete, separately identified Vita Lupi electronic edition.")
        binding = dict(source_path=source_path.as_posix(), source_sha256=spec["source_sha256"],
                       source_bytes=len(raw), source_scope=scope)
        derived = bind_reviewed_header(candidate_bytes, expected_sha256=item["candidate_sha256"],
                                       identity=identity, source=binding, source_url=acquisition["url"],
                                       declared_scope=scope, revision=revision)
        if derived.split(b"</teiHeader>", 1)[1] != candidate_bytes.split(b"</teiHeader>", 1)[1]:
            raise ValueError(f"{code} reviewed header changed source body")
        candidate = _put(stage, evidence / "candidate.tei.xml", derived)
        if errors := validate_file(_io_path(candidate)):
            raise ValueError(f"{code} staged candidate P5 XSD failed: {errors[:3]}")
        expected = [dict(path=package_path.as_posix(), position=1), dict(path=source_path.as_posix(), position=2)]
        included = [dict(path=source_path.as_posix(), position=2, bytes=len(raw),
                         sha256=spec["source_sha256"], scope=scope)]
        excluded = [dict(path=package_path.as_posix(), position=1,
                         reason="ZIP is retained acquisition packaging; extracted XML is text authority.")]
        accepted_scope = dict(kind="selection", declared=scope, expected_members=expected,
                              included_members=included, excluded_members=excluded)
        common = dict(identity=identity, source={k: acquisition[k] for k in ("source_path", "source_sha256", "source_bytes", "source_scope")},
                      candidate=make_file_binding(stage, candidate), scope=scope,
                      accepted_scope=dict(kind="selection", declared=scope), expected_members=expected,
                      included_members=included, excluded_members=excluded, missing_members=[], unknown_members=[])
        account = _put_json(stage, evidence / "source-accounting.json", common | dict(
            scope=acquisition["source_scope"], source_sha256=spec["source_sha256"],
            source_bytes=len(raw),
            source_oracle=oracle, direct_receipt_sha256=DIRECT_SHA,
            original_candidate_sha256=item["candidate_sha256"], accepted_body_unchanged=True,
            source_div_c14n_sha256=oracle["source_div_c14n_sha256"],
            other_work_divisions=oracle["other_work_divisions"]))
        technical = dict(producer=dict(id=source.CONTRACT), checker=dict(id=oracle["contract"]),
                         shared_assumptions=["Producer and checker parse the same retained XML; checker independently compares the complete source division and header."],
                         independent_corroboration="Clean-process byte reproduction and TEI P5 XSD corroborate extraction; actual-master native projection follows.")
        command = "py -3 -m build.tools.stage_openmgh_vita_lupi_dual --stage <fresh-external-root>"
        for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
            path = _put_json(stage, evidence / (name + ".json"), common | dict(
                status="pass", command=command, exit_code=0, claim=name, source_oracle=oracle,
                direct_receipt_sha256=DIRECT_SHA, clean_process_reproduction="pass", tei_xsd="pass"))
            technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
        review = dict(reviewer=f"agent:{source.WORK_ID}-{code}-source-review", reviewed_at=now,
                      coverage=dict(status="unavailable", declared=scope,
                                    reached=["complete electronic source-tree and header oracle"],
                                    inspected=["complete electronic source-tree and header oracle"],
                                    unreviewed=["CVW visual comparison and print collation"]),
                      source_quality_uncertainty=["No print witness was independently collated."],
                      discrepancies=[], unreviewed_residuals=["Visual and human review remain unrecorded."])
        review_path = _put_json(stage, evidence / "review.json", common | review)
        decision = dict(source_local_disposition="Agent acceptance of the exact electronic text and P5 mapping only.",
                        blockers=[], human_decision=dict(status="not-recorded"),
                        agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                                              supported_scope=scope, unresolved_claims=[],
                                              unassessed_stronger_claims=["visual review", "human acceptance", "print collation", "rights clearance", "publication"]))
        acceptance_path, master_path = edition / "acceptance.json", edition / "master.tei.xml"
        if _io_path(ROOT / acceptance_path).exists() or _io_path(ROOT / master_path).exists():
            raise ValueError(f"{code} canonical edition already accepted")
        acceptance = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                             source_accounting_path=account, scope=accepted_scope,
                                             technical=technical, review=review | dict(report_path=review_path),
                                             representation_revision=revision, decision=decision)
        write_acceptance(_io_path(stage / acceptance_path), acceptance)
        validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
        master = _put(stage, master_path, derived)
        acceptance["promotion"].update(status="promoted", promoted_at=now,
                                       master=make_file_binding(stage, master))
        write_acceptance(_io_path(stage / acceptance_path), acceptance)
        targets = [t for t in state["targets"] if t["target_type"] == "edition" and t["target_id"] == old_edition["edition_id"]]
        if len(targets) != 1 or targets[0]["stage"] != "acquired":
            raise ValueError(f"{code} edition state is not uniquely acquired")
        targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
        targets[0]["evidence"].extend([master_path.as_posix(), acceptance_path.as_posix()])
        visible = (f"# Electronic source credit: {code}\n\n"
                   f"This Vita Lupi edition derives from {source_path.as_posix()} (SHA-256 {spec['source_sha256']}). "
                   "Credit Monumenta Germaniae Historica and the Bavarian State Library, Munich. "
                   "Preserve the source header's publication, license, and printed-volume bibliography. "
                   "The ZIP is acquisition packaging only. This stage does not establish print collation, "
                   "rights clearance, human acceptance, or public release.\n")
        _put(stage, edition / "README.source.md", visible.encode("utf-8"))
        credit_lines.append(f"- {code}: `{source_path.as_posix()}` (SHA-256 `{spec['source_sha256']}`).")
        results.append(dict(code=code, edition_id=old_edition["edition_id"], source_path=source_path.as_posix(),
                            source_sha256=spec["source_sha256"], package_path=package_path.as_posix(),
                            package_sha256=spec["package_sha256"], receipt_path=receipt_path.as_posix(),
                            receipt_sha256=spec["receipt_sha256"], oracle=oracle,
                            direct_candidate_sha256=item["candidate_sha256"],
                            accepted_master_sha256=_sha(master), acceptance_sha256=_sha(stage / acceptance_path),
                            projection_rows=1))
    _put_json(stage, work / "state.json", state)
    for item in results:
        edition = work / "forms" / old_form["textual_form_id"] / "editions" / item["edition_id"]
        acceptance_path = edition / "acceptance.json"
        validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
        projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path), category="prose")
        errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path),
                                          rows=projected["rows"], receipt=projected["receipt"], category="prose")
        if errors or len(projected["rows"]) != 1:
            raise ValueError(f"{item['code']} actual-master native prose failed: {errors[:3]}")
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    credit = (f"# Electronic source credit for {source.WORK_ID}\n\n"
              "Two retained openMGH electronic editions are separately preserved:\n" + "\n".join(credit_lines)
              + "\n\nCredit Monumenta Germaniae Historica and the Bavarian State Library, Munich. "
              "Each edition carries its own visible credit and complete electronic source header. "
              "ZIP files are acquisition packages only. Human review, print collation, rights clearance, "
              "and public release remain separate.\n")
    _put(stage, work / "SOURCE_CREDIT.md", credit.encode("utf-8"))
    result = dict(contract=CONTRACT, status="staged-only", work_id=source.WORK_ID,
                  canonical_root=ROOT.as_posix(), stage_root=stage.as_posix(),
                  direct_receipt=(DIRECT / "receipt.json").as_posix(), direct_receipt_sha256=DIRECT_SHA,
                  before=before, after=_files(stage / work), editions=results,
                  language="la", category="prose", projection_rows=2,
                  projection_status="independent-check-pass", installation="not-performed")
    _put_json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps(dict(status=result["status"], editions=len(result["editions"]),
                          stage_receipt=(args.stage / "stage-receipt.json").as_posix(),
                          stage_receipt_sha256=_sha(args.stage / "stage-receipt.json")), sort_keys=True))


if __name__ == "__main__":
    main()
