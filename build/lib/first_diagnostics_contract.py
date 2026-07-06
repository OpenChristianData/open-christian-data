"""Validation helpers for the first diagnostics report contract."""

from __future__ import annotations

import json
from numbers import Real
from pathlib import Path
from typing import Any

REPORTS_FIRST_SUBPATH: Path = Path("reports") / "diagnostics" / "first"
ORACLE_REPORT_NAME = "vol_01_oracle_accuracy.json"
SEGMENTATION_REPORT_NAME = "vol_01_segmentation_difference.json"
REQUIRED_REPORTS = (ORACLE_REPORT_NAME, SEGMENTATION_REPORT_NAME)

_ORACLE_NUMERIC_KEYS = ("candidate_oracle", "alignment_oracle", "gap")


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _require_object(doc: dict, key: str, problems: list[str]) -> dict | None:
    value = doc.get(key)
    if not isinstance(value, dict):
        problems.append(f"{key} must be an object")
        return None
    return value


def _validate_numeric_keys(doc: dict, keys: tuple[str, ...], prefix: str, problems: list[str]) -> None:
    for key in keys:
        if key not in doc:
            problems.append(f"{prefix}{key} is required")
        elif not _is_number(doc[key]):
            problems.append(f"{prefix}{key} must be a number")


def _validate_breakdown(
    doc: dict,
    key: str,
    required_metrics: tuple[str, ...],
    problems: list[str],
) -> None:
    breakdown = _require_object(doc, key, problems)
    if breakdown is None:
        return

    for label, metrics in breakdown.items():
        if not isinstance(metrics, dict):
            problems.append(f"{key}.{label} must be an object")
            continue
        _validate_numeric_keys(metrics, required_metrics, f"{key}.{label}.", problems)


def validate_oracle_report(doc: dict) -> list[str]:
    """Return human-readable oracle report problems, or an empty list when valid."""
    problems: list[str] = []
    _validate_numeric_keys(doc, _ORACLE_NUMERIC_KEYS, "", problems)
    _validate_breakdown(doc, "by_zone", _ORACLE_NUMERIC_KEYS, problems)
    _validate_breakdown(doc, "by_script", _ORACLE_NUMERIC_KEYS, problems)
    return problems


def validate_segmentation_report(doc: dict) -> list[str]:
    """Return human-readable segmentation report problems, or an empty list when valid."""
    problems: list[str] = []
    engine_pairs = _require_object(doc, "segmentation_difference_by_engine_pair", problems)
    if engine_pairs is not None:
        for pair, value in engine_pairs.items():
            if not _is_number(value):
                problems.append(f"segmentation_difference_by_engine_pair.{pair} must be a number")

    for key in ("by_zone", "by_script"):
        breakdown = _require_object(doc, key, problems)
        if breakdown is None:
            continue
        for label, engine_pair_rates in breakdown.items():
            if not isinstance(engine_pair_rates, dict):
                problems.append(f"{key}.{label} must be an object")
                continue
            for pair, value in engine_pair_rates.items():
                if not _is_number(value):
                    problems.append(f"{key}.{label}.{pair} must be a number")
    return problems


def _load_json(path: Path) -> tuple[dict | None, list[str]]:
    if not path.exists():
        return None, [f"{path.name} is missing"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"{path.name} is not valid JSON: {exc.msg}"]
    except OSError as exc:
        return None, [f"{path.name} could not be read: {exc}"]

    if not isinstance(doc, dict):
        return None, [f"{path.name} must contain a JSON object"]
    return doc, []


def _first_diagnostics_problems(reports_root: Path) -> list[str]:
    report_dir = reports_root / REPORTS_FIRST_SUBPATH
    oracle_path = report_dir / ORACLE_REPORT_NAME
    segmentation_path = report_dir / SEGMENTATION_REPORT_NAME
    problems: list[str] = []

    oracle_doc, load_problems = _load_json(oracle_path)
    problems.extend(load_problems)
    if oracle_doc is not None:
        problems.extend(f"{ORACLE_REPORT_NAME}: {problem}" for problem in validate_oracle_report(oracle_doc))

    segmentation_doc, load_problems = _load_json(segmentation_path)
    problems.extend(load_problems)
    if segmentation_doc is not None:
        problems.extend(
            f"{SEGMENTATION_REPORT_NAME}: {problem}"
            for problem in validate_segmentation_report(segmentation_doc)
        )

    return problems


def first_diagnostics_report_present(reports_root: Path) -> bool:
    """Return True only when all first diagnostics reports exist and validate."""
    return _first_diagnostics_problems(reports_root) == []


def assert_first_diagnostics_valid(reports_root: Path) -> None:
    problems = _first_diagnostics_problems(reports_root)
    if problems:
        raise ValueError("first diagnostics report is invalid: " + "; ".join(problems))


def write_minimal_valid_reports(reports_root: Path) -> None:
    report_dir = reports_root / REPORTS_FIRST_SUBPATH
    report_dir.mkdir(parents=True, exist_ok=True)

    oracle_report = {
        "candidate_oracle": 0.95,
        "alignment_oracle": 0.9,
        "gap": 0.05,
        "by_zone": {
            "body": {
                "candidate_oracle": 0.95,
                "alignment_oracle": 0.9,
                "gap": 0.05,
            }
        },
        "by_script": {
            "latin": {
                "candidate_oracle": 0.95,
                "alignment_oracle": 0.9,
                "gap": 0.05,
            }
        },
    }
    segmentation_report = {
        "segmentation_difference_by_engine_pair": {"tesseract__abbyy": 0.12},
        "by_zone": {"body": {"tesseract__abbyy": 0.12}},
        "by_script": {"latin": {"tesseract__abbyy": 0.08}},
    }

    (report_dir / ORACLE_REPORT_NAME).write_text(
        json.dumps(oracle_report, indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / SEGMENTATION_REPORT_NAME).write_text(
        json.dumps(segmentation_report, indent=2) + "\n",
        encoding="utf-8",
    )
