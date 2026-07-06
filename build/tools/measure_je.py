"""Compute M0-M3 accuracy metrics from JE phase-3 gold alignment files.

Definitions
-----------
M0  Consensus match rate.
    Population: all aligned (reference, WCT-position) pairs.
    Numerator:  pairs where norm(ocr_consensus) == norm(reference_token).
    This is the headline rate: "how often does the best candidate match?"

M1  Any-engine match rate.
    Population: all aligned pairs where the WCT position file is found.
    Numerator:  pairs where any candidate in the position's candidate_set
                has norm(raw_reading) == norm(reference_token).
    Signal: M1 - M0 = positions where consensus was wrong but some engine
            had the right answer (conflict-resolution opportunity).

M2  Multi-family consensus accuracy.
    Population: aligned pairs where the consensus candidate (best by
                attesting-family count, then engine count) is attested
                by >= 2 independent engine families.
    Numerator:  M2-population pairs where consensus matches reference.
    Signal: the expected accuracy of the "auto-accept when >= 2 families
            agree" trust rule, measured non-circularly.

M3  All-engine-attestation accuracy.
    Population: aligned pairs where the WCT position's alignment_confidence
                float meets a threshold.  alignment_confidence is computed as
                0.5 + 0.5 * (attesting_engines / available_engines), capped
                at 0.99.  It measures POSITION ATTESTATION (engines that
                produced a token at this slot), NOT reading agreement.  A
                position can reach conf=0.99 while engines emit different
                readings: 41% of M3t positions have candidate_set > 1.
    M3h: confidence >= 0.875 (>= 3/4 available engines attest this position).
    M3t: confidence >= 0.99  (all available engines attest this position).
    M3-agree: confidence >= 0.99 AND candidate_set has exactly 1 candidate
              (engines attest the position AND agree on the reading).
    Numerator:  M3-population pairs where consensus matches reference.
    Signal: accuracy when all (or most) available engines attest this position.
            Use M3-agree for the stricter "engines agree on the reading" gate.

Exclusions (reported, never silently dropped)
---------------------------------------------
- Articles with n_aligned == 0 (no WCT pages available) are excluded from
  all rates but listed explicitly.
- WCT pages that are missing (LayoutEscalation etc.) are counted in
  n_pages_missing_wct and excluded from any per-page breakdown.
- Aligned pairs where the WCT position file is not found (should not
  happen in a coherent run) are excluded from M1/M2/M3 but counted.

NON-CIRCULARITY GUARD
---------------------
JE.com human transcription is ALWAYS the reference.
IA ABBYY GZ is ENGINE INPUT (a WCT candidate), never the reference.
Both must never be confused here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.s3_reconciler import _best_candidate  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GOLD_ROOT = REPO_ROOT / "reports" / "je-gold" / "vol_02"
WCT_ROOT = REPO_ROOT / "reports" / "je-wct" / "vol_02"


# ---------------------------------------------------------------------------
# Normalisation (mirrors align_je_to_wct._norm exactly)
# ---------------------------------------------------------------------------


def _norm(token: str) -> str:
    folded = unicodedata.normalize("NFKC", token).casefold()
    return re.sub(r"^\W+|\W+$", "", folded, flags=re.UNICODE)


# ---------------------------------------------------------------------------
# Per-article metric accumulator
# ---------------------------------------------------------------------------


# alignment_confidence in the WCT is a float: 0.5 + 0.5 * coverage, capped at 0.99,
# where coverage = attesting_engines / available_engines.
# 0.99 = all engines ATTEST this position (each produced a token; readings may differ).
# 0.875 = 3/4 engines attest.
# 0.75  = 1/2 engines attest (modal value for a 4-engine run).
# M3_HIGH_THRESHOLD defines "high confidence" for the auto-accept stratum.
M3_HIGH_THRESHOLD = 0.875   # >= 3/4 engines attest
M3_TOP_THRESHOLD = 0.99     # all engines attest (== 1.0 before the cap)


@dataclass
class MetricAccum:
    """Numerator / denominator pairs for each metric."""

    m0_num: int = 0
    m0_den: int = 0
    m1_num: int = 0
    m1_den: int = 0
    m2_num: int = 0
    m2_den: int = 0
    m3_high_num: int = 0    # alignment_confidence >= M3_HIGH_THRESHOLD
    m3_high_den: int = 0
    m3_top_num: int = 0    # alignment_confidence >= M3_TOP_THRESHOLD
    m3_top_den: int = 0
    m3_agree_num: int = 0  # conf >= M3_TOP_THRESHOLD AND candidate_set == 1 candidate
    m3_agree_den: int = 0  # (engines attest AND agree on the reading)
    n_pos_missing: int = 0  # aligned pairs with no WCT position record

    def rate(self, num: int, den: int) -> str:
        if den == 0:
            return "N/A (n=0)"
        return f"{num / den:.1%} ({num}/{den})"

    @property
    def m0_str(self) -> str:
        return self.rate(self.m0_num, self.m0_den)

    @property
    def m1_str(self) -> str:
        return self.rate(self.m1_num, self.m1_den)

    @property
    def m2_str(self) -> str:
        return self.rate(self.m2_num, self.m2_den)

    @property
    def m3_high_str(self) -> str:
        return self.rate(self.m3_high_num, self.m3_high_den)

    @property
    def m3_top_str(self) -> str:
        return self.rate(self.m3_top_num, self.m3_top_den)

    @property
    def m3_agree_str(self) -> str:
        return self.rate(self.m3_agree_num, self.m3_agree_den)

    def merge(self, other: "MetricAccum") -> None:
        self.m0_num += other.m0_num
        self.m0_den += other.m0_den
        self.m1_num += other.m1_num
        self.m1_den += other.m1_den
        self.m2_num += other.m2_num
        self.m2_den += other.m2_den
        self.m3_high_num += other.m3_high_num
        self.m3_high_den += other.m3_high_den
        self.m3_top_num += other.m3_top_num
        self.m3_top_den += other.m3_top_den
        self.m3_agree_num += other.m3_agree_num
        self.m3_agree_den += other.m3_agree_den
        self.n_pos_missing += other.n_pos_missing


def _compute_article_metrics(
    gold_data: dict,
    wct_dir: Path,
    *,
    exclude_pos_ids: "set[str] | None" = None,
) -> MetricAccum:
    """Compute M0-M3 for one article.

    gold_data: parsed gold.json dict.
    wct_dir: directory containing page_NNNN.json WCT files.
    exclude_pos_ids: optional set of position_ids to skip.  Used for the
        de-duplicated aggregate (first-occurrence-wins across articles).
    """
    acc = MetricAccum()

    # Build position-id -> position-dict lookup from all WCT pages.
    wct_by_pos: dict[str, dict] = {}
    for page_num in gold_data.get("pages_with_wct", []):
        wct_path = wct_dir / f"page_{page_num:04d}.json"
        if wct_path.exists():
            wct_page = json.loads(wct_path.read_text(encoding="utf-8"))
            for pos in wct_page.get("positions", []):
                wct_by_pos[pos["position_id"]] = pos

    for pair in gold_data.get("aligned_pairs", []):
        pos_id = pair["position_id"]
        ref_norm = pair["reference_norm"]
        is_match = pair["match"]

        # Skip positions already counted by an earlier article (dedup mode).
        if exclude_pos_ids is not None and pos_id in exclude_pos_ids:
            continue

        # Skip punctuation-only tokens: _norm(":") == "" and "" == "" counts
        # as a match, producing phantom M0 hits.  Pairs with empty ref_norm
        # are unscorable regardless of the OCR reading.
        if not ref_norm:
            continue

        # M0 -- all aligned pairs, no WCT lookup needed.
        acc.m0_den += 1
        if is_match:
            acc.m0_num += 1

        pos = wct_by_pos.get(pos_id)
        if pos is None:
            # Should not happen in a coherent run; track for transparency.
            acc.n_pos_missing += 1
            continue

        candidates = pos.get("candidate_set", [])
        if not candidates:
            continue

        # M1 -- any engine has the correct reading.
        acc.m1_den += 1
        for cand in candidates:
            if _norm(cand["raw_reading"]) == ref_norm:
                acc.m1_num += 1
                break

        # M2 -- best candidate attested by >= 2 independent families.
        best = _best_candidate(candidates)
        if len(set(best.get("attesting_families", []))) >= 2:
            acc.m2_den += 1
            if is_match:
                acc.m2_num += 1

        # M3 -- WCT alignment_confidence is a float (0.5 + 0.5 * engine_coverage,
        # capped at 0.99).  Measures POSITION ATTESTATION (engines that produced a
        # token), NOT reading agreement.  41% of M3t positions have >1 candidate.
        #   m3_high:  confidence >= 0.875 (>= 3/4 engines attest this position)
        #   m3_top:   confidence >= 0.99  (all engines attest this position)
        #   m3_agree: conf >= 0.99 AND candidate_set == 1 candidate
        #             (all engines attest AND agree on the reading)
        conf = pos.get("alignment_confidence")
        if conf is not None:
            if conf >= M3_HIGH_THRESHOLD:
                acc.m3_high_den += 1
                if is_match:
                    acc.m3_high_num += 1
            if conf >= M3_TOP_THRESHOLD:
                acc.m3_top_den += 1
                if is_match:
                    acc.m3_top_num += 1
                if len(candidates) == 1:
                    acc.m3_agree_den += 1
                    if is_match:
                        acc.m3_agree_num += 1

    return acc


# ---------------------------------------------------------------------------
# Batch measurement
# ---------------------------------------------------------------------------


def measure_all(
    gold_root: Path = GOLD_ROOT,
    wct_dir: Path = WCT_ROOT,
    complete_only: bool = True,
) -> dict:
    """Compute M0-M3 for all articles in gold_root.

    complete_only: if True (default), exclude articles with pages_missing_wct
        from the aggregate.  Partial articles are structurally misaligned --
        the NW aligner distributes ALL reference tokens proportionally across
        only the PRESENT pages, so reference text belonging to missing pages
        gets force-aligned onto the wrong physical pages (e.g. apologists page-8
        body tokens align to page-10 positions).  The contaminated aggregate
        inflates M0 and M3t.  Pass complete_only=False / --include-partial to
        include partial articles and see the contaminated aggregate.

    Returns a dict with keys:
        'per_article'        list of per-article result dicts
        'aggregate'          MetricAccum over included articles (position reuse counted)
        'dedup_aggregate'    MetricAccum over unique positions only (first-occurrence-wins)
        'zero_aligned'       slugs with n_aligned==0 (no WCT at all)
        'partial_excluded'   slugs skipped by complete_only
        'n_pos_duplicate'    aligned pairs that reuse a position_id from another
                             article (same physical page spanned by multiple
                             articles; inflates denominators by this count)
    """
    article_dirs = sorted(d for d in gold_root.iterdir() if d.is_dir())
    per_article = []
    aggregate = MetricAccum()
    dedup_aggregate = MetricAccum()
    zero_aligned: list[str] = []
    partial_excluded: list[str] = []

    # Detect position_id reuse across articles (same WCT page scored multiple
    # times because several short articles span the same physical page).
    seen_pos_ids: set[str] = set()  # position_ids already counted in dedup_aggregate
    n_pos_dup: int = 0
    all_seen: dict[str, str] = {}   # pos_id -> first-seen slug (for dup count only)

    for art_dir in article_dirs:
        gold_path = art_dir / "gold.json"
        if not gold_path.exists():
            continue
        gold_data = json.loads(gold_path.read_text(encoding="utf-8"))
        slug = gold_data["article_slug"]

        if gold_data.get("n_aligned", 0) == 0:
            zero_aligned.append(slug)
            per_article.append(
                {
                    "slug": slug,
                    "n_aligned": 0,
                    "pages_spanned": gold_data.get("pages_spanned", []),
                    "pages_missing_wct": gold_data.get("pages_missing_wct", []),
                    "metrics": None,
                    "note": "excluded: n_aligned=0 (no WCT pages available)",
                }
            )
            continue

        # --complete-only: skip articles where any WCT page is missing.
        # Missing pages are often the hard/abnormal pages (pictures, tables),
        # so their exclusion concentrates measurement on cleaner pages and
        # inflates all-engine-attest metrics for those articles.
        if complete_only and gold_data.get("pages_missing_wct"):
            partial_excluded.append(slug)
            per_article.append(
                {
                    "slug": slug,
                    "n_aligned": gold_data["n_aligned"],
                    "pages_spanned": gold_data.get("pages_spanned", []),
                    "pages_missing_wct": gold_data.get("pages_missing_wct", []),
                    "metrics": None,
                    "note": "excluded: pages_missing_wct (--complete-only mode)",
                }
            )
            continue

        acc = _compute_article_metrics(gold_data, wct_dir)
        dedup_acc = _compute_article_metrics(
            gold_data, wct_dir, exclude_pos_ids=seen_pos_ids
        )
        aggregate.merge(acc)
        dedup_aggregate.merge(dedup_acc)
        per_article.append(
            {
                "slug": slug,
                "n_aligned": gold_data["n_aligned"],
                "n_reference_tokens": gold_data["n_reference_tokens"],
                "n_wct_positions": gold_data["n_wct_positions"],
                "pages_spanned": gold_data.get("pages_spanned", []),
                "pages_missing_wct": gold_data.get("pages_missing_wct", []),
                "n_reference_unaligned": gold_data.get("n_reference_unaligned", 0),
                "n_positions_unaligned": gold_data.get("n_positions_unaligned", 0),
                "metrics": acc,
            }
        )

        # Update seen_pos_ids AFTER computing dedup_acc for this article so
        # that THIS article's positions are included in dedup_aggregate and
        # only SUBSEQUENT articles see them as already-counted.
        for pair in gold_data.get("aligned_pairs", []):
            pid = pair["position_id"]
            if pid in all_seen:
                n_pos_dup += 1
            else:
                all_seen[pid] = slug
                seen_pos_ids.add(pid)

    return {
        "per_article": per_article,
        "aggregate": aggregate,
        "dedup_aggregate": dedup_aggregate,
        "zero_aligned": zero_aligned,
        "partial_excluded": partial_excluded,
        "n_pos_duplicate": n_pos_dup,
    }


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------


def print_report(results: dict) -> None:
    """Print a human-readable M0-M3 report to stdout."""
    per_article = results["per_article"]
    agg = results["aggregate"]
    dedup_agg = results.get("dedup_aggregate")
    zero = results["zero_aligned"]
    partial_excluded = results.get("partial_excluded", [])
    n_pos_dup = results.get("n_pos_duplicate", 0)

    print("=" * 68)
    print("JE Surrogate Oracle -- M0-M3 Accuracy Metrics")
    print("=" * 68)
    print()

    if zero:
        print(f"Excluded (n_aligned=0, no WCT pages): {', '.join(zero)}")
        print()

    if partial_excluded:
        print(f"Excluded (--complete-only, pages_missing_wct): {', '.join(partial_excluded)}")
        print()

    n_articles = sum(1 for a in per_article if a["metrics"] is not None)
    print(f"Articles measured: {n_articles}")
    print(
        "NON-CIRCULARITY: reference = JE.com human transcription; "
        "ABBYY = engine input only."
    )
    print()

    def _r(n: int, d: int) -> str:
        return f"{n/d:.1%}" if d else "N/A"

    # Per-article detail
    print("-" * 92)
    print(f"{'Article':<35} {'M0':>8} {'M1':>8} {'M2':>8} {'M3h':>8} {'M3t':>8} {'M3-ag':>8}")
    print(f"{'':35} {'':8} {'':8} {'':8} {'(>=.875)':>8} {'(>=.99)':>8} {'agree':>8}")
    print("-" * 92)
    for art in per_article:
        acc = art["metrics"]
        if acc is None:
            print(f"{art['slug']:<35} {'excluded':>41}")
            continue
        missing = art.get("pages_missing_wct", [])
        note = f" [miss_wct={missing}]" if missing else ""
        slug_label = art["slug"][:34]

        print(
            f"{slug_label:<35} "
            f"{_r(acc.m0_num, acc.m0_den):>8} "
            f"{_r(acc.m1_num, acc.m1_den):>8} "
            f"{_r(acc.m2_num, acc.m2_den):>8} "
            f"{_r(acc.m3_high_num, acc.m3_high_den):>8} "
            f"{_r(acc.m3_top_num, acc.m3_top_den):>8} "
            f"{_r(acc.m3_agree_num, acc.m3_agree_den):>8}"
            f"{note}"
        )
    print("-" * 92)

    # Aggregate
    def _ar(n: int, d: int) -> str:
        return f"{n/d:.1%} ({n}/{d})" if d else "N/A"

    print(f"{'AGGREGATE M0:':<22} {_ar(agg.m0_num, agg.m0_den)}")
    print(f"{'AGGREGATE M1:':<22} {_ar(agg.m1_num, agg.m1_den)}")
    print(f"{'AGGREGATE M2:':<22} {_ar(agg.m2_num, agg.m2_den)}")
    print(f"{'AGGREGATE M3h:':<22} {_ar(agg.m3_high_num, agg.m3_high_den)}")
    print(f"{'AGGREGATE M3t:':<22} {_ar(agg.m3_top_num, agg.m3_top_den)}")
    print(f"{'AGGREGATE M3-agree:':<22} {_ar(agg.m3_agree_num, agg.m3_agree_den)}")
    if dedup_agg is not None and n_pos_dup > 0:
        print()
        print(f"DEDUP aggregate (first-occurrence-wins, {n_pos_dup} dup pairs removed):")
        print(f"  {'M0:':<18} {_ar(dedup_agg.m0_num, dedup_agg.m0_den)}")
        print(f"  {'M3t:':<18} {_ar(dedup_agg.m3_top_num, dedup_agg.m3_top_den)}")
        print(f"  {'M3-agree:':<18} {_ar(dedup_agg.m3_agree_num, dedup_agg.m3_agree_den)}")
    print("=" * 82)
    print()

    # Metric explanations
    print("Metric definitions:")
    print("  M0       Consensus match rate (all aligned positions)")
    print("  M1       Any-engine match rate (any WCT candidate has correct reading)")
    print("  M2       Multi-family accuracy (>=2 distinct families attest consensus)")
    print("  M3h      High-attestation: alignment_confidence >= 0.875 (>=3/4 engines attest position)")
    print("  M3t      Top-attestation:  alignment_confidence >= 0.99  (all engines attest position)")
    print("  M3-agree Top-attestation AND single candidate (engines attest AND agree on reading)")
    print()

    # Alignment quality note
    total_ref = sum(a.get("n_reference_tokens", 0) for a in per_article)
    total_wct = sum(a.get("n_wct_positions", 0) for a in per_article)
    n_aligned = agg.m0_den
    n_ref_unaligned = sum(a.get("n_reference_unaligned", 0) for a in per_article if a["metrics"] is not None)
    n_pos_unaligned = sum(a.get("n_positions_unaligned", 0) for a in per_article if a["metrics"] is not None)

    print(
        f"Alignment coverage ({n_articles} articles): "
        f"{n_aligned} aligned / {total_ref} ref tokens / {total_wct} WCT positions"
    )
    if total_ref > 0:
        print(
            f"  Ref coverage:  {n_aligned}/{total_ref} = {n_aligned/total_ref:.1%} aligned, "
            f"{n_ref_unaligned} unaligned"
        )
    if total_wct > 0:
        print(
            f"  WCT coverage:  {n_aligned}/{total_wct} = {n_aligned/total_wct:.1%} matched, "
            f"{n_pos_unaligned} unmatched"
        )
    print()

    # Duplication note
    if n_pos_dup > 0:
        print(
            f"Position-ID overlap: {n_pos_dup} aligned pairs share a position_id "
            f"with another article (same physical page spanned by multiple articles)."
        )
        print(
            "  Denominators are inflated by this count. Use --complete-only to see"
        )
        print(
            "  rates restricted to articles where no WCT pages are missing."
        )
        print()

    # Caveat
    print(
        "Residual caveat: all rates are mediated by the NW aligner (GAP_PENALTY=0.6,\n"
        "B8-tuned). Misaligned tokens inflate error rates and deflate match rates.\n"
        "alignment_confidence counts ALL engines that ATTEST the position (produced a\n"
        "token) -- it is NOT a reading-agreement gate. 41% of M3t positions have\n"
        "candidate_set > 1 (engines disagree). Use M3-agree for the reading-agreement\n"
        "stratum. M3 is an all-engine-attestation gate, not a geometry-only gate."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute M0-M3 metrics from JE gold alignment files."
    )
    parser.add_argument(
        "--gold-root",
        type=Path,
        default=GOLD_ROOT,
        help="Root dir containing per-slug gold.json files.",
    )
    parser.add_argument(
        "--wct-root",
        type=Path,
        default=WCT_ROOT,
        help="Root dir containing page_NNNN.json WCT files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit machine-readable JSON instead of the human-readable report.",
    )
    parser.add_argument(
        "--include-partial",
        action="store_true",
        dest="include_partial",
        help=(
            "Include articles with pages_missing_wct in the aggregate. "
            "These articles are structurally misaligned (reference text for "
            "missing pages gets force-aligned onto wrong physical pages), "
            "inflating M0 and M3t. Default is to exclude them."
        ),
    )
    # Legacy alias retained for backwards compatibility; --include-partial is preferred.
    parser.add_argument(
        "--complete-only",
        action="store_true",
        dest="complete_only_legacy",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    complete_only = not args.include_partial
    results = measure_all(args.gold_root, args.wct_root, complete_only=complete_only)

    if args.json_output:
        # Serialize MetricAccum fields to plain dict for JSON output.
        per_article_json = []
        for art in results["per_article"]:
            acc = art["metrics"]
            entry = {k: v for k, v in art.items() if k != "metrics"}
            if acc is not None:
                entry["metrics"] = {
                    "M0": [acc.m0_num, acc.m0_den],
                    "M1": [acc.m1_num, acc.m1_den],
                    "M2": [acc.m2_num, acc.m2_den],
                    "M3h": [acc.m3_high_num, acc.m3_high_den],
                    "M3t": [acc.m3_top_num, acc.m3_top_den],
                    "M3-agree": [acc.m3_agree_num, acc.m3_agree_den],
                    "n_pos_missing": acc.n_pos_missing,
                }
            per_article_json.append(entry)
        agg = results["aggregate"]
        output = {
            "per_article": per_article_json,
            "aggregate": {
                "M0": [agg.m0_num, agg.m0_den],
                "M1": [agg.m1_num, agg.m1_den],
                "M2": [agg.m2_num, agg.m2_den],
                "M3h": [agg.m3_high_num, agg.m3_high_den],
                "M3t": [agg.m3_top_num, agg.m3_top_den],
                "M3-agree": [agg.m3_agree_num, agg.m3_agree_den],
            },
            "zero_aligned": results["zero_aligned"],
            "partial_excluded": results.get("partial_excluded", []),
            "n_pos_duplicate": results.get("n_pos_duplicate", 0),
        }
        da = results.get("dedup_aggregate")
        if da is not None:
            output["dedup_aggregate"] = {
                "M0": [da.m0_num, da.m0_den],
                "M3t": [da.m3_top_num, da.m3_top_den],
                "M3-agree": [da.m3_agree_num, da.m3_agree_den],
            }
        print(json.dumps(output, indent=2))
    else:
        print_report(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
