"""Source-transliteration lexicons — ADR-0007 rules-as-data format."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_LEXICON_DIR = Path(__file__).resolve().parent


def load_source_transliteration_lexicons(lang: str) -> list[dict[str, Any]]:
    """Load source-transliteration lexicon for a given language code.

    Returns a list of entries. Each entry has: rule_id, source_tokens,
    underlying_language, enabled. Returns an empty list if the file does
    not exist or is empty.
    """
    yaml_path = _LEXICON_DIR / f"{lang}.yaml"
    if not yaml_path.exists():
        return []
    content = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return content or []
