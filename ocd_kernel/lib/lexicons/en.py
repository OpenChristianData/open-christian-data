"""English historical spelling and naming variants."""

from __future__ import annotations

import json
from importlib import resources


COVERAGE_STATUS = "production"
_LEXICON_RESOURCE = "archaic_forms_en.json"


def _load_lexicon() -> dict[str, str]:
    resource = resources.files(__package__).joinpath("data", _LEXICON_RESOURCE)
    with resource.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in loaded.items()):
        raise ValueError(f"{resource} must contain a JSON object mapping strings to strings")
    identity_maps = sorted(key for key, value in loaded.items() if key.casefold() == value.casefold())
    assert not identity_maps, f"English lexicon identity self-maps are forbidden: {identity_maps[:5]}"
    return loaded


ARCHAIC_FORMS = _load_lexicon()

