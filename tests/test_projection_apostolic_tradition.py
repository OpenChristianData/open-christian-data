"""Focused source-pinned Apostolic Tradition projection regressions."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import apostolic_tradition as producer
from ocd_kernel.projection.categories import apostolic_tradition_check as checker
from ocd_kernel.projection.categories import prose, sermons


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "apostolic-tradition-candidate-20260929-v1/package/content.tei.xml"
)
SOURCE = ROOT / "raw/gutenberg/61614/html/pg61614-images.html"
REVISION = "apostolic-tradition-pg61614-html-body-v1"
TITLE = "Project Gutenberg retained HTML witness"


@pytest.fixture
def projected():
    if not CANDIDATE.is_file() or not SOURCE.is_file():
        pytest.skip("retained Apostolic Tradition evidence is not mounted")
    result = producer.project_document(
        CANDIDATE, identity=producer.IDENTITY, language="en",
        representation_revision=REVISION, edition_title=TITLE, candidate_only=True,
    )
    return result


def _verify(projected_value: dict, *, rows: list[dict] | None = None,
            receipt: dict | None = None) -> list[str]:
    return checker.verify_document(
        CANDIDATE,
        projected_value["rows"] if rows is None else rows,
        projected_value["receipt"] if receipt is None else receipt,
        candidate_only=True, source_path=SOURCE,
        representation_revision=REVISION, edition_title=TITLE,
    )


def test_pinned_complete_eleven_span_candidate(projected, monkeypatch):
    rows = projected["rows"]
    receipt = projected["receipt"]
    assert len(rows) == 11
    assert sum(len(row["text"]) for row in rows) == 207_491
    assert receipt["body_sha256"] == producer.BODY_SHA
    assert len(receipt["inventory"]) == 4_085
    assert len(receipt["source_ids"]) == 731
    assert len(receipt["links"]) == 1_296
    assert receipt["projection_profile"] == producer.PROFILE
    monkeypatch.setattr(producer, "_content", lambda *_: pytest.fail("checker imported producer"))
    assert _verify(projected) == []


def test_checker_rejects_missing_introduction_and_wrong_profile(projected):
    rows = deepcopy(projected["rows"])
    rows.pop(3)
    receipt = deepcopy(projected["receipt"])
    receipt["row_count"] = len(rows)
    receipt["output_sha256"] = sha256(json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    assert _verify(projected, rows=rows, receipt=receipt)

    receipt = deepcopy(projected["receipt"])
    receipt["projection_profile"] = "wrong-profile"
    assert _verify(projected, receipt=receipt)


def test_wrong_identity_fails_closed(projected):
    wrong = producer.IDENTITY | {"work_id": "different-work"}
    with pytest.raises(PipelineError, match="identity/language/provenance"):
        producer.project_document(
            CANDIDATE, identity=wrong, language="en",
            representation_revision=REVISION, edition_title=TITLE,
            candidate_only=True,
        )


def test_accepted_prose_dispatch_preserves_pending_checker_marker(projected, monkeypatch):
    authority = {"acceptance": {"path": "fixture", "sha256": "fixture"}}
    context = {
        "root": ROOT,
        "edition": SimpleNamespace(path=CANDIDATE),
        "identity": producer.IDENTITY,
        "accepted": {"identity": producer.IDENTITY},
        "language": "en",
        "representation_revision": REVISION,
        "edition_title": TITLE,
        "authority": authority,
    }

    def accepted_context(_root, _acceptance_path, *, expected_category="prose"):
        assert expected_category == "prose"
        return context

    monkeypatch.setattr(sermons, "_accepted_context", accepted_context)
    monkeypatch.setattr(prose, "_accepted_projection_profile", lambda *_: producer.PROFILE)
    acceptance_path = ROOT / "fixture-acceptance.json"
    result = prose.project_accepted_prose(ROOT, acceptance_path=acceptance_path)
    assert result["receipt"]["independent_check"] == {"status": "pending"}
    assert prose.verify_accepted_prose(
        ROOT, acceptance_path=acceptance_path,
        rows=result["rows"], receipt=result["receipt"],
    ) == []
    assert result["receipt"]["independent_check"] == {"status": "pending"}

    omitted = deepcopy(result["rows"])
    omitted.pop(3)
    assert prose.verify_accepted_prose(
        ROOT, acceptance_path=acceptance_path,
        rows=omitted, receipt=result["receipt"],
    )
    wrong_profile = deepcopy(result["receipt"])
    wrong_profile["projection_profile"] = "wrong-profile"
    assert prose.verify_accepted_prose(
        ROOT, acceptance_path=acceptance_path,
        rows=result["rows"], receipt=wrong_profile,
    )
