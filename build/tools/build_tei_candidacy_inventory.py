"""Check the committed TEI candidacy inventory against the live repository.

The inventory is deliberately hand-curated; this tool only discovers the live
parser/config/data/IR surfaces and proves that every discovered item is covered.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

CLASSIFICATIONS = {
    "tei-now",
    "tei-later",
    "json-native",
    "correction-only",
    "do-not-migrate",
    "unknown",
}
PARSER_RE = re.compile(r"(build/parsers/[A-Za-z0-9_]+\.py)")


def _posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _matches_glob(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


def _nested_value(payload: dict[str, Any], dotted_key: str) -> Any:
    value: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _rule_matches(path: str, payload: dict[str, Any], rule: dict[str, Any]) -> bool:
    if not _matches_glob(path, rule.get("path_glob", "*")):
        return False
    if any(_matches_glob(path, pattern) for pattern in rule.get("exclude_paths", [])):
        return False
    for key, accepted in rule.get("field_in", {}).items():
        if _nested_value(payload, key) not in accepted:
            return False
    for key, needles in rule.get("field_contains", {}).items():
        value = str(_nested_value(payload, key) or "").lower()
        if not any(str(needle).lower() in value for needle in needles):
            return False
    return True


def _config_matches(entry: dict[str, Any], path: str, payload: dict[str, Any]) -> bool:
    return any(_rule_matches(path, payload, rule) for rule in entry.get("config_rules", []))


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path.as_posix()}")
    return payload


def discover_production_parsers(root: Path, excluded: set[str]) -> set[str]:
    parser_dir = root / "build" / "parsers"
    return {
        _posix(path, root)
        for path in parser_dir.glob("*.py")
        if _posix(path, root) not in excluded
    }


def discover_source_configs(root: Path, excluded_globs: list[str]) -> list[Path]:
    return [
        path
        for path in sorted((root / "sources").glob("**/config.json"))
        if not any(_matches_glob(_posix(path, root), pattern) for pattern in excluded_globs)
    ]


def discover_dataset_outputs(root: Path, excluded_globs: list[str]) -> list[Path]:
    outputs: list[Path] = []
    for path in sorted((root / "data").glob("**/*.json")):
        if any(_matches_glob(_posix(path, root), pattern) for pattern in excluded_globs):
            continue
        payload = _load_json(path)
        if "meta" in payload and "data" in payload:
            outputs.append(path)
    return outputs


def _output_parser(payload: dict[str, Any]) -> str | None:
    meta = payload.get("meta") or {}
    provenance = meta.get("provenance") or {}
    version = provenance.get("processing_script_version") or meta.get("processing_script_version")
    match = PARSER_RE.search(str(version or "").replace("\\", "/"))
    return match.group(1) if match else None


def _glob_owners(entries: list[dict[str, Any]], path: str, key: str) -> list[str]:
    owners: list[str] = []
    for entry in entries:
        if not any(_matches_glob(path, pattern) for pattern in entry.get(key, [])):
            continue
        exclude_key = "data_exclude_globs" if key == "data_globs" else ""
        if exclude_key and any(
            _matches_glob(path, pattern) for pattern in entry.get(exclude_key, [])
        ):
            continue
        owners.append(entry["id"])
    return owners


def check_inventory(root: Path, inventory_path: Path) -> tuple[list[str], dict[str, int]]:
    inventory = _load_json(inventory_path)
    entries = inventory.get("entries", [])
    errors: list[str] = []

    ids = [entry.get("id") for entry in entries]
    if len(ids) != len(set(ids)):
        errors.append("duplicate inventory entry id")
    for entry in entries:
        classification = entry.get("classification")
        if classification not in CLASSIFICATIONS:
            errors.append(f"{entry.get('id')}: invalid classification {classification!r}")
        for required in ("evidence", "priority", "owning_batch", "notes"):
            if required not in entry:
                errors.append(f"{entry.get('id')}: missing {required}")
        if not entry.get("evidence"):
            errors.append(f"{entry.get('id')}: evidence must not be empty")
        if entry.get("tei_status") == "proven-partial" and not entry.get("proof_works"):
            errors.append(f"{entry.get('id')}: proven-partial requires proof_works")

    excluded_items = inventory.get("excluded_parsers", [])
    excluded = {item["path"] for item in excluded_items}
    for item in excluded_items:
        if not item.get("reason"):
            errors.append(f"excluded parser missing reason: {item.get('path')}")
    for key in ("excluded_source_configs", "excluded_data_outputs"):
        for item in inventory.get(key, []):
            if not item.get("path_glob") or not item.get("reason"):
                errors.append(f"{key} item requires path_glob and reason")

    discovered_parsers = discover_production_parsers(root, excluded)
    classified_parsers = {parser for entry in entries for parser in entry.get("parsers", [])}
    for parser in sorted(discovered_parsers - classified_parsers):
        errors.append(f"unclassified production parser: {parser}")
    for parser in sorted(classified_parsers - discovered_parsers):
        errors.append(f"inventory parser is not a live production parser: {parser}")
    for parser in sorted(excluded):
        if not (root / parser).exists():
            errors.append(f"excluded parser does not exist: {parser}")

    excluded_config_globs = [item["path_glob"] for item in inventory.get("excluded_source_configs", [])]
    excluded_data_globs = [item["path_glob"] for item in inventory.get("excluded_data_outputs", [])]
    configs = discover_source_configs(root, excluded_config_globs)
    for path in configs:
        rel = _posix(path, root)
        payload = _load_json(path)
        owners = [entry["id"] for entry in entries if _config_matches(entry, rel, payload)]
        if not owners:
            errors.append(f"unclassified source config: {rel}")
        elif len(owners) > 1:
            errors.append(f"multiply classified source config: {rel} -> {', '.join(owners)}")

    outputs = discover_dataset_outputs(root, excluded_data_globs)
    single_owned_outputs = 0
    for path in outputs:
        rel = _posix(path, root)
        payload = _load_json(path)
        parser = _output_parser(payload)
        owners = _glob_owners(entries, rel, "data_globs")
        if not owners:
            errors.append(f"unclassified data output: {rel}")
        elif len(owners) > 1:
            errors.append(f"multiply owned data output: {rel} -> {', '.join(owners)}")
        else:
            single_owned_outputs += 1
            if parser is not None:
                owner = next(entry for entry in entries if entry["id"] == owners[0])
                if parser not in owner.get("parsers", []):
                    errors.append(
                        f"data output parser mismatch: {rel} -> {owners[0]} does not declare {parser}"
                    )

    ir_files = sorted((root / "ir").glob("**/*.tei.xml"))
    census_files = sorted((root / "ir" / "census").glob("*.census.json"))
    for path, key in [*((path, "ir_globs") for path in ir_files), *((path, "census_globs") for path in census_files)]:
        rel = _posix(path, root)
        owners = _glob_owners(entries, rel, key)
        if not owners:
            errors.append(f"unclassified IR artifact: {rel}")

    counts = Counter(entry["classification"] for entry in entries)
    counts["total"] = len(entries)
    counts["parsers"] = len(discovered_parsers)
    counts["configs"] = len(configs)
    counts["outputs"] = len(outputs)
    counts["single_owned_outputs"] = single_owned_outputs
    counts["ir_artifacts"] = len(ir_files) + len(census_files)
    return errors, dict(counts)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--inventory", type=Path, default=Path("docs/tei-candidacy-inventory.json"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.repo_root.resolve()
    inventory_path = args.inventory
    if not inventory_path.is_absolute():
        inventory_path = root / inventory_path
    errors, counts = check_inventory(root, inventory_path)
    if errors:
        print(f"FAIL: {len(errors)} inventory coverage error(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "PASS: zero unclassified production families; "
        f"{counts['total']} inventory entries cover {counts['parsers']} parsers, "
        f"{counts['configs']} source configs, {counts['outputs']} data outputs, "
        f"and {counts['ir_artifacts']} IR/census artifacts; "
        f"single ownership confirmed for {counts['single_owned_outputs']} data outputs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
