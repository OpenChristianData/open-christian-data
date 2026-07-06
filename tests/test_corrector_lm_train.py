from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.gold_free_corrector.lm_train import (  # noqa: E402
    L0TrainingViolation,
    PurePythonLanguageModel,
    train_l0_language_model,
    train_l0_language_model_from_results,
)


def _reading(text: str, level: str = "L0") -> dict[str, object]:
    return {
        "derivation_level": level,
        "origin_kind": "observed" if level == "L0" else "machine_composed",
        "text": text,
        "scores": {"confidence": 1.0},
    }


def test_hr7_rejects_non_l0_readings_before_counts_change() -> None:
    baseline = train_l0_language_model([_reading("alpha"), _reading("beta")])

    with pytest.raises(L0TrainingViolation, match="L1"):
        train_l0_language_model([_reading("alpha"), _reading("beta"), _reading("alphx", "L1")])

    after_violation = train_l0_language_model([_reading("alpha"), _reading("beta")])
    assert after_violation.snapshot() == baseline.snapshot()


def test_ingests_l0_readings_from_column_vote_results_only() -> None:
    result = {
        "corrected_position": {
            "position_id": "pos_001",
            "derivable_readings": [
                _reading("agreed"),
                _reading("composed", "L1"),
            ],
        }
    }

    with pytest.raises(L0TrainingViolation, match="L1"):
        train_l0_language_model_from_results([result])

    result["corrected_position"]["derivable_readings"] = [_reading("agreed")]
    model = train_l0_language_model_from_results([result])

    assert model.word_counts["agreed"] == 1
    assert "composed" not in model.word_counts


def test_counts_and_scores_are_deterministic_across_hash_seeds() -> None:
    script = """
import json
from build.lib.gold_free_corrector.lm_train import train_l0_language_model

def reading(text):
    return {"derivation_level": "L0", "text": text}

model = train_l0_language_model([reading("alpha"), reading("altar"), reading("alpha")])
payload = {
    "snapshot": model.snapshot(),
    "char": model.char_logprob("alph", "a"),
    "word": model.word_logprob("alpha", "altar"),
}
print(json.dumps(payload, sort_keys=True))
"""
    outputs = []
    for seed in ("0", "1"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(json.loads(completed.stdout))

    assert outputs[0] == outputs[1]


def test_unseen_char_ngram_and_word_bigram_return_finite_logprobs() -> None:
    model = train_l0_language_model([_reading("alpha"), _reading("beta")], add_k=0.25)

    assert math.isfinite(model.char_logprob("zzzz", "q"))
    assert math.isfinite(model.word_logprob("missing-prev", "missing-word"))


def test_order5_char_model_and_word_bigram_train_and_score_fixture_corpus() -> None:
    model = train_l0_language_model(
        [_reading("in principio"), _reading("erat verbum")],
        char_order=5,
        add_k=0.5,
    )

    assert isinstance(model, PurePythonLanguageModel)
    assert model.char_order == 5
    assert model.char_counts_by_context["in p"]["r"] == 1
    assert model.word_bigram_counts["in"]["principio"] == 1
    assert math.isfinite(model.char_logprob("in p", "r"))
    assert math.isfinite(model.word_logprob("erat", "verbum"))


def test_kenlm_absent_path_selects_pure_python_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "kenlm", None)

    model = train_l0_language_model([_reading("alpha")], backend="kenlm")

    assert isinstance(model, PurePythonLanguageModel)
    assert model.backend_name == "pure_python"
    assert math.isfinite(model.word_logprob("alpha", "omega"))
