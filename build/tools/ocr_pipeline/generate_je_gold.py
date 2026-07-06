"""Convert JE aligner output to M13-compatible per-page gold files.

The JE aligner (`build/tools/align_je_to_wct.py`) writes one `gold.json` per
article under `<align-root>/<slug>/gold.json`, in the `je-wct-alignment`
schema (a flat list of `aligned_pairs`, each carrying a `position_id` and the
human-transcription `reference_token`). The M13 surrogate harness
(`measure_corrector.py`) instead reads one `<page_id>.gold.json` per page in
the shape `{"positions": {"<position_id>": {"gold_text": "<str>"}, ...}}`.

This tool bridges the two: it reads every per-article alignment, regroups the
aligned pairs by page (the page id is encoded in the position id as
`<volume>:<page_id>:<zone>:...`), and emits one M13 gold file per page.

`gold_text` is the RAW `reference_token`, never the normalized form: the
corrector emits raw consensus text (column_vote L0 = `candidate.raw_reading`,
L1 = joined raw winner graphemes) and the harness compares with exact string
equality (see `tests/test_corrector_measure.py`). Feeding the normalized form
would make every accepted reading register as a false correction.

Position-id reuse: several short JE articles can span the same physical page,
so the same `position_id` may appear in more than one article's alignment with
a different `reference_token` (each article's Needleman-Wunsch pass is
independent). This tool resolves conflicts first-occurrence-wins, matching the
dedup convention in `measure_je.py`, and reports the conflict count so the bias
is visible rather than silent.

Non-circularity: the aligner's `reference_token` is the JE.com human
transcription, which is always the reference; the IA ABBYY GZ is engine input
only and never appears here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402

# Canonical locations (overridable on the CLI). The aligner writes per-article
# gold to je-gold/; this tool consolidates it into per-page gold under
# je-page-gold/. Both live in the reports/ data layer (pipeline-generated,
# regenerable) -- moved out of prompts/ 2026-07-04. The M13 harness reads
# per-page gold from the chosen output dir.
DEFAULT_ALIGN_ROOT = REPO_ROOT / "reports" / "je-gold" / "vol_02"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "je-page-gold" / "vol_02"


def _page_id_from_position(position_id: str) -> str:
    """Extract the WCT page id from a position id.

    Position ids look like `vol_02:page_0010:body:c1:l000:p000`; the page id
    is the second colon-delimited field and equals the WCT page file's
    `page_id` value (`page_0010`).
    """
    parts = position_id.split(":")
    if len(parts) < 2:
        raise ValueError(f"position_id has no page field: {position_id!r}")
    return parts[1]


def build_gold_by_page(
    align_root: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """Read every per-article alignment and regroup gold text by page.

    Returns `(gold_by_page, summary)` where `gold_by_page` maps
    `page_id -> {position_id: gold_text}` and `summary` carries the counts the
    CLI reports (articles read, pairs seen, conflicts dropped, etc.).
    """
    gold_files = sorted(align_root.glob("*/gold.json"))
    if not gold_files:
        raise FileNotFoundError(
            f"no per-article gold.json files found under {align_root}"
        )

    # page_id -> position_id -> gold_text (first occurrence wins)
    gold_by_page: dict[str, dict[str, str]] = {}
    # position_id -> gold_text already committed (for cross-article conflict detection)
    seen_positions: dict[str, str] = {}

    n_articles = 0
    n_articles_zero_aligned = 0
    n_pairs = 0
    n_conflicts = 0
    n_conflicts_divergent = 0

    for gold_file in gold_files:
        data = json.loads(gold_file.read_text(encoding="utf-8"))
        n_articles += 1
        if data.get("n_aligned", 0) == 0:
            n_articles_zero_aligned += 1
        for pair in data.get("aligned_pairs", []):
            position_id = pair["position_id"]
            gold_text = pair["reference_token"]
            n_pairs += 1

            if position_id in seen_positions:
                n_conflicts += 1
                if seen_positions[position_id] != gold_text:
                    n_conflicts_divergent += 1
                # First occurrence wins; skip later articles' claim on this position.
                continue

            seen_positions[position_id] = gold_text
            page_id = _page_id_from_position(position_id)
            gold_by_page.setdefault(page_id, {})[position_id] = gold_text

    summary = {
        "articles_read": n_articles,
        "articles_zero_aligned": n_articles_zero_aligned,
        "aligned_pairs": n_pairs,
        "distinct_positions": len(seen_positions),
        "position_conflicts": n_conflicts,
        "position_conflicts_divergent": n_conflicts_divergent,
        "pages_with_gold": len(gold_by_page),
    }
    return gold_by_page, summary


def write_gold_files(gold_by_page: dict[str, dict[str, str]], out_dir: Path) -> int:
    """Write one `<page_id>.gold.json` per page in M13 shape. Returns count written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for page_id, positions in sorted(gold_by_page.items()):
        payload = {
            "positions": {
                position_id: {"gold_text": gold_text}
                for position_id, gold_text in sorted(positions.items())
            }
        }
        out_path = out_dir / f"{page_id}.gold.json"
        # Atomic write (OUT-02): temp file then replace, so a partial write
        # never poisons a downstream measurement run.
        tmp_path = out_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, out_path)
        written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert JE aligner output to M13 per-page gold files."
    )
    parser.add_argument(
        "--align-root",
        type=Path,
        default=DEFAULT_ALIGN_ROOT,
        help="Directory of per-article <slug>/gold.json aligner output.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory to write <page_id>.gold.json files into.",
    )
    args = parser.parse_args()

    align_root: Path = args.align_root
    out_dir: Path = args.out_dir

    if not align_root.exists():
        print(f"ERROR: align root not found: {align_root}", file=sys.stderr)
        return 1

    gold_by_page, summary = build_gold_by_page(align_root)

    if not gold_by_page:
        print("ERROR: no gold positions produced (every article had 0 aligned pairs)",
              file=sys.stderr)
        return 1

    written = write_gold_files(gold_by_page, out_dir)

    print("JE gold conversion summary")
    print(f"  articles read:            {summary['articles_read']}")
    print(f"  articles 0-aligned:       {summary['articles_zero_aligned']}")
    print(f"  aligned pairs seen:       {summary['aligned_pairs']}")
    print(f"  distinct positions:       {summary['distinct_positions']}")
    print(f"  position conflicts:       {summary['position_conflicts']} "
          f"({summary['position_conflicts_divergent']} with divergent gold_text)")
    print(f"  pages with gold:          {summary['pages_with_gold']}")
    print(f"  gold files written:       {written}")
    print(f"  output dir:               {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
