from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "modernise" / "bootstrap"


def _modernise(record: dict) -> dict:
    from build.lib.modernisation.engine import modernise_record
    return modernise_record(deepcopy(record))


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _with_text(record: dict, block_idx: int, text: str) -> dict:
    r = deepcopy(record)
    r["blocks"][block_idx]["original_text"] = text
    r["blocks"][block_idx]["modern_text"] = ""
    r["blocks"][block_idx]["modernisations"] = []
    return r


def test_eth_rule_fires_correctly():
    """R16: hath->has, saith->says; exceptions not transformed; no hats/saits."""
    record = _with_text(
        _load_fixture("schaff_herzog.json"),
        0,
        "He saith that the breath of death hath no power beneath the wreath and sheath.",
    )
    result = _modernise(record)
    modern = result["blocks"][0]["modern_text"]

    # Positive: irregular table fires correctly
    assert "says" in modern
    assert "has" in modern

    # Negative: regex must not produce hats or saits via naive application
    assert "hats" not in modern
    assert "saits" not in modern

    # Negative: exceptions list must be respected
    for word in ("breath", "death", "beneath", "wreath", "sheath"):
        assert word in modern, f"Exception '{word}' was incorrectly transformed"


def test_editorial_modernisation_entry_survives_re_modernise():
    """Editorial entry (rule_id=None) must survive re-modernisation across ruleset versions."""
    record = deepcopy(_load_fixture("wesley.json"))
    editorial = {
        "rule_id": None,
        "kind": "editorial",
        "span": {"start_token": 0, "end_token": 1},
        "original": "Heav'n",
        "modern": "Heaven",
        "editor_decision": {
            "rationale": "archaic contraction modernisation",
            "decided_at": "2026-05-17T00:00:00Z",
        },
    }
    record["blocks"][0]["modernisations"] = [editorial]
    # Simulate record already carrying a prior ruleset version
    record["meta"]["modernisation_ruleset_version"] = "en@1.0.0"

    result = _modernise(record)

    editorial_out = [
        m for m in result["blocks"][0]["modernisations"]
        if m.get("rule_id") is None and m.get("kind") == "editorial"
    ]
    assert len(editorial_out) == 1, "Editorial entry must survive re-modernisation"


def test_reviewer_override_survives_re_modernise():
    """A Reviewer editorial entry on a token must survive re-running the engine."""
    record = _with_text(
        _load_fixture("catechism.json"),
        0,
        "God doth uphold all things by the word of his power.",
    )
    result_first = _modernise(record)

    # Reviewer chose to retain archaic form for liturgical register
    reviewer_entry = {
        "rule_id": None,
        "kind": "editorial",
        "span": {"start_token": 1, "end_token": 2},
        "original": "doth",
        "modern": "doth",
        "editor_decision": {
            "rationale": "Retained for liturgical register",
            "decided_at": "2026-05-17T00:00:00Z",
        },
    }
    result_first["blocks"][0]["modernisations"].append(reviewer_entry)

    result_second = _modernise(result_first)

    overrides = [
        m for m in result_second["blocks"][0]["modernisations"]
        if m.get("rule_id") is None
        and m.get("original") == "doth"
        and m.get("modern") == "doth"
    ]
    assert len(overrides) >= 1, "Reviewer editorial entry must survive re-modernisation"


def test_english_ruleset_v1_round_trip():
    """Every rule in en.yaml has test_cases coverage per ADR-0007 requirements."""
    import yaml
    from build.lib.modernisation.engine import modernise_record  # noqa: F401 — RED gate

    ruleset_path = (
        Path(__file__).parent.parent
        / "build" / "lib" / "modernisation" / "rulesets" / "en.yaml"
    )
    data = yaml.safe_load(ruleset_path.read_text(encoding="utf-8")) or {}
    rules = data.get("rules", [])

    assert rules, "en.yaml must have at least one rule"

    for rule in rules:
        rule_id = rule.get("id", "<missing-id>")
        test_cases = rule.get("test_cases", [])

        assert test_cases, f"Rule '{rule_id}' has no test_cases (ADR-0007 requires >= 1)"

        positive = [tc for tc in test_cases if tc.get("out") != tc.get("in")]
        assert positive, f"Rule '{rule_id}' has no positive test_case"

        # One negative case per exception entry
        for exc in rule.get("exceptions", []):
            exc_covered = any(
                exc.lower() in tc.get("in", "").lower() and tc.get("out") == tc.get("in")
                for tc in test_cases
            )
            assert exc_covered, (
                f"Rule '{rule_id}' missing negative test_case for exception '{exc}'"
            )

        # One case per table row
        for source_word, target_word in rule.get("table", {}).items():
            row_covered = any(source_word in tc.get("in", "") for tc in test_cases)
            assert row_covered, (
                f"Rule '{rule_id}' table row '{source_word}->{target_word}' has no test_case"
            )
