"""Language classifier for review tooling and structured pipeline output.

Provides two interfaces:

- Legacy: classify(text, resource_type) and classify_spans(text)
  Span-based detection used by existing review/dispatch code.

- Slot 2: classify_block(text, resource_type) -> dict
  Block-level dominant-language classification used by the structured
  pipeline. Runs Layer 1 (Unicode script), then Layer 2 (lexicon scoring
  with source-transliteration sub-check), then Layer 3 (cld3 fallback).
"""

from __future__ import annotations

import re
from typing import Any

from ocd_kernel.lib.lexicons import en, grc, hbo_latn, la, fr, de
from ocd_kernel.lib.source_transliteration_lexicons import (
    load_source_transliteration_lexicons,
)


# --- Legacy span-based classifier (existing interface) --------------------

GREEK_RE = re.compile(r"[Ͱ-Ͽ]+")
HEBREW_RE = re.compile(r"[֐-׿]+")
SYRIAC_RE = re.compile(r"[܀-ݏ]+")
COPTIC_RE = re.compile(r"[Ⲁ-⳿]+")
LATIN_LETTER_RE = re.compile(r"[A-Za-zÀ-ɏ]+")
HEBREW_LATN_TERMS = (
    "Jehovah",
    "Iehovah",
    "YHWH",
    "JHVH",
    "Jahveh",
    "Jahweh",
    "Yahweh",
    "Yahveh",
    "Yehovah",
    "Elohim",
    "Eloah",
    "Adonai",
    "Zebaoth",
)
HEBREW_LATN_PATTERNS = tuple(
    re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
    for term in HEBREW_LATN_TERMS
)
LATIN_PATTERNS = tuple(
    re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
    for term in la.ARCHAIC_FORMS
)
CONFIDENCE_ORDER = {"uncertain": 0, "low": 1, "medium": 2, "high": 3}


def classify(
    text: str,
    resource_type: str,
    *,
    uncertain_overrides: bool = False,
) -> tuple[str | None, list[dict[str, Any]]]:
    spans = classify_spans(text, uncertain_overrides=uncertain_overrides)
    lang_hint = _dominant_lang_hint(text, spans)
    return lang_hint, spans


def classify_spans(text: str, *, uncertain_overrides: bool = False) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    spans.extend(_script_spans(text, GREEK_RE, "grc", "high"))
    spans.extend(_script_spans(text, HEBREW_RE, "he", "high"))
    spans.extend(_term_spans(text, HEBREW_LATN_PATTERNS, "hbo_latn", "low"))
    spans.extend(_term_spans(text, LATIN_PATTERNS, "la", "medium"))

    merged = _drop_overlapping(sorted(spans, key=lambda span: (span["start"], span["end"], span["lang"])))
    if not merged and uncertain_overrides and text:
        return [{"start": 0, "end": len(text), "lang": "und", "confidence": "uncertain"}]
    return merged


def _script_spans(text: str, pattern: re.Pattern[str], lang: str, confidence: str) -> list[dict[str, Any]]:
    return [
        {"start": match.start(), "end": match.end(), "lang": lang, "confidence": confidence}
        for match in pattern.finditer(text)
    ]


def _term_spans(text: str, patterns: tuple[re.Pattern[str], ...], lang: str, confidence: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for pattern in patterns:
        spans.extend(
            {"start": match.start(), "end": match.end(), "lang": lang, "confidence": confidence}
            for match in pattern.finditer(text)
        )
    return spans


def _drop_overlapping(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    occupied: list[range] = []
    for span in sorted(spans, key=lambda item: (-CONFIDENCE_ORDER[item["confidence"]], item["start"], item["end"])):
        current = range(span["start"], span["end"])
        if any(_ranges_overlap(current, existing) for existing in occupied):
            continue
        kept.append(span)
        occupied.append(current)
    return sorted(kept, key=lambda item: (item["start"], item["end"], item["lang"]))


def _ranges_overlap(left: range, right: range) -> bool:
    return left.start < right.stop and right.start < left.stop


def _dominant_lang_hint(text: str, spans: list[dict[str, Any]]) -> str | None:
    eligible = [span for span in spans if CONFIDENCE_ORDER.get(str(span.get("confidence")), 0) >= CONFIDENCE_ORDER["medium"]]
    if not eligible:
        return None
    totals: dict[str, int] = {}
    for span in eligible:
        lang = str(span["lang"])
        totals[lang] = totals.get(lang, 0) + int(span["end"]) - int(span["start"])
    dominant_lang, dominant_chars = max(totals.items(), key=lambda item: item[1])
    non_space_chars = len(re.sub(r"\s+", "", text))
    if non_space_chars and dominant_chars / non_space_chars >= 0.5:
        return dominant_lang
    return None


# --- Slot 2: block-level classify_block (Layer 1/2/3) ---------------------

LANG_BLOCK_NEEDS_REVIEW = "LANG_BLOCK_NEEDS_REVIEW"


def check_language_confidence(result: dict[str, Any]) -> list[str]:
    """Return warning codes for blocks below the confidence floor."""
    warnings: list[str] = []
    if result.get("language") == "und" or result.get("language_confidence", 0.0) < 0.60:
        warnings.append(LANG_BLOCK_NEEDS_REVIEW)
    return warnings


# English stopwords removed from denominator in Layer 2 fraction scoring.
ENGLISH_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "nor", "yet", "so",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "in", "of", "to", "for", "by", "at", "on", "with", "from", "as", "into",
    "it", "its", "that", "this", "these", "those", "which", "who", "whom",
    "not", "no", "never", "ever",
    "i", "my", "we", "our", "you", "your", "he", "she", "his", "her",
    "they", "their",
    "all", "any", "some", "one", "two", "both", "each", "every",
    "will", "shall", "may", "might", "could", "would", "should", "can",
    "do", "does", "did", "have", "has", "had",
    "more", "most", "very", "also", "then", "than", "when", "where",
    "how", "why",
    "over", "under", "above", "below", "up", "down", "out", "off", "away",
    "if", "even", "still", "just", "now", "here", "there",
})


# Supplemental English biblical/theological vocabulary used by Layer 2.
# Lives here (not en.py) — en.py is the immutable archaic-forms lexicon.
_EN_SUPPLEMENTAL: frozenset[str] = frozenset({
    "God", "Lord", "Jesus", "Christ", "Spirit", "Holy", "Father", "Son",
    "Blessed", "blessed", "Behold", "behold", "Verily", "verily",
    "shepherd", "Lamb", "lamb", "kingdom", "Kingdom", "heaven", "Heaven",
    "earth", "Earth", "sin", "grace", "Grace", "faith", "Faith", "love",
    "Love", "hope", "Hope", "peace", "Peace", "truth", "Truth", "light",
    "Light", "life", "Life", "death", "Death", "soul", "Soul", "heart",
    "Heart", "salvation", "Salvation", "gospel", "Gospel", "prayer", "Prayer", "worship", "Worship", "glory",
    "Glory", "mercy", "Mercy", "judgment", "judgement", "righteousness",
    "word", "Word", "scripture", "Scripture", "law", "Law", "commandment",
    "commandments", "temple", "Temple", "sacrifice", "offering",
    "priest", "Priest", "king", "King", "servant", "master", "Master",
    "disciples", "disciple", "apostle", "Apostle", "covenant", "Covenant",
    "promise", "forgiveness", "repentance", "baptism", "Baptism", "amen",
    "lovingkindness", "steadfast", "wrath", "wisdom", "knowledge", "mystery",
    "eternal", "everlasting", "holy", "chosen", "elect", "righteous",
    "wicked", "nations", "peoples", "morning", "evening", "wilderness",
    "waters", "mountains", "heavenly", "appointed", "preacher",
    "prophet", "Prophet", "whereunto", "Whereunto", "gracious", "forgotten",
    "saith", "speaketh", "thinketh", "rejoiceth", "shed", "abroad",
    "proclaimed", "proclaim", "hath", "doth", "art", "thou", "thee",
    "thy", "thine", "ye", "yea", "nay", "unto", "according", "wherein",
    "whereof", "whereby", "whereto", "wherewith", "whereon", "whither",
    "whence", "henceforth", "heretofore", "thereof", "therein", "thereby",
    "thereto", "therewith", "thereon", "thereunto",
    "LORD", "Almighty", "almighty", "GOD",
    "loves", "loved", "loving", "loves", "saved", "saves", "saving",
    "saviour", "savior", "Saviour", "Savior", "redeem", "redeemer",
    "Redeemer", "redeemed", "redeeming", "redemption", "Redemption",
    "sanctified", "sanctifies", "sanctification", "sanctify", "sanctified",
    "justified", "justifies", "justification", "justify",
    "glorified", "glorifies", "glorify",
    "believer", "believers", "believing", "believed", "believe",
    "preaches", "preached", "preaching", "preach",
    "teaches", "taught", "teaching", "teach", "teacher", "teachers",
    "thy", "thou", "thee", "thine", "ye", "ye",
    "host", "hosts", "hosts",
    "taketh", "giveth", "maketh", "cometh", "goeth", "knoweth", "seeketh",
    "say", "said", "saith", "answereth", "answered",
    "told", "tell", "telleth", "speaks", "spoke", "spoken", "speak",
    "made", "make", "making", "making", "made",
    "worketh", "wrought", "worked", "working", "work", "works",
    "led", "lead", "leading",
    "called", "calls", "calling", "call",
    "sent", "sends", "sending", "send",
    "given", "gave", "giving", "give",
    "taken", "takes", "took", "taking", "take",
    "seen", "sees", "saw", "seeing", "see",
    "heard", "hears", "hearing", "hear",
    "found", "finds", "finding", "find",
    "known", "knows", "knew", "knowing", "know",
    "thought", "thinks", "thinking", "think",
    "asked", "asks", "asking", "ask",
    "remember", "remembered", "remembers", "remembering",
    "forgot", "forgotten", "forgets", "forgetting", "forget",
    "praise", "praises", "praised", "praising",
    "bless", "blesses", "blessed", "blessing", "blessings",
    "curse", "curses", "cursed", "cursing",
    "great", "greater", "greatest", "greatly",
    "good", "better", "best",
    "true", "truly", "truth",
    "false", "falsely", "falsehood",
    "mighty", "might", "powerful", "power", "powers",
    "wise", "wisely", "wisdom",
    "foolish", "fool", "folly",
    "way", "ways", "path", "paths",
    "house", "houses", "household",
    "kingdom", "kingdoms",
    "people", "peoples",
    "land", "lands",
    "place", "places",
    "thing", "things",
    "time", "times", "season", "seasons",
    "day", "days", "night", "nights", "year", "years",
    "world", "worlds", "ages",
    "voice", "voices",
    "hand", "hands",
    "name", "names",
    "face", "faces",
    "eye", "eyes",
    "tongue", "tongues",
    "mouth", "mouths",
    "ear", "ears",
    "foot", "feet",
    "head", "heads",
    "body", "bodies",
    "blood", "bloody",
    "flesh", "fleshly",
    "bone", "bones",
    "stone", "stones",
    "rock", "rocks",
    "tree", "trees",
    "fruit", "fruits",
    "leaf", "leaves",
    "seed", "seeds",
    "field", "fields",
    "garden", "gardens",
    "vineyard", "vineyards",
    "valley", "valleys",
    "hill", "hills",
    "mountain", "mountains",
    "river", "rivers",
    "sea", "seas",
    "ocean", "oceans",
    "water", "waters",
    "wind", "winds",
    "fire", "fires",
    "cloud", "clouds",
    "sun", "moon", "star", "stars",
    "sky", "skies",
    "angel", "angels",
    "devil", "devils", "demon", "demons",
    "Satan", "satanic",
    "hell", "Hell",
    "Paradise", "paradise",
    "altar", "altars",
    "Sabbath", "sabbath", "Sabbaths",
    "Lord's", "Lord", "Lord's-day",
    "Spirit", "spiritual", "spiritually",
    "flesh", "fleshly",
    "Israel", "Israelite", "Israelites", "Israel's",
    "Jew", "Jews", "Jewish", "Judah",
    "Gentile", "Gentiles",
    "Pharisee", "Pharisees", "Sadducee", "Sadducees",
    "scribe", "scribes",
    "Pharisaical",
    "Levite", "Levites",
    "Nazarene", "Nazarenes", "Nazareth",
    "Bethlehem",
    "Jerusalem",
    "Galilee",
    "Judea", "Judean", "Judeans",
    "Samaria", "Samaritan", "Samaritans",
    "Egypt", "Egyptian", "Egyptians",
    "Babylon", "Babylonian", "Babylonians",
    "Rome", "Roman", "Romans",
    "Greek", "Greeks",
    "Hebrew", "Hebrews",
    "Aramaic",
    "according",
    "wherefore",
    "anointed", "anoint",
    "exalted", "exalt",
    "humbled", "humble",
    "lifted", "lift",
    "ascended", "ascend", "ascending", "ascension", "Ascension",
    "descended", "descend", "descending", "descent",
    "received", "receive", "receiving",
    "Hath",
    "Greater",
    "Wherefore",
    "Therefore",
    "Yea",
    "Behold",
})


# Layer 2 vocabulary sets per language.
# en uses ARCHAIC_FORMS keys (388 entries) plus a supplemental biblical
# vocabulary defined above. Other languages use their VOCAB frozenset.
_EN_VOCAB: frozenset[str] = frozenset(en.ARCHAIC_FORMS.keys()) | _EN_SUPPLEMENTAL
_LA_VOCAB: frozenset[str] = la.VOCAB
_GRC_VOCAB: frozenset[str] = grc.VOCAB
_HBO_LATN_VOCAB: frozenset[str] = hbo_latn.VOCAB
_FR_VOCAB: frozenset[str] = fr.VOCAB
_DE_VOCAB: frozenset[str] = de.VOCAB

_LANG_VOCABS: dict[str, frozenset[str]] = {
    "en": _EN_VOCAB,
    "la": _LA_VOCAB,
    "grc": _GRC_VOCAB,
    "hbo_latn": _HBO_LATN_VOCAB,
    "fr": _FR_VOCAB,
    "de": _DE_VOCAB,
}

# Pre-built case-insensitive vocabularies for fast lookup.
_LANG_VOCABS_LOWER: dict[str, frozenset[str]] = {
    lang: frozenset(token.lower() for token in vocab)
    for lang, vocab in _LANG_VOCABS.items()
}


# Source-transliteration: cache lexicon entries on first use.
_ST_CACHE: dict[str, list[dict[str, Any]]] | None = None

# Map underlying_language in source-transliteration lexicons to the
# display language code used in classify_block output.
_ST_LANG_MAP: dict[str, str] = {
    "grc": "grc",
    "hbo": "hbo_latn",
    "la": "la",
}


def _get_source_transliteration_entries() -> dict[str, list[dict[str, Any]]]:
    global _ST_CACHE
    if _ST_CACHE is None:
        _ST_CACHE = {
            lang: load_source_transliteration_lexicons(lang)
            for lang in ("grc", "hbo", "la")
        }
    return _ST_CACHE


# --- cld3 graceful fallback ---

try:  # pragma: no cover - cld3 is optional
    import gcld3  # type: ignore[import-not-found]
    _CLD3_AVAILABLE = True
    _CLD3_IDENT: Any = gcld3.NNetLanguageIdentifier(min_num_bytes=0, max_num_bytes=1000)
except ImportError:  # pragma: no cover - exercised when cld3 missing
    _CLD3_AVAILABLE = False
    _CLD3_IDENT = None


_CLD3_LANG_MAP: dict[str, str] = {
    "en": "en", "la": "la", "fr": "fr", "de": "de",
    "el": "grc",  # modern Greek code mapped to ancient Greek for our schema
    "he": "hbo_latn",
}


# --- Script presence detection ---


def _detect_mixed_script(text: str) -> bool:
    """Return True if text contains characters from two or more script families."""
    scripts_present = sum([
        bool(GREEK_RE.search(text)),
        bool(HEBREW_RE.search(text)),
        bool(SYRIAC_RE.search(text)),
        bool(COPTIC_RE.search(text)),
        bool(LATIN_LETTER_RE.search(text)),
    ])
    return scripts_present >= 2


# --- Layer 1: Unicode script analysis ---


def _layer1_classify(text: str) -> dict[str, Any] | None:
    """Layer 1 Unicode-script classification.

    Returns a complete result dict if a script-based classification is
    decisive (≥90% Greek, ≥90% Hebrew, Syriac/Coptic present); otherwise
    returns None to fall through to Layer 2.
    """
    if not text:
        return None

    # Syriac and Coptic detection — treated as undetermined for Slot 2
    if SYRIAC_RE.search(text) or COPTIC_RE.search(text):
        return {
            "language": "und",
            "language_confidence": 0.0,
            "language_alternates": [],
            "language_segments": [],
            "chosen_layer": "layer1",
        }

    greek_chars = sum(len(m.group(0)) for m in GREEK_RE.finditer(text))
    hebrew_chars = sum(len(m.group(0)) for m in HEBREW_RE.finditer(text))
    latin_chars = sum(len(m.group(0)) for m in LATIN_LETTER_RE.finditer(text))
    total_alpha = greek_chars + hebrew_chars + latin_chars

    if total_alpha == 0:
        return None

    greek_ratio = greek_chars / total_alpha
    hebrew_ratio = hebrew_chars / total_alpha

    if greek_ratio >= 0.90:
        return {
            "language": "grc",
            "language_confidence": 0.95,
            "language_alternates": [],
            "language_segments": [],
            "chosen_layer": "layer1",
        }
    if hebrew_ratio >= 0.90:
        return {
            "language": "hbo",
            "language_confidence": 0.95,
            "language_alternates": [],
            "language_segments": [],
            "chosen_layer": "layer1",
        }
    # Mixed-script: fall through to Layer 2
    return None


# --- Layer 2: lexicon scoring ---


def _layer2_classify(text: str) -> dict[str, Any] | None:
    """Layer 2 lexicon scoring with exclusive-match boosting.

    Returns a result dict if a winner clears the 0.60 floor, otherwise None.
    """
    tokens = [t for t in re.split(r"\W+", text) if t]
    if not tokens:
        return None

    # Sub-check A: source-transliteration detection
    st_entries = _get_source_transliteration_entries()
    token_set_lower = {t.lower() for t in tokens}
    for _lang, entries in st_entries.items():
        for entry in entries:
            if not entry.get("enabled", True):
                continue
            source_tokens = entry.get("source_tokens", [])
            for st in source_tokens:
                if st.lower() in token_set_lower:
                    underlying = entry.get("underlying_language", "")
                    display_lang = _ST_LANG_MAP.get(underlying, underlying)
                    return {
                        "language": display_lang,
                        "language_confidence": 0.85,
                        "language_alternates": [],
                        "language_segments": [],
                        "chosen_layer": "layer2",
                    }

    # Sub-check B: exclusive-match + fraction scoring
    content_tokens = [t for t in tokens if t.lower() not in ENGLISH_STOPWORDS]
    if not content_tokens:
        return None

    # Per-language match counts and exclusive-match counts.
    matches_per_lang: dict[str, list[str]] = {}
    for lang, vocab_lower in _LANG_VOCABS_LOWER.items():
        matches = [t for t in content_tokens if t.lower() in vocab_lower]
        matches_per_lang[lang] = matches

    scores: dict[str, float] = {}
    for lang, matches in matches_per_lang.items():
        other_vocabs = [
            v for other_lang, v in _LANG_VOCABS_LOWER.items() if other_lang != lang
        ]
        exclusive = [
            t for t in matches
            if not any(t.lower() in v for v in other_vocabs)
        ]
        fraction = len(matches) / max(len(content_tokens), 1)
        if exclusive:
            scores[lang] = max(fraction, 0.65 + 0.05 * len(exclusive))
        else:
            scores[lang] = fraction

    if not scores or all(s == 0.0 for s in scores.values()):
        return None

    winner_lang = max(scores, key=lambda l: scores[l])
    winner_score = min(scores[winner_lang], 1.0)

    if winner_score < 0.60:
        return None  # Fall through to Layer 3

    alternates = [
        {"language": l, "confidence": min(s, 1.0)}
        for l, s in sorted(scores.items(), key=lambda x: -x[1])
        if l != winner_lang and s > 0.0
    ]

    return {
        "language": winner_lang,
        "language_confidence": winner_score,
        "language_alternates": alternates[:3],
        "language_segments": [],
        "chosen_layer": "layer2",
    }


# --- Layer 3: cld3 graceful fallback ---


def _layer3_classify(text: str) -> dict[str, Any]:
    """Layer 3 fallback — uses cld3 if available, else returns und."""
    if not _CLD3_AVAILABLE or not text.strip():
        return {
            "language": "und",
            "language_confidence": 0.0,
            "language_alternates": [],
            "language_segments": [],
            "chosen_layer": "layer3",
        }
    try:  # pragma: no cover
        result = _CLD3_IDENT.FindLanguage(text=text)
        if not result.is_reliable:
            return {
                "language": "und",
                "language_confidence": 0.0,
                "language_alternates": [],
                "language_segments": [],
                "chosen_layer": "layer3",
            }
        mapped = _CLD3_LANG_MAP.get(result.language, "und")
        return {
            "language": mapped,
            "language_confidence": float(result.probability),
            "language_alternates": [],
            "language_segments": [],
            "chosen_layer": "layer3",
        }
    except Exception:  # pragma: no cover
        return {
            "language": "und",
            "language_confidence": 0.0,
            "language_alternates": [],
            "language_segments": [],
            "chosen_layer": "layer3",
        }


# --- Public block-level API ---


def classify_block(text: str, resource_type: str) -> dict[str, Any]:
    """Classify the dominant language of a text block (Layer 1 → 2 → 3)."""
    if not text or not text.strip():
        return {
            "language": "und",
            "language_confidence": 0.0,
            "language_alternates": [],
            "language_segments": [],
            "chosen_layer": "layer2",
            "mixed_script": False,
        }

    mixed_script = _detect_mixed_script(text)

    layer1 = _layer1_classify(text)
    if layer1 is not None:
        layer1["mixed_script"] = mixed_script
        return layer1

    layer2 = _layer2_classify(text)
    if layer2 is not None:
        layer2["mixed_script"] = mixed_script
        return layer2

    layer3 = _layer3_classify(text)
    if layer3.get("language") != "und":
        layer3["mixed_script"] = mixed_script
        return layer3

    # Final fallback — undetermined.
    return {
        "language": "und",
        "language_confidence": 0.0,
        "language_alternates": [],
        "language_segments": [],
        "chosen_layer": "layer3",
        "mixed_script": mixed_script,
    }
