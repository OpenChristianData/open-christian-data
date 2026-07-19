"""Conservative historical variant lexicon for review tooling."""

from __future__ import annotations

import importlib
import re
from dataclasses import asdict, dataclass
from types import ModuleType
from typing import Any


DEFAULT_ACTION = "preserve_surface"
SUPPORTED_LANGS = ("en", "grc", "hbo_latn", "la")
PER_LANGUAGE_CONFIDENCE_THRESHOLD = frozenset({"medium", "high"})


@dataclass(frozen=True)
class LexiconEntry:
    surface: str
    normalised: str
    variant_type: str
    confidence: float
    action: str = DEFAULT_ACTION
    requires_biblical_book_context: bool = False


@dataclass(frozen=True)
class LexiconMatch:
    surface: str
    normalised: str
    variant_type: str
    confidence: float
    action: str
    start: int
    end: int
    snippet: str
    lang: str = "en"
    lang_hint: str | None = None
    confidence_band: str | None = None

    def to_record(self) -> dict[str, str | float | int | None]:
        return asdict(self)


def scan_historical_variants(
    text: str,
    *,
    lang_hint: str | None = None,
    lang_spans: list[dict[str, Any]] | None = None,
) -> list[LexiconMatch]:
    """Return lexicon matches with offsets without changing source text."""
    matches: list[LexiconMatch] = []
    for segment in _dispatch_segments(text, lang_hint=lang_hint, lang_spans=lang_spans or []):
        segment_text = text[segment["start"] : segment["end"]]
        for match in _scan_segment(
            segment_text,
            lang=str(segment["lang"]),
            offset=int(segment["start"]),
            full_text=text,
            confidence_band=segment.get("confidence"),
        ):
            matches.append(match)
    return sorted(matches, key=lambda item: (item.start, item.end, item.lang, item.surface.lower()))


def coverage_status(lang: str) -> str:
    """Return the declared coverage status for a supported lexicon."""
    return str(getattr(_lexicon_module(_normalise_lang(lang)), "COVERAGE_STATUS"))


def archaic_forms(lang: str) -> dict[str, str]:
    """Return a copy of the language lexicon mapping."""
    forms = getattr(_lexicon_module(_normalise_lang(lang)), "ARCHAIC_FORMS")
    return dict(forms)


def _dispatch_segments(
    text: str,
    *,
    lang_hint: str | None,
    lang_spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    eligible_spans = [
        span
        for span in lang_spans
        if _normalise_lang(span.get("lang")) in SUPPORTED_LANGS
        and span.get("confidence") in PER_LANGUAGE_CONFIDENCE_THRESHOLD
        and _valid_span(span, len(text))
    ]
    if eligible_spans:
        segments: list[dict[str, Any]] = []
        cursor = 0
        for span in sorted(eligible_spans, key=lambda item: (int(item["start"]), int(item["end"]))):
            start = int(span["start"])
            end = int(span["end"])
            if start > cursor:
                segments.append({"start": cursor, "end": start, "lang": "en", "confidence": None})
            if end > start:
                segments.append(
                    {
                        "start": start,
                        "end": end,
                        "lang": _normalise_lang(span.get("lang")),
                        "confidence": span.get("confidence"),
                    }
                )
            cursor = max(cursor, end)
        if cursor < len(text):
            segments.append({"start": cursor, "end": len(text), "lang": "en", "confidence": None})
        return [segment for segment in segments if segment["end"] > segment["start"]]

    lang = _normalise_lang(lang_hint)
    if lang in SUPPORTED_LANGS:
        return [{"start": 0, "end": len(text), "lang": lang, "confidence": None}]
    return [{"start": 0, "end": len(text), "lang": "en", "confidence": None}]


def _scan_segment(
    text: str,
    *,
    lang: str,
    offset: int,
    full_text: str,
    confidence_band: str | None,
) -> list[LexiconMatch]:
    matches: list[LexiconMatch] = []
    for entry in _entries_for_lang(lang):
        pattern = _entry_pattern(entry.surface)
        for match in pattern.finditer(text):
            start = offset + match.start()
            end = offset + match.end()
            if entry.requires_biblical_book_context and not _has_biblical_book_context(full_text, start, end):
                continue
            matches.append(
                LexiconMatch(
                    surface=match.group(0),
                    normalised=entry.normalised,
                    variant_type=entry.variant_type,
                    confidence=entry.confidence,
                    action=entry.action,
                    start=start,
                    end=end,
                    snippet=_snippet(full_text, start, end),
                    lang=lang,
                    lang_hint=lang,
                    confidence_band=confidence_band,
                )
            )
    return matches


def _entries_for_lang(lang: str) -> tuple[LexiconEntry, ...]:
    forms = archaic_forms(lang)
    variant_type = {
        "en": "archaic_spelling",
        "grc": "greek_ocr_or_historical_form",
        "hbo_latn": "hebrew_transliteration_variant",
        "la": "latin_abbreviation",
    }[lang]
    entries: list[LexiconEntry] = []
    for surface, normalised in forms.items():
        entries.append(
            LexiconEntry(
                surface=surface,
                normalised=normalised,
                variant_type=_variant_type_for(surface, variant_type),
                confidence=_confidence_for(lang),
                requires_biblical_book_context=surface in {"Apocalypse", "Canticles"},
            )
        )
    return tuple(entries)


def _variant_type_for(surface: str, default: str) -> str:
    if surface in {"Esaias", "Elias", "Noe", "Jeremias", "Osee", "Agar", "Sara", "Sarai"}:
        return "biblical_person"
    if surface in {"Apocalypse", "Canticles"}:
        return "biblical_book"
    if surface in {"Chrysostome", "Augustin", "Irenaeus", "Irenæus", "Tertullianus", "Cyprianus", "Hieronymus"}:
        return "patristic_name"
    return default


def _confidence_for(lang: str) -> float:
    return {"en": 0.95, "grc": 0.75, "hbo_latn": 0.7, "la": 0.8}[lang]


def _entry_pattern(surface: str) -> re.Pattern[str]:
    escaped = re.escape(surface)
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def _lexicon_module(lang: str) -> ModuleType:
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"Unsupported lexicon language: {lang}")
    return importlib.import_module(f"ocd_kernel.lib.lexicons.{lang}")


def _normalise_lang(lang: Any) -> str:
    if not isinstance(lang, str):
        return "en"
    normalised = lang.strip().lower().replace("-", "_")
    if normalised in {"eng", "english"}:
        return "en"
    if normalised in {"greek", "el"}:
        return "grc"
    if normalised in {"hebrew_latn", "hebrew_transliteration", "he_latn"}:
        return "hbo_latn"
    if normalised in {"latin"}:
        return "la"
    return normalised


def _valid_span(span: dict[str, Any], text_length: int) -> bool:
    try:
        start = int(span["start"])
        end = int(span["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return 0 <= start < end <= text_length


def _has_biblical_book_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 24) : start].lower()
    after = text[end : min(len(text), end + 24)]
    if re.search(r"(?:book|prophecy|revelation)\s+of\s+$", before):
        return True
    if re.match(r"\s+\d+(?::\d+)?\b", after):
        return True
    return False


def _snippet(text: str, start: int, end: int, radius: int = 40) -> str:
    snippet_start = max(0, start - radius)
    snippet_end = min(len(text), end + radius)
    return re.sub(r"\s+", " ", text[snippet_start:snippet_end]).strip()
