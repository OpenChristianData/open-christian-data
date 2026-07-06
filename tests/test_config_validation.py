import pytest

from build.lib.config_validation import validate_config_enums


def test_validate_config_enums_rejects_invalid_tradition() -> None:
    config = {
        "resource_id": "bad-sermon-config",
        "tradition": ["not-a-tradition"],
    }

    with pytest.raises(ValueError, match="bad-sermon-config: invalid tradition"):
        validate_config_enums(config, "sermon")


def test_validate_config_enums_rejects_unsupported_schema() -> None:
    with pytest.raises(ValueError, match="Unsupported schema_name"):
        validate_config_enums({"resource_id": "structured"}, "structured_text")
