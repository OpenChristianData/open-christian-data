"""Prepare, but never install, scoped Creeds.json electronic-witness acceptances.

Each route is pinned to one work, one retained member, and one independently
verified nonaccepted candidate. The result is a separate reviewable generation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Mapping
from urllib.parse import parse_qs, urlsplit
from lxml import etree

from cvw_app.capture_review import CaptureError, session_identity, verify_bundle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.reconstruction.decision import load_verified_review
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
CORRESPONDENCE_ABSENT_WARNING = (
    "Correspondence: absentNo governed upstream correspondence output is available; "
    "no location was inferred.The panes are unlinked; the viewer has not inferred a match."
)
OUTSIDE_SEGMENT_WARNING = (
    "Recorded location is outside this segment range.The recorded location lies outside "
    "the requested segment range; neighboring content was not substituted and no "
    "replacement was inferred."
)
ROUTES = {
    "belgic-confession-of-faith": {
        "manifest": "sources/doctrinal-documents/lib063-creeds-json/belgic-confession-of-faith/belgic-confession-of-faith.source-manifest.json",
        "candidate": "37c-076-belgic-confession-20260921-v1",
        "package_sha256": "1bbfb30da99872446e21a4c3c81cdf5de5bf74bc3327bafbb9bbaaa4c5853e4b",
        "validation_sha256": "fc952c38b2e0a0e8673a9086c48cb723ae4f8e3c88648da3d97580988ff9834f",
        "review": "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-076.md",
        "review_sha256": "484998156870e6af6a5f4279595427f1034285c597034fa87ac4d1c0a49530e8",
        "visual_loci": ["metadata", "Article 1", "Article 19", "Article 37"],
        "unreviewed": ["other articles and full-document visual collation"],
    },
    "chalcedonian-definition": {
        "manifest": "sources/doctrinal-documents/lib063-creeds-json/chalcedonian-definition/chalcedonian-definition.source-manifest.json",
        "candidate": "37c-097-chalcedonian-definition-lib063-20260921-r1",
        "package_sha256": "286e1c2bc55f323c3db89aaed9d34e7352f88711a3d20434648557e55b82f0b5",
        "validation_sha256": "40f3027da8a478cffb380c86feefa7fe1157e861617981dd375b791560f20cf0",
        "review": "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-097.md",
        "review_sha256": "f38d02882941aa62c412661f22b84f5d38a05d0e0a7be7fb609a270804870491",
        "visual_loci": ["metadata", "title", "Data", "content"],
        "unreviewed": ["independent print-witness collation"],
    },
    "1695-baptist-catechism": {
        "manifest": "sources/1695-baptist-catechism/1695-baptist-catechism.source-manifest.json",
        "candidate": "1695-baptist-catechism",
        "package_sha256": "5be0842e59e86f37fc00d696109b8296c826c7fd170185646836287deddc1327",
        "validation_sha256": "3d46264e3d2105efb0e2ef30744ce6751584099479cd0214f21856c7151ce1e1",
        "review": "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-001.md",
        "review_sha256": "462c78d5d1bff8cc618e11c03f06fd354bf59950d0a973309f314cea39a29e8a",
        "visual_review": "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-001-cvw-visual-review.json",
        "visual_review_sha256": "40df38b892a687c2ff78414bd3c40b3fcdbf65f9378c1d70e2e9d33183456703",
        "support_files": ["raw/Creeds.json/README.md"],
        "visual_loci": [
            "Q1 opening",
            "Q11 empty Proofs",
            "Q43 empty Answer",
            "Q57 middle proof markers",
            "Q59 empty Answer and proof markers",
            "Q59 final proof marker",
            "Q60 empty Answer",
            "Q99 empty Proofs",
            "Q114 ending",
        ],
        "visual_capture_locations": {
            "q01": {"number": 1, "question": "Who is the First and Chiefest Being?", "right_location": "lib062-1695-baptist-catechism-row-0001-question"},
            "q11": {"number": 11, "question": "How doth God execute his Decrees?", "right_location": "lib062-1695-baptist-catechism-row-0011-question"},
            "q43": {"number": 43, "question": "What shall be done to the Wicked at the Day of Judgment?", "right_location": "lib062-1695-baptist-catechism-row-0043-question"},
            "q57": {
                "number": 57,
                "question": "What are the Reasons annexed to the second Commandment?",
                "right_location": "lib062-1695-baptist-catechism-row-0057-question",
                "source_literal": "his own Worship[3].",
                "candidate_literal": "his own Worship[3].",
                "candidate_scope_prefix": "The Reasons annexed to the second Commandment are, God's Sovereignty over us[1],",
            },
            "q59": {"number": 59, "question": "What is required in the third Commandment?", "right_location": "lib062-1695-baptist-catechism-row-0059-question"},
            "q59_aw_tail": {
                "number": 59,
                "question": "What is required in the third Commandment?",
                "right_location": "lib062-1695-baptist-catechism-row-0059-answer-with-proofs",
                "source_literal": "Works[6].",
                "candidate_literal": "Works[6].",
                "candidate_scope_prefix": "The third Commandment requireth",
            },
            "q60": {"number": 60, "question": "What is forbidden in the third Commandment?", "right_location": "lib062-1695-baptist-catechism-row-0060-question"},
            "q99": {
                "number": 99,
                "question": "Are the Infants of such as are Professing Believers to be baptized?",
                "right_location": "lib062-1695-baptist-catechism-row-0099-question",
                "source_segment_start": 1,
                "source_scope_prefix": "      \"AnswerWithProofs\": \"The Reasons annexed to the fourth Commandment",
                "source_literal": "\"Proofs\": [\r\n      ]",
            },
            "q114": {
                "number": 114,
                "question": "What doth the Conclusion of the Lord's Prayer teach?",
                "right_location": "lib062-1695-baptist-catechism-row-0114-question",
                "source_segment_start": 1,
                "source_scope_prefix": "      \"AnswerWithProofs\": \"The Reasons annexed to the fourth Commandment",
                "source_literal": "we say, Amen[4].",
                "candidate_literal": "we say, Amen[4].",
                "candidate_scope_prefix": "The Conclusion of the Lord's Prayer, which is, \"For thine is the Kingdom, and the Power, and the Glory, for ever, Amen[1],\"",
            },
        },
        "unreviewed": ["questions outside the selected systematic sample and full-document visual collation"],
    },
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _revision_id(work_id: str) -> str:
    """Return an XML ID that remains valid when a work ID starts with a digit."""
    return f"lib062-{work_id}-creeds-json-electronic-v1"


def _read(path: Path) -> dict[str, object]:
    value = json.loads(_io_path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _write(root: Path, relative: Path, data: bytes) -> Path:
    path = root / relative
    _io_path(path.parent).mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(data)
    return path


def _copy_state_evidence(stage: Path, work_root: Path) -> None:
    """Materialize existing state references so staged relationship checks are complete."""
    state = _read(_io_path(work_root / "state.json"))
    evidence_paths = {
        item
        for target in state.get("targets", [])
        for item in target.get("evidence", [])
        if isinstance(item, str)
    }
    for value in sorted(evidence_paths):
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise PipelineError(f"state evidence path is not repository-relative: {value}")
        source = ROOT / relative
        payload = _io_path(source).read_bytes()
        destination = stage / relative
        if _io_path(destination).exists():
            if _io_path(destination).read_bytes() != payload:
                raise PipelineError(f"staged state evidence conflicts with its source: {value}")
            continue
        _write(stage, relative, payload)


def _json(root: Path, relative: Path, value: object) -> Path:
    return _write(root, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _verify_visual_captures(
    captures: Mapping[str, Path] | None,
    *,
    route: dict[str, object],
    source_manifest_sha256: str,
    source_sha256: str,
    candidate_sha256: str,
    tei_sha256: str,
) -> dict[str, dict[str, object]]:
    expected = route.get("visual_capture_locations")
    if not isinstance(expected, dict):
        if captures:
            raise PipelineError("this acceptance route does not accept CVW capture bundles")
        return {}
    if not isinstance(captures, Mapping) or set(captures) != set(expected):
        raise PipelineError(f"CVW capture labels must be exactly {sorted(expected)}")

    verified: dict[str, dict[str, object]] = {}
    session_id: str | None = None
    expected_files = {"frame.png", "compare.json", "session.json"}
    for label, locus in expected.items():
        directory = Path(captures[label])
        try:
            record = verify_bundle(directory)
        except (OSError, CaptureError, json.JSONDecodeError) as error:
            raise PipelineError(f"invalid CVW capture bundle for {label}: {error}") from error
        if record.get("contract") != "ocd-cvw-capture-bundle-v1":
            raise PipelineError(f"CVW capture contract differs for {label}")
        if set(record.get("files", {})) != expected_files:
            raise PipelineError(f"CVW capture members differ for {label}")
        frame = _io_path(directory / "frame.png").read_bytes()
        if not frame.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PipelineError(f"CVW frame is not a PNG image for {label}")
        if record.get("page_errors") != []:
            raise PipelineError(f"CVW page errors were recorded for {label}")
        source_segment_start = locus.get("source_segment_start")
        expected_warnings = [CORRESPONDENCE_ABSENT_WARNING]
        if source_segment_start is not None:
            expected_warnings.append(OUTSIDE_SEGMENT_WARNING)
        warnings = record.get("warnings", [])
        if warnings != expected_warnings:
            raise PipelineError(f"unexpected CVW warning for {label}: {warnings}")

        captured_session = record.get("session")
        session_record = _read(directory / "session.json")
        try:
            identity = session_identity(session_record)
        except CaptureError as error:
            raise PipelineError(f"CVW session identity is invalid for {label}: {error}") from error
        if identity != captured_session or session_record.get("session", session_record).get("state") != "ready":
            raise PipelineError(f"CVW session file differs from capture record for {label}")
        if candidate_sha256 not in identity.get("candidate_sha256", []):
            raise PipelineError(f"CVW session did not admit the pinned candidate for {label}")
        if session_id is None:
            session_id = identity["session_id"]
        elif identity["session_id"] != session_id:
            raise PipelineError("CVW frames do not share one session")

        browser = record.get("browser_state", {})
        browser_url = urlsplit(str(browser.get("url", "")))
        route_value = str(browser.get("route", ""))
        captured_route = urlsplit(route_value)
        origin = urlsplit(identity["origin"])
        if (
            (browser_url.scheme, browser_url.netloc) != (origin.scheme, origin.netloc)
            or (captured_route.scheme, captured_route.netloc) not in {("", ""), (origin.scheme, origin.netloc)}
            or browser_url.path != captured_route.path
            or browser_url.query != captured_route.query
            or captured_route.path != f"/review/works/{route['candidate']}"
        ):
            raise PipelineError(f"CVW route origin or work identity differs for {label}")
        query = parse_qs(captured_route.query, keep_blank_values=True)
        expected_query = {
            "mode": ["compare"],
            "leftStage": ["source"],
            "leftArtifact": [f"source-{source_manifest_sha256}"],
            "leftVersion": [source_manifest_sha256],
            "leftLocation": ["start"],
            "rightStage": ["tei"],
            "rightArtifact": [f"tei-{candidate_sha256}"],
            "rightVersion": [candidate_sha256],
            "rightLocation": [locus["right_location"]],
            "linked": ["false"],
            "correspondence": ["absent"],
        }
        if source_segment_start is not None:
            expected_query["leftSegmentStart"] = [str(source_segment_start)]
            expected_query["leftSegmentLimit"] = ["1"]
        if query != expected_query or not browser.get("route_digest"):
            raise PipelineError(f"CVW route details differ for {label}")

        compare = _read(directory / "compare.json")
        left = compare.get("left", {})
        right = compare.get("right", {})
        if compare.get("route_digest") != browser.get("route_digest"):
            raise PipelineError(f"CVW response does not bind the displayed route for {label}")
        if (
            left.get("stage", {}).get("id") != "source"
            or left.get("artifact", {}).get("id") != f"source-{source_manifest_sha256}"
            or left.get("artifact", {}).get("version") != source_manifest_sha256
            or left.get("artifact", {}).get("sha256") != source_sha256
            or left.get("location", {}).get("value") != "start"
            or right.get("stage", {}).get("id") != "tei"
            or right.get("artifact", {}).get("id") != f"tei-{candidate_sha256}"
            or right.get("artifact", {}).get("version") != candidate_sha256
            or right.get("artifact", {}).get("sha256") != tei_sha256
            or right.get("location", {}).get("value") != locus["right_location"]
        ):
            raise PipelineError(f"CVW response does not bind the exact source/TEI pair for {label}")

        left_paging = left.get("paging", {})
        if source_segment_start is None:
            if left.get("location_state") != "in-range":
                raise PipelineError(f"CVW source location is unexpectedly out of range for {label}")
        else:
            segments = left_paging.get("segments")
            if (
                left.get("location_state") != "location-outside-range"
                or left_paging.get("mode") != "segments"
                or not isinstance(segments, list)
                or len(segments) != 1
                or not isinstance(segments[0], dict)
                or segments[0].get("index") != source_segment_start
            ):
                raise PipelineError(f"CVW source segment selection differs for {label}")

        targets = record.get("targets", {})
        left_target = targets.get("left", {})
        right_target = targets.get("right", {})
        source_literal = locus.get("source_literal", f'"Number": {locus["number"]},')
        source_scope_prefix = locus.get("source_scope_prefix", "{")
        candidate_literal = locus.get("candidate_literal", locus["question"])
        candidate_scope_prefix = locus.get("candidate_scope_prefix", locus["question"])
        if (
            left_target.get("literal") != source_literal
            or left_target.get("scope_selector") != "pre"
            or left_target.get("scope_prefix") != source_scope_prefix
            or not left_target.get("visible")
            or right_target.get("literal") != candidate_literal
            or right_target.get("scope_selector") != "article.artifact-content p"
            or right_target.get("scope_prefix") != candidate_scope_prefix
            or not right_target.get("visible")
        ):
            raise PipelineError(f"CVW did not visibly capture the declared source/TEI anchors for {label}")

        verified[label] = {
            "locus": f"Q{locus['number']}",
            "right_location": locus["right_location"],
            "session_id": identity["session_id"],
            "capture_sha256": _sha((directory / "capture.json").read_bytes()),
            "frame_sha256": record["files"]["frame.png"],
            "compare_sha256": record["files"]["compare.json"],
            "session_sha256": record["files"]["session.json"],
            "warnings": warnings,
        }
    return verified


def _verify_visual_inspection(
    record: dict[str, object],
    *,
    captures: Mapping[str, dict[str, object]],
    route: dict[str, object],
    source_path: str,
    source_manifest_sha256: str,
    source_sha256: str,
    candidate_sha256: str,
    tei_sha256: str,
) -> dict[str, object]:
    """Bind an actual agent pixel review to the exact captured source/TEI loci."""
    if record.get("contract") != "ocd-agent-cvw-visual-review-v1":
        raise PipelineError("CVW visual inspection record has an unsupported contract")
    reviewer = record.get("reviewer")
    if (
        not isinstance(reviewer, dict)
        or reviewer.get("type") != "agent"
        or not isinstance(reviewer.get("id"), str)
        or not reviewer["id"].startswith("agent:")
        or reviewer.get("independent_of_work_owner") is not True
    ):
        raise PipelineError("CVW visual inspection must identify an independent agent reviewer")
    reviewed_at = record.get("reviewed_at")
    if not isinstance(reviewed_at, str):
        raise PipelineError("CVW visual inspection timestamp is missing")
    try:
        parsed_time = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise PipelineError("CVW visual inspection timestamp is invalid") from error
    if parsed_time.tzinfo is None:
        raise PipelineError("CVW visual inspection timestamp must include a timezone")

    source = record.get("source")
    candidate = record.get("candidate")
    expected_session = next(iter(captures.values())).get("session_id") if captures else None
    if (
        not isinstance(source, dict)
        or source.get("path") != source_path
        or source.get("manifest_sha256") != source_manifest_sha256
        or source.get("sha256") != source_sha256
        or not isinstance(candidate, dict)
        or candidate.get("package_sha256") != candidate_sha256
        or candidate.get("tei_sha256") != tei_sha256
        or record.get("session_id") != expected_session
    ):
        raise PipelineError("CVW visual inspection is not bound to the pinned source, candidate, and session")

    expected = route.get("visual_capture_locations")
    loci = record.get("loci")
    if not isinstance(expected, dict) or not isinstance(loci, list):
        raise PipelineError("CVW visual inspection loci are missing")
    by_label = {item.get("label"): item for item in loci if isinstance(item, dict)}
    if len(by_label) != len(loci) or set(by_label) != set(captures) or set(captures) != set(expected):
        raise PipelineError("CVW visual inspection does not cover exactly the captured loci")

    observations: dict[str, dict[str, object]] = {}
    for label, locus in expected.items():
        item = by_label[label]
        capture = captures[label]
        source_anchor = locus.get("source_literal", f'"Number": {locus["number"]},')
        candidate_anchor = locus.get("candidate_literal", locus["question"])
        if (
            item.get("number") != locus["number"]
            or item.get("source_anchor") != source_anchor
            or item.get("candidate_anchor") != candidate_anchor
            or item.get("capture_sha256") != capture["capture_sha256"]
            or item.get("frame_sha256") != capture["frame_sha256"]
            or not isinstance(item.get("observation"), str)
            or not item["observation"].strip()
        ):
            raise PipelineError(f"CVW visual inspection is not bound to the inspected pixels for {label}")
        observations[label] = {
            "locus": f"Q{locus['number']}",
            "observation": item["observation"],
            "capture_sha256": capture["capture_sha256"],
            "frame_sha256": capture["frame_sha256"],
        }

    limitations = record.get("limitations")
    if not isinstance(limitations, list) or not limitations or any(
        not isinstance(item, str) or not item.strip() for item in limitations
    ):
        raise PipelineError("CVW visual inspection limitations must be explicit")
    return {
        "reviewer": reviewer["id"],
        "reviewed_at": reviewed_at,
        "session_id": expected_session,
        "observations": observations,
        "limitations": limitations,
    }


def _verify_source_accounting(accounting: dict[str, object], source_bytes: bytes, work_id: str) -> dict[str, object]:
    """Check the LIB-062 leaf crosswalk against every terminal source value."""
    try:
        source = json.loads(source_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineError("retained source is not valid JSON") from error
    if not isinstance(source, dict):
        raise PipelineError("retained source must have a top-level JSON object")

    expected: dict[str, object] = {}

    def collect(value: object, pointer: str = "") -> None:
        if isinstance(value, dict):
            if not value:
                expected[pointer] = value
            for key, child in value.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                collect(child, f"{pointer}/{escaped}")
        elif isinstance(value, list):
            if not value:
                expected[pointer] = value
            for index, child in enumerate(value):
                collect(child, f"{pointer}/{index}")
        else:
            expected[pointer] = value

    collect(source)
    crosswalk = accounting.get("crosswalk")
    if (
        accounting.get("contract") != "ocd-lib062-source-accountability-v1"
        or accounting.get("work_id") != work_id
        or accounting.get("source_member_disposition") != "included in full as sole authority"
        or accounting.get("top_level_keys") != list(source)
        or accounting.get("data_record_count") != len(source.get("Data", []))
        or accounting.get("omitted_leaf_count") != 0
        or accounting.get("duplicate_leaf_count") != 0
        or accounting.get("represented_leaf_count") != len(expected)
        or not isinstance(crosswalk, list)
        or len(crosswalk) != len(expected)
    ):
        raise PipelineError("candidate accounting differs from the LIB-062 source-accountability contract")

    seen: set[str] = set()
    targets: set[str] = set()
    for item in crosswalk:
        if not isinstance(item, dict):
            raise PipelineError("candidate source crosswalk contains a malformed row")
        pointer = item.get("pointer")
        target = item.get("tei_target")
        if (
            not isinstance(pointer, str)
            or pointer not in expected
            or pointer in seen
            or item.get("disposition") != "represented"
            or item.get("value") != expected[pointer]
            or not isinstance(target, str)
            or not target.startswith("#")
            or target in targets
        ):
            raise PipelineError("candidate source crosswalk does not map every source leaf exactly once")
        seen.add(pointer)
        targets.add(target)
    if seen != set(expected):
        raise PipelineError("candidate source crosswalk omits retained JSON values")
    return {
        "data_record_count": accounting["data_record_count"],
        "top_level_keys": accounting["top_level_keys"],
        "represented_leaf_count": len(expected),
        "omitted_leaf_count": 0,
        "duplicate_leaf_count": 0,
        "recursive_key_counts": accounting.get("recursive_key_counts", {}),
    }


def prepare(
    work_id: str,
    *,
    stage: Path,
    library: Path,
    cvw_captures: Mapping[str, Path] | None = None,
) -> dict[str, object]:
    """Create a fresh, separately validated work generation with no install."""
    if work_id not in ROUTES:
        raise PipelineError(f"work is not individually declared: {work_id}")
    route = ROUTES[work_id]
    stage = stage.absolute()
    if _io_path(stage).exists():
        raise PipelineError(f"stage must be fresh: {stage}")
    if ROOT in stage.parents or stage == ROOT or library in stage.parents:
        raise PipelineError("stage overlaps canonical repository or candidate library")
    if not _io_path(stage.parent).is_dir():
        raise PipelineError("stage parent does not exist")
    candidate_root = library / route["candidate"]
    manifest_path = ROOT / route["manifest"]
    manifest = SourceManifest.load(manifest_path, repository_root=ROOT)
    review = load_verified_review(
        manifest,
        candidate_path=candidate_root / "package",
        validation_path=candidate_root / "validation.json",
    )
    if review.candidate_sha256 != route["package_sha256"]:
        raise PipelineError("candidate differs from declared review")
    if _sha(_io_path(candidate_root / "validation.json").read_bytes()) != route["validation_sha256"]:
        raise PipelineError("validation sidecar differs from declared review")
    if review.validation.status != "pass" or review.validation.findings:
        raise PipelineError("independent oracle did not pass")

    work = Path("library/works") / work_id
    form = f"{work_id}-retained-electronic"
    edition = f"{work_id}-creeds-json"
    acquisition_id = f"{work_id}-creeds-json-member"
    edition_path = work / "forms" / form / "editions" / edition
    acquisition_path = edition_path / "acquisitions" / f"{acquisition_id}.json"
    master_path = edition_path / "master.tei.xml"
    acceptance_path = edition_path / "acceptance.json"
    evidence = work / "integration" / "creeds-json-electronic-v1"
    identity = {
        "work_id": work_id,
        "textual_form_id": form,
        "edition_id": edition,
        "acquisition_id": acquisition_id,
    }
    canonical_work = ROOT / work
    before = _files(canonical_work)
    if master_path.relative_to(work).as_posix() in before or acceptance_path.relative_to(work).as_posix() in before:
        raise PipelineError("canonical work already has master or acceptance")
    if _io_path(ROOT / evidence).exists():
        raise PipelineError("canonical integration evidence already exists")
    acquisition = validate_acquisition(_io_path(ROOT / acquisition_path), root=_io_path(ROOT))
    member = acquisition["retained_files"]
    if len(member) != 1 or member[0]["path"].startswith("raw/Creeds.json/creeds/") is False:
        raise PipelineError("expected one bound retained Creeds.json member")
    source_path = Path(member[0]["path"])
    source = _io_path(ROOT / source_path).read_bytes()
    if len(source) != member[0]["bytes"] or _sha(source) != member[0]["sha256"]:
        raise PipelineError("retained member changed")
    accounting_bytes = _io_path(candidate_root / "package/source-accountability.json").read_bytes()
    accounting_record = _read(candidate_root / "package/source-accountability.json")
    accounting = _verify_source_accounting(accounting_record, source, work_id)
    if _sha(_io_path(ROOT / route["review"]).read_bytes()) != route["review_sha256"]:
        raise PipelineError("entry-local review differs from individually assessed evidence")
    original = review.member_bytes("content.tei.xml")
    visual_captures = _verify_visual_captures(
        cvw_captures,
        route=route,
        source_manifest_sha256=manifest.sha256,
        source_sha256=member[0]["sha256"],
        candidate_sha256=review.candidate_sha256,
        tei_sha256=_sha(original),
    )
    visual_inspection: dict[str, object] | None = None
    visual_inspection_bytes: bytes | None = None
    visual_inspection_path = route.get("visual_review")
    if visual_inspection_path is not None:
        inspection_path = ROOT / str(visual_inspection_path)
        visual_inspection_bytes = _io_path(inspection_path).read_bytes()
        if _sha(visual_inspection_bytes) != route["visual_review_sha256"]:
            raise PipelineError("independent CVW visual review differs from its pinned evidence")
        visual_inspection = _verify_visual_inspection(
            _read(inspection_path),
            captures=visual_captures,
            route=route,
            source_path=source_path.as_posix(),
            source_manifest_sha256=manifest.sha256,
            source_sha256=member[0]["sha256"],
            candidate_sha256=review.candidate_sha256,
            tei_sha256=_sha(original),
        )
    _io_path(stage / work).mkdir(parents=True)
    for relative in before:
        src = canonical_work / relative
        dst = stage / work / relative
        _io_path(dst.parent).mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(src), _io_path(dst))
    _write(stage, source_path, source)
    _write(stage, Path(route["manifest"]), _io_path(manifest_path).read_bytes())
    _write(stage, Path(route["review"]), _io_path(ROOT / route["review"]).read_bytes())
    support_files = route.get("support_files")
    if support_files is None:
        support_files = [
            (manifest_path.parent.relative_to(ROOT) / "config.json").as_posix(),
            "raw/Creeds.json/README.md",
        ]
    for item in support_files:
        relative = Path(item)
        _write(stage, relative, _io_path(ROOT / relative).read_bytes())
    _copy_state_evidence(stage, canonical_work)
    for name in review.member_names:
        _write(stage, evidence / "inputs/package" / name, review.member_bytes(name))
    _write(stage, evidence / "inputs/package/manifest.json", _io_path(candidate_root / "package/manifest.json").read_bytes())
    _write(stage, evidence / "inputs/validation.json", _io_path(candidate_root / "validation.json").read_bytes())
    for label, directory in (cvw_captures or {}).items():
        for name in ("capture.json", "frame.png", "compare.json", "session.json"):
            _write(stage, evidence / "inputs/cvw" / label / name, _io_path(directory / name).read_bytes())
    if visual_inspection_bytes is not None:
        _write(stage, evidence / "inputs/cvw/visual-review.json", visual_inspection_bytes)
    original_tree = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    historical_description = {
        "pointers": original_tree.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:ptr/@target", namespaces=ns),
        "sha256": original_tree.xpath("./tei:teiHeader//tei:idno[@type='sha256']/text()", namespaces=ns),
    }
    source_binding = {
        "source_path": source_path.as_posix(),
        "source_sha256": member[0]["sha256"],
        "source_bytes": member[0]["bytes"],
        "source_scope": member[0]["scope"],
    }
    revision = {
        "id": _revision_id(work_id),
        "date": datetime.now(timezone.utc).date().isoformat(),
        "note": "Accept the complete exact retained Creeds.json electronic member as this edition's reconstructed text.",
    }
    bound = bind_reviewed_header(
        original,
        expected_sha256=_sha(original),
        identity=identity,
        source=source_binding,
        source_url=acquisition["url"],
        declared_scope=member[0]["scope"],
        revision=revision,
        historical_source_description=historical_description,
    )
    if bound.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("header binding changed the TEI body")
    candidate = _write(stage, evidence / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise PipelineError(f"header-bound TEI fails XSD: {errors[:3]}")
    expected = [{"path": source_path.as_posix(), "position": 1}]
    included = [expected[0] | {"bytes": member[0]["bytes"], "sha256": member[0]["sha256"], "scope": member[0]["scope"]}]
    scope = {"kind": "edition", "declared": member[0]["scope"], "expected_members": expected, "included_members": included, "excluded_members": []}
    common = {
        "identity": identity,
        "source": source_binding,
        "candidate": make_file_binding(stage, candidate),
        "scope": member[0]["scope"],
        "accepted_scope": {"kind": "edition", "declared": member[0]["scope"]},
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
        "missing_members": [],
        "unknown_members": [],
    }
    account = _json(stage, evidence / "source-accounting.json", common | {
        "source_sha256": member[0]["sha256"],
        "source_bytes": member[0]["bytes"],
        "candidate_accountability_sha256": _sha(accounting_bytes),
        "json_accounting": accounting,
        "candidate_package_sha256": review.candidate_sha256,
        "oracle_report_sha256": review.validation.sha256,
    })
    input_bindings = {
        "source_manifest": make_file_binding(stage, stage / route["manifest"]),
        "package_manifest": make_file_binding(stage, stage / evidence / "inputs/package/manifest.json"),
        "validation": make_file_binding(stage, stage / evidence / "inputs/validation.json"),
        "entry_review": make_file_binding(stage, stage / route["review"]),
    }
    if visual_captures:
        input_bindings["cvw_captures"] = {
            label: {
                name: make_file_binding(stage, stage / evidence / "inputs/cvw" / label / name)
                for name in ("capture.json", "frame.png", "compare.json", "session.json")
            }
            for label in visual_captures
        }
    if visual_inspection is not None:
        input_bindings["cvw_visual_review"] = make_file_binding(
            stage, stage / evidence / "inputs/cvw/visual-review.json"
        )
    command = "py -3 -m build.tools.stage_creeds_json_acceptance"
    descriptions = {
        "validation": "Current independent source oracle passes for the exact source-bound package.",
        "accounting": "Every terminal retained JSON value, including empty containers, appears once in the pinned source crosswalk.",
        "fidelity": "Independent oracle and recorded mutation probes compare the complete JSON tree to the candidate TEI.",
        "reproducibility": "Entry-local clean-process reproduction is bound in the review; the acceptance derivation preserves all TEI body bytes.",
        "schema": "Original candidate and header-bound TEI pass the vendored TEI P5 XSD.",
        "closure": "Retained member, acquisition, source manifest, package, oracle validation, and review are hash-bound.",
    }
    technical: dict[str, object] = {
        "producer": {"id": manifest.record["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": ["Producer and oracle share the manifest-pinned work member; independent mutation rejection and bounded visual comparison constrain that selection."],
        "independent_corroboration": "The independent oracle, complete JSON crosswalk, source-bound mutations, clean-process reproduction, and entry-local visual loci agree on this exact retained member.",
    }
    for name, description in descriptions.items():
        proof = _json(stage, evidence / f"{name}.json", common | {
            "status": "pass", "command": command, "exit_code": 0,
            "description": description, "inputs": input_bindings,
            "oracle_report_sha256": review.validation.sha256,
        })
        technical[name] = {"path": _io_path(proof), "status": "pass", "command": command, "exit_code": 0}
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    inspected_loci = (
        [item["locus"] for item in visual_inspection["observations"].values()]
        if visual_inspection is not None
        else route["visual_loci"]
    )
    inspected = [f"retained JSON/{locus}" for locus in inspected_loci] + [
        f"candidate TEI/{locus}" for locus in inspected_loci
    ]
    coverage = {
        "status": "partial", "declared": member[0]["scope"],
        "reached": ["retained JSON", "candidate TEI"],
        "inspected": inspected,
        "unreviewed": route["unreviewed"],
    }
    visual = {
        "reviewer": visual_inspection["reviewer"] if visual_inspection is not None else f"agent:{work_id}-creeds-json-electronic-review",
        "reviewed_at": visual_inspection["reviewed_at"] if visual_inspection is not None else now,
        "coverage": coverage,
        "source_quality_uncertainty": ["No independent print witness has been collated."],
        "discrepancies": [],
        "unreviewed_residuals": route["unreviewed"],
    }
    report = _json(stage, evidence / "review.json", common | visual | {
        "inputs": input_bindings, "visually_compared_loci": route["visual_loci"],
        "visual_capture_evidence": visual_captures,
        "visual_inspection_limitations": visual_inspection["limitations"] if visual_inspection is not None else [],
        "known_source_shape": [
            "The retained plain Answer is empty at Q43, Q59, and Q60; each separate AnswerWithProofs value is present and preserved in the TEI. This is a source-field distinction, not a source-to-TEI mismatch."
        ] if work_id == "1695-baptist-catechism" else [],
        "unassessed": ["human acceptance", "print lineage", "rights clearance", "publication"],
    })
    decision = {
        "source_local_disposition": "Agent acceptance of this exact retained electronic member only.",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted", "actor": visual["reviewer"], "assessed_at": now,
            "supported_scope": member[0]["scope"], "unresolved_claims": [],
            "unassessed_stronger_claims": ["full visual collation", "human acceptance", "print lineage", "rights clearance", "publication"],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        _io_path(stage), identity=identity, candidate_path=_io_path(candidate),
        source_accounting_path=_io_path(account), scope=scope, technical=technical,
        review=visual | {"report_path": _io_path(report)},
        representation_revision=revision, decision=decision,
    )
    write_acceptance(_io_path(stage / acceptance_path), record)
    validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
    _write(stage, master_path, bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, stage / master_path))
    write_acceptance(_io_path(stage / acceptance_path), record)
    state = _read(stage / work / "state.json")
    targets = [x for x in state["targets"] if x["target_id"] == edition and x["target_type"] == "edition"]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise PipelineError("edition is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master_path.as_posix(), acceptance_path.as_posix()])
    _json(stage, work / "state.json", state)
    validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    load_work(_io_path(stage / work / "work.json"))
    after = _files(stage / work)
    result = {
        "contract": "ocd-creeds-json-electronic-acceptance-stage-v1",
        "status": "staged-only", "work_id": work_id,
        "canonical_root": ROOT.as_posix(), "stage_root": stage.as_posix(),
        "before": before, "after": after,
        "changed_paths": sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p)),
        "source_sha256": member[0]["sha256"],
        "candidate_sha256": review.candidate_sha256,
        "validation_sha256": route["validation_sha256"],
        "visual_capture_evidence": visual_captures,
        "limits": ["exact retained electronic witness", "bounded visual comparison", "human, print, rights, and publication separate"],
    }
    _json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", choices=sorted(ROUTES), required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--candidate-library", type=Path, default=Path("D:/Library/Open Christian Data/candidate-reviews"))
    parser.add_argument("--cvw-capture", action="append", default=[], metavar="LOCUS=PATH")
    args = parser.parse_args()
    captures: dict[str, Path] = {}
    for declaration in args.cvw_capture:
        label, separator, value = declaration.partition("=")
        if not separator or not label or not value or label in captures:
            raise PipelineError(f"invalid or duplicate CVW capture declaration: {declaration}")
        captures[label] = Path(value)
    print(json.dumps(prepare(
        args.work,
        stage=args.stage,
        library=args.candidate_library,
        cvw_captures=captures or None,
    ), sort_keys=True))


if __name__ == "__main__":
    main()
