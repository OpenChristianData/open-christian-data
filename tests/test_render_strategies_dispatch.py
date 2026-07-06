from __future__ import annotations

import pytest

from build.lib.render_strategies import RenderStrategyError, get_strategy


def test_dispatch_resolves_commentary_strategy() -> None:
    assert get_strategy("commentary").RESOURCE_TYPE == "commentary"


def test_dispatch_resolves_encyclopedia_strategy() -> None:
    assert get_strategy("encyclopedia").RESOURCE_TYPE == "encyclopedia"


def test_unknown_resource_type_raises() -> None:
    with pytest.raises(RenderStrategyError):
        get_strategy("unknown_type")
