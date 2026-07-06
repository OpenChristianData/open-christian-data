from __future__ import annotations

import json
from pathlib import Path

from build.lib import review_state
from build.lib.lexicons import grc, en, hbo_latn, la
from build.tools.text_confidence_report import build_confidence_report


def test_lexicon_status_constants_and_counts() -> None:
    assert en.COVERAGE_STATUS == "production"
    assert len(en.ARCHAIC_FORMS) >= 200
    assert not [key for key, value in en.ARCHAIC_FORMS.items() if key.casefold() == value.casefold()]
    assert grc.COVERAGE_STATUS == "seed_only"
    assert hbo_latn.COVERAGE_STATUS == "seed_only"
    assert la.COVERAGE_STATUS == "seed_only"
    assert len(grc.ARCHAIC_FORMS) >= 10
    assert len(hbo_latn.ARCHAIC_FORMS) >= 10
    assert len(la.ARCHAIC_FORMS) >= 10


def test_dominant_greek_seed_only_lexicon_blocks_reference_grade_text_fidelity(tmp_path: Path) -> None:
    record = tmp_path / "data" / "reference" / "sample.json"
    payload = {
        "meta": {"schema_type": "reference_entry", "schema_version": "2.1.0", "id": "sample", "language": "grc"},
        "data": [
            {
                "entry_id": "sample.greek",
                "term": "αντιλεγομενα",
                "alt_terms": [],
                "definition_blocks": ["αντιλεγομενα εκκληϲια λογοϲ κοϲμοϲ"],
            }
        ],
    }
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(payload), encoding="utf-8")
    sidecar = tmp_path / "review" / "state" / "reference" / "sample.json"
    sidecar_payload = review_state.empty_sidecar(
        record_path=str(record),
        record_resource_id="sample",
        record_checksum_sha256="0" * 64,
        parser_version_seen="parser@v1",
    )
    sidecar_payload["confidence"] = {
        "structural_fidelity": "reference-grade",
        "text_fidelity": "reference-grade",
        "edition_provenance": "reference-grade",
    }
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(sidecar_payload), encoding="utf-8")

    report = build_confidence_report(record, sidecar_path=sidecar)

    assert report["confidence_axes"]["text_fidelity"] == "human-reviewed"
    assert report["tier"] != "reference-grade"
    assert any("dominant language grc uses seed_only" in blocker for blocker in report["blockers"])
