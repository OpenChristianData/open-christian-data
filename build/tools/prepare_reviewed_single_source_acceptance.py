"""Prepare a pinned, single-member electronic witness for guarded acceptance.

The LIB-069 route is reusable: another source in this family needs a reviewed
``Witness`` declaration, not a new acceptance implementation.  Historical print identity and rights
remain outside this electronic-witness decision.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape, quoteattr

from lxml import etree

from build.tei.gutenberg_catechisms_oracle import _oracle
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = Path("plans/2026-08-31-sample-first-library-verification")
REVIEW = CAMPAIGN / "artifacts/2026-09-08-ticket37/reviews"
MEASUREMENT = CAMPAIGN / "artifacts/2026-09-09-detection-measurement"
CANDIDATES = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "ticket37-detection-measurement-20260909/lib069-repaired-20260909-standard-v1"
)
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


@dataclass(frozen=True)
class Witness:
    work_id: str
    ticket: str
    source: str
    source_sha: str
    manifest_sha: str
    package_sha: str
    tei_sha: str
    validation_sha: str
    report_sha: str
    form_title: str
    edition_title: str
    url: str
    scope: str
    visual_points: tuple[str, ...]
    visual_hashes: tuple[str, str, str, str]
    evidence_hashes: tuple[str, str, str]
    original_hashes: tuple[str, str]
    uncertainty: tuple[str, ...]


WITNESSES = {
    "baltimore-catechism-no-1": Witness(
        work_id="baltimore-catechism-no-1", ticket="37c-063",
        source="raw/gutenberg/pg14551.txt",
        source_sha="d4b49653b457cc11f39df004896d072892b534e49899def16cdd75761c80993e",
        manifest_sha="ed8f9751ea77600b8bbe4663d4cca9ec9efce9ee930f422ce406fdb8fca28159",
        package_sha="8637e02c30f5c7fcb80956e0a50e54c8ed637451eea71ead27aa333a1f6f95f1",
        tei_sha="780c4c550d329024e31df28ae1ea06eb7bbbc81f657d04011b69b1948f82080c",
        validation_sha="10957cfa95c0af00fecbe97423a6abb34bb0978678eb194c1c4c8416e0d3dd8f",
        report_sha="4c484733b53f8ec61cc7382659eada853721a376092f224564849376e8bd7fa4",
        form_title="English text in the retained Project Gutenberg witness",
        edition_title="Project Gutenberg electronic witness of Baltimore Catechism No. 1",
        url="https://www.gutenberg.org/ebooks/14551",
        scope="Complete retained Project Gutenberg #14551 electronic member: provider header, Baltimore Catechism No. 1 text, editorial notes, prayers, hymns, end marker, and included license. No print exemplar collation is claimed.",
        visual_points=("opening-imprimatur-ready", "lesson-first", "faith-question", "communion-revision", "hymns-transition", "work-ending"),
        visual_hashes=("542a2aca81a32a0b0b4050fd0425a2888e1484b2453e2ffe5c022dd32953e441", "7eec378deb7a20efc9617105b4cee6545c8572d393dbe01281e6d776709b34d8", "8a7c9136217836fd50949926c7f8e112a8327ce9a442d8a4f6d5818939fa5c02", "107d1c60eac56d7193441a5192e409a7dd36fa54228d89904c77e423310ea57d"),
        evidence_hashes=("85c6e1cb9a68fd95a3cc00072d3471c546c5fb61ec79df2e71663092ddbe4c3c", "c808ac4ec89505ebdf5192de9372e8b1d8e7ba6f09dad56c639e664d47b8d83a", "4e6b1725cfe13c39cc88955008d7e2b1f566ffe4afcda286b3943dd2a3f24f52"),
        original_hashes=("3dcf742858c8e930c790f883e022b573a6fc7bdb021c9de70fa09b5cdc739d0f", "357e28df9d16e0a995b437ae5bbbf566049a9bc4989e9ab302d1db719500d35b"),
        uncertainty=("The retained e-text acknowledges a composite transcription and a 1977 revision note; this is not a verified 1885 print exemplar.",),
    ),
    "luthers-small-catechism": Witness(
        work_id="luthers-small-catechism", ticket="37c-247",
        source="raw/gutenberg/pg1670.txt",
        source_sha="bef45c16f9785a86d2cc0a902415e50fb689915c5aaaf7328773b9949baaf61f",
        manifest_sha="87f392ea4264d4c743682a26e80f6b4526a44b75c1f05555bda9325d6afbcf14",
        package_sha="5ebd55d48869d372b59666165b8ca4ab97760c942d031ca0fea76560f6978321",
        tei_sha="5704a077994500e189d34ce5aa507895b0243c958747873b6c824b2fb118714c",
        validation_sha="da430deb0e5364ad935efdaf62a1686ee4f95fe931c59dd26076c0ac7f710871",
        report_sha="6df322424b24e5dfa65b3719f720e79c4702eea1fa6999c150210b719c3af7f8",
        form_title="Robert E. Smith English translation in the retained electronic witness",
        edition_title="Project Wittenberg 2004 / Project Gutenberg electronic witness",
        url="https://www.gutenberg.org/ebooks/1670",
        scope="Complete retained Project Gutenberg #1670 electronic member: provider header, Robert E. Smith translation and Project Wittenberg statement, catechism, appendices, Home Chart, revision footer, end marker, and included license. No print exemplar collation is claimed.",
        visual_points=("opening-translation", "first-commandment", "evening-prayer-body", "home-chart-opening", "home-chart-authorities", "home-chart-ending"),
        visual_hashes=("0b9f1f5f1c977d5412b2c6ea8b6990e2c1eea8cdfcdf32035ae8f76c03d4e47a", "0f3a2913315847ae31ed8e37cd39279ed970ae3a7a33e1f44a867854994f607e", "3bd5cb3653e02f57fa8097e14cf2f016e06ff54ec7bc1052b8f37aa8a3f3f44a", "129982e0da73af827258248524f2d2c1d151857bd22b769ad03bd8d857e4a6ef"),
        evidence_hashes=("44f54c80c11d4eb4a72974367792b6a8447dfc34b730af9b4ec10a1a603c48a9", "800a5d405f3d0e1934bda16cd2ffb57db95180085330abd6d2d25cc604849ee1", "276e5ed4b49daed813709a3a443e1dcb562184f5098c175d0b9ac49133f52982"),
        original_hashes=("e87b0c74d8b6c321cb31e40a5a06db636005caf194bf3eab60cc19a6e11bd5bd", "cd83589244a043665abdd8ae59b773b3a22e845dc46f3332ea9a197832405d20"),
        uncertainty=("The electronic text states it is under continuous revision; the 1921 printed German source was not collated against this electronic witness.",),
    ),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"required handoff evidence unavailable: {path}") from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"handoff evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid handoff JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"handoff JSON is not an object: {label}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _copy(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _stage_path(root: Path, stage: Path) -> Path:
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("handoff staging root must be fresh with an ordinary parent")
    resolved = stage.resolve()
    if resolved == root or root in resolved.parents or resolved in root.parents or CANDIDATES in resolved.parents:
        raise PipelineError("handoff staging root overlaps protected source or checkout")
    return stage


def _identity(w: Witness) -> dict[str, str]:
    return dict(
        work_id=w.work_id,
        textual_form_id=f"{w.work_id}-retained-english",
        edition_id=f"{w.work_id}-gutenberg-electronic-witness",
        acquisition_id=f"{w.work_id}-gutenberg-retained",
    )


def _derive_header(original: bytes, w: Witness, identity: dict[str, str], revision: dict[str, str], source_bytes: int) -> bytes:
    if _sha(original) != w.tei_sha:
        raise PipelineError("reviewed TEI bytes differ")
    root = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    if root.tag != "{http://www.tei-c.org/ns/1.0}TEI" or len(root.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc", namespaces=ns)) != 1:
        raise PipelineError("reviewed single-document TEI header differs")
    if original.count(b"</sourceDesc>") != 1 or original.count(b"</revisionDesc>") != 1 or original.count(b"</teiHeader>") != 1:
        raise PipelineError("reviewed TEI header byte boundary is ambiguous")
    facts = identity | {
        "source_sha256": w.source_sha,
        "sha256": w.source_sha,
        "source_bytes": str(source_bytes),
        "representation_revision": revision["id"],
    }
    binding = '<bibl type="ocd-acceptance-binding"><ptr target=' + quoteattr(w.url) + '/>'
    binding += "".join('<idno type=' + quoteattr(key) + '>' + escape(value) + '</idno>' for key, value in facts.items())
    binding += '<note type="source-location">' + w.source + '</note>'
    binding += '<note type="source-scope">' + escape(w.scope) + '</note></bibl>'
    change = '<change xml:id=' + quoteattr(revision["id"]) + ' when=' + quoteattr(revision["date"]) + '>' + escape(revision["note"]) + '</change>'
    old_availability = b"Nonaccepted candidate; publication is not authorized; human identity, edition, rights, textual, and editorial review remain separate."
    new_availability = b"Agent-accepted electronic witness; publication is not authorized; human identity, edition, rights, textual, and editorial review remain separate."
    if original.count(old_availability) != 1:
        raise PipelineError("reviewed availability statement differs")
    derived = original.replace(old_availability, new_availability, 1)
    derived = derived.replace(b"</sourceDesc>", binding.encode() + b"</sourceDesc>", 1)
    derived = derived.replace(b"</revisionDesc>", change.encode() + b"</revisionDesc>", 1)
    etree.fromstring(derived, etree.XMLParser(resolve_entities=False, no_network=True))
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("header derivation changed reviewed TEI text bytes")
    return derived


def _visual_evidence(root: Path, w: Witness) -> tuple[dict[str, bytes], str]:
    """Rebind a historical exact-pair CVW sample without claiming new pixel review."""
    visual_path = MEASUREMENT / w.ticket / "visual-final"
    visual_report_path = MEASUREMENT / w.ticket / "visual-final-review.md"
    visual_files = {
        "visual-final-review.md": _read(root / visual_report_path, w.visual_hashes[0]),
        "visual/reviewed-identity.json": _read(root / visual_path / "reviewed-identity.json", w.visual_hashes[1]),
        "visual/image-inventory.json": _read(root / visual_path / "image-inventory.json", w.visual_hashes[2]),
        "visual/observations.json": _read(root / visual_path / "observations.json", w.visual_hashes[3]),
    }
    visual_identity = _json(visual_files["visual/reviewed-identity.json"], "visual identity")
    if (visual_identity.get("work_id") != w.work_id
            or visual_identity.get("source", {}).get("sha256") != w.source_sha
            or visual_identity.get("source", {}).get("path") != w.source
            or visual_identity.get("candidate", {}).get("package_sha256") != w.package_sha
            or visual_identity.get("candidate", {}).get("artifact_sha256") != w.tei_sha
            or visual_identity.get("validation", {}).get("report_sha256") != w.report_sha):
        raise PipelineError("visual review did not bind the exact candidate/source pair")
    images = json.loads(visual_files["visual/image-inventory.json"])
    observations = json.loads(visual_files["visual/observations.json"])
    if not isinstance(images, list) or not isinstance(observations, list):
        raise PipelineError("visual review image or observation inventory is invalid")
    by_image = {item.get("file"): item for item in images if isinstance(item, dict)}
    by_observation = {item.get("name"): item for item in observations if isinstance(item, dict)}
    if len(by_image) != len(images) or len(by_observation) != len(observations):
        raise PipelineError("visual review contains duplicate or invalid entries")
    for point in w.visual_points:
        image = by_image.get(f"{point}.jpg")
        observation = by_observation.get(point)
        if not image or not observation or image.get("sha256") != observation.get("sha256"):
            raise PipelineError(f"visual point is not present with matching identity: {point}")
        route = parse_qs(urlsplit(observation.get("url", "")).query)
        if (route.get("leftArtifact") != [f"source-{w.manifest_sha}"]
                or route.get("rightArtifact") != [f"tei-{w.package_sha}"]
                or route.get("linked") != ["false"]
                or route.get("correspondence") != ["absent"]):
            raise PipelineError(f"visual point does not show the exact unlinked pair: {point}")
        visual_files[f"visual/{point}.jpg"] = _read(root / visual_path / f"{point}.jpg", image["sha256"])
    reviewed_at = max(item["after"] for item in observations if isinstance(item.get("after"), str))
    return visual_files, reviewed_at


def _preflight(root: Path, w: Witness) -> tuple[SourceManifest, CandidatePackage, dict[str, bytes], bytes, dict]:
    work = load_work(root / "library/works" / w.work_id / "work.json")
    if work["work_id"] != w.work_id or work["textual_forms"]:
        raise PipelineError("handoff requires this exact identity-only work")
    source = _read(resolve_repo_path(root, w.source), w.source_sha)
    manifest_path = root / "sources/gutenberg-catechisms" / w.work_id / "source-manifest.json"
    manifest_bytes = _read(manifest_path, w.manifest_sha)
    manifest = SourceManifest.load(manifest_path, repository_root=root)
    manifest.verify()
    if manifest.sha256 != w.manifest_sha or manifest.record.get("work_id") != w.work_id:
        raise PipelineError("single-work source manifest identity differs")
    candidate_home = CANDIDATES / w.work_id
    package = CandidatePackage.load(candidate_home / "package")
    original = package.member_bytes("content.tei.xml")
    validation_bytes = _read(candidate_home / "validation.json", w.validation_sha)
    recorded = _json(validation_bytes, "stored validation")
    if (package.sha256 != w.package_sha or _sha(original) != w.tei_sha
            or package.manifest.get("status") != "nonaccepted"
            or package.manifest.get("source_manifest", {}).get("sha256") != w.manifest_sha
            or recorded.get("candidate_sha256") != w.package_sha
            or recorded.get("source_manifest_sha256") != w.manifest_sha
            or recorded.get("status") != "pass" or recorded.get("findings") != []
            or recorded.get("report_sha256") != w.report_sha
            or recorded.get("attestation", {}).get("source_sha256") != w.source_sha):
        raise PipelineError("stored candidate or validation differs from reviewed exact pair")
    fresh = validate(manifest, package, _oracle)
    if fresh.status != "pass" or fresh.sha256 != w.report_sha:
        raise PipelineError("current independent LIB-069 oracle differs from reviewed pass")
    ticket_path = CAMPAIGN / "issues" / f"{w.ticket}-{w.work_id}.md"
    report_path = REVIEW / f"{w.ticket}.md"
    metadata_path = root / "metadata/source-evidence/catalog" / f"{w.work_id}.json"
    visual_files, reviewed_at = _visual_evidence(root, w)
    files = {
        "source-manifest.json": manifest_bytes,
        "validation.json": validation_bytes,
        "ticket.md": _read(root / ticket_path, w.evidence_hashes[0]),
        "report.md": _read(root / report_path, w.evidence_hashes[1]),
        **visual_files,
        "metadata-sidecar.json": _read(metadata_path, w.evidence_hashes[2]),
    }
    for anchor in (w.source_sha, w.manifest_sha, w.package_sha, w.tei_sha):
        if anchor.encode() not in files["report.md"]:
            raise PipelineError(f"ticket review lacks exact evidence anchor: {anchor}")
    files.update({f"package/{name}": package.member_bytes(name) for name in package.member_names})
    files["package/manifest.json"] = _read(candidate_home / "package/manifest.json", w.package_sha)
    return manifest, package, files, source, reviewed_at


def prepare(root: Path, stage: Path, work_id: str) -> Path:
    root = root.resolve(strict=True)
    w = WITNESSES[work_id]
    stage = _stage_path(root, stage)
    _manifest, package, files, source, historical_reviewed_at = _preflight(root, w)
    identity = _identity(w)
    work_dir = Path("library/works") / work_id
    edition = work_dir / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition_path = edition / "acquisitions" / f'{identity["acquisition_id"]}.json'
    stage.mkdir()
    evidence = stage / work_dir / "integration/single-source-agent-handoff"
    for name, content in files.items():
        _copy(stage, evidence.relative_to(stage) / "inputs" / name, content)
    original_work = _json(_read(root / work_dir / "work.json"), "work")
    original_state = _json(_read(root / work_dir / "state.json"), "state")
    _copy(stage, Path(w.source), source)
    _copy(stage, Path("sources/gutenberg-catechisms") / work_id / "source-manifest.json", files["source-manifest.json"])
    now = datetime.now(timezone.utc)
    revision = dict(id=f"{work_id}-gutenberg-agent-v1", date=now.date().isoformat(),
                    note="Bind agent-accepted retained electronic witness; reviewed TEI text unchanged.")
    derived = _derive_header(files["package/content.tei.xml"], w, identity, revision, len(source))
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived TEI failed vendored XSD: {errors}")
    acquisition = dict(schema_version="2.0", acquisition_id=identity["acquisition_id"],
                       edition_id=identity["edition_id"], provider="Project Gutenberg", url=w.url,
                       retained_files=[dict(path=w.source, bytes=len(source), sha256=w.source_sha,
                                            scope=w.scope, media_type="text/plain")],
                       warnings=[*w.uncertainty,
                                 "This record asserts no rights clearance or publication authorization."])
    acquisition_target = stage / acquisition_path
    acquisition_target.parent.mkdir(parents=True, exist_ok=True)
    _write(acquisition_target, acquisition)
    original_work["textual_forms"].append(dict(
        textual_form_id=identity["textual_form_id"], title=w.form_title, language="en",
        category="catechisms", editions=[dict(
            edition_id=identity["edition_id"], title=w.edition_title,
            language="en", category="catechisms", acquisition_ids=[identity["acquisition_id"]],
        )],
    ))
    _write(stage / work_dir / "work.json", original_work)
    original_state["targets"].append(dict(
        target_id=identity["edition_id"], target_type="edition", stage="review",
        updated_at=now.isoformat().replace("+00:00", "Z"),
        evidence=[(evidence.relative_to(stage) / "inputs/ticket.md").as_posix(),
                  (evidence.relative_to(stage) / "inputs/report.md").as_posix(),
                  acquisition_path.as_posix()],
    ))
    _write(stage / work_dir / "state.json", original_state)
    included = [dict(path=w.source, bytes=len(source), sha256=w.source_sha, scope=w.scope, position=1)]
    scope = dict(kind="edition", declared=w.scope,
                 expected_members=[dict(path=w.source, position=1)],
                 included_members=included, excluded_members=[])
    source_record = dict(source_path=w.source, source_sha256=w.source_sha,
                         source_bytes=len(source), source_scope=w.scope)
    common = dict(identity=identity, source=source_record, candidate=make_file_binding(stage, candidate),
                  scope=w.scope, accepted_scope=dict(kind="edition", declared=w.scope),
                  expected_members=scope["expected_members"], included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = evidence / "source-accounting.json"
    _write(account, common | dict(source_sha256=w.source_sha, source_bytes=len(source),
                                  original_accountability_sha256=_sha(files["package/source-accountability.json"])))
    bindings = {name: make_file_binding(stage, evidence / "inputs" / name) for name in files}
    original_body = files["package/content.tei.xml"].split(b"</teiHeader>", 1)[1]
    derived_body = derived.split(b"</teiHeader>", 1)[1]
    details = {
        "validation": dict(status="pass", sidecar=bindings["validation.json"],
                           report_sha256=w.report_sha, fresh_oracle_replayed=True),
        "accounting": dict(source_sha256=w.source_sha,
                           original_member=bindings["package/source-accountability.json"]),
        "fidelity": dict(original_tei_sha256=w.tei_sha, original_body_sha256=_sha(original_body),
                         derived_body_sha256=_sha(derived_body), header_only_derivation=True),
        "reproducibility": dict(original_package_sha256=w.package_sha, no_reconstruction_performed=True,
                                historical_report=bindings["report.md"]),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(source_manifest_sha256=w.manifest_sha, original_package_sha256=w.package_sha,
                        evidence_files=bindings),
    }
    command = "py -3 -m build.tools.prepare_reviewed_single_source_acceptance --work <reviewed-id> --stage <fresh-external-root>"
    technical = dict(
        producer=dict(id=package.manifest["converter"]["id"]),
        checker=dict(id="ocd-lib069-gutenberg-catechisms-independent-oracle"),
        shared_assumptions=["Producer and oracle share the retained member, source manifest, and source feature policy; the visual review is a targeted sample."],
        independent_corroboration="Fresh independent oracle, complete physical-line and structural accounting, historical mutation/determinism checks, exact-pair CVW sample, and unchanged TEI body after header binding.",
    )
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(path, common | dict(status="pass", command=command, exit_code=0, details=details[name]))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    points = list(w.visual_points)
    review = dict(
        reviewer=f"agent:{w.ticket}-current-candidate-cvw",
        reviewed_at=historical_reviewed_at,
        coverage=dict(status="partial", declared=w.scope, reached=points, inspected=points,
                      unreviewed=["Whole-document pixel or print-exemplar collation beyond the declared visual sample"]),
        source_quality_uncertainty=list(w.uncertainty) + ["Rights clearance remains unresolved."],
        discrepancies=[],
        unreviewed_residuals=["The complete declared sample was inspected; every physical line is mechanically accounted, but not visually proofread."],
    )
    _write(evidence / "review.json", common | review | dict(
        historical_review=bindings["visual-final-review.md"],
        reviewed_identity=bindings["visual/reviewed-identity.json"],
        image_bindings=[bindings[f"visual/{point}.jpg"] for point in points],
        reviewed_original_tei_sha256=w.tei_sha, derived_body_bytes_unchanged=True,
        no_new_pixel_review=True,
    ))
    decision = dict(
        source_local_disposition="Evidence-backed agent acceptance of the complete retained Project Gutenberg electronic member only.",
        blockers=[],
        agent_assessment=dict(status="accepted", actor=f"agent:{work_id}-retained-electronic-witness-review",
                              assessed_at=now.isoformat().replace("+00:00", "Z"), supported_scope=w.scope,
                              unassessed_stronger_claims=["human acceptance", "rights clearance", "historical print edition identity",
                                                          "exhaustive proofreading", "release", "publication"],
                              unresolved_claims=[]),
        human_decision=dict(status="not-recorded"),
    )
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                     source_accounting_path=account, scope=scope, technical=technical,
                                     review=review | dict(report_path=evidence / "review.json"),
                                     representation_revision=revision, decision=decision)
    acceptance = stage / edition / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance



def declare(root: Path, promoted: Path, work_id: str) -> tuple[Path, Path]:
    """Predeclare one source-backed form/edition without changing existing IDs.

    The ordinary installer only accepts an already declared work.json. This
    bounded step copies the validated proposed identity and acquisition from
    a promoted generation, then the guarded installer installs master/state.
    """
    root, promoted = root.resolve(strict=True), promoted.resolve(strict=True)
    w = WITNESSES[work_id]
    identity = _identity(w)
    work_dir = Path("library/works") / work_id
    edition = work_dir / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition = edition / "acquisitions" / f'{identity["acquisition_id"]}.json'
    live_work = root / work_dir / "work.json"
    live_state = root / work_dir / "state.json"
    live_acquisition = root / acquisition
    staged_work = promoted / work_dir / "work.json"
    staged_acquisition = promoted / acquisition
    staged_acceptance = promoted / edition / "acceptance.json"
    record = validate_acceptance(staged_acceptance, root=promoted)
    if record["promotion"]["status"] != "promoted" or record["identity"] != identity:
        raise PipelineError("declaration source is not this exact promoted acceptance")
    with acquire_jsonl_lock(root / work_dir, acquire_timeout=30.0):
        previous_bytes = _read(live_work, w.original_hashes[0])
        _read(live_state, w.original_hashes[1])
        if live_acquisition.exists() or (root / edition).exists():
            raise PipelineError("declaration target already exists")
        staged_bytes = _read(staged_work)
        proposed = _json(staged_bytes, "promoted work")
        previous = _json(previous_bytes, "live work")
        validate_identity_update(previous, proposed)
        if ({k: v for k, v in proposed.items() if k != "textual_forms"}
                != {k: v for k, v in previous.items() if k != "textual_forms"}
                or len(proposed["textual_forms"]) != 1
                or proposed["textual_forms"][0]["textual_form_id"] != identity["textual_form_id"]
                or len(proposed["textual_forms"][0]["editions"]) != 1
                or proposed["textual_forms"][0]["editions"][0]["edition_id"] != identity["edition_id"]):
            raise PipelineError("declaration changes more than the reviewed form and edition")
        acquisition_bytes = _read(staged_acquisition)
        live_acquisition.parent.mkdir(parents=True, exist_ok=False)
        with live_acquisition.open("xb") as handle:
            handle.write(acquisition_bytes)
        temporary = live_work.with_name(f".work.json.handoff-{uuid.uuid4().hex}")
        try:
            temporary.write_bytes(staged_bytes)
            os.replace(temporary, live_work)
        finally:
            if temporary.exists():
                temporary.unlink()
        load_work(live_work)
        if _read(live_acquisition) != acquisition_bytes:
            raise PipelineError("declared acquisition bytes drifted")
    return live_work, live_acquisition


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", choices=sorted(WITNESSES), required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--stage", type=Path)
    operation.add_argument("--declare-from", type=Path)
    args = parser.parse_args()
    if args.stage is not None:
        print(prepare(ROOT, args.stage, args.work))
    else:
        print(declare(ROOT, args.declare_from, args.work))


if __name__ == "__main__":
    main()
