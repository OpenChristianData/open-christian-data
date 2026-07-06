"""CER/WER evaluation for S1 sidecar OCR output against ground-truth text."""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build.lib.ocr_store_paths import S1_SIDECARS_ROOT


SCRIPT_TYPES = ("latin", "grc", "hbo")
REPORT_ZONE_TYPES = ("body", "footnote", "running-header", "page-number")

# Local copy of the WCT builder zone labels. This tool is deliberately
# self-contained and must not import build.lib.wct_builder.
ZONE_TYPE_MAP = {
    "body": "body",
    "running_header": "running-header",
    "footer_text": "running-header",
    "folio": "page-number",
    "footnote": "footnote",
    "marginalia": "marginalia",
    "caption": "figure",
    "drop_cap": "body",
    "column_rule_or_noise": "figure",
    "text": "body",
    "diagnostic": "body",
}


@dataclass
class GtLine:
    text: str
    script: str


@dataclass
class SidecarLine:
    text: str
    zone: str


@dataclass
class MetricTotals:
    char_edits: int = 0
    char_ref_len: int = 0
    word_edits: int = 0
    word_ref_len: int = 0
    line_count: int = 0

    def add(self, hypothesis: str, reference: str) -> None:
        hyp = unicodedata.normalize("NFC", hypothesis)
        ref = unicodedata.normalize("NFC", reference)
        hyp_words = hyp.split()
        ref_words = ref.split()
        self.char_edits += edit_distance(hyp, ref)
        self.char_ref_len += max(len(ref), 1)
        self.word_edits += edit_distance(hyp_words, ref_words)
        self.word_ref_len += max(len(ref_words), 1)
        self.line_count += 1

    def as_report(self) -> dict[str, float | int]:
        return {
            "cer": self.char_edits / self.char_ref_len if self.char_ref_len else 0.0,
            "wer": self.word_edits / self.word_ref_len if self.word_ref_len else 0.0,
            "line_count": self.line_count,
        }


def ascii_text(value: object) -> str:
    return str(value).encode("ascii", "replace").decode("ascii")


def warn(message: str) -> None:
    print(ascii_text(f"WARNING: {message}"), file=sys.stderr)


def edit_distance(left: str | list[str], right: str | list[str]) -> int:
    if left == right:
        return 0
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_item in enumerate(right, start=1):
            cost = 0 if left_item == right_item else 1
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def cer(hypothesis: str, reference: str) -> float:
    hyp = unicodedata.normalize("NFC", hypothesis)
    ref = unicodedata.normalize("NFC", reference)
    return edit_distance(hyp, ref) / max(len(ref), 1)


def wer(hypothesis: str, reference: str) -> float:
    hyp = unicodedata.normalize("NFC", hypothesis)
    ref = unicodedata.normalize("NFC", reference)
    return edit_distance(hyp.split(), ref.split()) / max(len(ref.split()), 1)


def parse_gt_text(text: str) -> list[GtLine]:
    lines: list[GtLine] = []
    current_script = "latin"
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if stripped.startswith("# script:"):
            script = stripped.removeprefix("# script:").strip()
            current_script = script if script in SCRIPT_TYPES else "latin"
            continue
        if stripped.startswith("#"):
            continue
        if stripped == "":
            current_script = "latin"
            continue
        lines.append(GtLine(unicodedata.normalize("NFC", line), current_script))
    return lines


def load_gt_index(gt_dir: Path) -> dict[str, list[GtLine]]:
    index: dict[str, list[GtLine]] = {}
    for gt_file in sorted(gt_dir.rglob("*.gt.txt")):
        if gt_file.name in index:
            warn(f"duplicate GT filename {gt_file.name}; using first match")
            continue
        index[gt_file.name] = parse_gt_text(gt_file.read_text(encoding="utf-8"))
    return index


def zone_type_for(block_type: str | None) -> str:
    zone = ZONE_TYPE_MAP.get(block_type or "unknown", "body")
    return zone if zone in REPORT_ZONE_TYPES else "body"


def extract_sidecar_lines(sidecar: dict[str, Any]) -> list[SidecarLine]:
    lines: list[SidecarLine] = []
    for block in sidecar.get("blocks", []):
        zone = zone_type_for(block.get("block_type"))
        for line in block.get("lines", []):
            source_raw = line.get("source_raw", "")
            lines.append(SidecarLine(unicodedata.normalize("NFC", str(source_raw)), zone))
    return lines


def empty_engine_stats() -> dict[str, Any]:
    return {
        "overall": MetricTotals(),
        "by_script": {script: MetricTotals() for script in SCRIPT_TYPES},
        "by_zone": {zone: MetricTotals() for zone in REPORT_ZONE_TYPES},
    }


def add_line_metrics(
    engine_stats: dict[str, Any],
    hypothesis: str,
    reference: str,
    script: str,
    zone: str,
) -> None:
    engine_stats["overall"].add(hypothesis, reference)
    engine_stats["by_script"][script].add(hypothesis, reference)
    engine_stats["by_zone"][zone].add(hypothesis, reference)


def gt_name_for_sidecar(sidecar_name: str) -> str:
    return f"{Path(sidecar_name).stem}.gt.txt"


def evaluate_sidecar(
    engine: str,
    sidecar: dict[str, Any],
    sidecar_name: str,
    gt_by_name: dict[str, list[GtLine]],
    stats_by_engine: dict[str, dict[str, Any]],
) -> bool:
    gt_name = gt_name_for_sidecar(sidecar_name)
    gt_lines = gt_by_name.get(gt_name)
    if gt_lines is None:
        warn(f"missing GT for {sidecar_name}")
        return False

    sidecar_lines = extract_sidecar_lines(sidecar)
    engine_stats = stats_by_engine.setdefault(engine, empty_engine_stats())
    pair_count = max(len(sidecar_lines), len(gt_lines))
    for index in range(pair_count):
        hypothesis = sidecar_lines[index].text if index < len(sidecar_lines) else ""
        zone = sidecar_lines[index].zone if index < len(sidecar_lines) else "body"
        reference = gt_lines[index].text if index < len(gt_lines) else ""
        script = gt_lines[index].script if index < len(gt_lines) else "latin"
        add_line_metrics(engine_stats, hypothesis, reference, script, zone)
    return True


def discover_engines(sidecar_root: Path, engine_filter: list[str] | None) -> list[str]:
    if engine_filter:
        return engine_filter
    if not sidecar_root.exists():
        return []
    return sorted(path.name for path in sidecar_root.iterdir() if path.is_dir())


def discover_sidecar_files(engine_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    if not engine_dir.exists():
        return files
    for sidecar_file in sorted(engine_dir.rglob("page_*.json")):
        files.setdefault(sidecar_file.name, sidecar_file)
    return files


def evaluate_paths(
    sidecar_root: Path,
    gt_dir: Path,
    engines: list[str] | None,
) -> dict[str, dict[str, Any]]:
    gt_by_name = load_gt_index(gt_dir)
    stats_by_engine: dict[str, dict[str, Any]] = {}
    engine_names = discover_engines(sidecar_root, engines)
    if engines:
        page_names = sorted(name.removesuffix(".gt.txt") + ".json" for name in gt_by_name)
        for engine in engine_names:
            sidecars = discover_sidecar_files(sidecar_root / engine)
            if not sidecars:
                warn(f"missing sidecar engine directory or files for {engine}")
            for page_name in page_names:
                sidecar_path = sidecars.get(page_name)
                if sidecar_path is None:
                    warn(f"missing sidecar file for {engine}/{page_name}")
                    continue
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                evaluate_sidecar(engine, sidecar, sidecar_path.name, gt_by_name, stats_by_engine)
        return stats_by_engine

    for engine in engine_names:
        for sidecar_path in discover_sidecar_files(sidecar_root / engine).values():
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            evaluate_sidecar(engine, sidecar, sidecar_path.name, gt_by_name, stats_by_engine)
    return stats_by_engine


def report_stats(stats_by_engine: dict[str, dict[str, Any]]) -> dict[str, Any]:
    engines: dict[str, Any] = {}
    for engine, stats in sorted(stats_by_engine.items()):
        engines[engine] = {
            "overall": stats["overall"].as_report(),
            "by_script": {
                script: stats["by_script"][script].as_report() for script in SCRIPT_TYPES
            },
            "by_zone": {
                zone: stats["by_zone"][zone].as_report() for zone in REPORT_ZONE_TYPES
            },
        }
    return engines


def build_report(gt_dir: Path, stats_by_engine: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gt_dir": str(gt_dir),
        "engines": report_stats(stats_by_engine),
    }


def write_report_atomic(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "cer_report.json"
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, output_path)
    return output_path


def print_summary(report: dict[str, Any], output_path: Path) -> None:
    if not report["engines"]:
        print("No matching (sidecar, GT) pairs found -- check --gt-dir and --sidecar-root")
        print(ascii_text(f"JSON report: {output_path}"))
        return
    print("CER/WER evaluation summary")
    for engine, engine_report in report["engines"].items():
        overall = engine_report["overall"]
        print(
            ascii_text(
                f"{engine}: cer={overall['cer']:.6f} "
                f"wer={overall['wer']:.6f} lines={overall['line_count']}"
            )
        )
    print(ascii_text(f"JSON report: {output_path}"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate S1 sidecar CER/WER.")
    parser.add_argument("--sidecar-root", type=Path, default=S1_SIDECARS_ROOT)
    parser.add_argument("--gt-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/cer-evaluation"))
    parser.add_argument("--engines", nargs="+")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.gt_dir.exists():
        warn(f"GT directory does not exist: {args.gt_dir}")
        stats_by_engine: dict[str, dict[str, Any]] = {}
    elif not args.sidecar_root.exists():
        warn(f"sidecar root does not exist: {args.sidecar_root}")
        stats_by_engine: dict[str, dict[str, Any]] = {}
    else:
        stats_by_engine = evaluate_paths(args.sidecar_root, args.gt_dir, args.engines)
    report = build_report(args.gt_dir, stats_by_engine)
    output_path = write_report_atomic(report, args.output_dir)
    print_summary(report, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
