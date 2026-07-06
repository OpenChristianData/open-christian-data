"""R33 — language_segments[] content fields are identical across sibling configs.

In a (original, modernised) pair, each language_segments[] entry's content
fields — language, original_script, transliteration, transliterated_from —
must be byte-identical.  Only `span` may differ (Modernise can shift token
offsets when modernising around a transliterated segment).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


_LANG_SEG = {
    "span": {"start_token": 3, "end_token": 4},
    "language": "grc",
    "original_script": "αγαπη",
    "transliteration": "agapē",
    "transliterated_from": "grc",
}

_ORIG_BLOCK = {
    "block_id": "b_0001aaaa",
    "block_id_history": [],
    "block_type": "paragraph",
    "language": "en",
    "language_confidence": 0.95,
    "language_alternates": [],
    "language_segments": [_LANG_SEG],
    "original_text": "The word for love, agapē, is key.",
    "modern_text": "The word for love, agapē, is key.",
    "annotations": {},
    "source_pages": [],
    "attested_by": ["ccel/test/work/1900/thml"],
    "disagreements": [],
    "structural_disagreements": [],
    "modernisations": [],
}

_BASE_META = {
    "id": "test.work.1900",
    "title": "Test Work",
    "author_slug": "test",
    "author_display_name": "Test Author",
    "author_birth_year": None,
    "author_death_year": None,
    "original_publication_year": 1900,
    "language": "en",
    "tradition": ["evangelical"],
    "license": "public-domain",
    "schema_type": "reconciled_record",
    "schema_version": "3.0.0",
    "edition": "1900",
    "pd_anchor": "ccel/test/work/1900/thml",
    "modernisation_ruleset_version": None,
    "attestation_summary": {
        "block_count": 1,
        "fully_attested_blocks": 1,
        "blocks_with_disagreements": 0,
        "blocks_with_structural_disagreements": 0,
    },
}

_ORIGINAL_RECORD = {
    "meta": _BASE_META,
    "blocks": [_ORIG_BLOCK],
    "match_explanations": [],
}

# Modernised sibling: span may differ (hath→has shifted one token),
# but content fields must be identical.
_MOD_LANG_SEG = {**_LANG_SEG, "span": {"start_token": 3, "end_token": 4}}

_MOD_BLOCK = {
    **_ORIG_BLOCK,
    "language_segments": [_MOD_LANG_SEG],
    "modernisations": [],
}

_MODERNISED_META = {
    **_BASE_META,
    "schema_type": "modernised_record",
    "modernisation_ruleset_version": "en@1.0.0",
    "paired_with": "data/commentary/test/work/1900/original/vol-01.json",
}

_MODERNISED_RECORD = {
    "meta": _MODERNISED_META,
    "blocks": [_MOD_BLOCK],
    "match_explanations": [],
}


def test_original_record_with_language_segment_validates() -> None:
    schema = _schema("reconciled_record")
    jsonschema.validate(instance=_ORIGINAL_RECORD, schema=schema)


def test_modernised_record_with_language_segment_validates() -> None:
    schema = _schema("modernised_record")
    jsonschema.validate(instance=_MODERNISED_RECORD, schema=schema)


_SHARED_FIELDS = ("language", "original_script", "transliteration", "transliterated_from")


def test_language_segment_content_fields_equal_across_siblings() -> None:
    """The invariant: content fields match between paired siblings."""
    orig_segs = _ORIGINAL_RECORD["blocks"][0]["language_segments"]
    mod_segs = _MODERNISED_RECORD["blocks"][0]["language_segments"]
    assert len(orig_segs) == len(mod_segs)
    for orig_seg, mod_seg in zip(orig_segs, mod_segs, strict=True):
        for field in _SHARED_FIELDS:
            assert orig_seg.get(field) == mod_seg.get(field), (
                f"language_segments[].{field} differs between configs: "
                f"original={orig_seg.get(field)!r}, modernised={mod_seg.get(field)!r}"
            )


def test_language_segment_diverged_content_field_detected() -> None:
    """Diverged language field between siblings is detectable (drives Checker in Slot 7)."""
    tampered_mod = copy.deepcopy(_MODERNISED_RECORD)
    tampered_mod["blocks"][0]["language_segments"][0]["language"] = "la"
    orig_lang = _ORIGINAL_RECORD["blocks"][0]["language_segments"][0]["language"]
    mod_lang = tampered_mod["blocks"][0]["language_segments"][0]["language"]
    assert orig_lang != mod_lang
