from __future__ import annotations

import math

from build.tools.ocr_scanner import patterns, scanner


def _dictionary() -> patterns.DictionaryStack:
    return patterns.DictionaryStack(whitelist_terms=set(), lexicon_terms=set(), enable_enchant=False)


def test_scan_entries_accepts_math_inf_as_no_truncation_sentinel() -> None:
    cfg = scanner.load_config("schaff-herzog")
    entries = [
        {"entry_id": f"test.{i}", "term": f"THE{i}T0K0S", "definition_blocks": []}
        for i in range(25)
    ]

    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _dictionary(), max_candidates=math.inf)

    assert result.truncated is False
    assert result.truncated_reason is None
    assert len(result.candidates) < math.inf


def test_scan_entries_accepts_none_as_no_truncation_sentinel() -> None:
    cfg = scanner.load_config("schaff-herzog")
    entries = [{"entry_id": "test.one", "term": "THE0T0K0S", "definition_blocks": []}]

    result = scanner.scan_entries(entries, cfg, "schaff-herzog", _dictionary(), max_candidates=None)

    assert result.truncated is False
    assert len(result.candidates) >= 1
