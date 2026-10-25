"""Complete-file Hugging Face feature metadata without a runtime HF dependency."""

from __future__ import annotations

import math
from typing import Any, Iterable

from ocd_kernel.library._common import PipelineError


def configuration_features(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union fields at every nesting level, including fields in later records.

    Missing fields are nullable in Arrow. Incompatible types fail explicitly;
    this metadata must never stringify, flatten, or coerce source content.
    """
    def describe(value: Any):
        if value is None:
            return ("null", None)
        if isinstance(value, dict):
            return ("struct", {key: describe(child) for key, child in value.items()})
        if isinstance(value, list):
            element = ("null", None)
            for child in value:
                element = merge(element, describe(child))
            return ("list", element)
        if type(value) is bool:
            return ("bool", None)
        if type(value) is int and -(2**63) <= value < 2**63:
            return ("int64", None)
        if type(value) is float and math.isfinite(value):
            return ("float64", None)
        if isinstance(value, str):
            return ("string", None)
        raise PipelineError("configuration has an unsupported feature value")

    def merge(left, right):
        if left[0] == "null":
            return right
        if right[0] == "null":
            return left
        if left[0] != right[0]:
            raise PipelineError(f"incompatible configuration feature types: {left[0]} / {right[0]}")
        if left[0] == "struct":
            fields = dict(left[1])
            for key, child in right[1].items():
                fields[key] = merge(fields.get(key, ("null", None)), child)
            return ("struct", fields)
        if left[0] == "list":
            return ("list", merge(left[1], right[1]))
        return left

    def fields(node):
        return [{"name": key, **feature(value)} for key, value in sorted(node[1].items())]

    def feature(node):
        kind, child = node
        if kind == "struct":
            return {"struct": fields(node)}
        if kind == "list":
            if child[0] == "struct":
                return {"list": fields(child)}
            if child[0] == "list":
                return {"list": feature(child)}
            return {"list": child[0]}
        return {"dtype": kind}

    combined = ("struct", {})
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            raise PipelineError("configuration feature inference requires object rows")
        combined = merge(combined, describe(row))
        count += 1
    if not count:
        raise PipelineError("configuration feature inference requires nonempty rows")
    return fields(combined)
