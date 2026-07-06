"""test_schema_enums.py
Tests for build.lib.schema_enums.get_enum().

Covers:
  - Known top-level path (tradition via items.enum) returns frozenset
  - Nested path (data → work_kind via direct enum) works
  - Missing key raises KeyError with a helpful message
  - Missing schema raises FileNotFoundError
  - Return type is frozenset, not list or set
  - null values are excluded from the result
  - Loading the same schema twice does not re-read the file (lru_cache)
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.schema_enums import _load_schema, get_enum  # noqa: E402


class TestGetEnum:
    def setup_method(self):
        """Clear the schema cache before each test for isolation."""
        _load_schema.cache_clear()

    def test_tradition_returns_frozenset(self):
        result = get_enum("structured_text", "meta", "tradition")
        assert isinstance(result, frozenset)

    def test_tradition_contains_expected_values(self):
        result = get_enum("structured_text", "meta", "tradition")
        expected = {
            "reformed", "lutheran", "anglican", "baptist", "methodist",
            "catholic", "orthodox", "ecumenical", "evangelical",
            "dutch-reformed", "holiness", "quaker", "puritan",
        }
        assert expected.issubset(result), f"Missing: {expected - result}"

    def test_tradition_is_array_items_enum(self):
        """tradition is an array property; enum lives under items.enum."""
        result = get_enum("structured_text", "meta", "tradition")
        assert len(result) > 20, "Expected 30+ tradition values from the schema"

    def test_nested_data_work_kind(self):
        """work_kind lives under data (direct enum, not items)."""
        result = get_enum("structured_text", "data", "work_kind")
        assert isinstance(result, frozenset)
        assert "theological-work" in result
        assert "devotional-classic" in result
        assert "systematic-theology" in result

    def test_era_direct_enum(self):
        """era uses a direct enum (not items.enum)."""
        result = get_enum("structured_text", "meta", "era")
        assert isinstance(result, frozenset)
        assert "modern" in result
        assert "medieval" in result

    def test_null_excluded_from_enum(self):
        """era and audience allow null in the JSON schema; null must not appear in result."""
        era_result = get_enum("structured_text", "meta", "era")
        assert None not in era_result
        audience_result = get_enum("structured_text", "meta", "audience")
        assert None not in audience_result

    def test_missing_key_raises_key_error_with_message(self):
        with pytest.raises(KeyError, match="nonexistent_field"):
            get_enum("structured_text", "meta", "nonexistent_field")

    def test_key_error_names_schema(self):
        with pytest.raises(KeyError, match="structured_text"):
            get_enum("structured_text", "meta", "nonexistent_field")

    def test_missing_schema_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            get_enum("no_such_schema_xyz", "meta", "tradition")

    def test_return_type_is_frozenset_not_set(self):
        result = get_enum("structured_text", "meta", "tradition")
        assert not isinstance(result, set), "Must be frozenset, not mutable set"
        assert isinstance(result, frozenset)

    def test_return_type_is_frozenset_not_list(self):
        result = get_enum("structured_text", "data", "work_kind")
        assert not isinstance(result, list)
        assert isinstance(result, frozenset)

    def test_same_schema_loaded_once(self):
        """Two get_enum calls with the same schema produce exactly one file read."""
        _load_schema.cache_clear()
        get_enum("structured_text", "meta", "tradition")
        get_enum("structured_text", "meta", "era")
        info = _load_schema.cache_info()
        assert info.misses == 1, (
            f"Expected 1 cache miss (1 file read), got {info.misses}"
        )
        assert info.hits == 1, (
            f"Expected 1 cache hit (second call reused cache), got {info.hits}"
        )

    def test_different_schemas_each_loaded_once(self):
        """Two different schemas produce two file reads."""
        _load_schema.cache_clear()
        get_enum("structured_text", "meta", "tradition")
        get_enum("catechism_qa", "meta", "tradition")
        info = _load_schema.cache_info()
        assert info.misses == 2
        assert info.hits == 0

    def test_catechism_schema_tradition(self):
        result = get_enum("catechism_qa", "meta", "tradition")
        assert isinstance(result, frozenset)
        assert "reformed" in result
        assert "lutheran" in result

    def test_doctrinal_document_schema_tradition(self):
        result = get_enum("doctrinal_document", "meta", "tradition")
        assert isinstance(result, frozenset)
        assert "reformed" in result
