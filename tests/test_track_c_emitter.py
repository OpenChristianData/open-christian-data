"""Tests for Track-C gold emitter and validator.

TDD: failing tests written before implementation.

Core invariant: blank gold_text is OMITTED from the output, never fabricated.
A single engine-derived value in the gold silently corrupts the transfer measurement
and there is no automated check that catches it afterward.
"""
import json
import pathlib
import pytest
from build.tools.ocr_pipeline.emit_track_c_gold import (
    emit_gold_page,
    validate_gold_file,
    emit_gold_corpus,
)

ROWS_MIXED = [
    {
        "position_id": "vol_01:page_0010:body:c1:l000:p000",
        "page_id": "page_0010",
        "gold_text": "Abelard",
        "engine_guesses_do_not_copy": "Abalard | Abbelard",
    },
    {
        "position_id": "vol_01:page_0010:body:c1:l000:p001",
        "page_id": "page_0010",
        "gold_text": "",  # human didn't fill — omit, not fabricate
        "engine_guesses_do_not_copy": "NEW | new",
    },
    {
        "position_id": "vol_01:page_0010:body:c1:l000:p002",
        "page_id": "page_0010",
        "gold_text": "  ",  # whitespace-only — treat as blank
        "engine_guesses_do_not_copy": "the",
    },
]

ROWS_ALL_BLANK = [
    {
        "position_id": "vol_01:page_0010:body:c1:l000:p000",
        "page_id": "page_0010",
        "gold_text": "",
        "engine_guesses_do_not_copy": "Abelard",
    },
    {
        "position_id": "vol_01:page_0010:body:c1:l000:p001",
        "page_id": "page_0010",
        "gold_text": "",
        "engine_guesses_do_not_copy": "NEW",
    },
]


class TestEmitGoldPage:
    def test_output_has_positions_key(self):
        result = emit_gold_page(ROWS_MIXED)
        assert "positions" in result

    def test_filled_positions_included(self):
        result = emit_gold_page(ROWS_MIXED)
        assert "vol_01:page_0010:body:c1:l000:p000" in result["positions"]
        assert result["positions"]["vol_01:page_0010:body:c1:l000:p000"]["gold_text"] == "Abelard"

    def test_blank_gold_text_omitted_not_fabricated(self):
        """Non-circularity: a blank row is absent from output, not filled from engine guesses."""
        result = emit_gold_page(ROWS_MIXED)
        assert "vol_01:page_0010:body:c1:l000:p001" not in result["positions"]

    def test_whitespace_only_gold_text_omitted(self):
        result = emit_gold_page(ROWS_MIXED)
        assert "vol_01:page_0010:body:c1:l000:p002" not in result["positions"]

    def test_engine_guesses_never_bleed_into_gold_text(self):
        """For blank rows, engine_guesses_do_not_copy must not appear as gold_text."""
        result = emit_gold_page(ROWS_MIXED)
        for pid, entry in result["positions"].items():
            row = next(r for r in ROWS_MIXED if r["position_id"] == pid)
            if not row["gold_text"].strip():
                assert pid not in result["positions"], "Blank row must not appear in output"
            else:
                assert entry["gold_text"] == row["gold_text"].strip()

    def test_all_blank_produces_empty_positions(self):
        result = emit_gold_page(ROWS_ALL_BLANK)
        assert result["positions"] == {}

    def test_gold_text_is_stripped(self):
        rows = [
            {
                "position_id": "vol_01:page_0010:body:c1:l000:p000",
                "page_id": "page_0010",
                "gold_text": "  Trim me  ",
                "engine_guesses_do_not_copy": "",
            }
        ]
        result = emit_gold_page(rows)
        assert result["positions"]["vol_01:page_0010:body:c1:l000:p000"]["gold_text"] == "Trim me"

    def test_only_positions_key_in_output(self):
        """Ensure no extra keys are emitted that would confuse the harness."""
        result = emit_gold_page(ROWS_MIXED)
        assert set(result.keys()) == {"positions"}


class TestValidateGoldFile:
    def test_valid_file_passes(self, tmp_path):
        gold = {
            "positions": {
                "vol_01:page_0010:body:c1:l000:p000": {"gold_text": "Aaron"},
                "vol_01:page_0010:body:c1:l000:p001": {"gold_text": "ben"},
            }
        }
        path = tmp_path / "page_0010.gold.json"
        path.write_text(json.dumps(gold), encoding="utf-8")
        validate_gold_file(path)  # must not raise

    def test_missing_positions_key_raises(self, tmp_path):
        path = tmp_path / "page_0010.gold.json"
        path.write_text(json.dumps({"data": {}}), encoding="utf-8")
        with pytest.raises((KeyError, ValueError)):
            validate_gold_file(path)

    def test_empty_gold_text_raises(self, tmp_path):
        gold = {"positions": {"vol_01:page_0010:body:c1:l000:p000": {"gold_text": ""}}}
        path = tmp_path / "page_0010.gold.json"
        path.write_text(json.dumps(gold), encoding="utf-8")
        with pytest.raises(ValueError):
            validate_gold_file(path)

    def test_missing_gold_text_key_raises(self, tmp_path):
        gold = {"positions": {"vol_01:page_0010:body:c1:l000:p000": {"other_field": "x"}}}
        path = tmp_path / "page_0010.gold.json"
        path.write_text(json.dumps(gold), encoding="utf-8")
        with pytest.raises((KeyError, ValueError)):
            validate_gold_file(path)

    def test_harness_loader_roundtrip(self, tmp_path):
        """The emitted file must parse exactly as measure_corrector.py's loader does.

        Reproduces lines 190-192 of measure_corrector.py:
            page_id = gf.stem.removesuffix(".gold")
            gold_corpus[page_id] = json.loads(gf.read_text(encoding="utf-8"))["positions"]
        """
        gold = {
            "positions": {
                "vol_01:page_0010:body:c1:l000:p000": {"gold_text": "Aaron"},
                "vol_01:page_0010:body:c1:l000:p001": {"gold_text": "ben"},
            }
        }
        path = tmp_path / "page_0010.gold.json"
        path.write_text(json.dumps(gold), encoding="utf-8")

        # Replicate harness loader
        gf = path
        page_id = gf.stem.removesuffix(".gold")
        loaded = json.loads(gf.read_text(encoding="utf-8"))["positions"]

        assert page_id == "page_0010"
        assert loaded["vol_01:page_0010:body:c1:l000:p000"]["gold_text"] == "Aaron"
        assert loaded["vol_01:page_0010:body:c1:l000:p001"]["gold_text"] == "ben"


class TestEmitGoldCorpus:
    def test_groups_rows_by_page_id(self, tmp_path):
        rows = [
            {
                "position_id": "vol_01:page_0010:body:c1:l000:p000",
                "page_id": "page_0010",
                "gold_text": "Aaron",
                "engine_guesses_do_not_copy": "Aaron",
            },
            {
                "position_id": "vol_01:page_0011:body:c1:l000:p000",
                "page_id": "page_0011",
                "gold_text": "God",
                "engine_guesses_do_not_copy": "God",
            },
        ]
        emit_gold_corpus(rows, tmp_path)
        assert (tmp_path / "page_0010.gold.json").exists()
        assert (tmp_path / "page_0011.gold.json").exists()

    def test_page_with_all_blank_entries_not_written(self, tmp_path):
        """A page where every human entry is blank produces no gold file."""
        rows = [
            {
                "position_id": "vol_01:page_0010:body:c1:l000:p000",
                "page_id": "page_0010",
                "gold_text": "",
                "engine_guesses_do_not_copy": "Aaron",
            },
        ]
        emit_gold_corpus(rows, tmp_path)
        assert not (tmp_path / "page_0010.gold.json").exists()

    def test_written_files_pass_validation(self, tmp_path):
        rows = [
            {
                "position_id": "vol_01:page_0010:body:c1:l000:p000",
                "page_id": "page_0010",
                "gold_text": "Aaron",
                "engine_guesses_do_not_copy": "Aaron",
            },
        ]
        emit_gold_corpus(rows, tmp_path)
        validate_gold_file(tmp_path / "page_0010.gold.json")

    def test_written_file_json_structure(self, tmp_path):
        rows = [
            {
                "position_id": "vol_01:page_0010:body:c1:l000:p000",
                "page_id": "page_0010",
                "gold_text": "Abelard",
                "engine_guesses_do_not_copy": "Abalard",
            },
        ]
        emit_gold_corpus(rows, tmp_path)
        data = json.loads((tmp_path / "page_0010.gold.json").read_text(encoding="utf-8"))
        assert data == {
            "positions": {
                "vol_01:page_0010:body:c1:l000:p000": {"gold_text": "Abelard"}
            }
        }

    def test_blank_positions_within_multi_position_page_are_excluded(self, tmp_path):
        rows = [
            {
                "position_id": "vol_01:page_0010:body:c1:l000:p000",
                "page_id": "page_0010",
                "gold_text": "Abelard",
                "engine_guesses_do_not_copy": "Abalard",
            },
            {
                "position_id": "vol_01:page_0010:body:c1:l000:p001",
                "page_id": "page_0010",
                "gold_text": "",  # blank — must not appear
                "engine_guesses_do_not_copy": "NEW",
            },
        ]
        emit_gold_corpus(rows, tmp_path)
        data = json.loads((tmp_path / "page_0010.gold.json").read_text(encoding="utf-8"))
        assert "vol_01:page_0010:body:c1:l000:p001" not in data["positions"]
        assert "vol_01:page_0010:body:c1:l000:p000" in data["positions"]
