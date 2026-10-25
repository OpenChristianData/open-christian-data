from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from lxml import etree

from build.tools.stage_creeds_json_acceptance import (
    CORRESPONDENCE_ABSENT_WARNING,
    OUTSIDE_SEGMENT_WARNING,
    ROUTES,
    _revision_id,
    _verify_visual_captures,
    _verify_visual_inspection,
    _verify_source_accounting,
)
from ocd_kernel.library._common import PipelineError


WORK_ID = "1695-baptist-catechism"
SOURCE_MANIFEST_SHA256 = "d" * 64
SOURCE_SHA256 = "a" * 64
PACKAGE_SHA256 = "b" * 64
TEI_SHA256 = "c" * 64
QUESTION = "What shall be done to the Wicked at the Day of Judgment?"
LOCATION = "lib062-1695-baptist-catechism-row-0043-question"
SOURCE_PATH = "raw/Creeds.json/creeds/1695_baptist_catechism.json"
FRAME_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lZsAAAAASUVORK5CYII="
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _capture_bundle(root: Path, *, right_sha256: str = TEI_SHA256) -> Path:
    root.mkdir()
    origin = "http://127.0.0.1:61620"
    route_path = f"/review/works/{WORK_ID}"
    query = urlencode(
        [
            ("mode", "compare"),
            ("leftStage", "source"),
            ("leftArtifact", f"source-{SOURCE_MANIFEST_SHA256}"),
            ("leftVersion", SOURCE_MANIFEST_SHA256),
            ("leftLocation", "start"),
            ("rightStage", "tei"),
            ("rightArtifact", f"tei-{PACKAGE_SHA256}"),
            ("rightVersion", PACKAGE_SHA256),
            ("rightLocation", LOCATION),
            ("linked", "false"),
            ("correspondence", "absent"),
        ]
    )
    route = f"{route_path}?{query}"
    session = {
        "session_id": "test-session",
        "origin": origin,
        "implementation_sha256": "e" * 64,
        "catalog_sha256": None,
        "candidate_sha256": [PACKAGE_SHA256],
    }
    files = {
        "frame.png": FRAME_PNG,
        "compare.json": json.dumps(
            {
                "route_digest": "route-digest",
                "left": {
                    "stage": {"id": "source"},
                    "artifact": {
                        "id": f"source-{SOURCE_MANIFEST_SHA256}",
                        "version": SOURCE_MANIFEST_SHA256,
                        "sha256": SOURCE_SHA256,
                    },
                    "location": {"value": "start"},
                    "location_state": "in-range",
                    "paging": {"mode": "segments", "segments": [{"index": 0, "scalar_count": 49745}]},
                },
                "right": {
                    "stage": {"id": "tei"},
                    "artifact": {
                        "id": f"tei-{PACKAGE_SHA256}",
                        "version": PACKAGE_SHA256,
                        "sha256": right_sha256,
                    },
                    "location": {"value": LOCATION},
                    "location_state": "in-range",
                    "paging": {"mode": "segments", "segments": [{"index": 82, "scalar_count": 255}]},
                },
            }
        ).encode(),
        "session.json": json.dumps({"session": session | {"state": "ready"}}).encode(),
    }
    for name, payload in files.items():
        (root / name).write_bytes(payload)
    record = {
        "contract": "ocd-cvw-capture-bundle-v1",
        "files": {name: _sha(payload) for name, payload in files.items()},
        "session": session,
        "browser_state": {
            "url": f"{origin}{route}",
            "route": route,
            "route_digest": "route-digest",
        },
        "page_errors": [],
        "warnings": [CORRESPONDENCE_ABSENT_WARNING],
        "targets": {
            "left": {
                "literal": '"Number": 43,',
                "scope_selector": "pre",
                "scope_prefix": "{",
                "visible": True,
            },
            "right": {
                "literal": QUESTION,
                "scope_selector": "article.artifact-content p",
                "scope_prefix": QUESTION,
                "visible": True,
            },
        },
    }
    (root / "capture.json").write_text(json.dumps(record), encoding="utf-8")
    return root


def _route() -> dict[str, object]:
    return ROUTES[WORK_ID] | {
        "candidate": WORK_ID,
        "visual_capture_locations": {
            "q43": {"number": 43, "question": QUESTION, "right_location": LOCATION}
        },
    }


def test_visual_capture_must_bind_exact_source_candidate_and_visible_locus(tmp_path: Path) -> None:
    capture = _capture_bundle(tmp_path / "q43")

    result = _verify_visual_captures(
        {"q43": capture},
        route=_route(),
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_sha256=SOURCE_SHA256,
        candidate_sha256=PACKAGE_SHA256,
        tei_sha256=TEI_SHA256,
    )

    assert result["q43"]["locus"] == "Q43"
    assert result["q43"]["frame_sha256"] == _sha((capture / "frame.png").read_bytes())


def test_visual_capture_rejects_a_different_tei_artifact(tmp_path: Path) -> None:
    capture = _capture_bundle(tmp_path / "q43", right_sha256="f" * 64)

    with pytest.raises(PipelineError, match="exact source/TEI pair"):
        _verify_visual_captures(
            {"q43": capture},
            route=_route(),
            source_manifest_sha256=SOURCE_MANIFEST_SHA256,
            source_sha256=SOURCE_SHA256,
            candidate_sha256=PACKAGE_SHA256,
            tei_sha256=TEI_SHA256,
        )


def test_1695_route_requires_every_declared_systematic_locus() -> None:
    with pytest.raises(PipelineError, match="labels must be exactly"):
        _verify_visual_captures(
            None,
            route=ROUTES[WORK_ID],
            source_manifest_sha256=SOURCE_MANIFEST_SHA256,
            source_sha256=SOURCE_SHA256,
            candidate_sha256=PACKAGE_SHA256,
            tei_sha256=TEI_SHA256,
        )


def test_segment_one_capture_binds_the_selected_source_segment_and_known_warning(tmp_path: Path) -> None:
    capture = _capture_bundle(tmp_path / "q43")
    record_path = capture / "capture.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    route = record["browser_state"]["route"] + "&leftSegmentStart=1&leftSegmentLimit=1"
    record["browser_state"]["route"] = route
    record["browser_state"]["url"] = "http://127.0.0.1:61620" + route
    record["warnings"] = [CORRESPONDENCE_ABSENT_WARNING, OUTSIDE_SEGMENT_WARNING]

    compare_path = capture / "compare.json"
    compare = json.loads(compare_path.read_text(encoding="utf-8"))
    compare["left"]["location_state"] = "location-outside-range"
    compare["left"]["paging"] = {"mode": "segments", "segments": [{"index": 1, "scalar_count": 36892}]}
    compare_bytes = json.dumps(compare).encode()
    compare_path.write_bytes(compare_bytes)
    record["files"]["compare.json"] = _sha(compare_bytes)
    record_path.write_text(json.dumps(record), encoding="utf-8")

    route_config = _route() | {
        "visual_capture_locations": {
            "q43": {"number": 43, "question": QUESTION, "right_location": LOCATION, "source_segment_start": 1}
        }
    }
    result = _verify_visual_captures(
        {"q43": capture},
        route=route_config,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_sha256=SOURCE_SHA256,
        candidate_sha256=PACKAGE_SHA256,
        tei_sha256=TEI_SHA256,
    )

    assert result["q43"]["warnings"] == [CORRESPONDENCE_ABSENT_WARNING, OUTSIDE_SEGMENT_WARNING]

    compare["left"]["paging"]["segments"][0]["index"] = 0
    compare_bytes = json.dumps(compare).encode()
    compare_path.write_bytes(compare_bytes)
    record["files"]["compare.json"] = _sha(compare_bytes)
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(PipelineError, match="source segment selection differs"):
        _verify_visual_captures(
            {"q43": capture},
            route=route_config,
            source_manifest_sha256=SOURCE_MANIFEST_SHA256,
            source_sha256=SOURCE_SHA256,
            candidate_sha256=PACKAGE_SHA256,
            tei_sha256=TEI_SHA256,
        )


def test_visual_inspection_requires_independent_pixel_review_bound_to_capture(tmp_path: Path) -> None:
    capture = _capture_bundle(tmp_path / "q43")
    captures = _verify_visual_captures(
        {"q43": capture},
        route=_route(),
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_sha256=SOURCE_SHA256,
        candidate_sha256=PACKAGE_SHA256,
        tei_sha256=TEI_SHA256,
    )
    visual_review = {
        "contract": "ocd-agent-cvw-visual-review-v1",
        "reviewed_at": "2026-09-29T08:03:55Z",
        "reviewer": {
            "type": "agent",
            "id": "agent:independent-reviewer",
            "independent_of_work_owner": True,
        },
        "source": {
            "path": SOURCE_PATH,
            "manifest_sha256": SOURCE_MANIFEST_SHA256,
            "sha256": SOURCE_SHA256,
        },
        "candidate": {"package_sha256": PACKAGE_SHA256, "tei_sha256": TEI_SHA256},
        "session_id": "test-session",
        "loci": [
            {
                "label": "q43",
                "number": 43,
                "source_anchor": '"Number": 43,',
                "candidate_anchor": QUESTION,
                "capture_sha256": captures["q43"]["capture_sha256"],
                "frame_sha256": captures["q43"]["frame_sha256"],
                "observation": "The visible wording aligns.",
            }
        ],
        "limitations": ["One selected locus only."],
    }

    result = _verify_visual_inspection(
        visual_review,
        captures=captures,
        route=_route(),
        source_path=SOURCE_PATH,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_sha256=SOURCE_SHA256,
        candidate_sha256=PACKAGE_SHA256,
        tei_sha256=TEI_SHA256,
    )

    assert result["reviewer"] == "agent:independent-reviewer"
    assert result["observations"]["q43"]["locus"] == "Q43"

    visual_review["loci"][0]["frame_sha256"] = "f" * 64
    with pytest.raises(PipelineError, match="not bound to the inspected pixels"):
        _verify_visual_inspection(
            visual_review,
            captures=captures,
            route=_route(),
            source_path=SOURCE_PATH,
            source_manifest_sha256=SOURCE_MANIFEST_SHA256,
            source_sha256=SOURCE_SHA256,
            candidate_sha256=PACKAGE_SHA256,
            tei_sha256=TEI_SHA256,
        )


def test_capture_rejects_non_png_frame(tmp_path: Path) -> None:
    capture = _capture_bundle(tmp_path / "q43")
    (capture / "frame.png").write_bytes(b"not png")
    record = json.loads((capture / "capture.json").read_text(encoding="utf-8"))
    record["files"]["frame.png"] = _sha(b"not png")
    (capture / "capture.json").write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(PipelineError, match="not a PNG image"):
        _verify_visual_captures(
            {"q43": capture},
            route=_route(),
            source_manifest_sha256=SOURCE_MANIFEST_SHA256,
            source_sha256=SOURCE_SHA256,
            candidate_sha256=PACKAGE_SHA256,
            tei_sha256=TEI_SHA256,
        )


def test_source_accounting_requires_complete_exact_leaf_crosswalk() -> None:
    source = json.dumps(
        {"Metadata": {"Title": "A title"}, "Data": [{"Number": 1, "Proofs": []}]},
        separators=(",", ":"),
    ).encode()
    accounting = {
        "contract": "ocd-lib062-source-accountability-v1",
        "work_id": WORK_ID,
        "source_member_disposition": "included in full as sole authority",
        "top_level_keys": ["Metadata", "Data"],
        "data_record_count": 1,
        "omitted_leaf_count": 0,
        "duplicate_leaf_count": 0,
        "represented_leaf_count": 3,
        "crosswalk": [
            {"pointer": "/Metadata/Title", "disposition": "represented", "value": "A title", "tei_target": "#title"},
            {"pointer": "/Data/0/Number", "disposition": "represented", "value": 1, "tei_target": "#number"},
            {"pointer": "/Data/0/Proofs", "disposition": "represented", "value": [], "tei_target": "#proofs"},
        ],
    }

    result = _verify_source_accounting(accounting, source, WORK_ID)
    assert result["represented_leaf_count"] == 3
    assert result["omitted_leaf_count"] == 0

    accounting["crosswalk"][0]["value"] = "invented"
    with pytest.raises(PipelineError, match="does not map every source leaf"):
        _verify_source_accounting(accounting, source, WORK_ID)


def test_revision_id_is_valid_xml_id_for_numeric_work_id() -> None:
    revision_id = _revision_id(WORK_ID)
    document = etree.fromstring(f'<revision xml:id="{revision_id}" xmlns:xml="http://www.w3.org/XML/1998/namespace"/>')
    assert document.get("{http://www.w3.org/XML/1998/namespace}id") == revision_id
