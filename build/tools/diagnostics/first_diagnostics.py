"""B8 first diagnostics: candidate/alignment oracle + segmentation-difference.

Wave-3 measurement harness (arch D plan section 3). Consumes B6's vol_01
word-confusion-table pages + B7's vol_01 gold sample and emits the two reports the
B0 tuning embargo gates on (3d9bc567):

    reports/diagnostics/first/<volume>_oracle_accuracy.{json,md}
    reports/diagnostics/first/<volume>_segmentation_difference.{json,md}

Definitions (research-synthesis section 5.1 / R3-D4):

  candidate oracle  -- given the alignment table, how often is the gold truth in
                       the slot's candidate set?
  alignment oracle  -- given perfect alignment of raw outputs to ground truth, how
                       often did ANY engine produce the correct token?
  gap = alignment_oracle - candidate_oracle. A large gap => the ceiling is
        alignment-limited (the correct reading exists but was mis-routed); a small
        gap with both oracles low => diversity-limited. The gap is the diagnostic,
        computed here; the VERDICT (alignment-limited / diversity-limited) is a
        phase-2 reading made with the real reviewer-authored gold in front of the
        maintainer, not a conclusion B8 draws.
  segmentation-difference (per engine pair) -- fraction of shared positions where
        the two engines disagree on token boundaries (token_span_type class:
        exact / split / merge / skip / insertion). If high (research section 5.1
        flags >~20%/pair) geometric pre-grouping becomes load-bearing.

This builds the MEASUREMENT, never the conclusion (B8 prompt): no thresholds are
fitted and nothing is tuned. Every metric is reported by zone and by script so a
difference can never silently aggregate across them.

Scope boundary: the gold->position join (a gold-record-v1 observation_token_id
mapped onto a WCT position via the canonical-identity map) is a phase-2 / B9
concern. B8 takes an already-joined {position_id: truth} map and measures against
it -- the harness is the deliverable, the join and the verdict are downstream.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.first_diagnostics_contract import (  # noqa: E402
    ORACLE_REPORT_NAME,
    REPORTS_FIRST_SUBPATH,
    SEGMENTATION_REPORT_NAME,
)

ORACLE_METRICS = ("candidate_oracle", "alignment_oracle", "gap")


# --------------------------------------------------------------------------- #
# In-memory evaluation records. The pure metric functions operate on these so
# correctness is provable from a synthetic fixture; the extractors below build
# them from real WCT pages.
# --------------------------------------------------------------------------- #


@dataclass
class OraclePosition:
    """One evaluated WCT slot for oracle accuracy.

    truth is the normalised gold reading, or None when the gold is unverifiable /
    absent (excluded from both numerator and denominator). candidate_keys are the
    normalised readings the WCT actually placed in this slot; aligned_raw_keys are
    the normalised raw engine readings a perfect alignment would associate with
    this slot (a superset that recovers readings the as-built WCT mis-routed).
    """

    zone: str
    script: str
    truth: str | None
    candidate_keys: frozenset[str]
    aligned_raw_keys: frozenset[str]


@dataclass
class SegmentationPosition:
    """One WCT slot for segmentation-difference: engine_id -> token_span_type."""

    zone: str
    script: str
    engine_span_types: Mapping[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Normalisation -- the same transform on both sides of an oracle membership test,
# so gold truth and WCT readings compare on equal footing. Kept local to B8 (NFKC
# + casefold + strip); reconciling it with the builder's candidate_key
# normalisation (ligature / hyphen keys) is a tuning follow-up gated by this very
# diagnostic.
# --------------------------------------------------------------------------- #


def normalise_reading(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


# --------------------------------------------------------------------------- #
# Extractors: WCT page (word-confusion-table-v1) -> evaluation records.
# --------------------------------------------------------------------------- #


def _position_zone(position: Mapping) -> str:
    return position["zone"]["zone_type"]


def _position_script(position: Mapping) -> str:
    # image_level is the page-image script call; text_level is the derived block.
    return position["script"]["image_level"]["label"]


def oracle_positions_from_wct(
    page: Mapping,
    gold_by_position: Mapping[str, str | None],
    *,
    oracle_alignment: Mapping[str, Sequence[str]] | None = None,
) -> list[OraclePosition]:
    """Build oracle evaluation records from a WCT page + a position->truth map.

    oracle_alignment optionally injects, per position_id, the correct raw readings
    a perfect-alignment pass recovers that the as-built WCT routed elsewhere. With
    it absent the alignment oracle reduces to "any raw reading in this slot equals
    the truth" -- the floor, never an over-claim.
    """
    alignment = oracle_alignment or {}
    records: list[OraclePosition] = []
    for position in page["positions"]:
        position_id = position["position_id"]
        truth = gold_by_position.get(position_id)
        truth_key = normalise_reading(truth) if truth else None

        candidate_keys = frozenset(
            normalise_reading(candidate["raw_reading"])
            for candidate in position["candidate_set"]
        )

        # aligned_raw_keys is a SUPERSET of candidate_keys by construction: every
        # candidate in a slot is a real reading some engine produced, so perfect
        # alignment always has it available. Seeding candidate_keys here guarantees
        # alignment_oracle >= candidate_oracle (gap >= 0) even when a span record
        # omits its optional raw_text -- a negative gap would silently mislabel an
        # alignment-limited page as diversity-limited.
        raw_keys = set(candidate_keys)
        raw_keys.update(
            normalise_reading(span["raw_text"])
            for span in position["span_records"]
            if span.get("raw_text")
        )
        raw_keys.update(
            normalise_reading(reading) for reading in alignment.get(position_id, [])
        )

        records.append(
            OraclePosition(
                zone=_position_zone(position),
                script=_position_script(position),
                truth=truth_key,
                candidate_keys=candidate_keys,
                aligned_raw_keys=frozenset(raw_keys),
            )
        )
    return records


def segmentation_positions_from_wct(page: Mapping) -> list[SegmentationPosition]:
    records: list[SegmentationPosition] = []
    for position in page["positions"]:
        engine_span_types = {
            span["engine_id"]: span["token_span_type"]
            for span in position["span_records"]
        }
        records.append(
            SegmentationPosition(
                zone=_position_zone(position),
                script=_position_script(position),
                engine_span_types=engine_span_types,
            )
        )
    return records


# --------------------------------------------------------------------------- #
# Metric: oracle accuracy (candidate + alignment, gap = alignment - candidate).
# --------------------------------------------------------------------------- #


def _oracle_scores(positions: Sequence[OraclePosition]) -> dict:
    evaluated = [p for p in positions if p.truth is not None]
    n = len(evaluated)
    if n == 0:
        return {
            "candidate_oracle": 0.0,
            "alignment_oracle": 0.0,
            "gap": 0.0,
            "n": 0,
        }
    candidate = sum(1 for p in evaluated if p.truth in p.candidate_keys) / n
    alignment = sum(1 for p in evaluated if p.truth in p.aligned_raw_keys) / n
    return {
        "candidate_oracle": candidate,
        "alignment_oracle": alignment,
        "gap": alignment - candidate,
        "n": n,
    }


def _grouped(
    positions: Sequence,
    key: Callable[[object], str],
    scorer: Callable[[Sequence], dict],
) -> dict:
    groups: dict[str, list] = {}
    for position in positions:
        groups.setdefault(key(position), []).append(position)
    return {label: scorer(members) for label, members in sorted(groups.items())}


def compute_oracle_accuracy(positions: Sequence[OraclePosition]) -> dict:
    report = _oracle_scores(positions)
    report["by_zone"] = _grouped(positions, lambda p: p.zone, _oracle_scores)
    report["by_script"] = _grouped(positions, lambda p: p.script, _oracle_scores)
    return report


# --------------------------------------------------------------------------- #
# Metric: segmentation-difference per engine pair.
# --------------------------------------------------------------------------- #


def _pair_key(engine_a: str, engine_b: str) -> str:
    low, high = sorted((engine_a, engine_b))
    return f"{low}__{high}"


def _segmentation_rates(positions: Sequence[SegmentationPosition]) -> dict:
    numerator: dict[str, int] = {}
    denominator: dict[str, int] = {}
    for position in positions:
        engines = sorted(position.engine_span_types)
        for i in range(len(engines)):
            for j in range(i + 1, len(engines)):
                engine_a, engine_b = engines[i], engines[j]
                key = _pair_key(engine_a, engine_b)
                denominator[key] = denominator.get(key, 0) + 1
                if (
                    position.engine_span_types[engine_a]
                    != position.engine_span_types[engine_b]
                ):
                    numerator[key] = numerator.get(key, 0) + 1
    return {
        key: numerator.get(key, 0) / denominator[key]
        for key in sorted(denominator)
    }


def compute_segmentation_difference(
    positions: Sequence[SegmentationPosition],
) -> dict:
    return {
        "segmentation_difference_by_engine_pair": _segmentation_rates(positions),
        "by_zone": _grouped(positions, lambda p: p.zone, _segmentation_rates),
        "by_script": _grouped(positions, lambda p: p.script, _segmentation_rates),
    }


# --------------------------------------------------------------------------- #
# Report writers -- json + a human-readable md sibling, written atomically to the
# exact path the B0 embargo checks (names derived so they cannot drift).
# --------------------------------------------------------------------------- #


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_json(path: Path, doc: dict) -> None:
    _atomic_write(path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def _oracle_markdown(doc: dict, volume: str) -> str:
    lines = [
        f"# First diagnostics -- oracle accuracy ({volume})",
        "",
        "Candidate oracle: truth in the slot's candidate set. Alignment oracle:",
        "truth in any engine's raw reading under perfect alignment. Gap =",
        "alignment - candidate (large gap => alignment-limited). Verdict is phase 2.",
        "",
        "Membership is tested with a local NFKC + casefold + strip transform on both",
        "the gold truth and each candidate's raw_reading -- NOT the WCT builder's",
        "case-sensitive candidate_key (which also carries ligature + hyphen-unjoined",
        "keys). Reconciling the two normalisations is tuning gated by THIS diagnostic.",
        "",
        f"- candidate oracle: {doc['candidate_oracle']:.4f}",
        f"- alignment oracle: {doc['alignment_oracle']:.4f}",
        f"- gap (alignment - candidate): {doc['gap']:.4f}",
        f"- positions evaluated: {doc.get('n', 0)}",
        "",
    ]
    for axis in ("by_zone", "by_script"):
        lines.append(f"## {axis}")
        lines.append("")
        lines.append("| group | candidate | alignment | gap | n |")
        lines.append("|---|---|---|---|---|")
        for label, scores in doc.get(axis, {}).items():
            lines.append(
                f"| {label} | {scores['candidate_oracle']:.4f} | "
                f"{scores['alignment_oracle']:.4f} | {scores['gap']:.4f} | "
                f"{scores.get('n', 0)} |"
            )
        lines.append("")
    return "\n".join(lines)


def _segmentation_markdown(doc: dict, volume: str) -> str:
    lines = [
        f"# First diagnostics -- segmentation difference ({volume})",
        "",
        "Per engine pair: fraction of shared positions where the engines disagree",
        "on token boundaries (token_span_type class). >~20%/pair => geometric",
        "pre-grouping load-bearing (research section 5.1). Verdict is phase 2.",
        "",
        "## by engine pair",
        "",
        "| engine pair | segmentation difference |",
        "|---|---|",
    ]
    for pair, rate in doc["segmentation_difference_by_engine_pair"].items():
        lines.append(f"| {pair} | {rate:.4f} |")
    lines.append("")
    for axis in ("by_zone", "by_script"):
        lines.append(f"## {axis}")
        lines.append("")
        for label, pairs in doc.get(axis, {}).items():
            lines.append(f"### {label}")
            lines.append("")
            lines.append("| engine pair | segmentation difference |")
            lines.append("|---|---|")
            for pair, rate in pairs.items():
                lines.append(f"| {pair} | {rate:.4f} |")
            lines.append("")
    return "\n".join(lines)


def _report_dir(reports_root: Path) -> Path:
    report_dir = Path(reports_root) / REPORTS_FIRST_SUBPATH
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def write_oracle_report(reports_root: Path, doc: dict, *, volume: str = "vol_01") -> Path:
    # Fail closed on a vacuous measurement: a zero-position oracle report still
    # satisfies the embargo's shape validator and would unlock tuning on nothing.
    # An empty gold join is a precondition error, not a measurement (REL-02).
    if doc.get("n", 0) == 0:
        raise ValueError(
            "oracle report is vacuous (0 evaluated gold positions) -- refusing to "
            "write a report that would unlock the tuning embargo on no measurement"
        )
    json_name = f"{volume}_oracle_accuracy.json"
    # vol_01 is the embargo key -- fail fast if the name ever drifts from B0.
    if volume == "vol_01" and json_name != ORACLE_REPORT_NAME:
        raise RuntimeError(
            "oracle report name drifted from the B0 first-diagnostics contract"
        )
    report_dir = _report_dir(reports_root)
    _write_json(report_dir / json_name, doc)
    _atomic_write(report_dir / f"{volume}_oracle_accuracy.md", _oracle_markdown(doc, volume))
    return report_dir / json_name


def write_segmentation_report(
    reports_root: Path, doc: dict, *, volume: str = "vol_01"
) -> Path:
    # Fail closed on a vacuous measurement: no comparable engine pair means there
    # was nothing to compare (fewer than two engines anywhere on the page).
    if not doc.get("segmentation_difference_by_engine_pair"):
        raise ValueError(
            "segmentation report is vacuous (no comparable engine pairs) -- refusing "
            "to write a report that would unlock the tuning embargo on no measurement"
        )
    json_name = f"{volume}_segmentation_difference.json"
    if volume == "vol_01" and json_name != SEGMENTATION_REPORT_NAME:
        raise RuntimeError(
            "segmentation report name drifted from the B0 first-diagnostics contract"
        )
    report_dir = _report_dir(reports_root)
    _write_json(report_dir / json_name, doc)
    _atomic_write(
        report_dir / f"{volume}_segmentation_difference.md",
        _segmentation_markdown(doc, volume),
    )
    return report_dir / json_name


# --------------------------------------------------------------------------- #
# Orchestrator + CLI.
# --------------------------------------------------------------------------- #


def run_first_diagnostics(
    *,
    oracle_page: Mapping,
    oracle_gold: Mapping[str, str | None],
    segmentation_page: Mapping,
    reports_root: Path,
    oracle_alignment: Mapping[str, Sequence[str]] | None = None,
    volume: str = "vol_01",
    write: bool = True,
) -> dict:
    """Measure both first diagnostics and (by default) write the gated reports.

    write=False is the embargo's read-only diagnostic mode: compute and return the
    docs without touching disk, so the tuning embargo stays closed.
    """
    oracle_positions = oracle_positions_from_wct(
        oracle_page, oracle_gold, oracle_alignment=oracle_alignment
    )
    oracle_doc = compute_oracle_accuracy(oracle_positions)

    segmentation_positions = segmentation_positions_from_wct(segmentation_page)
    segmentation_doc = compute_segmentation_difference(segmentation_positions)

    if write:
        write_oracle_report(reports_root, oracle_doc, volume=volume)
        write_segmentation_report(reports_root, segmentation_doc, volume=volume)

    return {"oracle": oracle_doc, "segmentation": segmentation_doc}


def _load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="B8 first diagnostics: oracle accuracy + segmentation difference."
    )
    parser.add_argument("--oracle-wct", required=True, type=Path, help="WCT page JSON for oracle accuracy.")
    parser.add_argument(
        "--gold",
        required=True,
        type=Path,
        help="position_id -> truth map JSON (already joined; the join is phase 2).",
    )
    parser.add_argument(
        "--segmentation-wct",
        required=True,
        type=Path,
        help="WCT page JSON for segmentation difference (often the same page).",
    )
    parser.add_argument(
        "--oracle-alignment",
        type=Path,
        default=None,
        help="optional position_id -> [readings] map from a perfect-alignment pass.",
    )
    parser.add_argument("--reports-root", required=True, type=Path, help="report tree root.")
    parser.add_argument("--volume", default="vol_01", help="volume label (vol_01 is the embargo key).")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="compute and print without writing (embargo read-only mode).",
    )
    args = parser.parse_args(argv)

    alignment = _load_json(args.oracle_alignment) if args.oracle_alignment else None
    result = run_first_diagnostics(
        oracle_page=_load_json(args.oracle_wct),
        oracle_gold=_load_json(args.gold),
        segmentation_page=_load_json(args.segmentation_wct),
        reports_root=args.reports_root,
        oracle_alignment=alignment,
        volume=args.volume,
        write=not args.read_only,
    )

    oracle = result["oracle"]
    print(
        "oracle: candidate={:.4f} alignment={:.4f} gap={:.4f} n={}".format(
            oracle["candidate_oracle"],
            oracle["alignment_oracle"],
            oracle["gap"],
            oracle.get("n", 0),
        )
    )
    for pair, rate in result["segmentation"][
        "segmentation_difference_by_engine_pair"
    ].items():
        print("segmentation {}: {:.4f}".format(pair, rate))
    if args.read_only:
        print("read-only: reports not written; tuning embargo stays closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
