"""Prepare the exact reviewed Owen Worship CCEL witness for agent acceptance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape, quoteattr

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/john-owen-worship")
EDITION = (
    WORK
    / "forms/john-owen-worship-english/editions/john-owen-worship-ccel-thml-witness"
)
ACQUISITION = EDITION / "acquisitions/john-owen-worship-ccel-retained.json"
IDENTITY = dict(
    work_id="john-owen-worship",
    textual_form_id="john-owen-worship-english",
    edition_id="john-owen-worship-ccel-thml-witness",
    acquisition_id="john-owen-worship-ccel-retained",
)
SOURCE = Path("raw/ccel/owen/worship.xml")
MANIFEST = Path(
    "sources/structured-text/lib053-john-owen/john-owen-lib053.source-manifest.json"
)
REVIEW_HOME = Path(
    "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews"
)
TICKET = Path(
    "plans/2026-08-31-sample-first-library-verification/issues/37c-234-john-owen-worship.md"
)
REPORT = REVIEW_HOME / "37c-234.md"
RECEIPT = REVIEW_HOME / "37c-234-receipt.json"
AUDIT = REVIEW_HOME / "37c-234-owner-review-current-audit-20260922.json"
CANDIDATE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/37c-234-john-owen-worship-20260918-route-v4-paragraph-locations"
)
CVW_FIRST = CANDIDATE.with_name(CANDIDATE.name + "-cvw-12-locus")
CVW_INDEX = CANDIDATE.with_name(CANDIDATE.name + "-cvw-index-paging-fix-8-locus")
SOURCE_SHA = "88c1fee9f8907222dbef6bcc4fa9bed469b72d8c445bb9a605403af62829e1d3"
MANIFEST_SHA = "3e994bd292121744196a93be7143aad29cd3b4fb1cd390f588dc973c697551c0"
PACKAGE_SHA = "832ca6a6bace11a7e17484e38be27ec05771a86589eab028b579f1e8025254aa"
TEI_SHA = "fe8cdff4caf1e7aecf64abbab8f248d834556e46226446cd22645aa1bcd70194"
VALIDATION_SHA = "993c4111b92f0073503231b0523f30fcadc7e2d3778b500c1c0a8798dea69428"
SCOPE = "Complete single-member CCEL ThML electronic witness for A Brief Instruction in the Worship of God, including its header, title page, prefatory note, catechism, both index divisions, comments, page breaks, and inline references."
PROOFS = (
    "validation",
    "accounting",
    "fidelity",
    "reproducibility",
    "schema",
    "closure",
)
LOCI = (
    "i",
    "ii",
    "iii.i.i",
    "iii.i.xxvii",
    "iv.i",
    "iv.ii",
    "iv.iii",
    "iv.iv",
    "iv.v",
    "v.i",
    "v.ii",
    "v.iii",
)


CAPTURES = (
    (
        CVW_FIRST,
        "01-title-page",
        "201bd86b5f35d271b5e59ff7c0d3847c3f0afa05b4f33b9e9d9ec288c04f9ba2",
    ),
    (
        CVW_FIRST,
        "02-preface",
        "e7ff764a14ffb768075ea0502f464a1434edc6df1c839c324d933e044c26e078",
    ),
    (
        CVW_FIRST,
        "03-catechism-q1",
        "e236242271c9c5a302a8e0b073242b608d7c89326ca32be6a51187fab35de2b7",
    ),
    (
        CVW_FIRST,
        "04-catechism-q27",
        "cd52d94cbe553290989addcf4ef16c3ead3ea2b9a42dec7d92abb90ea88224b5",
    ),
    (
        CVW_INDEX,
        "iv-i-scripture",
        "1a71bf81191a6e89eecf9d47e5282a4562bd4f9a887cbacfcd25065bd00018ae",
    ),
    (
        CVW_INDEX,
        "iv-ii-citations",
        "88f74868f195c27991d9c9c8fe2487a106128480865d2a61705396334b6d2279",
    ),
    (
        CVW_INDEX,
        "iv-iii-names",
        "73071a7cc189017c70ca6aeca0a7fa9fbefce32a3004851ea746f89c1c19dd2f",
    ),
    (
        CVW_INDEX,
        "iv-iv-latin",
        "e397a1b8acd41d0c6e27f79e88614a2b8a62b23a59d174952e44000a58207a92",
    ),
    (
        CVW_INDEX,
        "iv-v-page-numbers",
        "88aa9b8061aff4612313780e46d6e7435b5f4c0268033478dc189618169c76f2",
    ),
    (
        CVW_INDEX,
        "v-i-scripture",
        "10d43146a79d467213fdabcb3992b8d729fd53ea3886e86439385bd57aae6115",
    ),
    (
        CVW_INDEX,
        "v-ii-names",
        "8a84587e105bd1439985d313eb7f5426a08f7eb8e539b7b79ebb2523c7d93cb4",
    ),
    (
        CVW_INDEX,
        "v-iii-ending",
        "d4a85fd9d756b9213670de48f73968a2d4ebdaa8e76843e78d83f43f803cfb31",
    ),
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(
            f"required Owen Worship evidence is unavailable: {path}"
        ) from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"Owen Worship SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Owen Worship JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Owen Worship JSON is not an object: {label}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _copy(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _check_stage(root: Path, stage: Path) -> Path:
    stage = stage.absolute()
    if stage.exists():
        raise PipelineError(f"Owen Worship staging root must be fresh: {stage}")
    resolved = stage.resolve()
    protected = (
        root.resolve(),
        CANDIDATE.resolve(),
        CVW_FIRST.resolve(),
        CVW_INDEX.resolve(),
    )
    if any(
        resolved == area or area in resolved.parents or resolved in area.parents
        for area in protected
    ):
        raise PipelineError(
            "Owen Worship staging root overlaps checkout or reviewed candidate"
        )
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError(
            "Owen Worship staging parent must be an ordinary existing directory"
        )
    return stage


def _bind_corpus_header(original: bytes, source: dict, revision: dict) -> bytes:
    """Insert a scoped acceptance binding in the outer header; preserve members byte for byte."""
    if _sha(original) != TEI_SHA:
        raise PipelineError("reviewed Owen Worship TEI differs")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(original, parser)
    ns = "http://www.tei-c.org/ns/1.0"
    if (
        root.tag != f"{{{ns}}}teiCorpus"
        or len(root) != 2
        or root[1].tag != f"{{{ns}}}TEI"
    ):
        raise PipelineError("reviewed Owen Worship corpus envelope differs")
    source_desc = b"</ns0:sourceDesc>"
    header_end = b"</ns0:teiHeader>"
    if original.count(source_desc) != 2 or original.count(header_end) != 2:
        raise PipelineError("reviewed Owen Worship headers are ambiguous")
    facts = IDENTITY | {
        "source_sha256": SOURCE_SHA,
        "source_bytes": str(source["source_bytes"]),
        "representation_revision": revision["id"],
        "sha256": SOURCE_SHA,
    }
    bibl = '<ns0:bibl type="ocd-acceptance-binding">'
    bibl += "<ns0:ptr target=" + quoteattr(source["source_url"]) + "/>"
    bibl += "".join(
        "<ns0:idno type=" + quoteattr(key) + ">" + escape(value) + "</ns0:idno>"
        for key, value in facts.items()
    )
    bibl += '<ns0:note type="source-location">' + SOURCE.as_posix() + "</ns0:note>"
    bibl += '<ns0:note type="source-scope">' + escape(SCOPE) + "</ns0:note></ns0:bibl>"
    change = (
        "<ns0:revisionDesc><ns0:change xml:id="
        + quoteattr(revision["id"])
        + " when="
        + quoteattr(revision["date"])
        + ">"
        + escape(revision["note"])
        + "</ns0:change></ns0:revisionDesc>"
    )
    source_open = b"<ns0:sourceDesc><ns0:p>"
    source_close = b"</ns0:p></ns0:sourceDesc>"
    if original.count(source_open) != 1 or original.count(source_close) != 1:
        raise PipelineError("reviewed Owen Worship outer source description differs")
    bibl_open = '<ns0:bibl type="ocd-acceptance-binding">'
    bibl_close = "</ns0:bibl>"
    binding_content = bibl[len(bibl_open) : -len(bibl_close)]
    result = original.replace(
        source_open,
        source_open.replace(
            b"<ns0:p>",
            (bibl_open + '<ns0:note type="historical-source-description">').encode(),
        ),
        1,
    )
    result = result.replace(
        source_close,
        ("</ns0:note>" + binding_content + bibl_close + "</ns0:sourceDesc>").encode(),
        1,
    )
    result = result.replace(header_end, change.encode() + header_end, 1)
    etree.fromstring(result, parser)
    if result.split(header_end, 1)[1] != original.split(header_end, 1)[1]:
        raise PipelineError(
            "Owen Worship header derivation changed reviewed corpus members"
        )
    return result


def _visual_inputs() -> dict[str, bytes]:
    """Bind each historical frame to the exact retained source and reviewed TEI."""
    if len(CAPTURES) != len(LOCI):
        raise PipelineError("Owen Worship visual capture inventory differs")
    files: dict[str, bytes] = {}
    for (home, name, capture_sha), source_locus in zip(CAPTURES, LOCI, strict=True):
        directory = home / name
        capture_bytes = _read(directory / "capture.json", capture_sha)
        capture = _json(capture_bytes, f"CVW capture {name}")
        members = capture.get("files", {})
        if not isinstance(members, dict) or set(members) != {
            "frame.png",
            "compare.json",
            "session.json",
        }:
            raise PipelineError(f"Owen Worship CVW bundle members differ: {name}")
        frame = _read(directory / "frame.png", members["frame.png"])
        compare_bytes = _read(directory / "compare.json", members["compare.json"])
        session_bytes = _read(directory / "session.json", members["session.json"])
        compare = _json(compare_bytes, f"CVW compare {name}")
        left, right = compare.get("left", {}), compare.get("right", {})
        route = parse_qs(
            urlsplit(capture.get("browser_state", {}).get("route", "")).query
        )
        if (
            not frame.startswith(b"\x89PNG\r\n\x1a\n")
            or left.get("artifact", {}).get("sha256") != SOURCE_SHA
            or right.get("artifact", {}).get("sha256") != TEI_SHA
            or left.get("location", {}).get("value") != source_locus
            or capture.get("session", {}).get("candidate_sha256") != [PACKAGE_SHA]
            or capture.get("acceptance") != "not-established"
            or capture.get("page_errors") != []
            or route.get("leftArtifact") != [left.get("artifact", {}).get("id")]
            or route.get("rightArtifact") != [right.get("artifact", {}).get("id")]
            or route.get("leftLocation") != [source_locus]
            or route.get("rightLocation") != [right.get("location", {}).get("value")]
            or route.get("linked") != ["false"]
            or route.get("correspondence") != ["absent"]
        ):
            raise PipelineError(
                f"Owen Worship CVW capture differs from exact pair: {name}"
            )
        files[f"cvw/{name}/capture.json"] = capture_bytes
        files[f"cvw/{name}/frame.png"] = frame
        files[f"cvw/{name}/compare.json"] = compare_bytes
        files[f"cvw/{name}/session.json"] = session_bytes
    return files


def _preflight(root: Path) -> tuple[dict, dict, dict[str, bytes], bytes]:
    source = _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA)
    if len(source) != 841339:
        raise PipelineError("Owen Worship retained source byte count changed")
    manifest_bytes = _read(root / MANIFEST, MANIFEST_SHA)
    acquisition_bytes = _read(root / ACQUISITION)
    acquisition = _json(acquisition_bytes, "acquisition")
    member = acquisition.get("retained_files", [])
    if (
        acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
        or acquisition.get("edition_id") != IDENTITY["edition_id"]
        or len(member) != 1
        or member[0].get("path") != SOURCE.as_posix()
        or member[0].get("sha256") != SOURCE_SHA
        or member[0].get("bytes") != len(source)
        or member[0].get("scope") != SCOPE
    ):
        raise PipelineError("Owen Worship acquisition or source scope differs")
    manifest = _json(manifest_bytes, "source manifest")
    if manifest.get("work_id") != IDENTITY["work_id"]:
        raise PipelineError("Owen Worship source manifest work binding differs")
    receipt_bytes = _read(root / RECEIPT)
    receipt = _json(receipt_bytes, "ticket receipt")
    current = receipt.get("current_route_update_20260918", {})
    candidate_record = current.get("candidate", {})
    visual = current.get("cvw", {})
    if (
        candidate_record.get("package_sha256") != PACKAGE_SHA
        or candidate_record.get("tei_sha256") != TEI_SHA
        or candidate_record.get("validation", {}).get("sidecar_sha256")
        != VALIDATION_SHA
        or visual.get("visually_inspected_loci") != 12
        or visual.get("declared_loci") != 12
        or visual.get("exact_pair") is not True
    ):
        raise PipelineError(
            "Owen Worship ticket no longer binds the reviewed candidate"
        )
    audit_bytes = _read(root / AUDIT)
    audit = _json(audit_bytes, "owner audit")
    if (
        audit.get("package_status") != "nonaccepted"
        or audit.get("stored_validation_status") != "pass"
        or audit.get("stale_file_bindings") != []
    ):
        raise PipelineError(
            "Owen Worship current audit contains stale or invalid bindings"
        )
    package = CandidatePackage.load(CANDIDATE / "package")
    validation_bytes = _read(CANDIDATE / "validation.json", VALIDATION_SHA)
    validation = _json(validation_bytes, "validation")
    original = package.member_bytes("content.tei.xml")
    if (
        package.sha256 != PACKAGE_SHA
        or _sha(original) != TEI_SHA
        or package.manifest.get("source_manifest", {}).get("sha256") != MANIFEST_SHA
        or validation.get("status") != "pass"
        or validation.get("findings") != []
        or validation.get("candidate_sha256") != PACKAGE_SHA
        or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA
    ):
        raise PipelineError(
            "Owen Worship candidate or validation differs from reviewed pair"
        )
    for binding in receipt["current_route_reverification_20260921"]["bindings"]:
        path = root / binding["path"]
        if binding["path"] == SOURCE.as_posix():
            path = resolve_repo_path(root, SOURCE.as_posix())
        content = _read(path, binding["sha256"])
        if len(content) != binding["bytes"]:
            raise PipelineError(f"Owen Worship route authority size changed: {path}")
    files = {
        "report.md": _read(root / REPORT),
        "receipt.json": receipt_bytes,
        "audit.json": audit_bytes,
        "source-manifest.json": manifest_bytes,
        "validation.json": validation_bytes,
    }
    files.update(
        {f"package/{name}": package.member_bytes(name) for name in package.member_names}
    )
    files.update(_visual_inputs())
    return receipt, acquisition, files, source


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = _check_stage(root, stage)
    receipt, acquisition, files, source_bytes = _preflight(root)
    stage.mkdir()
    evidence = stage / WORK / "integration/ccel-thml-agent-handoff"
    for name, content in files.items():
        _copy(stage, evidence.relative_to(stage) / "inputs" / name, content)
    for relative in (
        WORK / "work.json",
        WORK / "state.json",
        ACQUISITION,
        TICKET,
        REPORT,
    ):
        _copy(stage, relative, _read(root / relative))
    _copy(stage, SOURCE, source_bytes)
    _copy(stage, MANIFEST, files["source-manifest.json"])
    now = datetime.now(timezone.utc)
    revision = dict(
        id="owen-worship-ccel-thml-agent-v1",
        date=now.date().isoformat(),
        note="Bind agent-accepted electronic witness; reviewed corpus members unchanged.",
    )
    original = files["package/content.tei.xml"]
    source = dict(
        source_path=SOURCE.as_posix(),
        source_sha256=SOURCE_SHA,
        source_bytes=len(source_bytes),
        source_scope=SCOPE,
        source_url=acquisition["url"],
    )
    derived = _bind_corpus_header(original, source, revision)
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Owen Worship TEI failed vendored XSD: {errors}")
    included = [
        {
            key: acquisition["retained_files"][0][key]
            for key in ("path", "bytes", "sha256", "scope")
        }
        | {"position": 1}
    ]
    scope = dict(
        kind="edition",
        declared=SCOPE,
        expected_members=[dict(path=SOURCE.as_posix(), position=1)],
        included_members=included,
        excluded_members=[],
    )
    common = dict(
        identity=IDENTITY,
        source={
            key: source[key]
            for key in ("source_path", "source_sha256", "source_bytes", "source_scope")
        },
        candidate=make_file_binding(stage, candidate),
        scope=SCOPE,
        accepted_scope=dict(kind="edition", declared=SCOPE),
        expected_members=scope["expected_members"],
        included_members=included,
        excluded_members=[],
        missing_members=[],
        unknown_members=[],
    )
    account = evidence / "source-accounting.json"
    _write(
        account,
        common
        | dict(
            source_sha256=SOURCE_SHA,
            source_bytes=len(source_bytes),
            original_accountability_sha256=_sha(
                files["package/source-accountability.json"]
            ),
        ),
    )
    bindings = {
        name: make_file_binding(stage, evidence / "inputs" / name) for name in files
    }
    member_after = derived.split(b"</ns0:teiHeader>", 1)[1]
    member_before = original.split(b"</ns0:teiHeader>", 1)[1]
    details = {
        "validation": dict(
            status="pass",
            findings=[],
            original_sidecar=bindings["validation.json"],
            derived_xsd_errors=[],
        ),
        "accounting": dict(
            source_sha256=SOURCE_SHA,
            original_member=bindings["package/source-accountability.json"],
        ),
        "fidelity": dict(
            original_tei_sha256=TEI_SHA,
            original_member_sha256=_sha(member_before),
            derived_member_sha256=_sha(member_after),
            header_only_derivation=True,
        ),
        "reproducibility": dict(
            original_package_sha256=PACKAGE_SHA,
            historical_focused_verification=receipt[
                "current_route_reverification_20260921"
            ]["focused_result"],
            no_reconstruction_performed=True,
        ),
        "schema": dict(
            vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]
        ),
        "closure": dict(
            source_manifest_sha256=MANIFEST_SHA,
            original_package_sha256=PACKAGE_SHA,
            evidence_files=bindings,
        ),
    }
    technical = dict(
        producer=dict(id="ocd-john-owen-lib053-retained-xml-to-tei"),
        checker=dict(id="ocd-john-owen-lib053-retained-xml-oracle"),
        shared_assumptions=[
            "Producer and oracle share the exact retained source and source manifest; visual inspection covers twelve selected loci."
        ],
        independent_corroboration="Source census, mutation rejection, fresh-process reproduction, stored validation, current authority rehash, and twelve exact-pair CVW loci; all corpus member bytes are unchanged by header derivation.",
    )
    command = "py -3 -m build.tools.prepare_john_owen_worship_acceptance --stage <fresh-external-root>"
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(
            path,
            common
            | dict(status="pass", command=command, exit_code=0, details=details[name]),
        )
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    review = dict(
        reviewer="historical:37c-234-twelve-locus-agent-CVW",
        reviewed_at=receipt["verification_completed_at_utc"],
        coverage=dict(
            status="partial",
            declared=SCOPE,
            reached=list(LOCI),
            inspected=list(LOCI),
            unreviewed=["All other source and candidate loci in the retained member"],
        ),
        source_quality_uncertainty=[
            "Exact print exemplar and digital transcription lineage are unknown.",
            "The CCEL header's proofreading statement has not been independently verified.",
            "Rights remain unresolved.",
        ],
        discrepancies=[],
        unreviewed_residuals=[
            "Twelve selected loci were visually inspected; no whole-work proofreading or page-image collation was performed.",
            "CVW panes were unlinked; no alignment was inferred.",
        ],
    )
    _write(
        evidence / "review.json",
        common
        | review
        | dict(
            historical_review=bindings["report.md"],
            historical_receipt=bindings["receipt.json"],
            current_audit=bindings["audit.json"],
            capture_bindings={
                name: bindings[f"cvw/{name}/capture.json"]
                for _home, name, _sha256 in CAPTURES
            },
            no_new_pixel_review=True,
            review_basis="The historical twelve-locus review binds the identical retained source and original TEI; all corpus member bytes in the derived master are unchanged.",
        ),
    )
    decision = dict(
        source_local_disposition="Evidence-backed agent acceptance of the exact retained CCEL ThML electronic witness only.",
        blockers=[],
        agent_assessment=dict(
            status="accepted",
            actor="agent:john-owen-worship-ccel-thml-review",
            assessed_at=now.isoformat().replace("+00:00", "Z"),
            supported_scope=SCOPE,
            unassessed_stronger_claims=[
                "human acceptance",
                "rights clearance",
                "print exemplar and digital lineage",
                "whole-work proofreading",
                "page-image collation",
                "release",
                "publication",
            ],
            unresolved_claims=[],
        ),
        human_decision=dict(status="not-recorded"),
    )
    record = build_acceptance_record(
        stage,
        identity=IDENTITY,
        candidate_path=candidate,
        source_accounting_path=account,
        scope=scope,
        technical=technical,
        review=review | dict(report_path=evidence / "review.json"),
        representation_revision=revision,
        decision=decision,
    )
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(ROOT, args.stage))


if __name__ == "__main__":
    main()
