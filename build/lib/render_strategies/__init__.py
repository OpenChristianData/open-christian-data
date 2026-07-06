"""Resource-type dispatch for review HTML render strategies."""

from __future__ import annotations

import importlib
import re
from types import ModuleType
from typing import Any


_RESOURCE_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class RenderStrategyError(ValueError):
    """Raised when no valid renderer exists for a resource type."""


def get_strategy(resource_type: str) -> ModuleType:
    """Return the render strategy module for ``resource_type``."""
    if not isinstance(resource_type, str) or not _RESOURCE_TYPE_RE.fullmatch(resource_type):
        raise RenderStrategyError(f"Invalid resource_type for render strategy: {resource_type!r}")

    module_name = f"{__name__}.{resource_type}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise RenderStrategyError(f"No render strategy registered for resource_type={resource_type!r}") from exc
        raise

    declared = getattr(module, "RESOURCE_TYPE", None)
    if declared != resource_type:
        raise RenderStrategyError(
            f"Render strategy {module_name} declares RESOURCE_TYPE={declared!r}, expected {resource_type!r}"
        )
    for attr in ("render_resource", "render_navigation"):
        if not callable(getattr(module, attr, None)):
            raise RenderStrategyError(f"Render strategy {module_name} is missing callable {attr}()")
    return module


def render_resource(resource_type: str, record: dict[str, Any]) -> str:
    """Render resource-shaped body HTML for ``record``."""
    return get_strategy(resource_type).render_resource(record)


def render_navigation(resource_type: str, record: dict[str, Any]) -> str:
    """Render resource-shaped navigation HTML for ``record``."""
    return get_strategy(resource_type).render_navigation(record)
