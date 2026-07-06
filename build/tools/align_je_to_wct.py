"""Align JE.com article transcriptions to WCT reading-order positions.

For each sampled article:
  1. Load the human transcription from raw/jewish-encyclopedia/articles/{slug}/text.txt
  2. Load the page span from raw/jewish-encyclopedia/articles/{slug}/pages.json
  3. For each page in the span, load reports/je-wct/vol_02/page_{N:04d}.json
  4. Concatenate WCT position sequences across pages (reading order)
  5. Run Needleman-Wunsch alignment of article tokens vs WCT consensus tokens
  6. Write reports/je-gold/vol_02/{slug}/gold.json

Output artifact type: "je-wct-alignment" (NOT gold-record-v1 -- this is the
measurement oracle, not an OCD gold-production artifact; JE is never published
to data/).

NON-CIRCULARITY GUARD: JE.com human transcription is ALWAYS the reference.
IA ABBYY GZ is ENGINE INPUT (a WCT candidate), never the reference.

Alignment method: heuristic confusion-weighted Needleman-Wunsch over
wct_builder.confusion_distance (GAP_PENALTY=0.6, B8-tuned 2026-06-06).

Known failure modes (surfaced as unaligned/excluded, NOT silently resolved):
- Pages with LayoutEscalation have no WCT -> counted in pages_missing_wct
- Running headers / printed folios in WCT not present in article text ->
  route to positions_unaligned
- Article table of contents, section headers -> route to reference_unaligned
- Music notation pages (p0289), caption-only pages (p0287) -> built but sparse
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY = False

try:
    # rapidfuzz C extension -- ~250x faster than pure-Python confusion_distance
    # for building the alignment DP distance table.  The table drives the NW
    # path; confusion_distance is still used for the output confusion_dist field
    # (post-alignment, ~n_aligned calls rather than n_ref * n_wct calls).
    from rapidfuzz.distance import Levenshtein as _rf_lev

    def _align_dist(a: str, b: str) -> float:
        """Normalised Levenshtein for the NW distance table (no confusion weights)."""
        return _rf_lev.normalized_distance(a, b)

except ImportError:  # pragma: no cover
    # Fallback: use confusion_distance for both DP and output (slow but correct).
    def _align_dist(a: str, b: str) -> float:  # type: ignore[misc]
        return confusion_distance(a, b)  # noqa: F821  # imported below

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.s3_reconciler import _best_candidate  # noqa: E402
from build.lib.wct_builder import confusion_distance  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WORK_ID = "jewish-encyclopedia.vol_02"
VOLUME_ID = "vol_02"
VOLUME_NUMBER = 2

ARTICLE_ROOT = REPO_ROOT / "raw" / "jewish-encyclopedia" / "articles"
WCT_ROOT = REPO_ROOT / "reports" / "je-wct" / VOLUME_ID
OUTPUT_ROOT = REPO_ROOT / "reports" / "je-gold" / VOLUME_ID

SCHEMA_TYPE = "je-wct-alignment"
SCHEMA_VERSION = "1.0"
ALIGNMENT_METHOD = (
    "heuristic confusion-weighted Needleman-Wunsch over "
    "wct_builder.confusion_distance (GAP_PENALTY=0.6, tuned B8-2026-06-06)"
)

# Gap penalty -- B8 sweep over [0.3..1.0] confirmed 0.6 as optimum 2026-06-06
GAP_PENALTY = 0.6


# ---------------------------------------------------------------------------
# Normalisation and alignment (mirrors align_ccel_to_wct.py, kept local to
# avoid importing private symbols from another module)
# ---------------------------------------------------------------------------


def _norm(token: str) -> str:
    """Normalise for comparison only; never rewrites emitted raw token.

    NFKC + casefold + strip surrounding non-alphanumerics so headword
    small-caps and body forms compare equal.
    """
    folded = unicodedata.normalize("NFKC", token).casefold()
    return re.sub(r"^\W+|\W+$", "", folded, flags=re.UNICODE)


def _nw_align(
    left: list[str],
    right: list[str],
    *,
    dist_cache: dict[tuple[str, str], float] | None = None,
) -> list[tuple[int | None, int | None]]:
    """Needleman-Wunsch over normalised tokens; confusion-weighted substitution.

    Returns ordered (left_idx|None, right_idx|None) pairs. Uses a pointer
    matrix at fill time (not a float-== backtrace) so a long pure-gap run
    cannot walk off the array.

    dist_cache: optional precomputed {(a, b): confusion_distance(a, b)} dict.
    Callers aligning large articles should precompute the full unique-pair
    cache once (O(|V_left| * |V_right|)) and pass it in, converting O(n*m)
    confusion_distance calls to O(1) dict lookups in the inner loop.

    Performance: uses flat lists with integer pointers (0=None, 1=diag,
    2=up, 3=left) to reduce Python object overhead vs list-of-lists of
    strings. Flat indexing avoids inner-list dereferences in the hot path.
    """
    _NONE, _DIAG, _UP, _LEFT = 0, 1, 2, 3
    n, m = len(left), len(right)
    mp1 = m + 1
    # Flat DP and pointer arrays for minimum Python object overhead
    dp = [0.0] * ((n + 1) * mp1)
    ptr = [_NONE] * ((n + 1) * mp1)
    gap = GAP_PENALTY
    for i in range(1, n + 1):
        dp[i * mp1] = i * gap
        ptr[i * mp1] = _UP
    for j in range(1, mp1):
        dp[j] = j * gap
        ptr[j] = _LEFT
    if dist_cache is not None:
        for i in range(1, n + 1):
            li = left[i - 1]
            row = i * mp1
            prev_row = row - mp1
            for j in range(1, mp1):
                diag = dp[prev_row + j - 1] + dist_cache[(li, right[j - 1])]
                up = dp[prev_row + j] + gap
                lc = dp[row + j - 1] + gap
                if diag <= up:
                    if diag <= lc:
                        dp[row + j] = diag
                        ptr[row + j] = _DIAG
                    else:
                        dp[row + j] = lc
                        ptr[row + j] = _LEFT
                else:
                    if up <= lc:
                        dp[row + j] = up
                        ptr[row + j] = _UP
                    else:
                        dp[row + j] = lc
                        ptr[row + j] = _LEFT
    else:
        for i in range(1, n + 1):
            row = i * mp1
            prev_row = row - mp1
            for j in range(1, mp1):
                diag = dp[prev_row + j - 1] + confusion_distance(
                    left[i - 1], right[j - 1]
                )
                up = dp[prev_row + j] + gap
                lc = dp[row + j - 1] + gap
                if diag <= up:
                    if diag <= lc:
                        dp[row + j] = diag
                        ptr[row + j] = _DIAG
                    else:
                        dp[row + j] = lc
                        ptr[row + j] = _LEFT
                else:
                    if up <= lc:
                        dp[row + j] = up
                        ptr[row + j] = _UP
                    else:
                        dp[row + j] = lc
                        ptr[row + j] = _LEFT
    ops: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        move = ptr[i * mp1 + j]
        if move == _DIAG:
            ops.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif move == _UP:
            ops.append((i - 1, None))
            i -= 1
        else:
            ops.append((None, j - 1))
            j -= 1
    ops.reverse()
    return ops


def _nw_align_numpy(
    ref_norm: list[str],
    wct_norm: list[str],
    dist_table: "np.ndarray",
    ref_vidx: list[int],
    wct_vidx: list[int],
) -> list[tuple[int | None, int | None]]:
    """Needleman-Wunsch using numpy anti-diagonal vectorised sweep.

    Reduces the inner loop from O(n*m) pure-Python iterations to O(n+m)
    numpy vectorised calls. Benchmarks show ~200-500x speedup over the flat-
    list Python implementation for chunks ≥ 300 x 300.

    dist_table: precomputed (|V_ref|, |V_wct|) distance matrix, shared across
    all page chunks for one article.  ref_vidx / wct_vidx are vocabulary
    indices into it for each token in this chunk.

    Falls through to the same backtrace logic as _nw_align (pointer matrix,
    prefer DIAG > UP > LEFT on tie).
    """
    _DIAG, _UP, _LEFT = 1, 2, 3
    n, m = len(ref_norm), len(wct_norm)

    if n == 0:
        return [(None, j) for j in range(m)]
    if m == 0:
        return [(i, None) for i in range(n)]

    gap = GAP_PENALTY
    dp = np.zeros((n + 1, m + 1), dtype=np.float64)
    ptr = np.zeros((n + 1, m + 1), dtype=np.int8)

    dp[1:, 0] = np.arange(1, n + 1) * gap
    ptr[1:, 0] = _UP
    dp[0, 1:] = np.arange(1, m + 1) * gap
    ptr[0, 1:] = _LEFT

    # Extract the (n x m) sub-matrix for this chunk via vocabulary indices.
    # np.ix_ produces open mesh arrays so dist_table[np.ix_(r, w)] is a
    # proper copy (not a view) -- shape (n, m), no strided indexing in the loop.
    r_idx = np.asarray(ref_vidx, dtype=np.int64)
    w_idx = np.asarray(wct_vidx, dtype=np.int64)
    dist_mat = dist_table[np.ix_(r_idx, w_idx)]  # shape (n, m)

    # Anti-diagonal sweep: all cells with i+j == d share no data dependencies,
    # so the whole diagonal can be computed in one vectorised step.
    for d in range(1, n + m + 1):
        i_lo = max(1, d - m)
        i_hi = min(n, d - 1) + 1
        if i_lo >= i_hi:
            continue
        ii = np.arange(i_lo, i_hi, dtype=np.int64)
        jj = d - ii

        diag_v = dp[ii - 1, jj - 1] + dist_mat[ii - 1, jj - 1]
        up_v = dp[ii - 1, jj] + gap
        left_v = dp[ii, jj - 1] + gap

        best = np.minimum(np.minimum(diag_v, up_v), left_v)
        dp[ii, jj] = best

        # Prefer DIAG > UP > LEFT on exact tie (same priority as _nw_align).
        is_diag = best == diag_v
        is_up = (~is_diag) & (best == up_v)
        ptr[ii, jj] = np.where(is_diag, _DIAG, np.where(is_up, _UP, _LEFT))

    # Standard backtrace (pure Python -- n+m steps, not a bottleneck).
    ops: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        move = int(ptr[i, j])
        if move == _DIAG:
            ops.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif move == _UP:
            ops.append((i - 1, None))
            i -= 1
        else:
            ops.append((None, j - 1))
            j -= 1
    ops.reverse()
    return ops


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_pages_json(article_dir: Path) -> list[int]:
    """Return sorted list of vol-02 page numbers from pages.json.

    pages.json is a list of [vol, page_num, url] triplets. Only triplets
    where vol == VOLUME_NUMBER (2) are included.

    Raises:
        FileNotFoundError: if pages.json does not exist in article_dir.
    """
    pages_path = article_dir / "pages.json"
    if not pages_path.exists():
        raise FileNotFoundError(f"pages.json not found: {pages_path}")
    triplets = json.loads(pages_path.read_text(encoding="utf-8"))
    pages = sorted(
        page_num
        for vol, page_num, _url in triplets
        if vol == VOLUME_NUMBER
    )
    return pages


def _collect_wct_sequence(
    wct_pages: list[dict],
) -> list[tuple[str, str]]:
    """(position_id, consensus_raw_reading) pairs in reading order across pages.

    Positions with an empty candidate_set are skipped (no reading to align).
    Pages are concatenated in the order supplied -- caller is responsible for
    passing them in page-number order.
    """
    result: list[tuple[str, str]] = []
    for page in wct_pages:
        by_id = {p["position_id"]: p for p in page["positions"]}
        ordered_ids = [pid for pid in page.get("reading_order", []) if pid in by_id]
        # Append any positions not in reading_order (shouldn't normally happen)
        in_order = set(ordered_ids)
        for p in page["positions"]:
            if p["position_id"] not in in_order:
                ordered_ids.append(p["position_id"])
        for pid in ordered_ids:
            candidates = by_id[pid]["candidate_set"]
            if not candidates:
                continue
            best = _best_candidate(candidates)
            result.append((pid, best["raw_reading"]))
    return result


# ---------------------------------------------------------------------------
# Core aligner
# ---------------------------------------------------------------------------


def align_article(
    slug: str,
    article_dir: Path,
    wct_dir: Path,
    output_dir: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Align one JE article's text to WCT positions and write gold.json.

    Args:
        slug: article slug (e.g. "1654-apostasy-and-apostates")
        article_dir: directory containing pages.json and text.txt
        wct_dir: directory containing page_NNNN.json WCT files
        output_dir: base output dir; gold.json goes to output_dir/slug/gold.json
        dry_run: if True, compute alignment but do not write any files

    Returns:
        The alignment result dict (same structure as what is written to disk).
    """
    pages = _load_pages_json(article_dir)
    text = (article_dir / "text.txt").read_text(encoding="utf-8")

    pages_with_wct: list[int] = []
    pages_missing_wct: list[int] = []
    wct_pages: list[dict] = []

    for page_num in pages:
        wct_path = wct_dir / f"page_{page_num:04d}.json"
        if wct_path.exists():
            wct_pages.append(json.loads(wct_path.read_text(encoding="utf-8")))
            pages_with_wct.append(page_num)
        else:
            pages_missing_wct.append(page_num)

    # Tokenise reference text
    ref_tokens = text.split()
    ref_norm = [_norm(t) for t in ref_tokens]
    n_ref = len(ref_tokens)

    # Per-page WCT sequences -- used for page-chunked alignment.
    # Each entry corresponds to a page in pages_with_wct (same order).
    page_seqs: list[list[tuple[str, str]]] = [
        _collect_wct_sequence([page]) for page in wct_pages
    ]
    total_wct = sum(len(seq) for seq in page_seqs)

    aligned_pairs: list[dict] = []
    reference_unaligned: list[dict] = []
    positions_unaligned: list[str] = []

    if total_wct == 0 or n_ref == 0:
        # Nothing to align -- all ref tokens are unaligned.
        for i, tok in enumerate(ref_tokens):
            reference_unaligned.append(
                {"index": i, "token": tok, "norm": ref_norm[i]}
            )

    elif _HAS_NUMPY:
        # ---------------------------------------------------------------
        # NUMPY PAGE-CHUNKED ALIGNMENT
        #
        # The article text is split proportionally across WCT pages
        # (token count ∝ WCT position count per page), then each chunk is
        # aligned against its page via the numpy anti-diagonal NW.
        #
        # Why page-chunked? Full-article NW over a 6-page article is
        # O(n_ref * total_wct) -- apostasy has ~2000 ref tokens * ~6000
        # WCT positions = 12M pairs. Even with numpy that would require a
        # 12M-element DP matrix. Per-page chunks are ~300x300 = 90K cells:
        # fast to fill AND keep memory bounded.
        # ---------------------------------------------------------------

        # Flat lists for vocab precomputation across all pages.
        all_wct_readings: list[str] = [
            raw for seq in page_seqs for _, raw in seq
        ]
        all_wct_norm: list[str] = [_norm(r) for r in all_wct_readings]

        # Build global vocabularies once per article.
        ref_vocab = sorted(set(ref_norm))
        wct_vocab = sorted(set(all_wct_norm))
        ref_vidx_map: dict[str, int] = {w: i for i, w in enumerate(ref_vocab)}
        wct_vidx_map: dict[str, int] = {w: i for i, w in enumerate(wct_vocab)}

        # Precompute alignment distances -- O(|V_ref| * |V_wct|) calls, done
        # once rather than per-cell in the inner loop.  Uses confusion_distance
        # (OCR-aware character confusion weights) for both the DP path and the
        # output confusion_dist field.  Plain Levenshtein (_align_dist) was used
        # previously, but the "not affected in practice" claim was false: for
        # short tokens (1-2 chars), ci/cl gives 0.125 vs 0.500 -- enough to
        # flip alignment decisions across the 0.6 gap penalty.  confusion_distance
        # adds ~200us/call vs ~0.8us for rapidfuzz, but the vocab is shared across
        # all page chunks so the cost is O(|V_ref| * |V_wct|), not O(n_ref * n_wct).
        dist_table = np.array(
            [[confusion_distance(a, b) for b in wct_vocab] for a in ref_vocab],
            dtype=np.float64,
        )

        # Proportional token allocation: cumulative approach assigns every ref
        # token to exactly one page chunk with no rounding leftover.
        wct_flat_offset = 0  # tracks position in all_wct_readings / all_wct_norm
        ref_offset = 0
        cumulative_wct = 0

        for seq, page_readings_slice_start in zip(
            page_seqs,
            # build per-page slice start offsets for all_wct_* lists
            [
                sum(len(page_seqs[j]) for j in range(k))
                for k in range(len(page_seqs))
            ],
        ):
            m_page = len(seq)
            cumulative_wct += m_page
            chunk_end = round(n_ref * cumulative_wct / total_wct)
            n_chunk = chunk_end - ref_offset

            wct_pos_ids_page = [pid for pid, _ in seq]
            wct_readings_page = all_wct_readings[
                page_readings_slice_start : page_readings_slice_start + m_page
            ]
            wct_norm_page = all_wct_norm[
                page_readings_slice_start : page_readings_slice_start + m_page
            ]

            if n_chunk == 0:
                # No ref tokens allocated to this page -- all positions unaligned.
                positions_unaligned.extend(wct_pos_ids_page)
                ref_offset = chunk_end
                continue

            ref_chunk_raw = ref_tokens[ref_offset:chunk_end]
            ref_chunk_norm = ref_norm[ref_offset:chunk_end]
            ref_chunk_vidx = [ref_vidx_map[n] for n in ref_chunk_norm]
            wct_chunk_vidx = [wct_vidx_map[n] for n in wct_norm_page]

            ops = _nw_align_numpy(
                ref_chunk_norm, wct_norm_page,
                dist_table, ref_chunk_vidx, wct_chunk_vidx,
            )

            for ref_idx, wct_idx in ops:
                if ref_idx is not None and wct_idx is not None:
                    ref_tok = ref_chunk_raw[ref_idx]
                    ocr_reading = wct_readings_page[wct_idx]
                    rn = ref_chunk_norm[ref_idx]
                    wn = wct_norm_page[wct_idx]
                    # confusion_dist uses true confusion_distance (not the
                    # rapidfuzz table used for the DP) -- only ~n_aligned
                    # calls per article, so cost is negligible.
                    dist = round(confusion_distance(rn, wn), 4)
                    aligned_pairs.append(
                        {
                            "position_id": wct_pos_ids_page[wct_idx],
                            "reference_token": ref_tok,
                            "reference_norm": rn,
                            "ocr_consensus": ocr_reading,
                            "ocr_norm": wn,
                            "match": rn == wn,
                            "confusion_dist": dist,
                        }
                    )
                elif ref_idx is not None:
                    aligned_abs = ref_offset + ref_idx
                    reference_unaligned.append(
                        {
                            "index": aligned_abs,
                            "token": ref_chunk_raw[ref_idx],
                            "norm": ref_chunk_norm[ref_idx],
                        }
                    )
                else:
                    positions_unaligned.append(wct_pos_ids_page[wct_idx])

            ref_offset = chunk_end

    else:
        # ---------------------------------------------------------------
        # PURE PYTHON FALLBACK (numpy not available)
        #
        # Single-pass global NW with dist_cache precomputation.
        # ---------------------------------------------------------------
        wct_seq = [(pid, raw) for seq in page_seqs for pid, raw in seq]
        position_ids = [pid for pid, _ in wct_seq]
        wct_readings_flat = [raw for _, raw in wct_seq]
        wct_norm_flat = [_norm(r) for r in wct_readings_flat]

        unique_ref = sorted(set(ref_norm))
        unique_wct = sorted(set(wct_norm_flat))
        dist_cache = {
            (a, b): confusion_distance(a, b)
            for a in unique_ref
            for b in unique_wct
        }

        ops = _nw_align(ref_norm, wct_norm_flat, dist_cache=dist_cache)

        for ref_idx, wct_idx in ops:
            if ref_idx is not None and wct_idx is not None:
                ref_tok = ref_tokens[ref_idx]
                ocr_reading = wct_readings_flat[wct_idx]
                rn = ref_norm[ref_idx]
                wn = wct_norm_flat[wct_idx]
                dist = round(confusion_distance(rn, wn), 4)
                aligned_pairs.append(
                    {
                        "position_id": position_ids[wct_idx],
                        "reference_token": ref_tok,
                        "reference_norm": rn,
                        "ocr_consensus": ocr_reading,
                        "ocr_norm": wn,
                        "match": rn == wn,
                        "confusion_dist": dist,
                    }
                )
            elif ref_idx is not None:
                reference_unaligned.append(
                    {
                        "index": ref_idx,
                        "token": ref_tokens[ref_idx],
                        "norm": ref_norm[ref_idx],
                    }
                )
            else:
                positions_unaligned.append(position_ids[wct_idx])

    n_match = sum(1 for p in aligned_pairs if p["match"])
    result = {
        "schema_type": SCHEMA_TYPE,
        "schema_version": SCHEMA_VERSION,
        "article_slug": slug,
        "work_id": WORK_ID,
        "volume_id": VOLUME_ID,
        "pages_spanned": pages,
        "pages_with_wct": pages_with_wct,
        "pages_missing_wct": pages_missing_wct,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "alignment_method": ALIGNMENT_METHOD,
        "n_reference_tokens": n_ref,
        "n_wct_positions": total_wct,
        "n_aligned": len(aligned_pairs),
        "n_reference_unaligned": len(reference_unaligned),
        "n_positions_unaligned": len(positions_unaligned),
        "n_match": n_match,
        "aligned_pairs": aligned_pairs,
        "reference_unaligned": reference_unaligned,
        "positions_unaligned": positions_unaligned,
    }

    if not dry_run:
        out_dir = output_dir / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "gold.json"
        # Atomic write (OUT-02)
        tmp_path = out_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, out_path)

    return result


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Align JE article transcriptions to WCT positions."
    )
    parser.add_argument(
        "--article",
        metavar="SLUG",
        help="Process one article slug (default: all articles)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute alignment but do not write output files.",
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
        help="Override output root directory.",
    )
    args = parser.parse_args()

    article_root: Path = args.article_root
    wct_root: Path = args.wct_root
    output_root: Path = args.output_root

    if not article_root.exists():
        print(f"ERROR: article root not found: {article_root}", file=sys.stderr)
        return 1

    if args.article:
        slugs = [args.article]
    else:
        slugs = sorted(d.name for d in article_root.iterdir() if d.is_dir())

    errors = 0
    total = len(slugs)
    for i, slug in enumerate(slugs, 1):
        article_dir = article_root / slug
        print(f"[{i}/{total}] {slug}...")
        try:
            result = align_article(
                slug,
                article_dir,
                wct_root,
                output_root,
                dry_run=args.dry_run,
            )
            pct = (result["n_match"] / result["n_aligned"] * 100) if result["n_aligned"] else 0.0
            print(
                f"  pages={result['pages_spanned']} "
                f"aligned={result['n_aligned']} "
                f"match={result['n_match']} ({pct:.1f}%) "
                f"missing_wct={result['pages_missing_wct']}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}", file=sys.stderr)
            errors += 1

    if args.dry_run:
        print("(dry run -- no files written)")

    n_ok = total - errors
    print(f"\nDone: {n_ok}/{total} articles OK, {errors} errors.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
