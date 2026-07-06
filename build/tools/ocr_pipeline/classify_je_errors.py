"""Classify JE aligned pairs into gold-free error classes and measure how often
the gold-free detection signals fire on each class.

This is a READ-ONLY measurement analysis tool for U11b. It does not build or
modify any corrector module; it imports the locked corrector package
(`column_vote`, `decide`, `protect`, the M5 lexicon) and calls them as
detection signals. Its purpose is to turn the U11b error-class catalogue from
claim into number: for every aligned (reference, WCT-position) pair, assign an
error class, then for each error compute which gold-free signal -- engine
disagreement, non-lexicality, protected-class, script/cluster -- would have
flagged it WITHOUT the reference. The uncaught remainder per class is the NSH
risk register.

The gold (JE.com human transcription) is the teacher only: it tells us which
pairs are errors. NSH will have no such reference, so the question is which of
those errors a gold-free signal would still catch.

Error classes (U11 starting thresholds, tunable via --minor-max):
  clean         -- aligner `match` is True.
  real_minor    -- not matched, 0 < confusion_dist <= minor_max. Close-but-wrong.
  far_isolated  -- not matched, confusion_dist > minor_max, both sequence
                   neighbors clean. Likely a real catastrophic OCR error.
  far_clustered -- not matched, confusion_dist > minor_max, at least one
                   sequence neighbor also failed. Usually alignment drift /
                   scrambled zones, not a single-token OCR error.

Data location: the JE WCT pages and aligner gold live ONLY under the
quarantine (`reports/` is gitignored and was never committed). This tool reads
that quarantine read-only and writes its report to gitignored `prompts/`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.gold_free_corrector.column_vote import correct_position  # noqa: E402
from build.lib.gold_free_corrector.decide import _ACCEPT, decide  # noqa: E402
from build.lib.gold_free_corrector.lexicon.build_lexicon import (  # noqa: E402
    _normalise_word as lex_normalise,
    build_lexicon_from_wct_pages,
)
from build.lib.gold_free_corrector.protect import (  # noqa: E402
    build_consensus_capitalized_gazetteer,
    protected_signal_for_position,
)
from build.lib.paths import REPO_ROOT  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# The JE surrogate data was quarantined 2026-06-06; reports/ is gitignored so
# it never entered git. Read-only -- never mutate or move it.
QUARANTINE = REPO_ROOT / ".shrink-quarantine" / "je-surrogate-phase1-20260606"
DEFAULT_WCT_DIR = QUARANTINE / "reports" / "je-wct" / "vol_02"
DEFAULT_GOLD_DIR = QUARANTINE / "reports" / "je-gold" / "vol_02"
DEFAULT_OUT = REPO_ROOT / "prompts" / "je-error-classes-report.json"

# U11 starting threshold separating real_minor (close-but-wrong) from the
# far_* catastrophic/drift classes. Tunable on the CLI.
MINOR_MAX = 0.6

# All-levels-accept thresholds (mirrors prompts/je-measurement-thresholds.json):
# permissive so every produced reading is auto-accepted and FCR is measurable.
PERMISSIVE_THRESHOLDS = {
    "body": {
        "L0": {"auto_accept_enabled": True},
        "L1": {"auto_accept_enabled": True},
        "L2": {"auto_accept_enabled": True},
        "L3": {"auto_accept_enabled": True},
    }
}

# ADR-0015 statistical-acceptance denominator: a 95% upper bound < 0.1% needs
# ceil(log(0.05)/log(0.999)) = 2995 accepted corrections with zero errors.
POWERED_N = 2995

ERROR_CLASSES = ("real_minor", "far_isolated", "far_clustered")
ALL_CLASSES = ("clean",) + ERROR_CLASSES


# ---------------------------------------------------------------------------
# Pure logic -- classification
# ---------------------------------------------------------------------------


def parse_position_id(position_id: str) -> dict[str, str]:
    """Extract structural fields from a WCT position id.

    Position ids look like ``vol_02:page_0013:body:c1:l002:p010``: volume,
    page id, zone type, column, line, position.
    """
    parts = position_id.split(":")

    def _at(index: int) -> str:
        return parts[index] if len(parts) > index else ""

    return {
        "volume": _at(0),
        "page_id": _at(1),
        "zone_type": _at(2),
        "column": _at(3),
    }


def classify_article(
    aligned_pairs: list[dict], *, minor_max: float = MINOR_MAX
) -> list[str]:
    """Assign an error class to each aligned pair in one article.

    Neighbors are the immediately adjacent pairs in the article's reading-order
    sequence. A far error is ``far_clustered`` if any EXISTING neighbor also
    failed, else ``far_isolated`` (a boundary error with one clean neighbor is
    isolated, not clustered).
    """
    clean = [bool(pair["match"]) for pair in aligned_pairs]
    n = len(aligned_pairs)
    labels: list[str] = []
    for index, pair in enumerate(aligned_pairs):
        if clean[index]:
            labels.append("clean")
            continue
        cd = pair["confusion_dist"]
        if cd <= minor_max:
            labels.append("real_minor")
            continue
        neighbor_failed = (index > 0 and not clean[index - 1]) or (
            index < n - 1 and not clean[index + 1]
        )
        labels.append("far_clustered" if neighbor_failed else "far_isolated")
    return labels


# ---------------------------------------------------------------------------
# Pure logic -- gold-free detection coverage
# ---------------------------------------------------------------------------


def pair_signals(
    *,
    candidate_count: int,
    ocr_norm: str,
    lexicon_words: frozenset[str] | set[str],
    script: str | None,
    low_confidence: bool,
    protected: bool,
) -> dict[str, bool]:
    """Which gold-free signals would flag this error pair, with no reference.

    Every signal here is observable at a single WCT position WITHOUT any
    reference -- that is the whole point. The error *class* (real_minor /
    far_clustered) is gold-DEFINED and is deliberately NOT an input: at NSH
    runtime there is no gold, so "a neighbor also failed" is unobservable and
    cannot be a gold-free tell. The observable proxy for clustered drift is
    low attestation confidence and engine disagreement density, captured here.

    - engine_disagree: the WCT position has > 1 distinct candidate reading.
    - non_lexical: the observed (OCR) token is absent from the in-corpus lexicon.
    - protected: protect.py flags the position (proper name, number, date,
      Scripture ref, or non-latin script).
    - non_latin: the position's script field is not latin (greek/hebrew/mixed).
    - low_confidence: alignment_confidence < 0.99 -- not every available engine
      attests this position (a geometry/attestation tell, computed gold-free).
    """
    engine_disagree = candidate_count > 1
    non_lexical = ocr_norm not in lexicon_words
    non_latin = script not in (None, "latin")
    low_confidence = bool(low_confidence)
    protected = bool(protected)
    caught_any = bool(
        engine_disagree or non_lexical or protected or non_latin or low_confidence
    )
    return {
        "engine_disagree": engine_disagree,
        "non_lexical": non_lexical,
        "protected": protected,
        "non_latin": non_latin,
        "low_confidence": low_confidence,
        "caught_any": caught_any,
    }


_SIGNAL_KEYS = (
    "engine_disagree",
    "non_lexical",
    "protected",
    "non_latin",
    "low_confidence",
)


def aggregate_coverage(rows: list[dict]) -> dict[str, dict[str, int]]:
    """Roll signal rows up per class: total, per-signal hits, caught, uncaught."""
    agg: dict[str, dict[str, int]] = {}
    for row in rows:
        klass = row["klass"]
        bucket = agg.setdefault(
            klass,
            {key: 0 for key in _SIGNAL_KEYS}
            | {"n": 0, "caught_any": 0, "uncaught": 0},
        )
        bucket["n"] += 1
        for key in _SIGNAL_KEYS:
            if row.get(key):
                bucket[key] += 1
        if row.get("caught_any"):
            bucket["caught_any"] += 1
        else:
            bucket["uncaught"] += 1
    return agg


# ---------------------------------------------------------------------------
# Loaders (tmp-path friendly; the driver points them at the quarantine)
# ---------------------------------------------------------------------------


def load_gold_article(gold_path: Path) -> dict:
    """Load one per-article gold.json (je-wct-alignment schema)."""
    return json.loads(gold_path.read_text(encoding="utf-8"))


def load_wct_positions(wct_dir: Path) -> dict[str, dict]:
    """Index every WCT position across all pages by position_id."""
    by_pos: dict[str, dict] = {}
    for wct_path in sorted(wct_dir.glob("page_*.json")):
        page = json.loads(wct_path.read_text(encoding="utf-8"))
        for position in page.get("positions", []):
            by_pos[position["position_id"]] = position
    return by_pos


def load_wct_pages(wct_dir: Path) -> list[dict]:
    """Load every WCT page (for lexicon building and per-page protect context)."""
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(wct_dir.glob("page_*.json"))
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def script_label(position: dict) -> str | None:
    """Best-available script label for a WCT position (latin/greek/hebrew/...)."""
    script = position.get("script")
    if isinstance(script, str):
        return script.lower()
    if isinstance(script, dict):
        text_label = (script.get("text_level") or {}).get("label")
        if text_label:
            return str(text_label).lower()
        image_label = (script.get("image_level") or {}).get("label")
        if image_label:
            return str(image_label).lower()
    return None


_NORM_TRIM = re.compile(r"^\W+|\W+$", flags=re.UNICODE)


def norm_compare(token: str) -> str:
    """NFKC + casefold + strip surrounding non-word chars (mirrors aligner _norm)."""
    folded = unicodedata.normalize("NFKC", token).casefold()
    return _NORM_TRIM.sub("", folded)


def build_protected_map(wct_pages: list[dict]) -> dict[str, bool]:
    """position_id -> True if protect.py flags it (per-page gazetteer + neighbors)."""
    protected: dict[str, bool] = {}
    for page in wct_pages:
        positions = page.get("positions", [])
        by_id = {pos["position_id"]: pos for pos in positions}
        ordered_ids = [pid for pid in page.get("reading_order", []) if pid in by_id]
        seen = set(ordered_ids)
        for pos in positions:
            if pos["position_id"] not in seen:
                ordered_ids.append(pos["position_id"])
        gazetteer = build_consensus_capitalized_gazetteer(positions)
        for index, pid in enumerate(ordered_ids):
            position = by_id[pid]
            previous = by_id[ordered_ids[index - 1]] if index > 0 else None
            nxt = (
                by_id[ordered_ids[index + 1]]
                if index < len(ordered_ids) - 1
                else None
            )
            signal = protected_signal_for_position(
                position,
                previous_position=previous,
                next_position=nxt,
                gazetteer=gazetteer,
            )
            protected[pid] = signal.is_protected
    return protected


# ---------------------------------------------------------------------------
# Step 4 driver -- corrector FCR on a class-restricted subset
# ---------------------------------------------------------------------------


def corrector_fcr(
    positions_by_id: dict[str, dict],
    gold_by_pos: dict[str, str],
    class_by_pos: dict[str, str],
    *,
    exclude_classes: frozenset[str],
    conf_floor: float | None = None,
) -> dict[str, dict]:
    """Run correct_position + decide over positions, restricted by class/conf.

    Returns per-level (L0/L1/None) stats: total considered, auto_accepted,
    coverage, FCR exact and normalized, powered flag. Read-only on the locked
    corrector modules -- it imports and calls them, never modifies them.
    """
    levels: dict[str, dict] = {}

    def _bucket(level: str | None) -> dict:
        key = level if level is not None else "routed"
        return levels.setdefault(
            key,
            {
                "level": key,
                "total": 0,
                "auto_accepted": 0,
                "fcr_exact_errors": 0,
                "fcr_norm_errors": 0,
            },
        )

    for pid, gold_text in gold_by_pos.items():
        klass = class_by_pos.get(pid)
        if klass in exclude_classes:
            continue
        position = positions_by_id.get(pid)
        if position is None:
            continue
        if conf_floor is not None and (
            position.get("alignment_confidence") or 0.0
        ) < conf_floor:
            continue

        cvr = decide(correct_position(position), PERMISSIVE_THRESHOLDS, region_class="body")
        cp = cvr.corrected_position
        level = cp.get("derivation_method")
        bucket = _bucket(level)
        bucket["total"] += 1
        if cp["chosen_action"] == _ACCEPT:
            bucket["auto_accepted"] += 1
            idx = cp.get("chosen_reading_index")
            readings = cp.get("derivable_readings", [])
            if idx is not None and 0 <= idx < len(readings):
                chosen = readings[idx]["text"]
                if chosen != gold_text:
                    bucket["fcr_exact_errors"] += 1
                if norm_compare(chosen) != norm_compare(gold_text):
                    bucket["fcr_norm_errors"] += 1

    for bucket in levels.values():
        accepted = bucket["auto_accepted"]
        bucket["coverage"] = accepted / bucket["total"] if bucket["total"] else 0.0
        bucket["fcr_exact"] = (
            bucket["fcr_exact_errors"] / accepted if accepted else 0.0
        )
        bucket["fcr_normalized"] = (
            bucket["fcr_norm_errors"] / accepted if accepted else 0.0
        )
        bucket["powered"] = accepted >= POWERED_N
    return levels


# ---------------------------------------------------------------------------
# Full measurement (driver)
# ---------------------------------------------------------------------------


def run_measurement(
    wct_dir: Path,
    gold_dir: Path,
    *,
    minor_max: float = MINOR_MAX,
    complete_only: bool = False,
) -> dict:
    """Classify every aligned pair, measure gold-free coverage, run corrector FCR.

    complete_only: if True, skip articles with any missing WCT page. Those
    articles are structurally misaligned (the NW aligner spreads ALL reference
    tokens across only the present pages, so text for a missing page is
    force-aligned onto a wrong physical page), which injects alignment drift
    that masquerades as far_clustered/far_isolated OCR error. measure_je.py
    excludes them by default for the same reason.
    """
    wct_pages = load_wct_pages(wct_dir)
    positions_by_id = load_wct_positions(wct_dir)
    lexicon = build_lexicon_from_wct_pages(wct_pages)
    lexicon_words = lexicon.words
    protected_map = build_protected_map(wct_pages)

    # Classify per article, then join class labels back to position ids.
    class_by_pos: dict[str, str] = {}
    gold_by_pos: dict[str, str] = {}
    coverage_rows: list[dict] = []
    examples: dict[str, list[dict]] = {klass: [] for klass in ALL_CLASSES}
    class_counts: Counter[str] = Counter()
    by_script: dict[str, Counter] = {}

    article_files = sorted(gold_dir.glob("*/gold.json"))
    n_articles_used = 0
    partial_skipped: list[str] = []
    for gold_path in article_files:
        gold = load_gold_article(gold_path)
        pairs = gold.get("aligned_pairs", [])
        if not pairs:
            continue
        if complete_only and gold.get("pages_missing_wct"):
            partial_skipped.append(gold.get("article_slug", gold_path.parent.name))
            continue
        n_articles_used += 1
        labels = classify_article(pairs, minor_max=minor_max)
        slug = gold.get("article_slug", gold_path.parent.name)
        for pair, klass in zip(pairs, labels):
            pid = pair["position_id"]
            class_counts[klass] += 1
            # First-occurrence-wins for position reuse across articles (matches
            # the dedup convention in measure_je.py / generate_je_gold.py).
            if pid not in gold_by_pos:
                gold_by_pos[pid] = pair["reference_token"]
                class_by_pos[pid] = klass

            position = positions_by_id.get(pid)
            script = script_label(position) if position else None
            cand_count = len(position.get("candidate_set", [])) if position else 0
            conf = position.get("alignment_confidence") if position else None
            low_conf = conf is not None and conf < 0.99

            if len(examples[klass]) < 15:
                examples[klass].append(
                    {
                        "article": slug,
                        "position_id": pid,
                        "reference_token": pair["reference_token"],
                        "ocr_consensus": pair["ocr_consensus"],
                        "confusion_dist": pair["confusion_dist"],
                        "script": script,
                    }
                )

            # Compute gold-free signals for EVERY pair, including clean ones:
            # the clean firing rate is the false-alarm rate, which turns each
            # signal's recall on errors into something the verdict can weigh.
            signals = pair_signals(
                candidate_count=cand_count,
                ocr_norm=lex_normalise(pair["ocr_consensus"]),
                lexicon_words=lexicon_words,
                script=script,
                low_confidence=low_conf,
                protected=protected_map.get(pid, False),
            )
            coverage_rows.append({"klass": klass, "script": script or "unknown", **signals})
            if klass in ERROR_CLASSES:
                script_key = script or "unknown"
                by_script.setdefault(klass, Counter())
                by_script[klass][f"{script_key}:n"] += 1
                if not signals["caught_any"]:
                    by_script[klass][f"{script_key}:uncaught"] += 1

    coverage = aggregate_coverage(coverage_rows)

    fcr_all = corrector_fcr(
        positions_by_id,
        gold_by_pos,
        class_by_pos,
        exclude_classes=frozenset({"far_clustered"}),
    )
    fcr_conf = corrector_fcr(
        positions_by_id,
        gold_by_pos,
        class_by_pos,
        exclude_classes=frozenset({"far_clustered"}),
        conf_floor=0.99,
    )

    return {
        "minor_max": minor_max,
        "complete_only": complete_only,
        "n_articles": n_articles_used,
        "partial_skipped": partial_skipped,
        "class_counts": dict(class_counts),
        "total_pairs": sum(class_counts.values()),
        "distinct_positions": len(gold_by_pos),
        "coverage": coverage,
        "coverage_by_script": {k: dict(v) for k, v in by_script.items()},
        "corrector_fcr_excl_clustered": fcr_all,
        "corrector_fcr_conf99": fcr_conf,
        "examples": examples,
        "lexicon_size": len(lexicon_words),
    }


# ---------------------------------------------------------------------------
# CLI / report printing
# ---------------------------------------------------------------------------


def _print_report(result: dict) -> None:
    counts = result["class_counts"]
    total = result["total_pairs"]
    print("=" * 72)
    print("JE gold-free error-class classification + coverage")
    print("=" * 72)
    print(f"articles={result['n_articles']}  total_pairs={total}  "
          f"distinct_positions={result['distinct_positions']}  "
          f"lexicon_words={result['lexicon_size']}")
    print()
    print("Class counts:")
    for klass in ALL_CLASSES:
        n = counts.get(klass, 0)
        pct = (n / total * 100) if total else 0.0
        print(f"  {klass:<14} {n:>7}  ({pct:5.1f}%)")
    print()
    print("Gold-free coverage per error class:")
    print(f"  {'class':<14} {'n':>6} {'eng':>6} {'lex':>6} {'prot':>6} "
          f"{'nlat':>6} {'loconf':>7} {'caught':>7} {'uncaught':>9}")
    for klass in ERROR_CLASSES + ("clean",):
        c = result["coverage"].get(klass)
        if not c:
            continue
        label = klass if klass != "clean" else "clean(FA-rate)"
        print(f"  {label:<14} {c['n']:>6} {c['engine_disagree']:>6} "
              f"{c['non_lexical']:>6} {c['protected']:>6} "
              f"{c['non_latin']:>6} {c['low_confidence']:>7} "
              f"{c['caught_any']:>7} {c['uncaught']:>9}")
    print()
    print("Corrector FCR (excl far_clustered):")
    for key, bucket in sorted(result["corrector_fcr_excl_clustered"].items()):
        print(f"  {key:<8} accepted={bucket['auto_accepted']:>6} "
              f"cov={bucket['coverage']:.3f} fcr_exact={bucket['fcr_exact']:.4f} "
              f"fcr_norm={bucket['fcr_normalized']:.4f} powered={bucket['powered']}")
    print()
    print("Corrector FCR (excl far_clustered, alignment_confidence>=0.99):")
    for key, bucket in sorted(result["corrector_fcr_conf99"].items()):
        print(f"  {key:<8} accepted={bucket['auto_accepted']:>6} "
              f"cov={bucket['coverage']:.3f} fcr_exact={bucket['fcr_exact']:.4f} "
              f"fcr_norm={bucket['fcr_normalized']:.4f} powered={bucket['powered']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify JE aligned pairs into gold-free error classes "
        "and measure detection-signal coverage."
    )
    parser.add_argument("--wct-dir", type=Path, default=DEFAULT_WCT_DIR)
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    parser.add_argument("--minor-max", type=float, default=MINOR_MAX)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.wct_dir.exists():
        print(f"ERROR: WCT dir not found: {args.wct_dir}", file=sys.stderr)
        return 1
    if not args.gold_dir.exists():
        print(f"ERROR: gold dir not found: {args.gold_dir}", file=sys.stderr)
        return 1

    result_all = run_measurement(
        args.wct_dir, args.gold_dir, minor_max=args.minor_max, complete_only=False
    )
    result_complete = run_measurement(
        args.wct_dir, args.gold_dir, minor_max=args.minor_max, complete_only=True
    )
    print("### ALL non-empty articles (includes structurally-misaligned partials)")
    _print_report(result_all)
    print()
    print("### COMPLETE-ONLY articles (no missing WCT page; de-noised)")
    print(f"  partial articles skipped: {result_complete['partial_skipped']}")
    _print_report(result_complete)

    payload = {"all_articles": result_all, "complete_only": result_complete}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(args.out)
    print()
    print(f"Wrote report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
