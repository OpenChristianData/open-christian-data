"""Allowlist of writers permitted to mutate data/.

The pre-commit gate compares the staged writer manifest's ``writer_identity`` against
this allowlist. A manifest carrying an unregistered identity fails the gate. Test
fixtures may NOT register here; the only way to register a real identity is to add it
to ``_REGISTERED`` below in source.
"""

from __future__ import annotations

from typing import Iterable


# Producer types recognised by the pre-commit gate. Parsers regenerate parser-owned
# fields under data/<...>/layers.<field>.{source_raw,normalised,structured}; the
# correction applier mutates layers.<field>.display from approved ledger entries.
# Tool writers own durable auxiliary data that is not parser output.
_PRODUCER_TYPES = frozenset({"parser", "applier", "tool"})


# Registered writer identities. Each entry is (writer_identity, producer_type).
# Add a new parser or applier here in the same commit that ships its first
# manifest-emitting run.
_REGISTERED: dict[str, str] = {
    "ia_schaff_herzog_parser": "parser",
    "ccel_schaff_herzog_parser": "parser",
    "adam_clarke_parser": "parser",
    "church_fathers_parser": "parser",
    "ccel_puritan_parser": "parser",
    "correction_applier": "applier",
    "lexicon_writer": "tool",
    "schaff_herzog_catalog_author": "tool",
    "schaff_herzog_slot11_pipeline": "tool",
    "schaff_herzog_oss_tesseract_writer": "tool",
    "schaff_herzog_azure_writer": "tool",
    "meta_patch_author_year": "tool",
    "meta_patch_st_dates": "tool",
    "meta_patch_bsb": "tool",
    "meta_patch_schaff": "tool",
    "meta_patch_bsb_contributors": "tool",
    "meta_patch_schaff_contributors": "tool",
    "ccel_robertson_parser": "parser",
    "bcp_full_text_parser": "parser",
    "gutenberg_commentary_parser": "parser",
    "gutenberg_inline_markup_parser": "parser",
    "schleitheim_confession_parser": "parser",
    "ccel_boethius_tractates_parser": "parser",
    "gutenberg_evangelical_parser": "parser",
    "meta_patch_author_registry": "tool",
    "catholic_encyclopedia_parser": "parser",
    "ccel_expositors_bible_parser": "parser",
    "ccel_creeds_of_christendom_parser": "parser",
    "bible_text_translations_parser": "parser",
    "creeds_json_catechism_parser": "parser",
    "creeds_json_confession_parser": "parser",
    "sword_devotional_parser": "parser",
    "ia_fisher_marrow_parser": "parser",
    "ia_hastings_dictionary_parser": "parser",
    "spurgeon_mtp_parser": "parser",
    "naves_topical_parser": "parser",
    "bible_dictionaries_parser": "parser",
    "sword_commentary_parser": "parser",
    "westminster_standard_parser": "parser",
}


def is_authorised(writer_identity: str) -> bool:
    """Return True if ``writer_identity`` is registered."""
    return writer_identity in _REGISTERED


def producer_type_for(writer_identity: str) -> str | None:
    """Return the producer type ('parser' | 'applier') for a registered identity, or None."""
    return _REGISTERED.get(writer_identity)


def registered_identities() -> Iterable[str]:
    """Return the list of currently-registered writer identities."""
    return tuple(_REGISTERED.keys())


def known_producer_types() -> frozenset[str]:
    """Return the frozenset of allowed producer types."""
    return _PRODUCER_TYPES
