"""Focused outer-carrier regressions for the retained Westminster HTML."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from build.tei.westminster_shorter_catechism_carrier_census import (
    html_carrier_census,
    verify_html_carrier_census,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = (
    ROOT / "sources/catechisms/westminster-shorter-catechism/"
    "westminster-shorter-catechism.outer-html-profile.json"
)


def _profile() -> dict[str, object]:
    value = json.loads(PROFILE_PATH.read_bytes())
    assert isinstance(value, dict)
    return value


def _retained_html(profile: dict[str, object]) -> bytes:
    authority = profile["authority"]
    assert isinstance(authority, dict)
    path = resolve_repo_path(ROOT, str(authority["path"]))
    content = path.read_bytes()
    assert len(content) == authority["bytes"]
    assert hashlib.sha256(content).hexdigest() == authority["sha256"]
    return content


def test_exact_retained_html_matches_complete_outer_carrier_receipt() -> None:
    profile = _profile()
    census = profile["census"]
    assert isinstance(census, dict)
    assert verify_html_carrier_census(_retained_html(profile), census) == census
    assert census["paragraph_classes"] == {
        "assigned_questions": 107,
        "assigned_proof_groups": 107,
        "outer_evidence_only": 26,
    }
    assert census["elements"]["by_disposition"] == {
        "assigned-content": 647,
        "outer-evidence-only": 397,
    }
    assert census["attributes"]["by_disposition"] == {
        "assigned-content": 215,
        "outer-evidence-only": 823,
    }
    assert census["nonempty_text_carriers"]["by_disposition"] == {
        "assigned-content": 538,
        "outer-evidence-only": 107,
    }
    assert census["comments"]["by_disposition"] == {
        "outer-evidence-only": 22,
    }


def test_outer_evidence_text_change_fails_even_when_counts_are_unchanged() -> None:
    profile = _profile()
    census = profile["census"]
    assert isinstance(census, dict)
    content = _retained_html(profile)
    mutated = content.replace(
        b"The Westminster Standard.",
        b"The Westminster StandarD.",
        1,
    )
    observed = html_carrier_census(mutated)
    assert observed["elements"]["total"] == census["elements"]["total"]
    assert observed["attributes"]["total"] == census["attributes"]["total"]
    with pytest.raises(ValueError, match="outer-carrier census drifted"):
        verify_html_carrier_census(mutated, census)


def test_unexpected_outer_element_fails_closed() -> None:
    profile = _profile()
    census = profile["census"]
    assert isinstance(census, dict)
    content = _retained_html(profile)
    mutated = content.replace(b"</body>", b"<aside>Invented</aside></body>", 1)
    with pytest.raises(ValueError, match="outer-carrier census drifted"):
        verify_html_carrier_census(mutated, census)


def test_profile_preserves_human_rights_and_publication_boundaries() -> None:
    boundaries = _profile()["boundaries"]
    assert boundaries == {
        "textual_and_edition_acceptance": (
            "unresolved; no retained authority selects or reconciles a provider reading"
        ),
        "rights_clearance": False,
        "human_acceptance": False,
        "canonical_promotion_authorized": False,
        "publication_authorized": False,
    }
