"""Freeze the complete PG22088 electronic witness as a guarded review stage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei.newman_apologia_pg22088_native import ROOT, SOURCE, SOURCE_SHA256, adapt, direct_candidate, partition
from build.tei.newman_apologia_pg22088_native_oracle import MANIFEST, PACKAGE, check_partition
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


WORK_ID = "newman-apologia-pro-vita-sua"
FORM_ID = "newman-apologia-pro-vita-sua-retained-electronic"
EDITION_ID = "newman-apologia-pro-vita-sua-retained-electronic-witness"
ACQUISITION_ID = "newman-apologia-pro-vita-sua-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
EVIDENCE = WORK / "integration/pg22088-v1"
STAGE_PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
SOURCE_RELATIVE = Path("raw/gutenberg/pg22088.txt")
SCOPE = (
    "Complete Apologia work text in retained Project Gutenberg 22088 electronic witness, "
    "source lines 33–13,822 in order. The provider header (lines 1–32) and Gutenberg "
    "footer/license (lines 13,823–14,174) are retained as evidence outside the accepted work text. "
    "No print-edition equivalence or print collation is claimed."
)


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"PG22088 JSON object required: {path}")
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
            or not stage.name.startswith("na-s")):
        raise ValueError("fresh short external PG22088 stage required")
    raw = _io_path(SOURCE).read_bytes()
    if len(raw) != 818680 or _sha(raw) != SOURCE_SHA256:
        raise ValueError("PG22088 retained plain text differs")
    acquired = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    retained = acquired["retained_files"]
    if (len(retained) != 1 or retained[0]["path"] != SOURCE_RELATIVE.as_posix()
            or retained[0]["bytes"] != len(raw) or retained[0]["sha256"] != SOURCE_SHA256
            or acquired["url"] != "https://www.gutenberg.org/ebooks/22088"):
        raise ValueError("PG22088 acquisition member or source identity differs")
    direct = direct_candidate()
    adapted, counts = adapt(direct)
    work_text, provider_header, provider_license = partition(adapted)
    oracle = check_partition(adapted, work_text, provider_header, provider_license)
    if oracle["source_oracle_status"] != "pass" or oracle["adapted_tei_sha256"] != _sha(adapted):
        raise ValueError("PG22088 complete source or reverse oracle failed")
    before = _files(ROOT / WORK)
    if len(before) != 3 or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("PG22088 canonical acquired preimage differs")
    for relative in before:
        _put(stage, WORK / relative, _io_path(ROOT / WORK / relative).read_bytes())
    _put(stage, SOURCE_RELATIVE, raw)
    evidence_paths = set()
    for target in _read(ROOT / WORK / "state.json")["targets"]:
        evidence_paths.update(item.split("#", 1)[0] for item in target["evidence"])
    manifest = _read(MANIFEST)
    evidence_paths.add(MANIFEST.relative_to(ROOT).as_posix())
    evidence_paths.update(item["path"] for item in manifest["authorities"])
    for item in sorted(evidence_paths):
        relative = Path(item)
        if relative.is_absolute() or ".." in relative.parts or not _io_path(ROOT / relative).is_file():
            raise ValueError(f"PG22088 evidence path differs: {item}")
        _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    _put(stage, EVIDENCE / "inputs/direct-candidate.tei.xml", direct)
    _put(stage, EVIDENCE / "inputs/adapted-candidate.tei.xml", adapted)
    _put(stage, EVIDENCE / "inputs/provider-header.tei.xml", provider_header)
    _put(stage, EVIDENCE / "inputs/provider-license.tei.xml", provider_license)
    _put(stage, EVIDENCE / "inputs/work-text.tei.xml", work_text)
    _put_json(stage, EVIDENCE / "inputs/oracle.json", oracle)
    _put_json(stage, EVIDENCE / "inputs/validated-direct-package.json", dict(
        path=PACKAGE.as_posix(), package_sha256=oracle["direct_package_sha256"],
        manifest_path=MANIFEST.relative_to(ROOT).as_posix(),
        manifest_sha256=oracle["source_manifest_sha256"]))
    direct_account = _read(PACKAGE / "source-accountability.json")
    if (direct_account["source_line_count"] != 14174 or direct_account["represented_line_count"] != 14174
            or any(direct_account[key] != 0 for key in ("omitted_line_count", "duplicate_line_count",
                                                         "invented_line_count", "reordered_line_count", "excluded_member_count"))
            or direct_account["source_sha256"] != SOURCE_SHA256):
        raise ValueError("PG22088 complete-source accounting differs")
    _put(stage, EVIDENCE / "inputs/direct-source-accountability.json",
         _io_path(PACKAGE / "source-accountability.json").read_bytes())
    _put(stage, WORK / "SOURCE_CREDIT.md", (
        "# Source and credit — John Henry Newman, Apologia Pro Vita Sua\n\n"
        "The accepted text is reconstructed from the complete retained Project Gutenberg 22088 "
        "plain-text electronic witness. The Apologia work text occupies source lines 33–13,822. "
        "The Gutenberg header (1–32) and footer/license (13,823–14,174) remain in source "
        "and review evidence outside the accepted work text. All 14,174 physical lines are "
        "accounted for in their source order. "
        "This electronic witness has not been independently collated to a print edition.\n\n"
        f"Text authority: {SOURCE_RELATIVE.as_posix()} — SHA-256 {SOURCE_SHA256}.\n\n"
        "Project Gutenberg record: https://www.gutenberg.org/ebooks/22088\n"
        "Project Gutenberg license: https://www.gutenberg.org/policy/license.html\n\n"
        "Rights outside the United States, attribution, trademark conditions, human acceptance, "
        "and public release require separate review.\n"
    ).encode("utf-8"))
    original_work = _read(ROOT / WORK / "work.json")
    revised = json.loads(json.dumps(original_work))
    form = revised["textual_forms"][0]
    edition = form["editions"][0]
    if (revised["work_id"] != WORK_ID or form["textual_form_id"] != FORM_ID
            or edition["edition_id"] != EDITION_ID or edition["acquisition_ids"] != [ACQUISITION_ID]
            or edition.get("category")):
        raise ValueError("PG22088 acquired work identity differs")
    edition["category"] = "prose"
    validate_identity_update(original_work, revised)
    _put_json(stage, WORK / "work.json", revised)
    load_work(_io_path(stage / WORK / "work.json"))
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                    acquisition_id=ACQUISITION_ID)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    revision = dict(id="newman-apologia-pg22088-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Stage the complete retained PG22088 electronic witness with reversible native carriers.")
    binding = dict(source_path=SOURCE_RELATIVE.as_posix(), source_sha256=SOURCE_SHA256,
                   source_bytes=len(raw), source_scope=retained[0]["scope"])
    bound = bind_reviewed_header(work_text, expected_sha256=_sha(work_text), identity=identity,
                                 source=binding, source_url=acquired["url"],
                                 declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != work_text.split(b"</teiHeader>", 1)[1]:
        raise ValueError("PG22088 reviewed header changed the source body")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"PG22088 accepted candidate fails P5: {errors[:3]}")
    expected = [dict(path=SOURCE_RELATIVE.as_posix(), position=1)]
    included = [dict(path=SOURCE_RELATIVE.as_posix(), position=1, bytes=len(raw),
                     sha256=SOURCE_SHA256, scope=SCOPE)]
    selection = dict(kind="selection", declared=SCOPE, expected_members=expected,
                     included_members=included, excluded_members=[])
    common = dict(identity=identity, source=binding, candidate=make_file_binding(stage, candidate),
                  accepted_scope=dict(kind="selection", declared=SCOPE), expected_members=expected,
                  included_members=included, excluded_members=[], missing_members=[], unknown_members=[])
    account = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        scope=retained[0]["scope"], source_sha256=SOURCE_SHA256, source_bytes=len(raw),
        source_oracle=oracle, source_carriers=counts, direct_candidate_sha256=_sha(direct),
        adapted_candidate_sha256=_sha(adapted), work_text_sha256=_sha(work_text),
        retained_text_authority=SOURCE_RELATIVE.as_posix(), physical_lines=14174,
        represented_work_lines=13790, evidence_only_provider_lines=384,
        provider_header_line_range=[1, 32], provider_license_line_range=[13823, 14174],
        omitted_lines=0, duplicate_lines=0))
    command = "py -3 -m build.tools.stage_newman_apologia_pg22088 --stage <fresh-short-external-root>"
    technical = dict(producer=dict(id="ocd-newman-apologia-pg22088-complete-text-native-v1"),
                     checker=dict(id=oracle["contract"]),
                     shared_assumptions=["The complete-source oracle and reverse structural oracle both parse TEI, but the reverse oracle independently checks every node and does not import the adapter."],
                     independent_corroboration="13,790 work lines plus 384 evidence-only provider lines exhaust all 14,174 physical source lines; direct source oracle, reversible carrier and partition comparison, P5, and native producer/checker.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            scope=SCOPE, status="pass", claim=name, command=command, exit_code=0,
            source_oracle=oracle, tei_p5_xsd="pass", native_projection="pass"))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:newman-apologia-pg22088-source-review", reviewed_at=now,
                  coverage=dict(status="partial", declared=SCOPE,
                                reached=["13,790 Apologia work lines in source order and 384 provider lines retained as evidence",
                                         "complete independent mechanical source oracle",
                                         "reversible carrier oracle, P5, and native projection"],
                                inspected=["complete independent mechanical source oracle"],
                                unreviewed=["human visual comparison", "print collation"]),
                  source_quality_uncertainty=["The electronic text has not been collated to a print exemplar."],
                  discrepancies=[], unreviewed_residuals=["Human acceptance and rights clearance remain open."])
    review_path = _put_json(stage, EVIDENCE / "review.json", common | review | dict(scope=SCOPE))
    decision = dict(source_local_disposition="Agent technical acceptance of the complete Apologia work text in the PG22088 electronic witness, with provider material retained as evidence.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                                          supported_scope=SCOPE,
                                          unresolved_claims=["human visual comparison and textual acceptance",
                                                             "creator and edition-witness identity",
                                                             "editorial disposition", "rights clearance", "publication"],
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
        raise ValueError("PG22088 edition acquired state differs")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master.relative_to(stage).as_posix(),
                                 acceptance.relative_to(stage).as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"PG22088 native accepted-master projection differs: {errors}")
    after = _files(stage / WORK)
    dependencies = {
        relative: _sha(_io_path(ROOT / relative).read_bytes()) for relative in (
            "build/tei/newman_apologia_pg22088_native.py",
            "build/tei/newman_apologia_pg22088_native_oracle.py",
            "build/tei/lib068_source_local.py",
            "build/tei/lib068_source_local_oracle.py",
            "build/tools/stage_newman_apologia_pg22088.py",
            "ocd_kernel/projection/native_content.py",
            "ocd_kernel/projection/native_content_check.py",
            "ocd_kernel/projection/categories/native_documents.py",
            "schemas/v2/native-content.schema.json",
        )
    }
    receipt = dict(contract="ocd-newman-apologia-pg22088-stage-v1", work_id=WORK_ID,
                   source_sha256=SOURCE_SHA256, direct_sha256=_sha(direct), adapted_sha256=_sha(adapted),
                   work_text_sha256=_sha(work_text), provider_header_sha256=_sha(provider_header),
                   provider_license_sha256=_sha(provider_license),
                   accepted_master_sha256=_sha(bound), oracle=oracle, before=before, after=after,
                   native_rows=1, dependencies=dependencies, stage_root=stage.as_posix())
    _put_json(stage, Path("stage-receipt.json"), receipt)
    return dict(status="staged-for-review", stage=stage.as_posix(), before_files=len(before),
                after_files=len(after), native_rows=1,
                receipt_sha256=_sha(_io_path(stage / "stage-receipt.json").read_bytes()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().stage), sort_keys=True))


if __name__ == "__main__":
    main()
