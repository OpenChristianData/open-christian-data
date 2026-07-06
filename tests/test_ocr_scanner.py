"""test_ocr_scanner.py -- unit tests for the OCR scanner pipeline.

Run: py -3 -m pytest tests/test_ocr_scanner.py -v
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_scanner import scanner, patterns  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_dict() -> patterns.DictionaryStack:
    return patterns.DictionaryStack(whitelist_terms=set(), lexicon_terms=set(), enable_enchant=False)


def _make_entries(n: int = 5) -> list[dict]:
    """Minimal corpus: n clean entries plus one with a known corruption."""
    entries = [
        {"entry_id": f"test.clean{i}", "term": "AUGUSTINE", "definition_blocks": ["Augustine lived in Hippo."]}
        for i in range(n - 1)
    ]
    entries.append({
        "entry_id": "test.corrupted",
        "term": "THE0T0K0S",
        "definition_blocks": ["A theological term."],
    })
    return entries


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

def test_load_config_schaff_herzog():
    """schaff-herzog config loads and has required keys."""
    cfg = scanner.load_config("schaff-herzog")
    assert cfg["source_id"] == "schaff-herzog"
    assert cfg["pattern_set"] == "ia_djvu"
    assert "scan_fields" in cfg
    assert "ignore_fields" in cfg
    assert "whitelist_terms" in cfg
    assert "tier3_enabled" in cfg


def test_load_config_nonexistent_raises():
    """Unknown source_id raises FileNotFoundError."""
    try:
        scanner.load_config("nonexistent-source-xyz")
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_load_config_ccel_placeholder():
    """ccel-thml-placeholder config loads without error."""
    cfg = scanner.load_config("ccel-thml-placeholder")
    assert cfg["pattern_set"] == "ccel_thml"


# ---------------------------------------------------------------------------
# scan_entries
# ---------------------------------------------------------------------------

def test_scan_entries_detects_digit_in_letter():
    """5-entry corpus with one THE0T0K0S term -> exactly 1 Tier 1 candidate."""
    cfg = scanner.load_config("schaff-herzog")
    entries = _make_entries(5)
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
    tier1 = [c for c in result.candidates if c.tier == 1 and c.reason == "digit_in_letter"]
    assert len(tier1) >= 1
    assert any(c.value == "THE0T0K0S" for c in tier1)


def test_scan_entries_zero_entries_ccel():
    """Zero-entry corpus with ccel-thml-placeholder does not crash."""
    cfg = scanner.load_config("ccel-thml-placeholder")
    result = scanner.scan_entries([], cfg, "ccel-thml-placeholder", _empty_dict())
    assert result.entries_scanned == 0
    assert len(result.candidates) == 0
    assert result.truncated is False


def test_scan_entries_truncation():
    """max_candidates=2 on a corpus producing many candidates -> truncated=True."""
    cfg = scanner.load_config("schaff-herzog")
    # Build a corpus where every entry has a corrupted term
    entries = [
        {"entry_id": f"test.c{i}", "term": f"TH{i}0K0S", "definition_blocks": []}
        for i in range(10)
    ]
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict(), max_candidates=2)
    assert result.truncated is True
    assert len(result.candidates) <= 2
    assert result.truncated_reason is not None


def test_scan_entries_ignore_fields_respected():
    """Fields listed in ignore_fields are not scanned even if also in scan_fields."""
    # Build a local config that puts "term" in both scan_fields and ignore_fields.
    # This exercises the _field_iter ignore guard directly.
    import copy
    cfg = copy.deepcopy(scanner.load_config("schaff-herzog"))
    cfg["scan_fields"] = ["term", "definition_blocks"]
    cfg["ignore_fields"] = ["term"]  # term is in scan_fields but also ignored
    entries = [{
        "entry_id": "test.ignored",
        "term": "THE0T0K0S",        # corrupted -- but field is in ignore_fields
        "definition_blocks": [],
    }]
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
    # THE0T0K0S in term must not surface because term is ignored
    assert not any(c.reason == "digit_in_letter" for c in result.candidates)


def test_scan_entries_scanned_at_has_timezone():
    """scanned_at field is an ISO8601 string with a timezone offset."""
    cfg = scanner.load_config("schaff-herzog")
    result = scanner.scan_entries([], cfg, "schaff-herzog", _empty_dict())
    assert result.scanned_at.endswith("+11:00") or result.scanned_at.endswith("+10:00") or "+" in result.scanned_at or "Z" in result.scanned_at


def test_scan_entries_raises_on_invalid_whitelist_pattern():
    """scan_entries raises ValueError when a whitelist_pattern is invalid regex.

    load_config() validates at load time, but scan_entries() must also
    raise rather than silently skip if called with a bad config directly.
    """
    import copy
    cfg = copy.deepcopy(scanner.load_config("schaff-herzog"))
    cfg["whitelist_patterns"].append("[invalid(regex")  # intentionally broken
    entries = [{"entry_id": "t.e", "term": "TEST", "definition_blocks": []}]
    try:
        scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
        assert False, "Expected ValueError from invalid whitelist_pattern"
    except ValueError as exc:
        assert "whitelist_pattern" in str(exc).lower() or "invalid" in str(exc).lower()


def test_scan_entries_whitelist_suppresses_token_with_trailing_comma():
    """Whitelisted term 'MPL' suppresses token '(MPL,' via stripped form."""
    import copy
    cfg = copy.deepcopy(scanner.load_config("schaff-herzog"))
    cfg["whitelist_terms"] = list(set(cfg.get("whitelist_terms", [])) | {"MPL"})
    cfg["scan_fields"] = ["term"]
    cfg["ignore_fields"] = []
    # Inject a token that would otherwise be flagged by ligature_bracket
    entries = [{"entry_id": "test.mpl", "term": "(MPL,", "definition_blocks": []}]
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
    # Should be suppressed -- no candidates
    mpl_hits = [c for c in result.candidates if "(MPL" in c.value]
    assert mpl_hits == [], f"Expected (MPL, to be suppressed, got: {mpl_hits}"


def test_scan_entries_whitelist_suppresses_token_with_trailing_period():
    """Whitelisted term 'MGH' suppresses token '(MGH.' via stripped form."""
    import copy
    cfg = copy.deepcopy(scanner.load_config("schaff-herzog"))
    cfg["whitelist_terms"] = list(set(cfg.get("whitelist_terms", [])) | {"MGH"})
    cfg["scan_fields"] = ["term"]
    cfg["ignore_fields"] = []
    entries = [{"entry_id": "test.mgh", "term": "(MGH.", "definition_blocks": []}]
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
    mgh_hits = [c for c in result.candidates if "(MGH" in c.value]
    assert mgh_hits == [], f"Expected (MGH. to be suppressed, got: {mgh_hits}"


def test_scan_entries_whitelist_still_suppresses_exact_match():
    """Existing exact-match suppression still works (regression guard)."""
    import copy
    cfg = copy.deepcopy(scanner.load_config("schaff-herzog"))
    cfg["whitelist_terms"] = ["OF"]  # already in default config
    cfg["scan_fields"] = ["term"]
    cfg["ignore_fields"] = []
    entries = [{"entry_id": "test.of", "term": "OF", "definition_blocks": []}]
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
    of_hits = [c for c in result.candidates if c.value == "OF"]
    assert of_hits == [], "Exact-match whitelist suppression broken"


def test_schaff_herzog_config_has_citation_abbreviations():
    """schaff-herzog config includes standard citation abbreviations in whitelist_terms."""
    cfg = scanner.load_config("schaff-herzog")
    wl = {t.upper() for t in cfg.get("whitelist_terms", [])}
    required = {"MPL", "MGH", "ANF", "NPNF", "MPG", "DB", "RE", "TLZ", "ZKG", "TU"}
    missing = required - wl
    assert missing == set(), f"Missing citation abbreviations in whitelist_terms: {missing}"


def test_ligature_ae_loss_not_in_default_scan():
    """ligature_ae_loss does not fire when tier3_enabled=False (default)."""
    cfg = scanner.load_config("schaff-herzog")
    assert cfg["tier3_enabled"] is False  # config guard
    # Token that would trigger ligature_ae_loss if enabled
    entries = [{"entry_id": "t.e", "term": "N(ewcommen", "definition_blocks": []}]
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
    ae_loss_hits = [c for c in result.candidates if c.reason == "ligature_ae_loss"]
    assert ae_loss_hits == [], (
        f"ligature_ae_loss should not fire when tier3_enabled=False; got: {ae_loss_hits}"
    )


def test_ligature_ae_loss_fires_when_tier3_enabled():
    """ligature_ae_loss fires when tier3_enabled=True."""
    import copy
    cfg = copy.deepcopy(scanner.load_config("schaff-herzog"))
    cfg["tier3_enabled"] = True
    entries = [{"entry_id": "t.e", "term": "N(ewcommen", "definition_blocks": []}]
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
    ae_loss_hits = [c for c in result.candidates if c.reason == "ligature_ae_loss"]
    assert len(ae_loss_hits) >= 1, "ligature_ae_loss should fire when tier3_enabled=True"
    assert ae_loss_hits[0].tier == 3


def test_spurgeon_config_uses_html_transcription_pattern_set():
    """spurgeon-mtp config uses html_transcription pattern_set, not ia_djvu."""
    cfg = scanner.load_config("spurgeon-mtp")
    assert cfg["pattern_set"] == "html_transcription", (
        f"Expected html_transcription, got {cfg['pattern_set']}. "
        "Spurgeon MTP is HTML transcription, not DJVU OCR."
    )


def test_schaff_herzog_whitelist_suppresses_roman_numerals_with_l():
    """Extended Roman numeral pattern ^[IVXLCDM]+\\.?$ suppresses XL, IL, DC etc.

    Prior pattern ^[IVX]+\\.?$ did not cover L, C, D, M, so XL (40) and IL (49)
    were incorrectly flagged as short_allcaps_orphan candidates.
    """
    cfg = scanner.load_config("schaff-herzog")
    entries = [{"entry_id": "t.roman", "term": "XL IL DC", "definition_blocks": []}]
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
    flagged = {c.value for c in result.candidates if c.reason == "short_allcaps_orphan"}
    assert "XL" not in flagged, "XL (Roman 40) should be suppressed by ^[IVXLCDM]+\\.?$"
    assert "IL" not in flagged, "IL (Roman 49) should be suppressed by ^[IVXLCDM]+\\.?$"
    assert "DC" not in flagged, "DC (Roman 600) should be suppressed by ^[IVXLCDM]+\\.?$"


def test_schaff_herzog_whitelist_suppresses_single_letter_comma():
    """Pattern ^[A-Z][,;:]$ suppresses single-letter + punctuation tokens (A,, B,, C, etc.).

    These appear throughout SH as abbreviated author initials before commas.
    Prior config had no pattern for this form; all 23 letters generated false positives.
    """
    cfg = scanner.load_config("schaff-herzog")
    entries = [{"entry_id": "t.initials", "term": "A, B, C, J, P,", "definition_blocks": []}]
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
    flagged = {c.value for c in result.candidates if c.reason == "short_allcaps_orphan"}
    for tok in ("A,", "B,", "C,", "J,", "P,"):
        assert tok not in flagged, f"{tok!r} should be suppressed by ^[A-Z][,;:]$"


def test_schaff_herzog_whitelist_suppresses_french_particles():
    """DU, LA, LE added to whitelist_terms to suppress French name particles.

    These appear in SH proper names (du Cange, La Fontaine, Le Clerc) and are
    not OCR artifacts.
    """
    cfg = scanner.load_config("schaff-herzog")
    entries = [{"entry_id": "t.french", "term": "DU LA LE", "definition_blocks": []}]
    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _empty_dict())
    flagged = {c.value for c in result.candidates if c.reason == "short_allcaps_orphan"}
    assert "DU" not in flagged, "DU should be suppressed (French article in SH proper names)"
    assert "LA" not in flagged, "LA should be suppressed (French article)"
    assert "LE" not in flagged, "LE should be suppressed (French article)"


def test_html_transcription_scan_produces_no_ia_djvu_candidates():
    """html_transcription pattern_set produces zero candidates on clean HTML text."""
    cfg = scanner.load_config("spurgeon-mtp")
    entries = [
        {
            "sermon_id": "spurgeon-mtp.1",
            "title": "The Blood",
            "content_blocks": [
                "And the blood shall be to you for a token upon the houses.",
                "By faith they kept the passover.",
            ],
        }
    ]
    result = scanner.scan_entries(entries, cfg, "spurgeon-mtp", _empty_dict())
    # Clean prose should produce zero DJVU-style OCR candidates
    assert result.candidates == [], (
        f"Expected 0 candidates on clean HTML prose, got {len(result.candidates)}: "
        f"{[c.reason for c in result.candidates]}"
    )
