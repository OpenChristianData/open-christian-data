"""Coverage strategy registry and dispatcher."""

from __future__ import annotations

import importlib
from typing import Any


class CoverageStrategyError(ValueError):
    """Raised when a coverage strategy configuration is invalid."""


_REGISTRY: dict[str, Any] = {}

ALLOWED_PAIRS: dict[tuple[str, str], bool] = {
    ("commentary", "scriptural_canon"): True,
    ("commentary", "entry_inventory"): False,
    ("encyclopedia", "entry_inventory"): True,
    ("encyclopedia", "scriptural_canon"): False,
}


def register(name: str, strategy_module: Any) -> None:
    """Register a strategy module after validating its applicability contract."""
    applies_to = getattr(strategy_module, "APPLIES_TO_RESOURCE_TYPES", None)
    if not isinstance(applies_to, list) or not applies_to:
        raise CoverageStrategyError(f"{name}: APPLIES_TO_RESOURCE_TYPES must be a non-empty list")
    for resource_type in applies_to:
        if not isinstance(resource_type, str) or not resource_type:
            raise CoverageStrategyError(f"{name}: APPLIES_TO_RESOURCE_TYPES values must be strings")
        validate_pair(resource_type, name)
    _REGISTRY[name] = strategy_module


def dispatch(resource_type: str, strategy_name: str, parameters: dict[str, Any], record: dict) -> list[dict]:
    """Run a registered coverage strategy."""
    strategy_module = register_record_strategy(resource_type, strategy_name, parameters)
    return strategy_module.run(record, parameters)


def register_record_strategy(resource_type: str, strategy_name: str, parameters: dict[str, Any]) -> Any:
    """Validate a record's strategy config and return the registered module."""
    _ensure_default_strategies_registered()
    validate_pair(resource_type, strategy_name)
    if strategy_name != "none":
        validate_parameter_provenance(parameters)
    try:
        return _REGISTRY[strategy_name]
    except KeyError as exc:
        raise CoverageStrategyError(f"Unknown coverage strategy: {strategy_name}") from exc


def validate_pair(resource_type: str, strategy_name: str) -> None:
    """Raise when a resource type cannot use a coverage strategy."""
    if strategy_name == "none":
        return
    if ALLOWED_PAIRS.get((resource_type, strategy_name)) is True:
        return
    raise CoverageStrategyError(f"Coverage strategy {strategy_name!r} is not allowed for {resource_type!r}")


def validate_parameter_provenance(parameters: dict[str, Any]) -> None:
    """Raise when any strategy parameter lacks a provenance object."""
    if not isinstance(parameters, dict):
        raise CoverageStrategyError("coverage.parameters must be an object")
    for parameter_name, parameter in parameters.items():
        if not isinstance(parameter, dict):
            raise CoverageStrategyError(f"coverage parameter {parameter_name!r} must be an object")
        provenance = parameter.get("provenance")
        if not isinstance(provenance, dict):
            raise CoverageStrategyError(f"coverage parameter {parameter_name!r} is missing provenance")
        source = provenance.get("source")
        path = provenance.get("path")
        if source not in {"config", "source_metadata", "generated_inventory"}:
            raise CoverageStrategyError(f"coverage parameter {parameter_name!r} has invalid provenance.source")
        if not isinstance(path, str) or not path:
            raise CoverageStrategyError(f"coverage parameter {parameter_name!r} has invalid provenance.path")


def _ensure_default_strategies_registered() -> None:
    if _REGISTRY:
        return
    for strategy_name in ("scriptural_canon", "entry_inventory", "none"):
        module = importlib.import_module(f"{__name__}.{strategy_name}")
        register(strategy_name, module)
