"""Pre-run reuse summary line for the NSH S1 runners + orchestrator (R6a).

One ``vol_NN: N leaves | R reused | K to OCR`` line, emitted BEFORE any engine
call. A ``0 to OCR / N reused`` line makes a future redo regression -- the kind
that silently re-OCR'd vol_01 from scratch (10.5h) after the phantom-page
rename -- obvious in the run log at a glance. Single source of truth so all four
runners + the orchestrator emit the identical shape (CC-ARCH-05).
"""
from __future__ import annotations


def format_prerun_summary(lineage: str, volume: int, n_leaves: int, n_reused: int) -> str:
    """``    <lineage> vol_NN: <N> leaves | <R> reused | <K> to OCR`` (K = N - R)."""
    n_to_ocr = n_leaves - n_reused
    return (
        f"    {lineage} vol_{volume:02d}: "
        f"{n_leaves} leaves | {n_reused} reused | {n_to_ocr} to OCR"
    )


def format_unresolved_leaf_note(
    *,
    lineage: str,
    volume: int,
    sha: str,
    reason: str,
    edition_key: dict | None,
) -> str | None:
    """Log line for a page whose source-payload sha resolves to no body leaf.

    ``resolve_leaf`` only indexes body leaves, so it raises for recovered-gap
    and front/back-matter pages. Those pages are NOT defects: they legitimately
    carry no ``canonical_leaf_id`` (clid_exempt) and instead join the
    reconciliation chain via ``edition_page_key``. Returning ``None`` for them
    keeps the run log quiet -- the old unconditional "leaf unresolved ...
    emitting without canonical_leaf_id" line predated edition keys and read as a
    failure when it was a no-op (it fired once per gap/front-back page).

    Only a page that resolves to NEITHER a ``canonical_leaf_id`` NOR an
    ``edition_page_key`` is a real problem worth flagging -- and it will also
    fail ``sidecar-page-v1`` validation downstream, which requires
    ``edition_page_key`` on every page. For that case a warning string is
    returned naming the sha and both missing keys.
    """
    if edition_key is not None:
        return None
    return (
        f"    {lineage} vol_{volume:02d}: page resolves to NEITHER canonical_leaf_id "
        f"NOR edition_page_key for sha {sha[:18]}... ({reason})"
    )
