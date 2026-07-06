"""Tests for Track-C adjudication worksheet builder.

TDD: failing tests written before implementation.
Non-circularity invariant: gold_text column is ALWAYS blank — the human fills it
from the scan image, never from candidate readings.
"""
from build.tools.ocr_pipeline.build_track_c_worksheet import (
    build_worksheet_row,
    _get_script_label,
    _get_candidate_readings,
    sample_positions,
)

FIXTURE_LATIN_DISAGREE = {
    "position_id": "vol_01:page_0010:body:c1:l000:p000",
    "script": {
        "image_level": {"label": "latin", "confidence": 1.0, "method": "unicode-block-fallback"},
        "text_level": {"label": "latin", "method": "unicode-block"},
        "routing": "normal-latin",
    },
    "reference_bbox": {"x": 1170, "y": 697, "w": 259, "h": 49},
    "candidate_set": [
        {
            "candidate_id": "cand_001",
            "raw_reading": "Abelard",
            "candidate_key": "Abelard",
            "attesting_engines": ["tesseract-py314-v1"],
            "attesting_families": ["tesseract"],
        },
        {
            "candidate_id": "cand_002",
            "raw_reading": "Abalard",
            "candidate_key": "Abalard",
            "attesting_engines": ["ia-abbyy-v1"],
            "attesting_families": ["abbyy"],
        },
    ],
}

FIXTURE_GREEK = {
    "position_id": "vol_01:page_0241:body:c1:l012:p003",
    "script": {
        "image_level": {"label": "greek", "confidence": 0.95, "method": "unicode-block"},
        "text_level": {"label": "greek", "method": "unicode-block"},
    },
    "reference_bbox": {"x": 500, "y": 1200, "w": 100, "h": 45},
    "candidate_set": [
        {
            "candidate_id": "cand_001",
            "raw_reading": "αβα",
            "candidate_key": "αβα",
            "attesting_engines": ["tesseract-py314-v1"],
            "attesting_families": ["tesseract"],
        },
    ],
}

FIXTURE_NO_CANDIDATES = {
    "position_id": "vol_01:page_0010:body:c1:l005:p000",
    "script": {"text_level": {"label": "latin", "method": "unicode-block"}},
    "reference_bbox": {"x": 100, "y": 200, "w": 50, "h": 30},
    "candidate_set": [],
}

FIXTURE_SINGLE_CANDIDATE = {
    "position_id": "vol_01:page_0010:body:c1:l000:p001",
    "script": {"text_level": {"label": "latin", "method": "unicode-block"}},
    "reference_bbox": {"x": 300, "y": 400, "w": 80, "h": 35},
    "candidate_set": [
        {
            "candidate_id": "cand_001",
            "raw_reading": "Aaron",
            "candidate_key": "Aaron",
            "attesting_engines": ["tesseract-py314-v1"],
            "attesting_families": ["tesseract"],
        }
    ],
}


class TestBuildWorksheetRow:
    def test_required_columns_present(self):
        row = build_worksheet_row(FIXTURE_LATIN_DISAGREE, "raw/vol_01/page_0010.jpg", "page_0010")
        for col in (
            "position_id",
            "page_id",
            "scan_path",
            "bbox_x",
            "bbox_y",
            "bbox_w",
            "bbox_h",
            "script_label",
            "gold_text",
            "engine_guesses_do_not_copy",
        ):
            assert col in row, f"Missing required column: {col}"

    def test_gold_text_always_blank_for_disagreement_position(self):
        """Non-circularity: gold_text must NEVER be pre-filled from candidates."""
        row = build_worksheet_row(FIXTURE_LATIN_DISAGREE, "raw/vol_01/page_0010.jpg", "page_0010")
        assert row["gold_text"] == "", "gold_text must be blank; human fills from scan"

    def test_gold_text_always_blank_for_single_candidate(self):
        """Even when only one engine agrees, gold_text stays blank."""
        row = build_worksheet_row(FIXTURE_SINGLE_CANDIDATE, "raw/vol_01/page_0010.jpg", "page_0010")
        assert row["gold_text"] == ""

    def test_gold_text_always_blank_even_when_all_engines_agree(self):
        """All-engine consensus does not pre-fill gold_text — the human still adjudicates."""
        pos = {
            **FIXTURE_SINGLE_CANDIDATE,
            "candidate_set": [
                {**FIXTURE_SINGLE_CANDIDATE["candidate_set"][0], "attesting_engines": ["te", "abbyy", "az"]},
            ],
        }
        row = build_worksheet_row(pos, "raw/vol_01/page_0010.jpg", "page_0010")
        assert row["gold_text"] == ""

    def test_engine_guesses_populated_for_disagreement(self):
        row = build_worksheet_row(FIXTURE_LATIN_DISAGREE, "raw/vol_01/page_0010.jpg", "page_0010")
        guesses = row["engine_guesses_do_not_copy"]
        assert "Abelard" in guesses
        assert "Abalard" in guesses

    def test_engine_guesses_populated_for_single_candidate(self):
        row = build_worksheet_row(FIXTURE_SINGLE_CANDIDATE, "raw/vol_01/page_0010.jpg", "page_0010")
        assert "Aaron" in row["engine_guesses_do_not_copy"]

    def test_engine_guesses_empty_when_no_candidates(self):
        row = build_worksheet_row(FIXTURE_NO_CANDIDATES, "raw/vol_01/page_0010.jpg", "page_0010")
        assert row["engine_guesses_do_not_copy"] == ""

    def test_script_label_from_text_level(self):
        row = build_worksheet_row(FIXTURE_LATIN_DISAGREE, "raw/vol_01/page_0010.jpg", "page_0010")
        assert row["script_label"] == "latin"

    def test_script_label_greek(self):
        row = build_worksheet_row(FIXTURE_GREEK, "raw/vol_01/page_0241.jpg", "page_0241")
        assert row["script_label"] == "greek"

    def test_bbox_fields(self):
        row = build_worksheet_row(FIXTURE_LATIN_DISAGREE, "raw/vol_01/page_0010.jpg", "page_0010")
        assert row["bbox_x"] == 1170
        assert row["bbox_y"] == 697
        assert row["bbox_w"] == 259
        assert row["bbox_h"] == 49

    def test_position_and_page_id(self):
        row = build_worksheet_row(FIXTURE_LATIN_DISAGREE, "raw/vol_01/page_0010.jpg", "page_0010")
        assert row["position_id"] == "vol_01:page_0010:body:c1:l000:p000"
        assert row["page_id"] == "page_0010"
        assert row["scan_path"] == "raw/vol_01/page_0010.jpg"


class TestGetScriptLabel:
    def test_text_level_takes_precedence_over_image_level(self):
        pos = {
            "script": {
                "text_level": {"label": "greek"},
                "image_level": {"label": "latin"},
            }
        }
        assert _get_script_label(pos) == "greek"

    def test_falls_back_to_image_level_when_no_text_level(self):
        pos = {"script": {"image_level": {"label": "hebrew"}}}
        assert _get_script_label(pos) == "hebrew"

    def test_string_script(self):
        assert _get_script_label({"script": "latin"}) == "latin"

    def test_missing_script_returns_unknown(self):
        assert _get_script_label({}) == "unknown"

    def test_none_script_returns_unknown(self):
        assert _get_script_label({"script": None}) == "unknown"


class TestGetCandidateReadings:
    def test_multiple_candidates_returned(self):
        readings = _get_candidate_readings(FIXTURE_LATIN_DISAGREE)
        assert readings == ["Abelard", "Abalard"]

    def test_single_candidate(self):
        readings = _get_candidate_readings(FIXTURE_SINGLE_CANDIDATE)
        assert readings == ["Aaron"]

    def test_empty_candidate_set(self):
        assert _get_candidate_readings(FIXTURE_NO_CANDIDATES) == []

    def test_deduplicates_identical_readings(self):
        pos = {
            "candidate_set": [
                {"raw_reading": "Same", "candidate_key": "Same"},
                {"raw_reading": "Same", "candidate_key": "Same"},
            ]
        }
        assert _get_candidate_readings(pos) == ["Same"]

    def test_uses_raw_reading_before_candidate_key(self):
        pos = {
            "candidate_set": [
                {"raw_reading": "FromRaw", "candidate_key": "FromKey"},
            ]
        }
        assert _get_candidate_readings(pos) == ["FromRaw"]

    def test_falls_back_to_candidate_key_when_no_raw_reading(self):
        pos = {
            "candidate_set": [
                {"raw_reading": None, "candidate_key": "FromKey"},
            ]
        }
        assert _get_candidate_readings(pos) == ["FromKey"]


class TestSamplePositions:
    """Tests for stratified position sampling."""

    def _make_page(self, page_id, positions):
        return {
            "page_id": page_id,
            "source_image": {"path": f"raw/vol_01/{page_id}.jpg"},
            "positions": positions,
        }

    def _latin_pos(self, pos_suffix, n_candidates=1):
        return {
            "position_id": f"vol_01:page_0010:body:c1:l000:{pos_suffix}",
            "script": {"text_level": {"label": "latin", "method": "unicode-block"}},
            "reference_bbox": {"x": 100, "y": 100, "w": 50, "h": 30},
            "candidate_set": [
                {"raw_reading": f"word{i}", "candidate_key": f"word{i}"}
                for i in range(n_candidates)
            ],
        }

    def _greek_pos(self, pos_suffix):
        return {
            "position_id": f"vol_01:page_0241:body:c1:l000:{pos_suffix}",
            "script": {"text_level": {"label": "greek", "method": "unicode-block"}},
            "reference_bbox": {"x": 100, "y": 100, "w": 50, "h": 30},
            "candidate_set": [{"raw_reading": "αβ", "candidate_key": "αβ"}],
        }

    def test_respects_stratum_counts(self):
        pages = [
            self._make_page(
                "page_0010",
                [self._latin_pos(f"p{i:03d}", n_candidates=2) for i in range(20)]
                + [self._latin_pos(f"p{i:03d}") for i in range(20, 40)],
            )
        ]
        strategy = {"latin_disagree": 5, "latin_agree": 3, "greek": 0, "hebrew": 0}
        rows = sample_positions(pages, strategy)
        latin_disagree = [r for r in rows if r["script_label"] == "latin" and "|" in r["engine_guesses_do_not_copy"]]
        latin_agree = [r for r in rows if r["script_label"] == "latin" and "|" not in r["engine_guesses_do_not_copy"]]
        assert len(latin_disagree) == 5
        assert len(latin_agree) == 3

    def test_gold_text_blank_in_all_sampled_rows(self):
        pages = [
            self._make_page(
                "page_0010",
                [self._latin_pos(f"p{i:03d}", n_candidates=2) for i in range(10)],
            )
        ]
        strategy = {"latin_disagree": 5, "latin_agree": 0, "greek": 0, "hebrew": 0}
        rows = sample_positions(pages, strategy)
        for row in rows:
            assert row["gold_text"] == "", "Sampled rows must have blank gold_text"

    def test_greek_positions_included(self):
        pages = [
            self._make_page(
                "page_0241",
                [self._greek_pos(f"p{i:03d}") for i in range(10)],
            )
        ]
        strategy = {"latin_disagree": 0, "latin_agree": 0, "greek": 5, "hebrew": 0}
        rows = sample_positions(pages, strategy)
        assert len(rows) == 5
        assert all(r["script_label"] == "greek" for r in rows)

    def test_capped_at_available_positions(self):
        pages = [
            self._make_page(
                "page_0010",
                [self._latin_pos(f"p{i:03d}", n_candidates=2) for i in range(3)],
            )
        ]
        strategy = {"latin_disagree": 100, "latin_agree": 0, "greek": 0, "hebrew": 0}
        rows = sample_positions(pages, strategy)
        assert len(rows) == 3  # only 3 available
