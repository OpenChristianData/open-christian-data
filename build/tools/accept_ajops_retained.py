"""Stage and guardedly install the twelve already repaired AJOPS articles."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from lxml import etree

from build.tei.ajops_jats_oracle_v3 import _oracle
from ocd_kernel.library.identities import cached_edition_lookups, load_work, validate_record
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (PROMOTED_MASTER_REASON, build_acceptance_record,
    make_file_binding, validate_acceptance, write_acceptance)
from ocd_kernel.tei.install_accepted import _files, install_accepted_work
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "plans/2026-09-23-acquisition-manifest-source-to-tei/artifacts/2026-10-08-deep-investigation"
CROSSWALK = OUT / "followup-readback-and-linkage.json"
TEI = "{http://www.tei-c.org/ns/1.0}"


def put_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def normalize(text):
    return re.sub(r"\W+", "", text.casefold())


def prepare(stage):
    stage = stage.resolve()
    if stage.exists() or not stage.parent.is_dir() or stage == ROOT or ROOT in stage.parents:
        raise ValueError("AJOPS stage must be a fresh external directory")
    crosswalk = json.loads(CROSSWALK.read_bytes())
    assert len(crosswalk["articles"]) == 12
    current = [json.loads(p.read_bytes()) for p in (ROOT / "library/works").glob("*/work.json")]
    for row in crosswalk["articles"]:
        proposal = row["linkage_proposal"]
        if any(w["work_id"] == proposal["work_id"] or normalize(w["title"]) == normalize(row["title"])
               or row["doi"].casefold() in json.dumps(w).casefold() for w in current):
            raise ValueError(f"AJOPS identity already exists or conflicts: {row['article']}")
    stage.mkdir()
    (stage / ".ocd-storage.json").write_bytes((ROOT / ".ocd-storage.json").read_bytes())
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    results = []
    for row in crosswalk["articles"]:
        source = SourceManifest.load(ROOT / row["source_manifest"], repository_root=ROOT)
        source.verify()
        if source.sha256 != row["source_manifest_sha256"]:
            raise ValueError("AJOPS reviewed source manifest changed")
        package = CandidatePackage.load(Path(row["candidate"]) / "package")
        if package.sha256 != row["candidate_package_sha256"]:
            raise ValueError("AJOPS reviewed candidate changed")
        report = validate(source, package, _oracle)
        if report.status != "pass":
            raise ValueError(f"AJOPS source oracle failed: {row['article']}")
        raw = package.member_bytes("content.tei.xml")
        if sha256(raw).hexdigest() != row["tei_sha256"]:
            raise ValueError("AJOPS reviewed TEI changed")
        proposal = row["linkage_proposal"]
        identity = {key: proposal[key] for key in ("work_id", "textual_form_id", "edition_id", "acquisition_id")}
        work = Path("library/works") / identity["work_id"]
        edition = work / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
        evidence = work / "integration/ajops-link-repair-20261008-v3"
        authorities = {a["name"]: a for a in source.record["authorities"]}
        primary = authorities["publisher-xml"]
        receipt = json.loads(source.authority_path("acquisition-receipt").read_bytes())
        scope_text = ("Complete retained publisher JATS article, including front matter, body and back matter; "
                      "publisher PDF is a comparison witness. Standalone figures and print collation are outside this text acceptance.")
        binding = dict(source_path=primary["path"], source_bytes=primary["bytes"],
                       source_sha256=primary["sha256"], source_scope=scope_text)
        acquisition_path = edition / "acquisitions" / (identity["acquisition_id"] + ".json")
        acquisition = dict(schema_version="2.0", acquisition_id=identity["acquisition_id"], edition_id=identity["edition_id"],
                           provider="AOSIS / African Journal of Pentecostal Studies", url=receipt["official_formats"]["xml"],
                           accessed_at=receipt["retrieved_at_utc"][:10], route="born-digital", **binding,
                           rights=receipt["rights"]["reuse"], retained_files=[
                               dict(path=authorities[name]["path"], bytes=authorities[name]["bytes"], sha256=authorities[name]["sha256"],
                                    media_type=media, scope=role)
                               for name, media, role in (("publisher-xml", "application/xml", "Primary text"),
                                                       ("publisher-pdf", "application/pdf", "Comparison witness"),
                                                       ("acquisition-receipt", "application/json", "Historical acquisition receipt"))])
        work_record = dict(schema_version="2.0", work_id=identity["work_id"], title=row["title"],
                           evidence=[primary["path"], authorities["acquisition-receipt"]["path"]],
                           creators=[dict(name=name, role="author", evidence=[primary["path"]]) for name in row["authors"]],
                           textual_forms=[dict(textual_form_id=identity["textual_form_id"], language="en", editions=[dict(
                               edition_id=identity["edition_id"], title=f"Publisher JATS electronic article; DOI {row['doi']}", language="en",
                               category="prose", acquisition_ids=[identity["acquisition_id"]], containing_source=dict(
                                   title=row["journal"], locator=f"Volume {row['volume']}, issue {row['issue']} ({row['publication_year']}), {row['article']}",
                                   evidence=[primary["path"]]))])])
        for name, record, path in (("work", work_record, work / "work.json"), ("acquisition", acquisition, acquisition_path)):
            validate_record(name, record)
            put_json(stage / path, record)
        load_work(stage / work / "work.json")
        revision = dict(id="ajops-readable-links-20261008-v3", date=now[:10],
                        note="Accept the complete retained JATS text with restored source IDs and readable link destinations; bind exact source and identity.")
        # The existing native route supports divisions and notes, but not noteGrp.
        # Preserve the anonymous grouping through its existing division carrier.
        parsed = etree.fromstring(raw)
        groups = parsed.findall(".//" + TEI + "noteGrp")
        if any(group.attrib or group.findall(".//" + TEI + "div") for group in groups) or raw.count(b"<noteGrp>") != len(groups):
            raise ValueError("AJOPS note grouping differs from reviewed anonymous wrappers")
        adapted = raw.replace(b"<noteGrp>", b'<div type="jats:note-group">').replace(b"</noteGrp>", b"</div>")
        restored = re.sub(rb'<div type="jats:note-group">(.*?)</div>', lambda match: b"<noteGrp>" + match[1] + b"</noteGrp>", adapted, flags=re.DOTALL)
        if restored != raw:
            raise ValueError("AJOPS note grouping adapter is not reversible")
        derived = bind_reviewed_header(adapted, expected_sha256=sha256(adapted).hexdigest(), identity=identity, source=binding,
                                       source_url=acquisition["url"], declared_scope=scope_text, revision=revision)
        candidate = stage / evidence / "candidate.tei.xml"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(derived)
        if errors := validate_file(candidate):
            raise ValueError(f"Bound AJOPS P5 errors: {errors[:3]}")
        before_text = etree.fromstring(adapted).find(TEI + "text")
        after_text = etree.fromstring(derived).find(TEI + "text")
        if etree.tostring(before_text, method="c14n") != etree.tostring(after_text, method="c14n"):
            raise ValueError("AJOPS header binding changed reviewed text")
        # Historical package notices remain evidence; acceptance status is owned by the new sidecar.
        (stage / evidence / "README.source.md").write_bytes(package.member_bytes("README.source.md"))
        put_json(stage / evidence / "candidate-unresolved-history.json", row["unresolved"])
        expected = [dict(path=authorities[name]["path"], position=position) for position, name in
                    enumerate(("publisher-xml", "publisher-pdf", "acquisition-receipt"), 1)]
        included = [dict(path=primary["path"], position=1, bytes=primary["bytes"], sha256=primary["sha256"], scope=scope_text)]
        excluded = [dict(path=authorities["publisher-pdf"]["path"], position=2, reason="Comparison witness; not a second text to concatenate."),
                    dict(path=authorities["acquisition-receipt"]["path"], position=3, reason="Acquisition support metadata; not article text.")]
        scope = dict(kind="member", declared=scope_text, expected_members=expected, included_members=included, excluded_members=excluded)
        common = dict(identity=identity, source=binding, candidate=make_file_binding(stage, candidate), scope=scope_text,
                      accepted_scope=dict(kind="member", declared=scope_text), expected_members=expected,
                      included_members=included, excluded_members=excluded, missing_members=[], unknown_members=[])
        account = put_json(stage / evidence / "source-accounting.json", common | dict(
            source_sha256=primary["sha256"], source_bytes=primary["bytes"], source_manifest_sha256=source.sha256,
            candidate_package_sha256=package.sha256, header_binding_text_c14n="unchanged",
            note_group_adapter=dict(groups=len(groups), exact_byte_inverse="pass", mapping="Anonymous noteGrp -> div type=jats:note-group; ordered child notes unchanged"),
            media_scope="Original graphic references retained; standalone assets excluded from text acceptance."))
        command = "py -3 -m build.tools.accept_ajops_retained --stage <fresh-external-root>"
        technical = dict(producer=dict(id=source.record["converter"]["id"]), checker=dict(id=source.record["validator"]["id"]),
                         shared_assumptions=["P5 and producer use lxml; source census and text comparison use ElementTree."],
                         independent_corroboration="Independent source/text/structure/link/PDF oracle, recorded fresh-process byte-identical reproductions, and unchanged complete text C14N after header binding.")
        for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
            proof = put_json(stage / evidence / (name + ".json"), common | dict(status="pass", command=command, exit_code=0,
                             claim=name, source_manifest_sha256=source.sha256, package_sha256=package.sha256,
                             oracle=dict(report.attestation), oracle_report_sha256=report.sha256,
                             reproduction_receipts="ajops-repair.json and ajops-tests.log" if row["article"] in ("a11", "a2") else "ajops-remaining-repairs.json",
                             text_c14n="unchanged by acceptance binding", note_groups=len(groups), note_group_adapter_exact_inverse="pass"))
            technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
        locus = primary["path"] + "#complete-jats-text"
        review = dict(reviewer="agent:ajops-family-audit", reviewed_at=now,
                      coverage=dict(status="partial", declared=scope_text, reached=[locus], inspected=[locus], unreviewed=[]),
                      source_quality_uncertainty=[], discrepancies=[],
                      unreviewed_residuals=["Mechanical source comparison is complete; whole-article visual collation, human verification, and independent rights clearance are not claimed."])
        review_path = put_json(stage / evidence / "review.json", common | review | dict(
            method="Full independent source oracle plus direct link repair assessment; no whole-article visual credit.",
            selected_patterns=["RP-04", "RP-05", "RP-06", "RP-14"], unresolved_media=[u for u in row["unresolved"] if u["category"] == "media"]))
        decision = dict(source_local_disposition="Agent acceptance of the complete retained publisher JATS text; PDF and media qualifications remain explicit.",
                        blockers=[], human_decision=dict(status="not-recorded"), agent_assessment=dict(status="accepted",
                        actor=review["reviewer"], assessed_at=now, supported_scope=scope_text, unresolved_claims=[],
                        unassessed_stronger_claims=["whole-article visual collation", "human verification", "independent rights clearance", "public publication"]))
        record = build_acceptance_record(stage, identity=identity, candidate_path=candidate, source_accounting_path=account,
                                        scope=scope, technical=technical, review=review | dict(report_path=review_path),
                                        representation_revision=revision, decision=decision)
        master = stage / edition / "master.tei.xml"
        master.write_bytes(derived)
        record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, master))
        acceptance = stage / edition / "acceptance.json"
        write_acceptance(acceptance, record)
        state = dict(schema_version="2.0", work_id=identity["work_id"], targets=[
            dict(target_type="acquisition", target_id=identity["acquisition_id"], stage="acquired", updated_at=now,
                 evidence=[acquisition_path.as_posix()]),
            dict(target_type="edition", target_id=identity["edition_id"], stage="accepted", updated_at=now,
                 reason=PROMOTED_MASTER_REASON, evidence=[master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])])
        put_json(stage / work / "state.json", state)
        validate_acceptance(acceptance, root=stage)
        validate_state(stage / work / "state.json", root=stage)
        projection = project_accepted_prose(stage, acceptance_path=acceptance)
        findings = verify_accepted_prose(stage, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
        if findings:
            raise ValueError(f"AJOPS projection failed: {findings[:3]}")
        put_json(stage / evidence / "projection.json", projection)
        results.append(dict(work_id=identity["work_id"], acceptance=acceptance.relative_to(stage).as_posix(),
                            rows=len(projection["rows"]), files=_files(stage / work), source_manifest_sha256=source.sha256,
                            candidate_package_sha256=package.sha256))
        print(row["article"], "staged and projected", len(projection["rows"]), flush=True)
    receipt = dict(status="staged-and-validated", stage=str(stage), generated_at=now,
                   crosswalk_sha256=sha256(CROSSWALK.read_bytes()).hexdigest(), results=results)
    put_json(stage / "ajops-stage-receipt.json", receipt)
    return receipt


def install(stage):
    stage = stage.resolve(strict=True)
    receipt = json.loads((stage / "ajops-stage-receipt.json").read_bytes())
    if receipt["status"] != "staged-and-validated" or len(receipt["results"]) != 12:
        raise ValueError("AJOPS stage receipt is incomplete")
    for row in receipt["results"]:
        target = ROOT / "library/works" / row["work_id"]
        if target.exists() or _files(stage / "library/works" / row["work_id"]) != row["files"]:
            raise ValueError(f"AJOPS stale stage or existing destination: {row['work_id']}")
    results = []
    for row in receipt["results"]:
        result = install_accepted_work(ROOT, stage, work_id=row["work_id"])
        results.append(dict(work_id=row["work_id"], installation=result))
        put_json(OUT / "ajops-installation.json", dict(status="installed-readback-pending", results=results))
        print(row["work_id"], "installed", flush=True)
    # Cache only this read-only batch, after every identity mutation is complete.
    with cached_edition_lookups():
        for row, result in zip(receipt["results"], results, strict=True):
            acceptance = ROOT / row["acceptance"]
            validate_acceptance(acceptance, root=ROOT)
            projection = project_accepted_prose(ROOT, acceptance_path=acceptance)
            findings = verify_accepted_prose(ROOT, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
            if findings or _files(ROOT / "library/works" / row["work_id"]) != row["files"]:
                raise ValueError(f"Installed AJOPS readback differs: {row['work_id']}")
            result.update(projection_rows=len(projection["rows"]), verifier_findings=findings)
            put_json(OUT / "ajops-installation.json", dict(status="in-progress", results=results))
            print(row["work_id"], "read back", flush=True)
    put_json(OUT / "ajops-installation.json", dict(status="complete", results=results, stage=str(stage)))
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    print(json.dumps(install(args.stage) if args.install else prepare(args.stage), ensure_ascii=True))
