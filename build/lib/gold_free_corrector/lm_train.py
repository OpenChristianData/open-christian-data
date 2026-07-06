"""L0-only language-model trainer for downstream M8 rescoring."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class LanguageModel(Protocol):
    """Scoring interface consumed by M8 without coupling to the backend."""

    backend_name: str

    def char_logprob(self, context: str, char: str) -> float:
        """Return a finite smoothed log probability for one next character."""

    def word_logprob(self, prev: str, word: str) -> float:
        """Return a finite smoothed log probability for one next word."""

    def score(self, token: str) -> float:
        """Return a combined finite token score used by M8 rescoring."""


class L0TrainingViolation(ValueError):
    """Raised when non-L0 corrected readings reach the M7 trainer."""


@dataclass(frozen=True)
class PurePythonLanguageModel:
    """Pure-Python M7 model container exposing the scoring surface M8 calls."""

    char_order: int
    add_k: float
    char_counts_by_context: dict[str, Counter[str]]
    char_context_totals: dict[str, int]
    char_vocabulary: frozenset[str]
    word_counts: Counter[str]
    word_bigram_counts: dict[str, Counter[str]]
    word_context_totals: dict[str, int]
    word_vocabulary: frozenset[str]
    backend_name: str = "pure_python"

    def char_logprob(self, context: str, char: str) -> float:
        trimmed_context = context[-(self.char_order - 1) :] if self.char_order > 1 else ""
        counts = self.char_counts_by_context.get(trimmed_context, Counter())
        total = self.char_context_totals.get(trimmed_context, 0)
        vocab_size = len(self.char_vocabulary | frozenset({char}))
        return _add_k_logprob(counts.get(char, 0), total, vocab_size, self.add_k)

    def word_logprob(self, prev: str, word: str) -> float:
        counts = self.word_bigram_counts.get(prev, Counter())
        total = self.word_context_totals.get(prev, 0)
        vocab_size = len(self.word_vocabulary | frozenset({word}))
        return _add_k_logprob(counts.get(word, 0), total, vocab_size, self.add_k)

    def score(self, token: str) -> float:
        """Return a combined finite token score for callers that need one value."""
        chars = list(token)
        char_score = 0.0
        for index, char in enumerate(chars):
            start = max(0, index - self.char_order + 1)
            char_score += self.char_logprob(token[start:index], char)

        words = token.split()
        word_score = 0.0
        for prev, word in zip(words, words[1:]):
            word_score += self.word_logprob(prev, word)
        return char_score + word_score

    def snapshot(self) -> dict[str, Any]:
        """Return deterministic, JSON-serializable model state for tests/audits."""
        return {
            "backend_name": self.backend_name,
            "char_order": self.char_order,
            "add_k": self.add_k,
            "char_counts_by_context": _snapshot_nested_counter(self.char_counts_by_context),
            "char_context_totals": dict(sorted(self.char_context_totals.items())),
            "char_vocabulary": sorted(self.char_vocabulary),
            "word_counts": dict(sorted(self.word_counts.items())),
            "word_bigram_counts": _snapshot_nested_counter(self.word_bigram_counts),
            "word_context_totals": dict(sorted(self.word_context_totals.items())),
            "word_vocabulary": sorted(self.word_vocabulary),
        }


def train_l0_language_model(
    readings: list[Mapping[str, Any]],
    *,
    char_order: int = 5,
    add_k: float = 0.5,
    backend: str = "pure_python",
) -> LanguageModel:
    """Train an L0-only language model; non-L0 readings raise before counting."""
    _validate_hyperparameters(char_order, add_k)
    l0_texts = _assert_l0_texts(readings)
    if backend == "pure_python":
        return _train_pure_python(l0_texts, char_order=char_order, add_k=add_k)
    if backend in {"kenlm", "auto"}:
        return _train_kenlm_optional(l0_texts, char_order=char_order, add_k=add_k)
    raise ValueError(f"unsupported LM backend: {backend}")


def train_l0_language_model_from_results(
    results: list[Mapping[str, Any]],
    *,
    char_order: int = 5,
    add_k: float = 0.5,
    backend: str = "pure_python",
) -> LanguageModel:
    """Train from ColumnVoteResult-like mappings by ingesting derivable readings."""
    readings: list[Mapping[str, Any]] = []
    for result in results:
        corrected_position = result.get("corrected_position")
        if not isinstance(corrected_position, Mapping):
            raise ValueError("ColumnVoteResult mapping is missing corrected_position")
        derivable_readings = corrected_position.get("derivable_readings", [])
        if not isinstance(derivable_readings, list):
            raise ValueError("corrected_position.derivable_readings must be a list")
        for reading in derivable_readings:
            if not isinstance(reading, Mapping):
                raise ValueError("derivable_readings entries must be mappings")
            readings.append(reading)
    return train_l0_language_model(
        readings,
        char_order=char_order,
        add_k=add_k,
        backend=backend,
    )


def _train_kenlm_optional(
    texts: list[str],
    *,
    char_order: int,
    add_k: float,
) -> PurePythonLanguageModel:
    try:
        import kenlm  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        return _train_pure_python(texts, char_order=char_order, add_k=add_k)
    return _train_pure_python(texts, char_order=char_order, add_k=add_k)


def _assert_l0_texts(readings: list[Mapping[str, Any]]) -> list[str]:
    texts = []
    for index, reading in enumerate(readings):
        level = reading.get("derivation_level")
        if level != "L0":
            raise L0TrainingViolation(f"non-L0 reading at index {index}: {level}")
        text = reading.get("text")
        if not isinstance(text, str):
            raise ValueError(f"L0 reading at index {index} has no string text")
        texts.append(text)
    return texts


def _train_pure_python(
    texts: list[str],
    *,
    char_order: int,
    add_k: float,
) -> PurePythonLanguageModel:
    char_counts_by_context: dict[str, Counter[str]] = {}
    char_context_totals: Counter[str] = Counter()
    char_vocabulary: set[str] = set()
    word_counts: Counter[str] = Counter()
    word_bigram_counts: dict[str, Counter[str]] = {}
    word_context_totals: Counter[str] = Counter()
    word_vocabulary: set[str] = set()

    for text in texts:
        char_vocabulary.update(text)
        for index, char in enumerate(text):
            start = max(0, index - char_order + 1)
            context = text[start:index]
            char_counts_by_context.setdefault(context, Counter())[char] += 1
            char_context_totals[context] += 1

        words = text.split()
        word_counts.update(words)
        word_vocabulary.update(words)
        for prev, word in zip(words, words[1:]):
            word_bigram_counts.setdefault(prev, Counter())[word] += 1
            word_context_totals[prev] += 1

    return PurePythonLanguageModel(
        char_order=char_order,
        add_k=add_k,
        char_counts_by_context=char_counts_by_context,
        char_context_totals=dict(char_context_totals),
        char_vocabulary=frozenset(char_vocabulary),
        word_counts=word_counts,
        word_bigram_counts=word_bigram_counts,
        word_context_totals=dict(word_context_totals),
        word_vocabulary=frozenset(word_vocabulary),
    )


def _add_k_logprob(count: int, total: int, vocab_size: int, add_k: float) -> float:
    denominator = total + (add_k * max(vocab_size, 1))
    return math.log((count + add_k) / denominator)


def _snapshot_nested_counter(counters: dict[str, Counter[str]]) -> dict[str, dict[str, int]]:
    return {
        context: dict(sorted(counter.items()))
        for context, counter in sorted(counters.items())
    }


def _validate_hyperparameters(char_order: int, add_k: float) -> None:
    if char_order < 1:
        raise ValueError("char_order must be >= 1")
    if add_k <= 0:
        raise ValueError("add_k must be > 0")
