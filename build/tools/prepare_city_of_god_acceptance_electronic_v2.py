"""Stage source-bound City of God electronic acceptance without installing it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei import city_of_god_oracle_electronic_v2 as oracle
from build.tei import city_of_god_reconstruction_electronic_v2 as producer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.acceptance import (
    _source_binding, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/augustine-city-of-god")
RECEIPT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-326-electronic-v2-repair-20260926.json")
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")
EDITION_DATA = {
    "dods-1871": ("dods", "augustine-city-of-god-dods-retained-en", "augustine-city-of-god-dods-retained-electronic", "augustine-city-of-god-dods-acquired", "dods-chapter-17-16", "Zion", "edition"),
    "npnf-1887": ("npnf", "augustine-city-of-god-npnf-retained-en", "augustine-city-of-god-npnf-retained-electronic", "augustine-city-of-god-npnf-acquired", "npnf-iv-X-2", "their blessed life, and the light of truth", "selection"),
}


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    if digest(source.read_bytes()) != digest(target.read_bytes()):
        raise PipelineError(f"stage copy changed bytes: {source}")


def bind_header(original: bytes, identity: dict[str, str], source: dict, url: str, scope: str, revision: dict) -> bytes:
    bound = bind_reviewed_header(original, expected_sha256=digest(original), identity=identity,
                                 source=source, source_url=url, declared_scope=scope, revision=revision)
    opening, closing = b"<sourceDesc>", b"</sourceDesc>"
    historical = original.split(opening, 1)[1].split(closing, 1)[0]
    middle = bound.split(opening, 1)[1].split(closing, 1)[0]
    if not middle.startswith(historical) or historical.count(b"<p>") != 2 or historical.count(b"</p>") != 2:
        raise PipelineError("City source description layout changed")
    bibl = middle[len(historical):]
    if not bibl.startswith(b"<bibl ") or not bibl.endswith(b"</bibl>"):
        raise PipelineError("City acceptance bibl layout changed")
    historical_notes = historical.replace(b"<p>", b'<note type="historical-source-description">').replace(b"</p>", b"</note>")
    new_middle = bibl.replace(b">", b">" + historical_notes, 1)
    result = bound.replace(opening + middle + closing, opening + new_middle + closing, 1)
    old_publisher = b"Open Christian Data \xe2\x80\x94 nonaccepted candidate, not canonical or authorized for publication"
    new_publisher = b"Open Christian Data \xe2\x80\x94 reviewed electronic representation; publication not authorized"
    if result.count(old_publisher) != 1:
        raise PipelineError("City publication statement layout changed")
    result = result.replace(old_publisher, new_publisher, 1)
    if result.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("City acceptance header changed original TEI text bytes")
    return result


def stage_one(root: Path, stage: Path, key: str, receipt: dict) -> dict:
    short, form, edition, acquisition_id, chapter_id, reading, kind = EDITION_DATA[key]
    identity = dict(work_id="augustine-city-of-god", textual_form_id=form,
                    edition_id=edition, acquisition_id=acquisition_id)
    edition_dir = WORK / "forms" / form / "editions" / edition
    acquisition_rel = edition_dir / "acquisitions" / f"{acquisition_id}.json"
    acquisition = json.loads((root / acquisition_rel).read_bytes())
    source = _source_binding(acquisition, context=str(acquisition_rel))
    if acquisition["edition_id"] != edition or acquisition["acquisition_id"] != acquisition_id:
        raise PipelineError("City acquisition identity differs")
    declared = acquisition["source_scope"] if short == "dods" else (
        "The City of God div1 iv and retained Schaff series-editor preface div1 iii "
        "within the CCEL NPNF1-02 electronic volume; other volume divisions are context, not City of God text."
    )
    source_manifest_rel = Path(f"sources/city-of-god/city-of-god-{key}-electronic-v2.source-manifest.json")
    route = json.loads((root / source_manifest_rel).read_bytes())
    retained = acquisition["retained_files"]
    primary = [(item["path"], item["sha256"], item["bytes"]) for item in route["authorities"] if item["role"] == "primary-source"]
    if primary != [(item["path"], item["sha256"], item["bytes"]) for item in retained]:
        raise PipelineError("City source manifest primary files differ from installed acquisition")
    for item in retained:
        original_file = resolve_repo_path(root, item["path"])
        if original_file.stat().st_size != item["bytes"] or digest(original_file.read_bytes()) != item["sha256"]:
            raise PipelineError(f"City retained source changed: {item['path']}")
        copy_file(original_file, stage / item["path"])
    copy_file(root / acquisition_rel, stage / acquisition_rel)
    if acquisition.get("source_kind") == "retained-member-set":
        copy_file(root / acquisition["source_path"], stage / acquisition["source_path"])
    original_root = Path(f"C:/Scratch/Open Christian Data/city-of-god-electronic-fidelity-20260926-{short}-v2")
    original_file = original_root / "package/content.tei.xml"
    original = original_file.read_bytes()
    receipt_entry = receipt["edition_candidates"][key]
    package_manifest = original_root / "package/manifest.json"
    validation = original_root / "validation.json"
    if digest(package_manifest.read_bytes()) != receipt_entry["package_manifest"]["sha256"] or digest(validation.read_bytes()) != receipt_entry["validation_report"]["sha256"]:
        raise PipelineError("City reviewed v2 candidate or validation report changed")
    report = json.loads(validation.read_bytes())
    if report["status"] != "pass" or report["findings"] or report["attestation"]["implementation_sha256"] != digest((root / "build/tei/city_of_god_oracle_electronic_v2.py").read_bytes()):
        raise PipelineError("City independent v2 validation is not current and passing")
    profile = json.loads((root / "sources/city-of-god/city-of-god.electronic-v2.reconstruction-profile.json").read_bytes())
    if producer._tei(root, short + "-" + ("1871" if short == "dods" else "1887"), profile) != original:
        raise PipelineError("City electronic producer does not reproduce the exact v2 TEI")
    original_tree = etree.fromstring(original)
    oracle._body_checks(original_tree, short + "-" + ("1871" if short == "dods" else "1887"), root)
    revision = dict(id=f"city-{short}-electronic-v2-binding", date="2026-09-26",
                    note="Bind the retained electronic witness; original TEI text bytes are unchanged.")
    derived = bind_header(original, identity, source, acquisition["url"], declared, revision)
    evidence = stage / WORK / "integration" / f"city-{short}-electronic-v2-acceptance"
    evidence.mkdir(parents=True, exist_ok=True)
    candidate = evidence / "candidate.tei.xml"
    candidate.write_bytes(derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"City acceptance derivative failed TEI XSD: {errors[:2]}")
    chapter = etree.fromstring(derived).xpath(".//*[@xml:id=$id]", namespaces={"xml":"http://www.w3.org/XML/1998/namespace"}, id=chapter_id)[0]
    if " ".join("".join(chapter.itertext()).split()).count(reading) != 2:
        raise PipelineError("City electronic source reading was not preserved")
    expected = [{"path": item["path"], "position": i} for i,item in enumerate(retained, 1)]
    included = [{key: item[key] for key in ("path", "bytes", "sha256", "scope") if key in item} | {"position": i} for i,item in enumerate(retained, 1)]
    scope = dict(kind=kind, declared=declared, expected_members=expected, included_members=included, excluded_members=[])
    binding = make_file_binding(stage, candidate)
    common = dict(identity=identity, candidate=binding, source=source, scope=declared,
                  accepted_scope=dict(kind=kind, declared=declared), expected_members=expected,
                  included_members=included, excluded_members=[], missing_members=[], unknown_members=[])
    account = evidence / "source-accounting.json"
    write_json(account, common | dict(scope=source["source_scope"], source_sha256=source["source_sha256"],
                                      source_bytes=source["source_bytes"], verified_actual_source_files=len(retained),
                                      original_v2_accountability_sha256=receipt_entry["package_members"]["source-accountability.json"]["sha256"]))
    command = "py -3 -m build.tools.prepare_city_of_god_acceptance_electronic_v2 --stage <fresh-external-root>"
    details = {
      "validation": dict(original_independent_validation_sha256=digest(validation.read_bytes()), status="pass", findings=[], derived_tei_xsd_errors=[]),
      "accounting": dict(verified_actual_source_files=len(retained), original_v2_accountability_sha256=receipt_entry["package_members"]["source-accountability.json"]["sha256"], all_primary_members_match_sidecar=True),
      "fidelity": dict(original_tei_sha256=digest(original), derived_tei_sha256=digest(derived), text_bytes_unchanged=True, source_reading=reading, source_reading_occurrences=2, original_oracle_pass=True),
      "reproducibility": dict(producer_reproduced_original_tei_sha256=digest(original), header_derivative_sha256=digest(derived), original_text_bytes_unchanged=True),
      "schema": dict(vendored_tei_xsd_errors=[], original_candidate_validation_status="pass"),
      "closure": dict(versioned_source_manifest_sha256=digest((root / source_manifest_rel).read_bytes()),
                      producer_sha256=digest((root / "build/tei/city_of_god_reconstruction_electronic_v2.py").read_bytes()),
                      oracle_sha256=digest((root / "build/tei/city_of_god_oracle_electronic_v2.py").read_bytes()),
                      reviewed_receipt_sha256=digest((root / RECEIPT).read_bytes())),
    }
    technical = dict(producer={"id":route["converter"]["id"]}, checker={"id":route["validator"]["id"]},
                     shared_assumptions=["Producer and oracle share the exact retained electronic files and route manifest; direct locus review is bounded."],
                     independent_corroboration="Current independent full-candidate oracle and XSD, exact source-file rehash, in-memory TEI reproduction, source-reading mutation test, and unchanged tei:text after header binding.")
    for name in PROOFS:
        proof = evidence / f"{name}.json"
        write_json(proof, common | dict(status="pass", command=command, exit_code=0, details=details[name]))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(reviewer="agent:city-electronic-v2-source-fidelity", reviewed_at=now,
                  coverage=dict(status="partial", declared=declared, reached=[chapter_id], inspected=[chapter_id], unreviewed=[]),
                  source_quality_uncertainty=["Print exemplar and electronic transcription lineage are not established by this electronic-source acceptance."],
                  discrepancies=[], unreviewed_residuals=["Only the named electronic-reading locus received this new direct source comparison; whole-edition visual review is not claimed."],
                  report_path=evidence / "review.json")
    write_json(review["report_path"], common | {key:value for key,value in review.items() if key!="report_path"} |
               dict(method="Direct exact retained source reading compared with the current derivative TEI; historical twelve-view receipt is not carried forward as current visual review."))
    decision = dict(source_local_disposition="Isolated proposed agent acceptance of exact retained electronic witness only; canonical installation, human review, rights, and publication are unrecorded.",
                    blockers=[], agent_assessment=dict(status="accepted", actor="agent:city-electronic-v2-source-fidelity",
                        assessed_at=now, supported_scope=declared,
                        unassessed_stronger_claims=["human acceptance", "print-edition identity", "whole-edition visual review", "rights clearance", "publication"], unresolved_claims=[]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                     source_accounting_path=account, scope=scope, technical=technical,
                                     review=review, representation_revision=revision, decision=decision)
    acceptance = stage / edition_dir / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    original_record = acceptance.read_bytes()
    mutant = json.loads(original_record)
    mutant["scope"]["included_members"][0]["sha256"] = "0" * 64
    write_acceptance(acceptance, mutant)
    try:
        try:
            validate_acceptance(acceptance, root=stage)
        except PipelineError as exc:
            mutation_error = str(exc)
        else:
            raise PipelineError("public validate_acceptance accepted a mutated retained source binding")
    finally:
        acceptance.write_bytes(original_record)
    validate_acceptance(acceptance, root=stage)
    return dict(edition=edition, acceptance_path=acceptance.relative_to(stage).as_posix(),
                acceptance_sha256=digest(original_record), candidate_sha256=digest(derived),
                original_tei_sha256=digest(original), primary_source_files=len(retained),
                public_validate_acceptance="pass", mutation_rejected=mutation_error)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    root = ROOT.resolve(strict=True)
    stage = args.stage.resolve(strict=False)
    if stage.exists() or stage == root or root in stage.parents or stage in root.parents or not stage.parent.is_dir():
        raise PipelineError("City acceptance stage must be a fresh external directory")
    receipt = json.loads((root / RECEIPT).read_bytes())
    if receipt["contract"] != "ocd-city-of-god-electronic-v2-repair-review-v1":
        raise PipelineError("City electronic-v2 review receipt differs")
    stage.mkdir()
    copy_file(root / WORK / "work.json", stage / WORK / "work.json")
    copy_file(root / WORK / "state.json", stage / WORK / "state.json")
    for _short, form, edition, acquisition_id, *_rest in EDITION_DATA.values():
        relative = WORK / "forms" / form / "editions" / edition / "acquisitions" / f"{acquisition_id}.json"
        copy_file(root / relative, stage / relative)
    result = [stage_one(root, stage, key, receipt) for key in EDITION_DATA]
    write_json(stage / "city-electronic-v2-acceptance-stage.json", dict(
        contract="ocd-city-electronic-v2-acceptance-stage-v1", status="isolated-pending-promotion",
        source_role="Exact extracted XHTML/XML files; ZIPs are acquisition packages only", editions=result))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
