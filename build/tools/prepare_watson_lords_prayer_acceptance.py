"""Prepare an exact electronic-witness acceptance handoff for Watson's Lord's Prayer."""

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
WORK = Path("library/works/watson-lords-prayer")
EDITION = (
    WORK
    / "forms/watson-lords-prayer-route-source-form/editions/watson-lords-prayer-retained-thml-route"
)
ACQUISITION = EDITION / "acquisitions/watson-lords-prayer-retained-source.json"
IDENTITY = dict(
    work_id="watson-lords-prayer",
    textual_form_id="watson-lords-prayer-route-source-form",
    edition_id="watson-lords-prayer-retained-thml-route",
    acquisition_id="watson-lords-prayer-retained-source",
)
SOURCE = Path("raw/ccel/watson/prayer.xml")
MANIFEST = Path(
    "sources/structured-text/watson-lords-prayer/watson-lords-prayer.source-manifest.json"
)
TICKET = Path(
    "plans/2026-08-31-sample-first-library-verification/issues/37c-317-watson-lords-prayer.md"
)
REPORT = Path(
    "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-317.md"
)
RECEIPT = REPORT.with_name("37c-317-receipt.json")
CANDIDATE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/37c-317-watson-20260924-current-manifest"
)
PRIOR = Path(
    "D:/Library/Open Christian Data/candidate-reviews/37c-317-watson-20260920-parent"
)
CVW = Path(
    "D:/Library/Open Christian Data/candidate-reviews/37c-317-watson-20260920-cvw-v1"
)
SOURCE_SHA = "9f14813ac77f4a44ce08b63ec6343ec8f59f006df7f80f11fcf87926730468ca"
MANIFEST_SHA = "d5049a3b573c0586fe668033c74269c8137f57181c901e0ea837ac2e59d41b5b"
PACKAGE_SHA = "cead97460d0881f0a94dfd366521a9fc668e24398a56ba10183e5a10b90b8273"
PRIOR_SHA = "e180c8734868421a5087df0c20c84fc3fd5846ecb1cfa5312111e80508a5e75d"
TEI_SHA = "6c398e9fbfec2d906266c06ccd3d73d979f0cecf80e4f339a59b8af78c5e072d"
VALIDATION_SHA = "48d809a8a0e25a59997ff70982ec919fa6d5ea0cd861efb64b7509103fd07cdc"
REPORT_SHA = "fe783939cc15a65618a341daffac9ba38812f3728107578a963a783e701605e8"
SESSION_ID = "51c6fe981ac14960bc25b613f929b4a9"
NATIVE_IDS = tuple("i ii iii iv v vi vii viii ix x".split())
PROOFS = (
    "validation",
    "accounting",
    "fidelity",
    "reproducibility",
    "schema",
    "closure",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"required Watson Prayer evidence missing: {path}") from exc
    if expected and _sha(content) != expected:
        raise PipelineError(f"Watson Prayer evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Watson Prayer JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Watson Prayer JSON is not an object: {label}")
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


def _bind_header(original: bytes, acquisition: dict, revision: dict) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    tree = etree.fromstring(original, parser)
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    headers = tree.xpath("./t:teiHeader", namespaces=ns)
    if len(headers) != 1 or headers[0].xpath("./t:revisionDesc", namespaces=ns):
        raise PipelineError("Watson Prayer header has an unexpected revision layout")
    bibls = headers[0].xpath("./t:fileDesc/t:sourceDesc/t:bibl", namespaces=ns)
    if len(bibls) != 1:
        raise PipelineError("Watson Prayer header needs one source bibl")
    bibl = bibls[0]
    facts = {
        node.get("type"): "".join(node.itertext()).strip()
        for node in bibl.xpath("./t:idno", namespaces=ns)
    }
    expected = dict(IDENTITY) | {
        "sha256": SOURCE_SHA,
        "source_sha256": SOURCE_SHA,
        "source_bytes": "1376060",
    }
    if (
        any(facts.get(key) != value for key, value in expected.items())
        or "representation_revision" in facts
        or bibl.xpath("./t:ptr/@target", namespaces=ns) != [acquisition["url"]]
        or bibl.xpath("./t:note[@type='source-location']/text()", namespaces=ns)
        != [SOURCE.as_posix()]
        or bibl.xpath("./t:note[@type='source-scope']/text()", namespaces=ns)
        != [acquisition["source_scope"]]
    ):
        raise PipelineError("Watson Prayer existing header differs from bound source")
    if original.count(b"</bibl>") != 1 or original.count(b"</teiHeader>") != 1:
        raise PipelineError("Watson Prayer header boundaries are not unique")
    identity_note = (
        '<idno type="representation_revision">' + escape(revision["id"]) + "</idno>"
    ).encode()
    change = (
        '<revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xml:id='
        + quoteattr(revision["id"])
        + " when="
        + quoteattr(revision["date"])
        + ">"
        + escape(revision["note"])
        + "</change></revisionDesc>"
    ).encode()
    derived = original.replace(b"</bibl>", identity_note + b"</bibl>", 1)
    derived = derived.replace(b"</teiHeader>", change + b"</teiHeader>", 1)
    etree.fromstring(derived, parser)
    if derived.replace(identity_note, b"", 1).replace(change, b"", 1) != original:
        raise PipelineError("Watson Prayer header derivation changed reviewed bytes")
    return derived


def _preflight(root: Path) -> tuple[dict, dict, dict[str, bytes], bytes]:
    source = _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA)
    if len(source) != 1_376_060:
        raise PipelineError("Watson Prayer source byte count changed")
    manifest_bytes = _read(root / MANIFEST, MANIFEST_SHA)
    manifest = _json(manifest_bytes, "source manifest")
    acquisition = _json(_read(root / ACQUISITION), "acquisition")
    work = _json(_read(root / WORK / "work.json"), "work")
    members = acquisition.get("retained_files", [])
    units = acquisition.get("source_selection", {}).get("units", [])
    if (
        work.get("work_id") != IDENTITY["work_id"]
        or manifest.get("work_id") != IDENTITY["work_id"]
        or manifest.get("source_id")
        != "37c-317-watson-lords-prayer-retained-thml-route"
        or acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
        or acquisition.get("edition_id") != IDENTITY["edition_id"]
        or len(members) != 1
        or any(
            members[0].get(k) != v
            for k, v in (
                ("path", SOURCE.as_posix()),
                ("bytes", len(source)),
                ("sha256", SOURCE_SHA),
            )
        )
        or tuple(unit.get("native_id") for unit in units) != NATIVE_IDS
    ):
        raise PipelineError("Watson Prayer source and route identity changed")
    receipt_bytes = _read(root / RECEIPT)
    receipt = _json(receipt_bytes, "ticket receipt")
    current = receipt.get("current_manifest_reverification", {})
    technical = receipt.get("technical_completion", {})
    cvw = technical.get("cvw", {})
    if (
        receipt.get("work_id") != IDENTITY["work_id"]
        or current.get("source_manifest", {}).get("sha256") != MANIFEST_SHA
        or current.get("candidate", {}).get("package_sha256") != PACKAGE_SHA
        or current.get("candidate", {}).get("tei_sha256") != TEI_SHA
        or current.get("candidate", {}).get("status") != "nonaccepted"
        or current.get("validation", {}).get("sidecar_sha256") != VALIDATION_SHA
        or current.get("validation", {}).get("report_sha256") != REPORT_SHA
        or current.get("validation", {}).get("status") != "pass"
        or current.get("validation", {}).get("findings") != []
        or current.get("fresh_process_reproduction", {}).get(
            "path_set_and_all_bytes_match"
        )
        is not True
        or technical.get("candidate", {}).get("package_sha256") != PRIOR_SHA
        or cvw.get("session_id") != SESSION_ID
        or cvw.get("status") != "bounded_visual_review_complete"
    ):
        raise PipelineError(
            "Watson Prayer receipt no longer binds current and reviewed pairs"
        )
    ticket = _read(root / TICKET)
    report = _read(root / REPORT)
    for anchor in (SOURCE_SHA, MANIFEST_SHA, PACKAGE_SHA, TEI_SHA, SESSION_ID):
        if anchor.encode() not in ticket + report:
            raise PipelineError(f"Watson Prayer review lacks evidence anchor: {anchor}")
    package = CandidatePackage.load(CANDIDATE / "package")
    prior = CandidatePackage.load(PRIOR / "package")
    original = package.member_bytes("content.tei.xml")
    if (
        package.sha256 != PACKAGE_SHA
        or prior.sha256 != PRIOR_SHA
        or _sha(original) != TEI_SHA
        or prior.member_bytes("content.tei.xml") != original
        or package.manifest.get("status") != "nonaccepted"
        or package.manifest.get("source_manifest", {}).get("sha256") != MANIFEST_SHA
    ):
        raise PipelineError("Watson Prayer current and reviewed TEI differ")
    account = _json(
        package.member_bytes("source-accountability.json"), "source accountability"
    )
    if (
        tuple(item.get("native_id") for item in account.get("source_envelope", []))
        != NATIVE_IDS
    ):
        raise PipelineError("Watson Prayer source envelope changed")
    validation_bytes = _read(CANDIDATE / "validation.json", VALIDATION_SHA)
    validation = _json(validation_bytes, "validation")
    if (
        validation.get("status") != "pass"
        or validation.get("findings") != []
        or validation.get("candidate_sha256") != PACKAGE_SHA
        or validation.get("source_manifest_sha256") != MANIFEST_SHA
        or validation.get("report_sha256") != REPORT_SHA
        or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA
    ):
        raise PipelineError("Watson Prayer validation differs from reviewed route")
    files = {
        "ticket.md": ticket,
        "report.md": report,
        "receipt.json": receipt_bytes,
        "source-manifest.json": manifest_bytes,
        "validation.json": validation_bytes,
        "prior-package-manifest.json": _read(
            PRIOR / "package/manifest.json", PRIOR_SHA
        ),
    }
    files.update(
        {f"package/{name}": package.member_bytes(name) for name in package.member_names}
    )
    frames = cvw.get("captures", [])
    if len(frames) != 3 or {item.get("bundle") for item in frames} != {
        "opening",
        "middle",
        "ending",
    }:
        raise PipelineError("Watson Prayer review must bind three distinct captures")
    for item in frames:
        name = item["bundle"]
        directory = CVW / name
        capture_bytes = _read(directory / "capture.json", item["capture_sha256"])
        capture = _json(capture_bytes, f"CVW capture {name}")
        route = capture.get("browser_state", {}).get("route", "")
        if (
            capture.get("session", {}).get("candidate_sha256") != [PRIOR_SHA]
            or capture.get("session", {}).get("session_id") != SESSION_ID
            or f"leftLocation={item['source_location']}" not in route
            or f"rightLocation={item['tei_location']}" not in route
            or "linked=false&correspondence=absent" not in route
            or capture.get("files", {}).get("frame.png") != item["frame_sha256"]
            or capture.get("acceptance") != "not-established"
            or capture.get("page_errors") != []
        ):
            raise PipelineError(f"Watson Prayer visual capture differs: {name}")
        compare_sha = capture.get("files", {}).get("compare.json")
        if not isinstance(compare_sha, str) or len(compare_sha) != 64:
            raise PipelineError(f"Watson Prayer visual compare binding missing: {name}")
        compare = _json(
            _read(directory / "compare.json", compare_sha), f"CVW compare {name}"
        )
        left, right = compare.get("left"), compare.get("right")
        route_fields = parse_qs(urlsplit(route).query)
        if (
            not isinstance(left, dict)
            or not isinstance(right, dict)
            or left.get("artifact", {}).get("sha256") != SOURCE_SHA
            or right.get("artifact", {}).get("sha256") != TEI_SHA
            or left.get("location", {}).get("value") != item["source_location"]
            or right.get("location", {}).get("value") != item["tei_location"]
            or route_fields.get("leftArtifact") != [left.get("artifact", {}).get("id")]
            or route_fields.get("rightArtifact")
            != [right.get("artifact", {}).get("id")]
            or route_fields.get("leftVersion")
            != [left.get("artifact", {}).get("version")]
            or route_fields.get("rightVersion")
            != [right.get("artifact", {}).get("version")]
        ):
            raise PipelineError(
                f"Watson Prayer visual compare differs from exact pair: {name}"
            )
        for member_name, digest in capture["files"].items():
            files[f"cvw/{name}/{member_name}"] = _read(directory / member_name, digest)
        files[f"cvw/{name}/capture.json"] = capture_bytes
    return receipt, acquisition, files, source


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = stage.absolute()
    if stage.exists():
        raise PipelineError(f"Watson Prayer staging root must be fresh: {stage}")
    resolved = stage.resolve()
    for area in (root, CANDIDATE.resolve(), PRIOR.resolve(), CVW.resolve()):
        if resolved == area or area in resolved.parents or resolved in area.parents:
            raise PipelineError(
                "Watson Prayer stage overlaps a protected input or checkout"
            )
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Watson Prayer stage parent must be an ordinary directory")
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
        RECEIPT,
    ):
        _copy(stage, relative, _read(root / relative))
    _copy(stage, SOURCE, source_bytes)
    _copy(stage, MANIFEST, files["source-manifest.json"])
    original = files["package/content.tei.xml"]
    now = datetime.now(timezone.utc)
    revision = dict(
        id="watson-lords-prayer-retained-thml-electronic-witness-v1",
        date=now.date().isoformat(),
        note="Bind the exact retained CCEL electronic witness; work boundary and print identity remain unresolved.",
    )
    derived = _bind_header(original, acquisition, revision)
    original_text = original.split(b"</teiHeader>", 1)[1]
    if original_text != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Watson Prayer derivation changed reviewed TEI text")
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Watson Prayer TEI failed XSD: {errors}")
    member = acquisition["retained_files"][0]
    included = [
        {key: member[key] for key in ("path", "bytes", "sha256", "scope")}
        | {"position": 1}
    ]
    scope_text = acquisition["source_scope"]
    scope = dict(
        kind="edition",
        declared=scope_text,
        expected_members=[dict(path=SOURCE.as_posix(), position=1)],
        included_members=included,
        excluded_members=[],
    )
    source = dict(
        source_path=SOURCE.as_posix(),
        source_sha256=SOURCE_SHA,
        source_bytes=len(source_bytes),
        source_scope=scope_text,
    )
    common = dict(
        identity=IDENTITY,
        source=source,
        candidate=make_file_binding(stage, candidate),
        scope=scope_text,
        accepted_scope=dict(kind="edition", declared=scope_text),
        expected_members=scope["expected_members"],
        included_members=included,
        excluded_members=[],
        missing_members=[],
        unknown_members=[],
    )
    account_path = evidence / "source-accounting.json"
    account_sha = _sha(files["package/source-accountability.json"])
    _write(
        account_path,
        common
        | dict(
            source_sha256=SOURCE_SHA,
            source_bytes=len(source_bytes),
            native_carriers=list(NATIVE_IDS),
            original_accountability_sha256=account_sha,
        ),
    )
    bindings = {
        name: make_file_binding(stage, evidence / "inputs" / name) for name in files
    }
    details = {
        "validation": dict(
            status="pass",
            findings=[],
            sidecar=bindings["validation.json"],
            validation_report_sha256=REPORT_SHA,
        ),
        "accounting": dict(
            source_sha256=SOURCE_SHA,
            original_accountability_sha256=account_sha,
            original_member=bindings["package/source-accountability.json"],
            native_carriers=list(NATIVE_IDS),
        ),
        "fidelity": dict(
            original_tei_sha256=TEI_SHA,
            original_text_sha256=_sha(original_text),
            derived_text_sha256=_sha(original_text),
            header_only_derivation=True,
        ),
        "reproducibility": dict(
            original_package_sha256=PACKAGE_SHA,
            current_fresh_process=receipt["current_manifest_reverification"][
                "fresh_process_reproduction"
            ],
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
        producer=dict(id="ocd-watson-lords-prayer-selected-thml-route"),
        checker=dict(id="ocd-watson-lords-prayer-selected-thml-independent-check"),
        shared_assumptions=[
            "Producer and oracle share retained source bytes and SourceManifest; visual review sampled only three loci."
        ],
        independent_corroboration="Current oracle validation, source accounting, mutation checks, fresh-process byte reproduction, and prior three-locus CVW review bound through identical TEI text bytes.",
    )
    command = "py -3 -m build.tools.prepare_watson_lords_prayer_acceptance --stage <fresh-external-root>"
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(
            path,
            common
            | dict(status="pass", command=command, exit_code=0, details=details[name]),
        )
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    loci = [
        f"{item['bundle']}: {item['source_location']} -> {item['tei_location']}"
        for item in receipt["technical_completion"]["cvw"]["captures"]
    ]
    reviewed_at = max(
        _json(files[f"cvw/{name}/capture.json"], "capture")["captured_at"]
        for name in ("opening", "middle", "ending")
    ).replace("+00:00", "Z")
    review = dict(
        reviewer="historical:37c-317-three-locus-agent-CVW",
        reviewed_at=reviewed_at,
        coverage=dict(
            status="partial",
            declared=scope_text,
            reached=loci,
            inspected=loci,
            unreviewed=["All other locations in the retained member"],
        ),
        source_quality_uncertainty=[
            "Print witness and transcription lineage remain unresolved.",
            "Containing-work and constituent-part boundaries remain unresolved.",
        ],
        discrepancies=[],
        unreviewed_residuals=[
            "Three sampled loci do not establish exhaustive proofreading or print collation.",
            "CVW panes were unlinked and correspondence was absent.",
        ],
    )
    _write(
        evidence / "review.json",
        common
        | review
        | dict(
            capture_bindings={
                name: bindings[f"cvw/{name}/capture.json"]
                for name in ("opening", "middle", "ending")
            },
            no_new_pixel_review=True,
            review_basis="Prior CVW captures bind the same source SHA and byte-identical TEI text; current SourceManifest and package differ.",
        ),
    )
    decision = dict(
        source_local_disposition="Agent acceptance of this complete retained CCEL ThML electronic witness only.",
        blockers=[],
        agent_assessment=dict(
            status="accepted",
            actor="agent:watson-lords-prayer-electronic-witness-review",
            assessed_at=now.isoformat().replace("+00:00", "Z"),
            supported_scope=scope_text,
            unassessed_stronger_claims=[
                "containing-work and part identity",
                "print edition identity",
                "human acceptance",
                "rights clearance",
                "exhaustive visual review",
                "release",
                "publication",
            ],
            unresolved_claims=[
                "The electronic source describes a third volume; semantic work and part boundaries are not adopted from this route."
            ],
        ),
        human_decision=dict(status="not-recorded"),
    )
    record = build_acceptance_record(
        stage,
        identity=IDENTITY,
        candidate_path=candidate,
        source_accounting_path=account_path,
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
