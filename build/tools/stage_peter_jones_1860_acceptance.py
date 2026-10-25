"""Stage one accepted electronic Peter Jones witness from the retained L759 candidate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from xml.sax.saxutils import escape, quoteattr

from lxml import etree

from build.tei.peter_jones_1860_oracle_v2 import _oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.validate import validate_file


_REPO_ROOT = Path(__file__).resolve().parents[2]
# The selected acquisition path exceeds Win32's ordinary path limit in this
# checkout. Keep the canonical checkout and address it through the extended
# path prefix; no short-path copy of source authority is introduced.
ROOT = Path("\\\\?\\" + str(_REPO_ROOT)) if os.name == "nt" else _REPO_ROOT
WORK_ID = "peter-jones-life-and-journals"
FORM_ID = "peter-jones-life-and-journals-wikisource-retained"
EDITION_ID = "peter-jones-life-and-journals-wikisource-electronic"
ACQUISITION_ID = "peter-jones-life-and-journals-wikisource-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
MANIFEST = Path("sources/manifest-acquisitions/peter-jones-life-and-journals-1860/reconstruction-source-manifest-v2.json")
SOURCE = Path("raw/wikisource/peter-jones-life-and-journals-1860/wikisource-export.xml")
SOURCE_RECEIPT = SOURCE.with_name("acquisition-receipt.json")
REVIEW_EVIDENCE = MANIFEST.with_name("candidate-review-evidence.json")
CLOSEOUT = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/L759_CURRENT_TECHNICAL_LINKAGE_CLOSEOUT_20260930.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260925/peter-jones-1860-wikisource-v2-declared-link-20260930")
REPLAY = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260925/peter-jones-1860-wikisource-v2-declared-link-20260930-replay")
EVIDENCE = WORK / "integration/l759-electronic-acceptance-v1"
SOURCE_SHA256 = "36b99ee46d93a3f5c253f97ecf10cddbc95947d1430e2276c77ffa061b489100"
MANIFEST_SHA256 = "5aad66adcc8772f6e6f5a369c0cf79ec2741b0f500d20cb3e2d0d8696cae13ad"
PACKAGE_SHA256 = "74a24035d5e186c385c3bfc12cfcd6478e95b40cd1690d3a27a4d64700b429bd"
TEI_SHA256 = "4252d3b043275508d633eeecefae880de5698322016f60e07a302d4083094530"
VALIDATION_SHA256 = "47a070f95afabdee03fb384764468b07fd4ac46e8966530be0f09106ef618591"
REPORT_SHA256 = "ab4a46fe951c779504bec02ea83551dcaa874b073c178c39b1d12b0e38c0663c"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = path.read_bytes()
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"L759 evidence digest changed: {path}")
    return content


def _put(root: Path, relative: Path, content: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def _derived_tei(original: bytes, *, identity: dict[str, str], source_scope: str,
                 source_url: str, revision: dict[str, str]) -> bytes:
    if _sha(original) != TEI_SHA256:
        raise PipelineError("reviewed L759 TEI bytes changed")
    if original.count(b"</sourceDesc>") != 1 or original.count(b"</teiHeader>") != 1:
        raise PipelineError("L759 TEI header byte boundary is ambiguous")
    if b"<revisionDesc" in original or b"ocd-acceptance-binding" in original:
        raise PipelineError("L759 candidate unexpectedly already carries acceptance history")
    facts = identity | {
        "source_sha256": SOURCE_SHA256,
        "sha256": SOURCE_SHA256,
        "source_bytes": str(len(_read(ROOT / SOURCE, SOURCE_SHA256))),
        "representation_revision": revision["id"],
    }
    binding = '<bibl type="ocd-acceptance-binding"><ptr target=' + quoteattr(source_url) + '/>'
    binding += "".join('<idno type=' + quoteattr(key) + '>' + escape(value) + '</idno>'
                       for key, value in facts.items())
    binding += '<note type="source-location">' + SOURCE.as_posix() + '</note>'
    binding += '<note type="source-scope">' + escape(source_scope) + '</note></bibl>'
    change = '<revisionDesc><change xml:id=' + quoteattr(revision["id"])
    change += ' when=' + quoteattr(revision["date"]) + '>' + escape(revision["note"])
    change += '</change></revisionDesc>'
    old = b"Nonaccepted Wikisource transcription candidate. Human acceptance, print collation, rights clearance, and publication remain pending."
    new = b"Agent-accepted Wikisource electronic witness. Human review, print collation, rights clearance, and publication remain pending."
    if original.count(old) != 1:
        raise PipelineError("L759 candidate availability statement differs")
    derived = original.replace(old, new, 1)
    # TEI P5 sourceDesc accepts a run of bibliographic elements or a run of
    # paragraphs, but not a mixture. Retain the original prose verbatim in a
    # bibliographic note before adding the scoped acceptance binding.
    if derived.count(b"<sourceDesc><p>") != 1 or derived.count(b"</p></sourceDesc>") != 1:
        raise PipelineError("L759 original source description differs")
    derived = derived.replace(b"<sourceDesc><p>",
                              b'<sourceDesc><bibl type="source-description"><note>', 1)
    derived = derived.replace(b"</p></sourceDesc>", b"</note></bibl></sourceDesc>", 1)
    derived = derived.replace(b"</sourceDesc>", binding.encode("utf-8") + b"</sourceDesc>", 1)
    derived = derived.replace(b"</teiHeader>", change.encode("utf-8") + b"</teiHeader>", 1)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("acceptance changed L759 TEI text or page markers")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    tree = etree.fromstring(derived, parser)
    pages = tree.xpath(".//t:pb/@n", namespaces={"t": "http://www.tei-c.org/ns/1.0"})
    if pages != [str(number) for number in range(8, 445)]:
        raise PipelineError("L759 acceptance does not preserve all 437 page markers")
    return derived


def stage_acceptance(root: Path, stage: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    stage = stage.absolute()
    if stage.exists() or stage == root or root in stage.parents:
        raise PipelineError("acceptance stage must be fresh and outside the repository")
    manifest_bytes = _read(root / MANIFEST, MANIFEST_SHA256)
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    if manifest.record.get("work_id") != WORK_ID or len(manifest.record["authorities"]) != 454:
        raise PipelineError("L759 manifest identity or 454-authority envelope differs")
    source = _read(root / SOURCE, SOURCE_SHA256)
    package = CandidatePackage.load(CANDIDATE / "package")
    replay = CandidatePackage.load(REPLAY / "package")
    if (package.sha256 != replay.sha256 or package.sha256 != PACKAGE_SHA256
            or any(package.member_bytes(name) != replay.member_bytes(name) for name in package.member_names)):
        raise PipelineError("L759 current candidate/replay package differs")
    original = package.member_bytes("content.tei.xml")
    stored_validation = json.loads(_read(CANDIDATE / "validation.json", VALIDATION_SHA256))
    fresh = validate(manifest, package, _oracle)
    if (fresh.status != "pass" or fresh.sha256 != REPORT_SHA256
            or stored_validation.get("candidate_sha256") != PACKAGE_SHA256
            or stored_validation.get("source_manifest_sha256") != MANIFEST_SHA256
            or stored_validation.get("report_sha256") != REPORT_SHA256
            or stored_validation.get("findings") != []):
        raise PipelineError("L759 current candidate validation differs")
    if _sha(_read(REPLAY / "validation.json")) != VALIDATION_SHA256:
        raise PipelineError("L759 replay validation differs")
    closeout = json.loads(_read(root / CLOSEOUT))
    if (closeout.get("work_id") != WORK_ID or closeout["checks"]["focused_test_exit"] != 0
            or closeout["source"]["accounted_authority_count"] != 454
            or closeout["candidate"]["tei_sha256"] != TEI_SHA256):
        raise PipelineError("L759 closeout does not bind the selected work and source")
    acquisition = json.loads(_read(root / EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"))
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("source_bytes") != len(source)):
        raise PipelineError("L759 canonical acquisition binding differs")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                    edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
    now = datetime.now(timezone.utc)
    revision = {
        "id": "peter-jones-1860-wikisource-agent-accepted-v1",
        "date": now.date().isoformat(),
        "note": "Accept the exact retained Wikisource electronic transcription; reviewed TEI text unchanged.",
    }
    derived = _derived_tei(original, identity=identity, source_scope=acquisition["source_scope"],
                           source_url=acquisition["url"], revision=revision)
    stage.mkdir(parents=True)
    shutil.copytree(root / WORK, stage / WORK)
    for relative, content in (
        (SOURCE, source),
        (SOURCE_RECEIPT, _read(root / SOURCE_RECEIPT)),
        (MANIFEST, manifest_bytes),
        (REVIEW_EVIDENCE, _read(root / REVIEW_EVIDENCE)),
        (CLOSEOUT, _read(root / CLOSEOUT)),
    ):
        _put(stage, relative, content)
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json", _read(CANDIDATE / "validation.json", VALIDATION_SHA256))
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"header-bound L759 TEI fails P5: {errors[0]}")
    included = [dict(path=SOURCE.as_posix(), bytes=len(source), sha256=SOURCE_SHA256,
                     scope=acquisition["source_scope"], position=1)]
    scope = dict(kind="edition", declared=acquisition["source_scope"],
                 expected_members=[dict(path=SOURCE.as_posix(), position=1)],
                 included_members=included, excluded_members=[])
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA256,
                          source_bytes=len(source), source_scope=acquisition["source_scope"])
    common = dict(identity=identity, source=source_binding, candidate=make_file_binding(stage, candidate),
                  scope=acquisition["source_scope"], accepted_scope=dict(kind="edition", declared=scope["declared"]),
                  expected_members=scope["expected_members"], included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    original_accounting = package.member_bytes("source-accountability.json")
    account = stage / EVIDENCE / "source-accounting.json"
    _write(account, common | dict(source_sha256=SOURCE_SHA256, source_bytes=len(source),
                                  authority_count=454, page_markers=437,
                                  original_accountability_sha256=_sha(original_accounting)))
    command = "py -3 -m build.tools.stage_peter_jones_1860_acceptance --stage <fresh-external-root>"
    technical: dict[str, object] = {
        "producer": {"id": package.manifest["converter"]["id"]},
        "checker": {"id": "ocd-peter-jones-1860-independent-source-oracle-v2"},
        "shared_assumptions": ["Producer and oracle share the manifest-pinned Wikisource export and fixed child/page boundaries; seven source-feature mutations and fresh replay constrain this assumption."],
        "independent_corroboration": "Live 454-authority rehash, fresh independent oracle, seven P5-valid mutation rejections, byte-identical replay, header-only acceptance derivation, and 437 ordered source page markers.",
    }
    details = {
        "validation": dict(candidate_package_sha256=PACKAGE_SHA256, report_sha256=REPORT_SHA256,
                           validation_sidecar_sha256=VALIDATION_SHA256, findings=[]),
        "accounting": dict(source_authorities=454, page_markers=437,
                           original_accountability_sha256=_sha(original_accounting)),
        "fidelity": dict(original_tei_sha256=TEI_SHA256,
                         original_body_sha256=_sha(original.split(b"</teiHeader>", 1)[1]),
                         accepted_body_sha256=_sha(derived.split(b"</teiHeader>", 1)[1]),
                         header_only_derivation=True),
        "reproducibility": dict(candidate_package_sha256=PACKAGE_SHA256,
                                replay_package_sha256=replay.sha256, byte_identical=True),
        "schema": dict(vendored_tei_p5_errors=[], candidate_tei_sha256=_sha(derived)),
        "closure": dict(source_manifest_sha256=MANIFEST_SHA256, local_links_resolved=15,
                        external_tokens_not_checked=89, print_scan_retained=False),
    }
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = stage / EVIDENCE / f"{name}.json"
        _write(proof, common | dict(status="pass", command=command, exit_code=0, details=details[name]))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    review = dict(
        reviewer="agent:l759-retained-electronic-technical-assessment",
        reviewed_at=now.isoformat().replace("+00:00", "Z"),
        coverage=dict(status="partial", declared=scope["declared"],
                      reached=["retained-export", "candidate-tei"],
                      inspected=["retained-export/authority-envelope", "candidate-tei/header", "candidate-tei/page-markers"],
                      unreviewed=["print-scan", "retained-export/full-visual-collation"]),
        source_quality_uncertainty=["The 1860 printed scan is not retained or visually collated.",
                                    "Fifteen source-located image/page references have no retained image bytes."],
        discrepancies=[],
        unreviewed_residuals=["No human review or exhaustive visual collation is claimed; rights and Wikisource contributor attribution remain unresolved."],
    )
    review_path = stage / EVIDENCE / "review.json"
    _write(review_path, common | review | dict(no_new_pixel_review=True,
                                              original_candidate_sha256=TEI_SHA256,
                                              accepted_body_unchanged=True))
    decision = dict(
        source_local_disposition="Agent acceptance of the complete exact retained 1860 Wikisource electronic member only; no print-exemplar equivalence or publication decision.",
        blockers=[],
        agent_assessment=dict(status="accepted", actor=review["reviewer"],
                              assessed_at=review["reviewed_at"], supported_scope=scope["declared"],
                              unassessed_stronger_claims=["print-scan visual collation", "human acceptance",
                                                          "Wikisource attribution and rights clearance", "publication"],
                              unresolved_claims=[]),
        human_decision=dict(status="not-recorded"),
    )
    record = build_acceptance_record(
        stage, identity=identity, candidate_path=candidate, source_accounting_path=account,
        scope=scope, technical=technical, review=review | dict(report_path=review_path),
        representation_revision=revision, decision=decision,
    )
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / "state.json", root=stage)
    return {"status": "pending-acceptance-validated", "stage": str(stage),
            "candidate_sha256": _sha(derived), "accepted_body_sha256": details["fidelity"]["accepted_body_sha256"],
            "acceptance_sha256": _sha(acceptance.read_bytes()), "source_authorities": 454,
            "page_markers": 437, "source_sha256": SOURCE_SHA256}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(stage_acceptance(ROOT, args.stage), sort_keys=True))


if __name__ == "__main__":
    main()
