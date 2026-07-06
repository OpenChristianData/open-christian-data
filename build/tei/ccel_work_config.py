"""Shared CCEL TEI work-config helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree


@dataclass(frozen=True)
class CcelWorkConfig:
    work_id: str
    rendering_id: str
    raw_path: Path
    scope: dict[str, str]
    title: str
    author: str
    contributors: list[str]
    source_url: str
    source_hash: str
    source_edition: str
    division_rules: list[dict[str, Any]]


def load_ccel_work_config(
    config_path: str | Path,
    work_id: str,
    repo_root: str | Path = ".",
) -> CcelWorkConfig:
    root = Path(repo_root)
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    for item in payload.get("works", []):
        if item.get("work_id") != work_id:
            continue
        raw_path = Path(item["raw_path"])
        if not raw_path.is_absolute():
            raw_path = root / raw_path
        return CcelWorkConfig(
            work_id=str(item["work_id"]),
            rendering_id=str(item.get("rendering_id") or ""),
            raw_path=raw_path,
            scope=dict(item["scope"]),
            title=str(item.get("title") or ""),
            author=str(item.get("author") or ""),
            contributors=[str(value) for value in item.get("contributors", [])],
            source_url=str(item.get("source_url") or ""),
            source_hash=str(item.get("source_hash") or ""),
            source_edition=str(item.get("source_edition") or ""),
            division_rules=[dict(rule) for rule in item.get("division_rules", [])],
        )
    raise ValueError(f"No CCEL work config found for work_id {work_id!r}")


def select_ccel_scope(root: etree._Element, config: CcelWorkConfig) -> etree._Element:
    tag = config.scope.get("tag")
    source_id = config.scope.get("id")
    if not tag or not source_id:
        raise ValueError(f"Work config {config.work_id!r} must declare scope tag and id")
    matches = [node for node in root.iter(tag) if node.get("id") == source_id]
    if not matches:
        raise ValueError(f"No {tag} with id {source_id!r} found in {config.raw_path.as_posix()}")
    return matches[0]


def ccel_rule_matches(rule: dict[str, Any], node: etree._Element) -> bool:
    tag = etree.QName(node).localname
    if rule.get("tag") and rule["tag"] != tag:
        return False
    if rule.get("source_type") and rule["source_type"] != node.get("type"):
        return False
    if rule.get("id") and rule["id"] != node.get("id"):
        return False
    if rule.get("title") and rule["title"] != node.get("title"):
        return False
    return True


def ccel_division_rule(node: etree._Element, rules: list[dict[str, Any]]) -> dict[str, Any]:
    for rule in rules:
        if ccel_rule_matches(rule, node):
            return rule
    source_type = (node.get("type") or "").strip().lower()
    return {"tei_type": source_type or "section", "place": "body"}


def ccel_scope_label(config: CcelWorkConfig) -> str:
    return f"{config.scope.get('tag')}[@id='{config.scope.get('id')}']"
