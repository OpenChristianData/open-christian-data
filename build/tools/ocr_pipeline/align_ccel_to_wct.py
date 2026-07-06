"""Align CCEL page reference text to WCT reading-order positions (PROPOSAL, not gold).

This is the CCEL-word-to-WCT-position aligner (arch A's engine-agnostic text
alignment, applied to the human-proofread CCEL reference rather than an OCR engine).
It lines the page-keyed CCEL prose (``ccel-page-gold-proposal``) up against the WCT
page's reading-order OCR consensus, so:

  * where CCEL AGREES with the OCR consensus -> a *gold candidate* on CCEL's
    independent human-proofread authority; no maintainer review needed.
  * where CCEL DISAGREES with the OCR -> a *reviewer-queue item* the maintainer
    adjudicates against the scan crop (mirroring the reconcile_s3 reviewer_queue
    shape, keyed on position_id).

The maintainer's review unit is the DISAGREEMENT, not the page. We never ask anyone
to confirm a whole transcript.

Why this is a PROPOSAL, not a ``gold-record-v1`` (same reason as extract_ccel_page_gold):
``gold-record-v1`` has no machine-proposed middle state -- ``verified`` requires a
non-empty ``ground_truth_text`` (authored gold), ``unverifiable`` requires null. The
tuning embargo forbids machine-authored gold ``ground_truth_text``. So this tool emits
candidates a human mints into gold via the existing ``ccel_gold`` mark/withdraw/
supersede authority events; it never asserts gold itself.

Alignment method (named honestly): a heuristic confusion-weighted Needleman-Wunsch
between the CCEL word sequence and the WCT reading-order OCR-consensus sequence,
scored with ``wct_builder.confusion_distance``. It is un-tuned; threshold tuning is
gated by the B8 first-diagnostics verdict.

Known failure modes (recorded in the artifact caveats, surfaced as disagreements by
design, NOT silently resolved):
  * CCEL omits running headers + printed folios that ARE in the WCT as body tokens
    (Surya mislabels them body) -> ``ccel_omits_token`` review items.
  * hyphenation / line-break splits, small-caps headwords -> distance disagreements.
  * mid-article page breaks (page_0010 left col = an Abelard continuation, right col
    a new article) -> alignment near the column boundary is the least certain.
  * where the alignment itself is uncertain (a CCEL word maps to no position, or a
    position to no CCEL word) -> routed to review, never guessed into gold.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.ocr_store_paths import WCT_ROOT  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.s3_reconciler import _best_candidate  # noqa: E402
from build.lib.wct_builder import confusion_distance  # noqa: E402

ARTIFACT_KIND = "ccel-wct-alignment-proposal"
# Loud, deliberately not a schema_version: this is NOT a gold-record-v1.
PROPOSAL_STATUS = "PROPOSAL_NOT_GOLD"
ALIGNMENT_METHOD = (
    "heuristic confusion-weighted Needleman-Wunsch over "
    "wct_builder.confusion_distance (un-tuned; tuning gated by B8)"
)

# Gap penalty for the NW alignment path (mirrors wct_builder; un-tuned, B8-gated).
# confusion_distance drives ALIGNMENT (which CCEL word maps to which position despite
# OCR noise). The AGREEMENT decision is deliberately NOT distance-based: a gold
# candidate requires CCEL and the OCR consensus to be the SAME token after
# normalisation. A visually-close-but-different reading ("rnerit" vs "merit",
# "wlth" vs "with") is exactly where OCR silently errs -- CCEL's differing reading is
# the disagreement the maintainer must see, not a near-agreement to wave through.
GAP_PENALTY = 0.6

DEFAULT_WCT = WCT_ROOT / "vol_{volume:02d}" / "page_{page:04d}.json"
DEFAULT_PROPOSAL = REPO_ROOT / "reports" / "gold" / "vol_{volume:02d}" / "ccel_page_gold_proposal.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "reports" / "gold" / "vol_{volume:02d}" / "ccel_wct_alignment_page_{page:04d}.json"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _norm(token: str) -> str:
    """Normalisation for comparison only (never rewrites the emitted raw token).

    NFKC + casefold + strip surrounding non-alphanumerics, so a small-caps headword
    (``AACHEN,``) and the body form (``aachen``) are not a spurious case/punctuation
    disagreement. The raw CCEL token and raw OCR reading are preserved in the output.
    """
    folded = unicodedata.normalize("NFKC", token).casefold()
    return re.sub(r"^\W+|\W+$", "", folded, flags=re.UNICODE)


def _ocr_consensus_sequence(wct_page: dict) -> list[tuple[str, str]]:
    """(position_id, OCR-consensus raw_reading) in WCT reading order.

    Consensus = s3_reconciler._best_candidate (most-attested candidate); reused, not
    reinvented. Positions with an empty candidate_set (all engines skipped) are
    dropped -- they contribute no reading to align against.
    """
    by_id = {p["position_id"]: p for p in wct_page["positions"]}
    ordered_ids = [pid for pid in wct_page.get("reading_order", []) if pid in by_id]
    for p in wct_page["positions"]:
        if p["position_id"] not in ordered_ids:
            ordered_ids.append(p["position_id"])
    sequence: list[tuple[str, str]] = []
    for pid in ordered_ids:
        candidates = by_id[pid]["candidate_set"]
        if not candidates:
            continue
        sequence.append((pid, _best_candidate(candidates)["raw_reading"]))
    return sequence


def _nw_align(left: list[str], right: list[str]) -> list[tuple[int | None, int | None]]:
    """Needleman-Wunsch over normalised tokens; confusion-weighted substitution.

    Returns ordered (left_idx|None, right_idx|None) pairs. Uses a pointer matrix
    recorded at fill time (not a float-`==` backtrace) so a long pure-gap run can't
    walk off the array -- the same fix wct_builder._nw_align carries.
    """
    n, m = len(left), len(right)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    ptr: list[list[str | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * GAP_PENALTY
        ptr[i][0] = "up"
    for j in range(1, m + 1):
        dp[0][j] = j * GAP_PENALTY
        ptr[0][j] = "left"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1][j - 1] + confusion_distance(left[i - 1], right[j - 1])
            up = dp[i - 1][j] + GAP_PENALTY
            left_cost = dp[i][j - 1] + GAP_PENALTY
            best = min(diag, up, left_cost)
            dp[i][j] = best
            if best == diag:
                ptr[i][j] = "diag"
            elif best == up:
                ptr[i][j] = "up"
            else:
                ptr[i][j] = "left"
    ops: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        move = ptr[i][j]
        if move == "diag":
            ops.append((i - 1, j - 1)); i -= 1; j -= 1
        elif move == "up":
            ops.append((i - 1, None)); i -= 1
        else:
            ops.append((None, j - 1)); j -= 1
    ops.reverse()
    return ops


def _select_ccel_page(
    ccel_proposal: dict,
    page_id: str,
    canonical_leaf_id: int | None = None,
    edition_page_key: dict | None = None,
) -> dict | None:
    """Find the CCEL page for this WCT page.

    Prefer the scan-independent ``edition_page_key`` for cross-copy joins. Fall
    back to the per-copy ``canonical_leaf_id`` when no edition key is available,
    then to the legacy filename stem.
    """
    if edition_page_key is not None:
        for page in ccel_proposal.get("pages", []):
            if page.get("edition_page_key") == edition_page_key:
                return page
    if canonical_leaf_id is not None:
        for page in ccel_proposal.get("pages", []):
            if page.get("canonical_leaf_id") == canonical_leaf_id:
                return page
    for page in ccel_proposal.get("pages", []):
        if page.get("page_native_id") == page_id:
            return page
    return None


def _zone_type_from_pid(pid: str) -> str:
    """Extract zone type from a WCT position_id (format: vol:page:zone:col:line:pos).

    Returns "body" as a safe default for any unexpected format so new zone types
    never silently produce spurious gold -- they route to review instead.
    """
    parts = pid.split(":")
    return parts[2] if len(parts) >= 3 else "body"


def align_page(
    wct_page: dict,
    ccel_proposal: dict,
    *,
    page_id: str | None = None,
    generated_at: str | None = None,
    wct_path: str | None = None,
    proposal_path: str | None = None,
) -> dict:
    """Align one WCT page's OCR consensus to its CCEL page text. Returns the proposal.

    Agreements become gold candidates (CCEL's independent authority); disagreements,
    unaligned CCEL words, and CCEL-omitted positions become reviewer-queue items.
    """
    page_id = page_id or wct_page["page_id"]
    canonical_leaf_id = wct_page.get("canonical_leaf_id")
    edition_page_key = wct_page.get("edition_page_key")
    ccel_page = _select_ccel_page(ccel_proposal, page_id, canonical_leaf_id, edition_page_key)
    if ccel_page is None:
        raise ValueError(
            f"CCEL proposal has no page for page_id {page_id!r} / "
            f"edition_page_key {edition_page_key!r} / canonical_leaf_id {canonical_leaf_id!r} "
            "to align against "
            f"(pages: {[(p.get('page_native_id'), p.get('edition_page_key'), p.get('canonical_leaf_id')) for p in ccel_proposal.get('pages', [])]})"
        )

    consensus = _ocr_consensus_sequence(wct_page)        # [(position_id, ocr_reading)]
    ocr_readings = [reading for _, reading in consensus]
    position_ids = [pid for pid, _ in consensus]
    ccel_tokens = ccel_page["ccel_page_text"].split()

    ccel_norm = [_norm(t) for t in ccel_tokens]
    ocr_norm = [_norm(t) for t in ocr_readings]
    ops = _nw_align(ccel_norm, ocr_norm)

    # position_id -> reference_bbox + candidate raw readings, for the queue/candidate rows.
    pos_by_id = {p["position_id"]: p for p in wct_page["positions"]}

    def _candidates_for(pid: str) -> list[str]:
        return [c["raw_reading"] for c in pos_by_id[pid]["candidate_set"]]

    def _ref_bbox(pid: str) -> dict | None:
        return pos_by_id[pid].get("reference_bbox")

    source_basis = ccel_proposal.get("source", {}).get("source_basis", "")
    scan_path = ccel_page.get("scan_path")

    gold_candidates: list[dict] = []
    reviewer_queue: list[dict] = []

    for ccel_idx, ocr_idx in ops:
        if ccel_idx is not None and ocr_idx is not None:
            pid = position_ids[ocr_idx]
            ccel_tok = ccel_tokens[ccel_idx]
            ocr_reading = ocr_readings[ocr_idx]
            dist = round(confusion_distance(ccel_norm[ccel_idx], ocr_norm[ocr_idx]), 4)
            zone_type = _zone_type_from_pid(pid)
            if zone_type != "body":
                # NW paired a CCEL body word with a non-body WCT position (running
                # header, printed folio).  CCEL omits these by design -- certifying
                # them as gold would inflate the gold count with semantically wrong
                # pairs.  Route the WCT position as ccel_omits_token and the orphaned
                # CCEL token as ccel_token_unaligned so both reach the reviewer.
                reviewer_queue.append({
                    "position_id": pid,
                    "reason": "ccel_omits_token",
                    "ccel_token": None,
                    "chosen_reading": ocr_reading,
                    "candidates": _candidates_for(pid),
                    "confusion_distance": None,
                    "reference_bbox": _ref_bbox(pid),
                    "scan_path": scan_path,
                })
                reviewer_queue.append({
                    "position_id": None,
                    "reason": "ccel_token_unaligned",
                    "ccel_token": ccel_tok,
                    "chosen_reading": None,
                    "candidates": [],
                    "confusion_distance": None,
                    "reference_bbox": None,
                    "scan_path": scan_path,
                })
            # Agreement = same token after normalisation (NOT visual proximity).
            elif ccel_norm[ccel_idx] == ocr_norm[ocr_idx]:
                gold_candidates.append({
                    "position_id": pid,
                    "ccel_token": ccel_tok,
                    "ocr_reading": ocr_reading,
                    "confusion_distance": dist,
                    "reference_bbox": _ref_bbox(pid),
                    "source_basis": source_basis,
                    "scan_path": scan_path,
                })
            else:
                reviewer_queue.append({
                    "position_id": pid,
                    "reason": "ccel_ocr_disagreement",
                    "ccel_token": ccel_tok,
                    "chosen_reading": ocr_reading,
                    "candidates": _candidates_for(pid),
                    "confusion_distance": dist,
                    "reference_bbox": _ref_bbox(pid),
                    "scan_path": scan_path,
                })
        elif ocr_idx is not None:
            # WCT position with no CCEL word: a running header / printed folio CCEL
            # omits, or an OCR-only token. Route to review (CCEL omits by design).
            pid = position_ids[ocr_idx]
            reviewer_queue.append({
                "position_id": pid,
                "reason": "ccel_omits_token",
                "ccel_token": None,
                "chosen_reading": ocr_readings[ocr_idx],
                "candidates": _candidates_for(pid),
                "confusion_distance": None,
                "reference_bbox": _ref_bbox(pid),
                "scan_path": scan_path,
            })
        else:
            # CCEL word with no WCT position: the OCR dropped it, or the alignment is
            # uncertain. Route to review rather than guess a gold token.
            reviewer_queue.append({
                "position_id": None,
                "reason": "ccel_token_unaligned",
                "ccel_token": ccel_tokens[ccel_idx],
                "chosen_reading": None,
                "candidates": [],
                "confusion_distance": None,
                "reference_bbox": None,
                "scan_path": scan_path,
            })

    aligned_pairs = sum(1 for a, b in ops if a is not None and b is not None)
    total_decisions = len(gold_candidates) + len(reviewer_queue)
    disagreement_rate = (
        len(reviewer_queue) / total_decisions if total_decisions else 0.0
    )
    # Decompose the queue so the disagreement rate is not read as "OCR is N% wrong":
    # gap reasons (ccel_omits_token / ccel_token_unaligned) are inflated by the
    # un-tuned WCT reading-order scramble (B8-gated), not all genuine OCR errors.
    by_reason: dict[str, int] = {}
    for item in reviewer_queue:
        by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1

    return {
        "artifact_kind": ARTIFACT_KIND,
        "status": PROPOSAL_STATUS,
        "volume": ccel_proposal.get("volume"),
        "work_id": wct_page.get("work_id"),
        "volume_id": wct_page.get("volume_id"),
        "page_id": page_id,
        "canonical_leaf_id": canonical_leaf_id,
        "edition_page_key": dict(edition_page_key) if edition_page_key is not None else None,
        "alignment_method": ALIGNMENT_METHOD,
        "source": {
            "wct_path": wct_path,
            "ccel_proposal_path": proposal_path,
            "ccel_source_basis": source_basis,
            "ccel_print_edition": ccel_proposal.get("source", {}).get("ccel_print_edition"),
            "pipeline_scan_edition": ccel_proposal.get("source", {}).get("pipeline_scan_edition"),
            "scan_path": scan_path,
            "generated_at": generated_at or _utc_now(),
        },
        "caveats": [
            "NOT a gold-record-v1: machine-proposed agreement candidates, not human-verified gold.",
            "A gold candidate is CCEL agreeing with the OCR consensus; a human mints gold via "
            "the ccel_gold mark/withdraw/supersede events. The maintainer reviews disagreements only.",
            "CCEL omits running headers and printed folios that ARE in the WCT as body tokens "
            "(Surya mislabels them body) -> they surface as ccel_omits_token review items by design.",
            "Hyphenation/line-break splits and small-caps headwords surface as distance disagreements.",
            "page_0010 has a mid-article page break (left col Abelard continuation, right col a new "
            "article); alignment near the column boundary is the least certain and routes to review.",
            "Alignment is an un-tuned heuristic; uncertain maps route to review, never guessed into gold.",
        ],
        "coverage": {
            "ccel_tokens": len(ccel_tokens),
            "wct_positions": len(position_ids),
            "tokens_aligned": aligned_pairs,
            "gold_candidates": len(gold_candidates),
            "reviewer_queue_items": len(reviewer_queue),
            "reviewer_queue_by_reason": by_reason,
            "disagreement_rate": round(disagreement_rate, 4),
        },
        "gold_candidates": gold_candidates,
        "reviewer_queue": reviewer_queue,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--volume", type=int, default=1)
    parser.add_argument("--page", type=int, default=10, help="Scan page number (default 10).")
    parser.add_argument("--wct", type=Path, default=None)
    parser.add_argument("--proposal", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--write", action="store_true", help="Write the artifact. Default: dry-run summary.")
    return parser.parse_args(list(argv or []))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    wct_path = args.wct or Path(str(DEFAULT_WCT).format(volume=args.volume, page=args.page))
    proposal_path = args.proposal or Path(str(DEFAULT_PROPOSAL).format(volume=args.volume))
    if not wct_path.exists():
        print(f"ERROR: WCT page not found: {wct_path}", file=sys.stderr)
        return 2
    if not proposal_path.exists():
        print(f"ERROR: CCEL proposal not found: {proposal_path}", file=sys.stderr)
        return 2

    wct_page = json.loads(wct_path.read_text(encoding="utf-8"))
    ccel_proposal = json.loads(proposal_path.read_text(encoding="utf-8"))

    def _rel(path: Path) -> str:
        try:
            return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    artifact = align_page(
        wct_page,
        ccel_proposal,
        wct_path=_rel(wct_path),
        proposal_path=_rel(proposal_path),
    )
    cov = artifact["coverage"]
    print(
        f"{ARTIFACT_KIND} vol={args.volume} page={args.page} "
        f"ccel_tokens={cov['ccel_tokens']} wct_positions={cov['wct_positions']} "
        f"gold_candidates={cov['gold_candidates']} queued={cov['reviewer_queue_items']} "
        f"disagreement_rate={cov['disagreement_rate']}"
    )
    if not args.write:
        return 0

    output = args.output or Path(str(DEFAULT_OUTPUT).format(volume=args.volume, page=args.page))
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(output)
    print(f"wrote {_rel(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
