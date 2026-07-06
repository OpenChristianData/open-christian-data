"""GAP_PENALTY sweep tool for align_je_to_wct.py.

Iterates over a range of GAP_PENALTY values, runs dry-run alignment for all
article slugs, and prints a comparison table of M0/coverage/confusion metrics.

Usage:
    py -3 build/tools/tune_je_gap_penalty.py \\
        --article-root <path> \\
        --wct-root <path> \\
        --output-root <path>

Writes nothing to disk (all alignments run with dry_run=True).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

import build.tools.align_je_to_wct as _aligner  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GAP_VALUES: list[float] = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]

ARTICLE_ROOT = REPO_ROOT / "raw" / "jewish-encyclopedia" / "articles"
WCT_ROOT = REPO_ROOT / "reports" / "je-wct" / "vol_02"
OUTPUT_ROOT = REPO_ROOT / "reports" / "je-gold" / "vol_02"


# ---------------------------------------------------------------------------
# Core sweep
# ---------------------------------------------------------------------------


def sweep_gap_penalty(
    article_root: Path,
    wct_root: Path,
    output_root: Path,
    gap_values: list[float] | None = None,
) -> dict[float, dict[str, float]]:
    """Sweep GAP_PENALTY values and aggregate alignment metrics.

    For each value, runs dry-run alignment over all article slugs and returns
    aggregated M0, ref_coverage, wct_coverage, and mean_confusion_dist.

    Returns:
        Dict mapping each gap value to a metrics dict with keys:
        m0, ref_coverage, wct_coverage, mean_confusion_dist.
    """
    if gap_values is None:
        gap_values = GAP_VALUES

    slugs = sorted(d.name for d in article_root.iterdir() if d.is_dir())
    original_gap = _aligner.GAP_PENALTY

    results: dict[float, dict[str, float]] = {}

    try:
        for gap in gap_values:
            _aligner.GAP_PENALTY = gap
            total_match = 0
            total_aligned = 0
            total_ref = 0
            total_wct = 0
            conf_dists: list[float] = []

            for slug in slugs:
                article_dir = article_root / slug
                result = _aligner.align_article(
                    slug,
                    article_dir,
                    wct_root,
                    output_root,
                    dry_run=True,
                )
                total_match += result["n_match"]
                total_aligned += result["n_aligned"]
                total_ref += result["n_reference_tokens"]
                total_wct += result["n_wct_positions"]
                conf_dists.extend(
                    pair["confusion_dist"] for pair in result["aligned_pairs"]
                )

            results[gap] = {
                "m0": total_match / total_aligned if total_aligned else 0.0,
                "ref_coverage": total_aligned / total_ref if total_ref else 0.0,
                "wct_coverage": total_aligned / total_wct if total_wct else 0.0,
                "mean_confusion_dist": (
                    sum(conf_dists) / len(conf_dists) if conf_dists else 0.0
                ),
            }
    finally:
        _aligner.GAP_PENALTY = original_gap

    return results


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def pick_best(
    results: dict[float, dict[str, float]],
    baseline_gap: float = 0.6,
    tie_window_pp: float = 0.2,
    max_cov_drop_pp: float = 3.0,
) -> tuple[float, str]:
    """Return (best_gap, reason_string).

    Selects the gap with highest M0.  On ties within tie_window_pp, prefers
    higher ref_coverage.  Excludes values that drop ref_coverage more than
    max_cov_drop_pp relative to the baseline value.
    """
    if baseline_gap not in results:
        raise KeyError(f"baseline_gap={baseline_gap} not in sweep results")

    baseline_cov = results[baseline_gap]["ref_coverage"]
    min_cov = baseline_cov - max_cov_drop_pp / 100.0

    candidates = [
        (gap, r) for gap, r in results.items() if r["ref_coverage"] >= min_cov
    ]
    if not candidates:
        return (
            baseline_gap,
            f"all candidates drop ref_coverage beyond {max_cov_drop_pp}pp threshold; "
            f"keeping baseline {baseline_gap}",
        )

    best_m0 = max(r["m0"] for _, r in candidates)
    near_best = [
        (gap, r)
        for gap, r in candidates
        if best_m0 - r["m0"] <= tie_window_pp / 100.0
    ]

    # Deterministic tie-break: highest ref_coverage, then lowest gap value
    chosen_gap, chosen_r = max(
        near_best,
        key=lambda gr: (gr[1]["m0"], gr[1]["ref_coverage"], -gr[0]),
    )

    reason = (
        f"M0={chosen_r['m0'] * 100:.1f}%, "
        f"ref_cov={chosen_r['ref_coverage'] * 100:.1f}%"
    )
    return chosen_gap, reason


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_table(results: dict[float, dict[str, float]], best_gap: float) -> None:
    header = (
        f"{'GAP':>5}  {'M0':>8}  {'ref_cov':>8}  {'wct_cov':>8}  {'mean_cdist':>11}"
    )
    print(header)
    print("-" * len(header))
    for gap in sorted(results):
        r = results[gap]
        marker = " <-- best" if gap == best_gap else ""
        print(
            f"{gap:>5.1f}  "
            f"{r['m0'] * 100:>7.1f}%  "
            f"{r['ref_coverage'] * 100:>7.1f}%  "
            f"{r['wct_coverage'] * 100:>7.1f}%  "
            f"{r['mean_confusion_dist']:>11.4f}"
            f"{marker}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sweep GAP_PENALTY values for align_je_to_wct.py (dry run only)."
    )
    parser.add_argument(
        "--article-root",
        type=Path,
        default=ARTICLE_ROOT,
        help="Override article root directory.",
    )
    parser.add_argument(
        "--wct-root",
        type=Path,
        default=WCT_ROOT,
        help="Override WCT root directory.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
        help="Override output root (pass-through to align_article; dry_run=True).",
    )
    args = parser.parse_args()

    article_root: Path = args.article_root
    wct_root: Path = args.wct_root
    output_root: Path = args.output_root

    if not article_root.exists():
        print(f"ERROR: article root not found: {article_root}", file=sys.stderr)
        return 1

    slugs = sorted(d.name for d in article_root.iterdir() if d.is_dir())
    print(f"Sweeping GAP_PENALTY over {GAP_VALUES}")
    print(f"Articles ({len(slugs)}): {', '.join(slugs)}")
    print(f"WCT root: {wct_root}")
    print()

    results = sweep_gap_penalty(article_root, wct_root, output_root, GAP_VALUES)

    best_gap, reason = pick_best(results, baseline_gap=0.6)
    _print_table(results, best_gap)
    print()

    baseline_m0 = results[0.6]["m0"]
    best_m0 = results[best_gap]["m0"]
    baseline_cov = results[0.6]["ref_coverage"]
    best_cov = results[best_gap]["ref_coverage"]

    print(f"Best GAP_PENALTY: {best_gap} ({reason})")
    print(
        f"Baseline (0.6): M0={baseline_m0 * 100:.1f}%, "
        f"ref_cov={baseline_cov * 100:.1f}%"
    )
    print(
        f"Best    ({best_gap}): M0={best_m0 * 100:.1f}%, "
        f"ref_cov={best_cov * 100:.1f}% "
        f"(M0 delta={best_m0 * 100 - baseline_m0 * 100:+.1f}pp)"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
