"""Explicit no-op coverage strategy."""

from __future__ import annotations


APPLIES_TO_RESOURCE_TYPES = [
    "commentary",
    "encyclopedia",
    "sermon_collection",
    "anthology",
    "hymnary",
    "creed_corpus",
]


def run(record: dict, parameters: dict) -> list[dict]:
    return []
