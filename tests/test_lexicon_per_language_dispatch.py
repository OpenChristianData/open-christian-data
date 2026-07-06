from __future__ import annotations

from build.lib.historical_lexicon import scan_historical_variants
from build.lib.warning_producers.historical_lexicon import run


def _commentary(text: str, lang_spans: list[dict] | None = None) -> dict:
    entry = {"entry_id": "e1", "commentary_text": text}
    if lang_spans is not None:
        entry["lang_spans"] = {"commentary_text": lang_spans}
    return {"meta": {"schema_type": "commentary", "id": "sample", "language": "en"}, "data": [entry]}


def test_span_level_dispatch_routes_only_eligible_span_to_greek() -> None:
    text = "They shew the term αντιλεγομενα here."
    start = text.index("αντιλεγομενα")
    spans = [{"start": start, "end": start + len("αντιλεγομενα"), "lang": "grc", "confidence": "high"}]

    matches = scan_historical_variants(text, lang_hint="en", lang_spans=spans)

    assert [(match.surface, match.lang) for match in matches] == [("shew", "en"), ("αντιλεγομενα", "grc")]


def test_low_or_uncertain_span_confidence_falls_through_to_english() -> None:
    text = "They shew the term αντιλεγομενα here."
    start = text.index("αντιλεγομενα")

    for confidence in ("low", "uncertain"):
        matches = scan_historical_variants(
            text,
            lang_hint="en",
            lang_spans=[{"start": start, "end": start + len("αντιλεγομενα"), "lang": "grc", "confidence": confidence}],
        )
        assert [(match.surface, match.lang) for match in matches] == [("shew", "en")]


def test_warning_producer_signature_and_evidence_include_language_dispatch() -> None:
    text = "They shew the term αντιλεγομενα here."
    start = text.index("αντιλεγομενα")
    spans = [{"start": start, "end": start + len("αντιλεγομενα"), "lang": "grc", "confidence": "high"}]

    warnings = run(_commentary(text, spans), {"resource_type": "commentary"}, {})["warnings"]

    assert len(warnings) == 2
    greek = next(warning for warning in warnings if warning["evidence"]["lang"] == "grc")
    assert greek["evidence"]["archaic_form"] == "αντιλεγομενα"
    assert greek["evidence"]["suggested_modern_form"] == "ἀντιλεγόμενα"
    assert greek["evidence"]["confidence_band"] == "high"
    assert greek["signature"]
