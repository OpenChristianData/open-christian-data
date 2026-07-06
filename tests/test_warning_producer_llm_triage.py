from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.lib.warning_producers import llm_triage


def _candidate(signature: str = "candidate-1") -> dict:
    return {
        "id": "cand-0001",
        "tier": 1,
        "reason": "digit_in_letter",
        "source_id": "schaff-herzog",
        "entry_id": "schaff-herzog.theotokos",
        "field_path": "term",
        "value": "THE0T0K0S",
        "suggestion": "THEOTOKOS",
        "suggestion_source": "digit_substitution_table",
        "confidence": 0.45,
        "context_before": "",
        "context_after": "Greek theological term",
        "occurrences": 1,
        "signature": signature,
        "snippet": "THE0T0K0S Greek theological term",
    }


def _ocr_output(candidate: dict | None = None) -> dict:
    return {"ocr_scanner": {"warnings": [], "candidates": [candidate or _candidate()]}}


def _write_cache(cache_dir: Path, candidate_signature: str, classification: str = "error_no_fix") -> None:
    key = llm_triage.cache_key(
        model=llm_triage.MODEL,
        prompt_version=llm_triage.PROMPT_VERSION,
        candidate_signature=candidate_signature,
        evidence_schema_version=llm_triage.EVIDENCE_SCHEMA_VERSION,
        llm_temperature=llm_triage.LLM_TEMPERATURE,
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "cache.json").write_text(
        json.dumps(
            {
                "model": llm_triage.MODEL,
                "prompt_version": llm_triage.PROMPT_VERSION,
                "evidence_schema_version": llm_triage.EVIDENCE_SCHEMA_VERSION,
                "llm_temperature": llm_triage.LLM_TEMPERATURE,
                "responses": {
                    key: {
                        "classification": classification,
                        "confidence": 0.9,
                        "reasoning": "test cache",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_cached_fixture_metadata_is_pinned() -> None:
    payload = json.loads(Path("tests/fixtures/llm_triage/sh_cached_responses.json").read_text(encoding="utf-8"))

    assert payload["prompt_version"] == llm_triage.PROMPT_VERSION
    assert payload["evidence_schema_version"] == llm_triage.EVIDENCE_SCHEMA_VERSION
    assert payload["candidate_count"] > 0
    assert len(payload["responses"]) > 0


def test_cached_responses_replay(tmp_path: Path) -> None:
    _write_cache(tmp_path, "candidate-1", classification="error_no_fix")
    options = llm_triage.TriageOptions(llm_cache_dir=tmp_path)

    output = llm_triage.run_with_options({}, {}, _ocr_output(), options)

    assert output["warnings"][0]["code"] == "error_no_fix"
    assert output["warnings"][0]["evidence"]["classification"] == "error_no_fix"
    assert output["silenced_by_threshold"] == 0


def test_max_llm_calls_zero_aborts_cleanly_with_budget_warning(tmp_path: Path) -> None:
    options = llm_triage.TriageOptions(llm_cache_dir=tmp_path, max_llm_calls=0, max_llm_cost_usd=0)

    output = llm_triage.run_with_options({}, {}, _ocr_output(), options)

    assert output["warnings"][0]["code"] == "producer_budget_exhausted"
    assert output["silenced_by_threshold"] == 1


def test_cache_key_is_deterministic() -> None:
    first = llm_triage.cache_key(
        model=llm_triage.MODEL,
        prompt_version=llm_triage.PROMPT_VERSION,
        candidate_signature="abc",
        evidence_schema_version=llm_triage.EVIDENCE_SCHEMA_VERSION,
        llm_temperature=llm_triage.LLM_TEMPERATURE,
    )
    second = llm_triage.cache_key(
        model=llm_triage.MODEL,
        prompt_version=llm_triage.PROMPT_VERSION,
        candidate_signature="abc",
        evidence_schema_version=llm_triage.EVIDENCE_SCHEMA_VERSION,
        llm_temperature=llm_triage.LLM_TEMPERATURE,
    )

    assert first == second


def test_live_mode_is_opt_in(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called = {"value": False}

    def fake_live(candidate, options):
        called["value"] = True
        return {"classification": "uncertain", "confidence": 0.1, "reasoning": "live"}

    monkeypatch.setattr(llm_triage, "_classify_with_live_clients", fake_live)
    cache_only = llm_triage.TriageOptions(llm_cache_dir=tmp_path)
    live = llm_triage.TriageOptions(
        llm_cache_dir=tmp_path,
        enable_llm_triage=True,
        max_llm_calls=1,
        max_llm_cost_usd=0.01,
    )

    llm_triage.run_with_options({}, {}, _ocr_output(_candidate("cache-only")), cache_only)
    assert called["value"] is False

    output = llm_triage.run_with_options({}, {}, _ocr_output(_candidate("live")), live)
    assert called["value"] is True
    assert output["warnings"][0]["code"] == "uncertain"
