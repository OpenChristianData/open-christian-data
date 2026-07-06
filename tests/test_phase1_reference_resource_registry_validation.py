"""R15 — reference_resources/<lang>.yaml validation.

Phase 1 minimum entries: grc → Liddell-Scott, hbo → BDB, la → Lewis & Short.
Each registry file must:
  - name a language code in the ADR-0010 active set
  - list entries with work_handle, resource_type, scope_note
  - resource_type in {lexicon, concordance, grammar, theological_dictionary}
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIR = REPO_ROOT / "build" / "lib" / "reference_resources"

VALID_RESOURCE_TYPES = frozenset(
    ["lexicon", "concordance", "grammar", "theological_dictionary"]
)

# ADR-0010 active set for Phase 1
ACTIVE_LANG_CODES = frozenset(["en", "grc", "hbo", "hbo_latn", "la", "fr", "de"])

PHASE1_MINIMUM: dict[str, str] = {
    "grc": "liddell-scott",
    "hbo": "bdb",
    "la": "lewis-and-short",
}


def _load_registry(lang: str) -> list[dict]:
    path = REGISTRY_DIR / f"{lang}.yaml"
    if not path.exists():
        pytest.fail(f"Missing registry file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if data else []


@pytest.mark.parametrize("lang", list(PHASE1_MINIMUM.keys()))
def test_phase1_minimum_registry_files_exist(lang: str) -> None:
    path = REGISTRY_DIR / f"{lang}.yaml"
    assert path.exists(), f"Phase 1 minimum registry file missing: {path}"


@pytest.mark.parametrize("lang", list(PHASE1_MINIMUM.keys()))
def test_registry_entries_have_required_fields(lang: str) -> None:
    entries = _load_registry(lang)
    assert len(entries) >= 1, f"Registry {lang}.yaml must have at least one entry"
    for entry in entries:
        assert "work_handle" in entry, f"{lang}: missing work_handle in {entry}"
        assert "resource_type" in entry, f"{lang}: missing resource_type in {entry}"
        assert "scope_note" in entry, f"{lang}: missing scope_note in {entry}"


@pytest.mark.parametrize("lang", list(PHASE1_MINIMUM.keys()))
def test_registry_resource_types_valid(lang: str) -> None:
    entries = _load_registry(lang)
    for entry in entries:
        rt = entry.get("resource_type", "")
        assert rt in VALID_RESOURCE_TYPES, (
            f"{lang}: invalid resource_type {rt!r}; "
            f"must be one of {sorted(VALID_RESOURCE_TYPES)}"
        )


@pytest.mark.parametrize("lang,expected_handle_fragment", PHASE1_MINIMUM.items())
def test_phase1_minimum_entries_present(lang: str, expected_handle_fragment: str) -> None:
    entries = _load_registry(lang)
    handles = [e.get("work_handle", "") for e in entries]
    assert any(expected_handle_fragment in h for h in handles), (
        f"Phase 1 minimum entry for {lang} not found; "
        f"expected a work_handle containing {expected_handle_fragment!r}, "
        f"got: {handles}"
    )
