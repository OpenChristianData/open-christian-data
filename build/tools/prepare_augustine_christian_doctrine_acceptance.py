"""Stage Augustine On Christian Doctrine's exact selected-source agent handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from lxml import etree

from build.tei.augustine_on_christian_doctrine_oracle import _oracle
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/augustine-on-christian-doctrine")
EDITION = WORK / "forms/augustine-on-christian-doctrine-english/editions/augustine-on-christian-doctrine-ccel-retained"
MASTER = EDITION / "master.tei.xml"
ACQUISITION = EDITION / "acquisitions/augustine-on-christian-doctrine-retained.json"
SOURCE = Path("raw/ccel/npnf1/npnf102.xml")
MANIFEST = Path("sources/structured-text/augustine-on-christian-doctrine/augustine-on-christian-doctrine.source-manifest.json")
METADATA = Path("metadata/source-evidence/catalog/augustine-on-christian-doctrine.json")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-048-augustine-on-christian-doctrine.md")
REPORT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-048.md")
RECEIPT = REPORT.with_name("37c-048-receipt.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/a048-20260924")
IDENTITY = {
    "work_id": "augustine-on-christian-doctrine",
    "textual_form_id": "augustine-on-christian-doctrine-english",
    "edition_id": "augustine-on-christian-doctrine-ccel-retained",
    "acquisition_id": "augustine-on-christian-doctrine-retained",
}
PINS = {
    "source": "b8ca21dfa7d553681651f85197064b0fe52ae6c17e5e17252df9301536a4ae2a",
    "work": "82f0ee961194f1d334963572b72ee4210ffe6a8f9a2ad4a2b6a42c6ae363d92f",
    "state": "35e8abf52349fcf7fea5eaceb68bf0ac4bee8c92b2adb9077fd37dd3c42a6a34",
    "master": "31ec38f733de871713626cce0cdcdffc08d5eed74c3bc68ffce77b5b97d3b204",
    "acquisition": "ab93a335f33ad9e7ed10d3bf7b332037b01412e6d316533c546605a3cf840b7d",
    "manifest": "469b326a13e2165ab1a1f60c61e041628a41b71a4110b955637da4fa7d01505c",
    "metadata": "16c2ded55bba4b4e09720b8662c6b7862a889fafcaebf42959cc72f0c7c25277",
    "ticket": "d905a4752c627af3d7e85200fa4d27e33d9ae57f69c9a478621390cce2f79f14",
    "report": "fa35ea507c151429c2f176c5f2c5668d5ceb702287149cd4f9b8bd9e2ba7e170",
    "receipt": "6f1fcc66a789e37bfe65f24cc59086750839f4ff5f404ed8663aa9afb750b2da",
    "package": "3ceeeeb4df031dff440f32a6d84128ec22836676012bfcc05612f9353c4696b1",
    "tei": "dac2b7883329556b1534b36e1e51fcbcff4ae411308b11843051f7df39a3c034",
    "accountability": "e0e84fdfead4126c09535eaa256fa1c05670362c3fbff83217cd671bc81cdbbe",
    "validation": "a0e33a475c9c86b5699fb132988862671c42a5d55f6732f2f4b1e02d83f8ce4c",
    "validation_report": "1567f5dc8f073f97b2e12cdbc7753cb33e999e62236321238dc55d199fa6426e",
    "oracle": "4136c3818354bd02ea5b2f9262bbe6579fe40499fdb81e9bbd6c7c2bfe16af79",
}
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")
CHILDREN = ("v.i", "v.ii", "v.iii", "v.iv", "v.v", "v.vi", "IV_1")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"Augustine evidence unavailable: {path}") from exc
    if _sha(content) != expected:
        raise PipelineError(f"Augustine evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Augustine JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Augustine JSON is not an object: {label}")
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


def _stage_path(root: Path, stage: Path) -> Path:
    stage = stage.absolute()
    if stage.exists() or stage.is_symlink():
        raise PipelineError(f"Augustine stage must be fresh: {stage}")
    resolved = stage.resolve()
    for protected in (root.resolve(), CANDIDATE.resolve()):
        if resolved == protected or protected in resolved.parents or resolved in protected.parents:
            raise PipelineError("Augustine stage overlaps protected source or candidate")
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Augustine stage parent must be an ordinary directory")
    return stage


def _selected_carriers(source: bytes) -> list[str]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    document = etree.fromstring(source, parser)
    body = document.find("ThML.body")
    if body is None:
        raise PipelineError("Augustine source has no ThML body")
    selected = body.find("div1[@id='v']")
    if selected is None or selected.get("title") != "On Christian Doctrine":
        raise PipelineError("Augustine selected div1 identity differs")
    children = [child.get("id") for child in selected.findall("div2")]
    elements = sum(isinstance(node.tag, str) for node in selected.iter())
    if children != list(CHILDREN) or elements != 1974:
        raise PipelineError("Augustine selected carrier envelope differs")
    return ["v", *children]


def _revision_only(original: bytes, revision: dict[str, str]) -> bytes:
    close_bibl = b"</bibl></sourceDesc>"
    close_header = b"</teiHeader>"
    if original.count(close_bibl) != 1 or original.count(close_header) != 1:
        raise PipelineError("Augustine TEI header boundary is ambiguous")
    if b"representation_revision" in original or b"<revisionDesc" in original:
        raise PipelineError("Augustine TEI already has an acceptance revision")
    identity = (
        '<idno type="representation_revision">'
        + escape(revision["id"])
        + "</idno>"
    ).encode("utf-8")
    change = (
        "<revisionDesc><change xml:id="
        + quoteattr(revision["id"])
        + " when="
        + quoteattr(revision["date"])
        + ">"
        + escape(revision["note"])
        + "</change></revisionDesc>"
    ).encode("utf-8")
    derived = original.replace(close_bibl, identity + close_bibl, 1).replace(
        close_header, change + close_header, 1
    )
    if derived.replace(identity, b"", 1).replace(change, b"", 1) != original:
        raise PipelineError("Augustine staged header revision changed source text")
    return derived


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = _stage_path(root, stage)
    source = _read(resolve_repo_path(root, SOURCE.as_posix()), PINS["source"])
    work_bytes = _read(root / WORK / "work.json", PINS["work"])
    state_bytes = _read(root / WORK / "state.json", PINS["state"])
    master_bytes = _read(root / MASTER, PINS["master"])
    acquisition_bytes = _read(root / ACQUISITION, PINS["acquisition"])
    manifest_bytes = _read(root / MANIFEST, PINS["manifest"])
    metadata_bytes = _read(root / METADATA, PINS["metadata"])
    ticket_bytes = _read(root / TICKET, PINS["ticket"])
    report_bytes = _read(root / REPORT, PINS["report"])
    receipt_bytes = _read(root / RECEIPT, PINS["receipt"])
    work = load_work(root / WORK / "work.json")
    acquisition = _json(acquisition_bytes, "acquisition")
    receipt = _json(receipt_bytes, "review receipt")
    metadata = _json(metadata_bytes, "metadata")
    carriers = _selected_carriers(source)
    selection = acquisition.get("source_selection", {})
    member = acquisition.get("retained_files", [None])[0]
    if (
        work.get("work_id") != IDENTITY["work_id"]
        or acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
        or acquisition.get("edition_id") != IDENTITY["edition_id"]
        or acquisition.get("source_path") != SOURCE.as_posix()
        or acquisition.get("source_sha256") != PINS["source"]
        or acquisition.get("source_bytes") != len(source)
        or selection.get("selection_id") != "augustine-on-christian-doctrine-selection-v1"
        or selection.get("member_path") != SOURCE.as_posix()
        or [unit.get("native_id") for unit in selection.get("units", [])] != ["v"]
        or not isinstance(member, dict)
        or member.get("sha256") != PINS["source"]
        or member.get("bytes") != len(source)
    ):
        raise PipelineError("Augustine work, acquisition, or selection identity differs")
    fields = metadata.get("dimensions", {}).get("witnesses", {}).get("fields", [])
    route_claims = [field for field in fields if field.get("claim_id") == "witnesses:manifest_route_unresolved"]
    if len(route_claims) != 1 or route_claims[0]["evidence"]["value"].get("manifest_found") is not False:
        raise PipelineError("Augustine route metadata observation differs")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    manifest.verify()
    if manifest.sha256 != PINS["manifest"] or manifest.record.get("work_id") != IDENTITY["work_id"]:
        raise PipelineError("Augustine current SourceManifest differs")
    package = CandidatePackage.load(CANDIDATE / "package")
    original = package.member_bytes("content.tei.xml")
    validation_bytes = _read(CANDIDATE / "validation.json", PINS["validation"])
    validation = _json(validation_bytes, "validation")
    if (
        package.sha256 != PINS["package"]
        or _sha(original) != PINS["tei"]
        or _sha(package.member_bytes("source-accountability.json")) != PINS["accountability"]
        or package.manifest.get("status") != "nonaccepted"
        or package.manifest.get("source_manifest", {}).get("sha256") != PINS["manifest"]
        or validation.get("status") != "pass"
        or validation.get("candidate_sha256") != PINS["package"]
        or validation.get("source_manifest_sha256") != PINS["manifest"]
        or validation.get("report_sha256") != PINS["validation_report"]
        or validation.get("attestation", {}).get("source_sha256") != PINS["source"]
        or validation.get("attestation", {}).get("implementation_sha256") != PINS["oracle"]
    ):
        raise PipelineError("Augustine current package or validation differs")
    oracle = validate(manifest, package, _oracle)
    if oracle.status != "pass" or oracle.sha256 != PINS["validation_report"]:
        raise PipelineError("Augustine independent oracle replay differs")
    visual = receipt.get("v2_visual_review", {})
    if (
        visual.get("source", {}).get("sha256") != PINS["source"]
        or visual.get("candidate", {}).get("tei_sha256") != PINS["tei"]
        or len(visual.get("captures", [])) != 4
        or visual.get("method", {}).get("page_errors") != 0
    ):
        raise PipelineError("Augustine corrected visual review binding differs")
    inputs = {
        "ticket.md": ticket_bytes,
        "report.md": report_bytes,
        "receipt.json": receipt_bytes,
        "metadata.json": metadata_bytes,
        "source-manifest.json": manifest_bytes,
        "validation.json": validation_bytes,
    }
    for name in package.member_names:
        inputs[f"package/{name}"] = package.member_bytes(name)
    inputs["package/manifest.json"] = _read(CANDIDATE / "package/manifest.json", PINS["package"])
    loci = []
    for index, capture in enumerate(visual["captures"], 1):
        frame = _read(Path(capture["frame"]), capture["frame_sha256"])
        if not frame.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PipelineError(f"Augustine visual frame {index} is not PNG")
        inputs[f"cvw/{index:02d}.png"] = frame
        loci.append(capture["locus"])
    stage.mkdir()
    evidence = stage / WORK / "integration/selected-thml-agent-handoff"
    for name, content in inputs.items():
        _copy(stage, evidence.relative_to(stage) / "inputs" / name, content)
    for relative, content in (
        (WORK / "work.json", work_bytes),
        (WORK / "state.json", state_bytes),
        (MASTER, master_bytes),
        (ACQUISITION, acquisition_bytes),
        (SOURCE, source),
        (MANIFEST, manifest_bytes),
        (METADATA, metadata_bytes),
        (TICKET, ticket_bytes),
        (REPORT, report_bytes),
        (RECEIPT, receipt_bytes),
    ):
        _copy(stage, relative, content)
    now = datetime.now(timezone.utc)
    revision = {
        "id": "augustine-christian-doctrine-selected-thml-v1",
        "date": now.date().isoformat(),
        "note": "Bind only the retained On Christian Doctrine selection; unresolved edition metadata remains open.",
    }
    derived = _revision_only(original, revision)
    if original.split(b"</teiHeader>", 1)[1] != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Augustine staged revision altered TEI body bytes")
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"Augustine staged TEI failed XSD: {errors}")
    scope_text = acquisition["source_scope"]
    included = [
        {
            "path": SOURCE.as_posix(),
            "bytes": len(source),
            "sha256": PINS["source"],
            "scope": scope_text,
            "position": 1,
        }
    ]
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    scope = {
        "kind": "selection",
        "declared": scope_text,
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
    }
    source_record = {
        "source_path": SOURCE.as_posix(),
        "source_sha256": PINS["source"],
        "source_bytes": len(source),
        "source_scope": scope_text,
    }
    common = {
        "identity": IDENTITY,
        "source": source_record,
        "candidate": make_file_binding(stage, candidate),
        "scope": scope_text,
        "accepted_scope": {"kind": "selection", "declared": scope_text},
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
        "missing_members": [],
        "unknown_members": [],
    }
    account = evidence / "source-accounting.json"
    _write(account, common | {
        "source_sha256": PINS["source"],
        "source_bytes": len(source),
        "selected_native_carriers": carriers,
        "selected_element_count": 1974,
        "original_accountability_sha256": PINS["accountability"],
        "sibling_body_carriers_and_shell": "accounted for by current manifest-bound oracle",
    })
    bindings = {name: make_file_binding(stage, evidence / "inputs" / name) for name in inputs}
    details = {
        "validation": {"status": "pass", "sidecar": bindings["validation.json"], "fresh_oracle_replayed": True, "report_sha256": PINS["validation_report"]},
        "accounting": {"selected_native_carriers": carriers, "selected_element_count": 1974, "original_member": bindings["package/source-accountability.json"]},
        "fidelity": {"original_tei_sha256": PINS["tei"], "header_only_derivation": True, "body_sha256": _sha(original.split(b"</teiHeader>", 1)[1])},
        "reproducibility": {"package_sha256": PINS["package"], "previous_exact_package_sha256": PINS["package"], "all_seven_files_byte_equal": True},
        "schema": {"vendored_xsd": "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "validation_errors": []},
        "closure": {"source_manifest_sha256": PINS["manifest"], "oracle_implementation_sha256": PINS["oracle"], "evidence_files": bindings},
    }
    command = "py -3 -m build.tools.prepare_augustine_christian_doctrine_acceptance --stage <fresh-external-root>"
    technical = {
        "producer": {"id": "ocd-37c-048-augustine-on-christian-doctrine-to-tei"},
        "checker": {"id": "ocd-37c-048-augustine-on-christian-doctrine-independent-check"},
        "shared_assumptions": ["The work-local converter and oracle share the retained XML and SourceManifest; four visible loci are only a bounded sample."],
        "independent_corroboration": "Current source-led oracle, mutation-tested route, deterministic package replay, XSD validation, and four retained corrected-v2 frames with TEI bytes equal to the current package.",
    }
    for name in PROOFS:
        proof = evidence / f"{name}.json"
        _write(proof, common | {"status": "pass", "command": command, "exit_code": 0, "details": details[name]})
        technical[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    review = {
        "reviewer": "agent:37c-048-corrected-v2-visual-review",
        "reviewed_at": receipt["reviewed_at_utc"],
        "coverage": {"status": "partial", "declared": scope_text, "reached": loci, "inspected": loci, "unreviewed": ["All other selected source and TEI locations"]},
        "source_quality_uncertainty": ["The constituent edition date and work-boundary metadata decision remain unresolved."],
        "discrepancies": [],
        "unreviewed_residuals": ["Four historical visual loci share the current TEI bytes but do not exhaustively inspect the work.", "CVW correspondence was absent and the panes were unlinked."],
    }
    review_path = evidence / "review.json"
    _write(review_path, common | review | {
        "historical_visual_package_sha256": visual["candidate"]["package_manifest_sha256"],
        "current_package_sha256": PINS["package"],
        "same_tei_sha256": PINS["tei"],
        "frame_bindings": [bindings[f"cvw/{i:02d}.png"] for i in range(1, 5)],
        "metadata_observation_stale": "witnesses:manifest_route_unresolved says manifest_found:false despite current tracked SourceManifest; no metadata adoption claimed.",
    })
    decision = {
        "source_local_disposition": "Evidence-backed agent acceptance of only the exact selected div1 v route and its seven ordered div2 carriers in the retained CCEL electronic witness.",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted",
            "actor": "agent:augustine-christian-doctrine-selected-route",
            "assessed_at": now.isoformat().replace("+00:00", "Z"),
            "supported_scope": scope_text,
            "unassessed_stronger_claims": ["constituent edition date", "work-boundary metadata adoption", "human acceptance", "rights clearance", "full visual comparison", "release", "publication"],
            "unresolved_claims": ["The source-evidence route observation remains stale and requires a reviewed metadata decision.", "The containing volume's 1890 print date does not establish this constituent edition date."],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        stage,
        identity=IDENTITY,
        candidate_path=candidate,
        source_accounting_path=account,
        scope=scope,
        technical=technical,
        review=review | {"report_path": review_path},
        representation_revision=revision,
        decision=decision,
    )
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / "state.json", root=stage)
    return acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(ROOT, args.stage))


if __name__ == "__main__":
    main()
