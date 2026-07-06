"""classify — disagreement classification decision tree.

Decision tree (in order):
1. capitalisation    — differ only in case
2. punctuation       — identical after stripping all punctuation
3. ocr_noise         — matches OCR error model patterns (NOT general edit distance)
4. spelling_variant  — edit distance 1-2 + result is a valid word
5. word_substitution — >50% token overlap but specific word differs
6. paraphrase        — everything else
"""

from __future__ import annotations

import re
import string
from pathlib import Path

import yaml



# Path: build/lib/reconcile/classify.py → parents[1] = build/lib → ocr_error_models
_MODEL_DIR = Path(__file__).resolve().parents[1] / "ocr_error_models"

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def _load_ocr_model(language: str) -> list[dict]:
    path = _MODEL_DIR / f"{language}.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or []


def _strip_punctuation(text: str) -> str:
    return text.translate(_PUNCT_TABLE)


def _levenshtein(a: str, b: str) -> int:
    """Simple O(mn) Levenshtein distance."""
    if a == b:
        return 0
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[:]
        dp[0] = i
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev[j - 1] + cost)
    return dp[n]


def _apply_ocr_confusions(text: str, confusions: list[tuple[str, str]]) -> str:
    """Apply all confusion substitutions to produce an OCR-normalised form."""
    result = text
    for source, target in confusions:
        result = result.replace(source, target)
    return result


def _is_ocr_noise_via_model(anchor: str, attestor: str, language: str) -> bool:
    """Return True only if the pair matches a specific OCR error model pattern.

    This is intentionally strict — only patterns from the YAML model count.
    General edit distance or similarity does NOT qualify here.
    """
    model = _load_ocr_model(language)
    if not model:
        return False

    confusions: list[tuple[str, str]] = []
    for entry in model:
        confusion = entry.get("confusion", {})
        src = confusion.get("source", "")
        tgt = confusion.get("target", "")
        if src and tgt:
            confusions.append((src, tgt))

    if not confusions:
        return False

    anchor_lower = anchor.lower()
    attestor_lower = attestor.lower()

    # Normalise both sides with the full confusion set
    anchor_norm = _apply_ocr_confusions(anchor_lower, confusions)
    attestor_norm = _apply_ocr_confusions(attestor_lower, confusions)

    # They're an OCR pair if normalising one (or both) makes them equal
    if anchor_norm == attestor_norm:
        return True

    # Also check the reverse direction (e.g. attestor has the corruption)
    # Re-apply confusions to the already-normalised form isn't meaningful;
    # instead check if applying confusions to attestor gives anchor, or vice versa
    # The key question: does one side become the other when confusions are applied?
    anchor_corrected = _apply_ocr_confusions(attestor_lower, confusions)
    if anchor_corrected == anchor_lower:
        return True

    return False


def _token_overlap_ratio(a: str, b: str) -> float:
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


# Simple English word-like check: only alphabetic characters
_WORD_RE = re.compile(r"^[a-zA-Z]+$")


def _looks_like_word(text: str) -> bool:
    return bool(_WORD_RE.match(text.strip()))


def _with_correlation_prefix(kind: str, attesting_families: list[str] | None) -> str:
    if attesting_families and len(set(attesting_families)) == 1:
        return f"correlated_{kind}"
    return kind


def classify_disagreement(
    anchor_text: str,
    attestor_text: str,
    language: str = "en",
    ocr_models: dict | None = None,
    attesting_families: list[str] | None = None,
) -> str:
    """Classify the disagreement between anchor_text and attestor_text.

    Returns one of: ocr_noise, capitalisation, punctuation, spelling_variant,
    word_substitution, paraphrase. When attesting_families contains exactly one
    distinct family, the result is prefixed with "correlated_" (e.g.
    "correlated_ocr_noise") to distinguish within-family noise from independent
    cross-family evidence.
    """
    if anchor_text == attestor_text:
        raise ValueError(
            "classify_disagreement called with identical texts; "
            "caller should check for equality before classifying"
        )

    # 1. Capitalisation: differ only in case
    if anchor_text.lower() == attestor_text.lower():
        return _with_correlation_prefix("capitalisation", attesting_families)

    # 2. Punctuation: identical after stripping all punctuation
    if _strip_punctuation(anchor_text).strip() == _strip_punctuation(attestor_text).strip():
        return _with_correlation_prefix("punctuation", attesting_families)

    anchor_stripped = anchor_text.strip()
    attestor_stripped = attestor_text.strip()
    anchor_tokens = anchor_stripped.split()
    attestor_tokens = attestor_stripped.split()

    # 3. OCR noise — ONLY via explicit OCR error model patterns.
    # This must come BEFORE spelling_variant so that clear OCR confusions
    # (rn→m, cl→d, etc.) are classified as noise, not as spelling edits.
    # "recieve"/"receive" does NOT match any OCR pattern, so it falls through
    # to spelling_variant below.
    if _is_ocr_noise_via_model(anchor_text, attestor_text, language):
        return _with_correlation_prefix("ocr_noise", attesting_families)

    # 4. Spelling variant — edit distance 1-2 + result is a valid word-like form.
    # Operates on single-token pairs or multi-token pairs with one differing token.
    if len(anchor_tokens) == 1 and len(attestor_tokens) == 1:
        dist = _levenshtein(anchor_stripped.lower(), attestor_stripped.lower())
        if 1 <= dist <= 2 and _looks_like_word(attestor_stripped):
            return _with_correlation_prefix("spelling_variant", attesting_families)

    # For multi-token: check if exactly one token differs by edit distance 1-2
    if len(anchor_tokens) == len(attestor_tokens):
        differing = [
            (a, b) for a, b in zip(anchor_tokens, attestor_tokens, strict=True)
            if a.lower() != b.lower()
        ]
        if len(differing) == 1:
            a_tok, b_tok = differing[0]
            dist = _levenshtein(a_tok.lower(), b_tok.lower())
            if 1 <= dist <= 2 and _looks_like_word(b_tok):
                return _with_correlation_prefix("spelling_variant", attesting_families)

    # 5. Word substitution — token sets overlap or both are single words that differ.
    # Single-word pairs that aren't OCR noise or spelling variants are word substitutions.
    if len(anchor_tokens) == 1 and len(attestor_tokens) == 1:
        return _with_correlation_prefix("word_substitution", attesting_families)

    overlap = _token_overlap_ratio(anchor_text, attestor_text)
    if overlap > 0.5:
        return _with_correlation_prefix("word_substitution", attesting_families)

    # 6. Paraphrase — everything else
    return _with_correlation_prefix("paraphrase", attesting_families)
