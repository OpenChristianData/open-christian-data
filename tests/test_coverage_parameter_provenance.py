from __future__ import annotations

import pytest

from build.lib.coverage_strategies import CoverageStrategyError, register_record_strategy


def test_strategy_parameter_missing_provenance_fails_registration() -> None:
    with pytest.raises(CoverageStrategyError, match="missing provenance"):
        register_record_strategy(
            "commentary",
            "scriptural_canon",
            {"books": {"value": ["2John"]}},
        )
