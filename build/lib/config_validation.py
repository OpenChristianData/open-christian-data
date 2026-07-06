"""Helpers for validating parser source config values against generated schema enums."""

from __future__ import annotations

from build.lib import _generated_enums as enums


_SCHEMA_FIELD_CONSTANTS = {
    "sermon": {
        "tradition": "SERMON__META__TRADITION",
        "era": "SERMON__META__ERA",
        "audience": "SERMON__META__AUDIENCE",
        "completeness": "SERMON__META__COMPLETENESS",
        "processing_method": "SERMON__META__PROVENANCE__PROCESSING_METHOD",
    },
    "prayer": {
        "tradition": "PRAYER__META__TRADITION",
        "era": "PRAYER__META__ERA",
        "audience": "PRAYER__META__AUDIENCE",
        "completeness": "PRAYER__META__COMPLETENESS",
        "processing_method": "PRAYER__META__PROVENANCE__PROCESSING_METHOD",
    },
    "devotional": {
        "tradition": "DEVOTIONAL__META__TRADITION",
        "era": "DEVOTIONAL__META__ERA",
        "audience": "DEVOTIONAL__META__AUDIENCE",
        "completeness": "DEVOTIONAL__META__COMPLETENESS",
        "processing_method": "DEVOTIONAL__META__PROVENANCE__PROCESSING_METHOD",
        "period": "DEVOTIONAL__DATA__PERIOD",
    },
    "hymn_collection": {
        "tradition": "HYMN_COLLECTION__META__TRADITION",
        "completeness": "HYMN_COLLECTION__META__COMPLETENESS",
        "processing_method": "HYMN_COLLECTION__META__PROVENANCE__PROCESSING_METHOD",
    },
    "commentary": {
        "tradition": "COMMENTARY__META__TRADITION",
        "completeness": "COMMENTARY__META__COMPLETENESS",
        "processing_method": "COMMENTARY__META__PROVENANCE__PROCESSING_METHOD",
    },
    "bible_text": {
        "tradition": "BIBLE_TEXT__META__TRADITION",
        "completeness": "BIBLE_TEXT__META__COMPLETENESS",
        "processing_method": "BIBLE_TEXT__META__PROVENANCE__PROCESSING_METHOD",
    },
}


def _config_label(config: dict) -> str:
    for key in (
        "slug",
        "resource_id",
        "collection_id",
        "commentary_id",
        "work_id",
        "document_id",
        "id",
        "title",
    ):
        if value := config.get(key):
            return str(value)
    return "config"


def validate_config_enums(config: dict, schema_name: str) -> None:
    """Validate supported external-config parser fields against generated enums."""
    field_map = _SCHEMA_FIELD_CONSTANTS.get(schema_name)
    if field_map is None:
        raise ValueError(f"Unsupported schema_name {schema_name!r}")

    label = _config_label(config)
    for field_name, constant_name in field_map.items():
        allowed = getattr(enums, constant_name, None)
        if allowed is None or field_name not in config:
            continue
        if field_name == "tradition":
            for value in config.get("tradition", []):
                if value not in allowed:
                    raise ValueError(f"{label}: invalid tradition value {value!r}")
            continue
        value = config[field_name]
        if value not in allowed:
            raise ValueError(f"{label}: invalid {field_name} value {value!r}")
