"""Content-based leaf alignment for ALTERNATE-scan ABBYY lineages (design sec 6).

The alternate IA scans (``ia-abbyy-dli-v1``, ``ia-abbyy-haucgoog-v1``, ``-c1..c4``)
are the SAME edition as the canonical New Schaff-Herzog scan, but DIFFERENT physical
scans: each has its own leaf order (front-matter length, duplicate/missing/inserted
plate leaves), so its leaf N does NOT correspond to canonical leaf N. The field-offset
oracle in ``abbyy_leaf_alignment.py`` assumes implicit same-stem and is defeated here:
the scandata ``page_num`` field numerically collides with the canonical page number,
faking a constant offset 0 while the real content is shifted (measured 2026-06-15:
same-stem Jaccard ~0.07 vs canonical, best-match Jaccard ~0.85 -- the scan IS the same
edition, just reordered).

This module computes the REORDER by content: each alternate leaf is matched to the
canonical leaf whose OCR text it shares the most words with, against a leaf-stamped
reference (``ia-abbyy-v1`` -- the canonical scan's own ABBYY OCR, which covers every
volume and is the same engine family so overlap is cleanest). The match is greedy and
MONOTONE (reading order is preserved across editions), which absorbs duplicate, missing
and inserted leaves: a duplicate alt leaf maps to the same canonical leaf; a missing alt
leaf simply skips a canonical leaf. Pages that match nothing above threshold (blank
leaves, full-page plates, front/back matter absent from the body reference) are left
unmapped and logged -- never force-mapped (PIPE-29: never stamp an unverified leaf).

The Jaccard separation between a correct match (~0.85) and a wrong one (~0.07) is wide,
so a 0.30 acceptance threshold has large slack for cross-scan OCR noise.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

from build.lib.nsh_leaf_model import canonical_leaf_id
from build.lib.paths import REPO_ROOT
from build.lib.text_alignment import align_tokens, looks_like_ocr_difference

# A word token for the cheap overlap pre-filter: 4+ ASCII letters. Short tokens
# (the, and, page numbers, single initials) are dropped -- they are shared by every
# page and add only noise. The pre-filter narrows candidates; the OCR-tolerant text
# aligner (build/lib/text_alignment) makes the final accept decision.
_WORD = re.compile(r"[a-z]{4,}")
# Ordered tokens for the text aligner: 2+ letters keeps word order signal that the
# set-based pre-filter discards (distinguishes adjacent same-article pages).
_TOKEN = re.compile(r"[a-z]{2,}")

# Tuning. The OCR-tolerant similarity gap between a correct match (~0.7-0.9) and a
# wrong one (<0.2) is wide; 0.40 leaves generous slack for cross-scan OCR noise.
DEFAULT_THRESHOLD = 0.40  # accept a match at/above this OCR-tolerant similarity
DEFAULT_WINDOW = 30  # how many canonical leaves ahead to search (skips plates/missing)
DEFAULT_BACK_SLACK = 3  # how far back to search (duplicate alt leaves, minor reorder)
TOP_K = 3  # Jaccard pre-filter shortlist re-scored by the text aligner
MIN_WORDS = 8  # an alt leaf with fewer real words is unalignable (blank/plate/figure)

# Global (non-monotone) fallback pass tuning (Task 1). The monotone pass leaves a
# few mid-body out-of-order / mis-bound leaves unmapped; the global pass searches the
# WHOLE reference for them behind a HIGHER floor than the monotone threshold, plus an
# independent primary cross-check, so a recovered match cannot be a weak coincidence.
GLOBAL_THRESHOLD = 0.55  # global-pass accept floor (well above the 0.40 monotone floor)
MIN_BODY_WORDS = 50  # an unmapped leaf with fewer real words is non-body (blank/plate)
PRIMARY_FLOOR = 0.20  # min word-overlap vs primary tesseract at the chosen leaf (PIPE-29)
# Primary-tesseract fallback (Task 1): where the ia-abbyy-v1 reference is MISSING a body
# leaf (a real gap in the canonical scan's ABBYY OCR), the alt page has no reference to
# match. The PRIMARY tesseract (a different engine) covers it; a strong word-set overlap
# against the primary IS the independent content verification, so it can match directly.
# The floor is set FAR above the cross-scan noise (~0.10) so a fallback match is unambiguous.
PRIMARY_MATCH_FLOOR = 0.40


def word_set(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def page_similarity(alt_tokens: list[str], ref_tokens: list[str]) -> float:
    """OCR-tolerant page similarity in [0,1] using the shared text aligner.

    Counts ``equal`` token runs plus ``replace`` runs that are mere OCR noise
    (digit/letter confusion, ligatures -- ``looks_like_ocr_difference``) as matches,
    normalised by the longer page. This folds cross-scan OCR variance into the score
    so a correctly-aligned page reads as a strong match despite engine differences.
    """
    if not alt_tokens or not ref_tokens:
        return 0.0
    matched = 0
    for op in align_tokens(ref_tokens, alt_tokens):
        c0, c1 = op.canonical_range
        w0, w1 = op.witness_range
        if op.tag == "equal":
            matched += c1 - c0
        elif op.tag == "replace" and looks_like_ocr_difference(
            " ".join(op.canonical_text), " ".join(op.witness_text)
        ):
            matched += min(c1 - c0, w1 - w0)
    return matched / max(len(alt_tokens), len(ref_tokens))


@dataclass(frozen=True)
class ContentPageAlignment:
    stem: str
    canonical_leaf_id: int | None
    best_jaccard: float
    runner_up_jaccard: float  # 2nd-best in the search band -- a tight gap flags ambiguity
    recovered: bool = False  # mapped by the global fallback pass, not the monotone pass
    recovered_via: str | None = None  # 'reference' | 'primary' when recovered
    classification: str | None = None  # unmapped only: 'non-body' | 'body-unrecoverable'
    words: int = 0  # real-word count (set-of 4+ letter tokens) -- drives classification


@dataclass(frozen=True)
class ContentAlignment:
    lineage: str
    volume: int
    reference: str
    pages: list[ContentPageAlignment]
    unmapped: list[str] = field(default_factory=list)

    @property
    def mapped_pages(self) -> int:
        return sum(1 for p in self.pages if p.canonical_leaf_id is not None)

    @property
    def mean_mapped_jaccard(self) -> float:
        js = [p.best_jaccard for p in self.pages if p.canonical_leaf_id is not None]
        return sum(js) / len(js) if js else 0.0

    @property
    def recovered_pages(self) -> int:
        return sum(1 for p in self.pages if p.recovered)

    @property
    def monotonic_violations(self) -> int:
        """Count of MONOTONE-mapped leaves whose canonical_leaf_id decreases vs the
        prior mapped leaf by more than the back-slack -- a real out-of-order assignment.
        Global-pass ``recovered`` pages are intentionally out-of-order (mis-bound leaves
        slotted back to their canonical home) and are excluded from the count."""
        viol = 0
        prev: int | None = None
        for p in self.pages:
            if p.canonical_leaf_id is None or p.recovered:
                continue
            if prev is not None and p.canonical_leaf_id < prev - DEFAULT_BACK_SLACK:
                viol += 1
            prev = max(prev, p.canonical_leaf_id) if prev is not None else p.canonical_leaf_id
        return viol

    @property
    def unmapped_classified(self) -> dict[str, dict]:
        """Per still-unmapped stem: its classification + the evidence behind it, so
        R6b / R-final can exempt non-body pages by category and surface the rest."""
        out: dict[str, dict] = {}
        for p in self.pages:
            if p.canonical_leaf_id is not None:
                continue
            out[p.stem] = {
                "class": p.classification or "non-body",
                "words": p.words,
                "best_score": round(p.best_jaccard, 4),
            }
        return out


def _rich_suffix(lineage: str) -> str:
    return re.sub(r"-v\d+$", "", lineage) + ".json"


def _ordered_rich_views(input_root: Path, lineage: str, volume: int) -> list[tuple[str, str]]:
    """(stem, text) for each rich sidecar of a lineage/volume, in stem order."""
    suffix = _rich_suffix(lineage)
    vol_dir = input_root / f"vol_{volume:02d}"
    out: list[tuple[str, str]] = []
    for path in sorted(vol_dir.glob(f"*.{suffix}")):
        stem = path.name.split(".")[0]
        d = json.loads(path.read_text(encoding="utf-8"))
        out.append((stem, d.get("text", "")))
    return out


def build_reference(
    input_root: Path,
    *,
    reference_lineage: str,
    volume: int,
) -> list[tuple[int, set[str], list[str]]]:
    """Reference = canonical leaf -> (wordset, ordered tokens), ordered by leaf.

    The reference lineage (``ia-abbyy-v1``) IS the canonical scan, so its stem maps to
    its canonical leaf by same-stem (valid only for the canonical scan). Built from the
    raw rich files so it does not depend on the S1 store being stamped.
    """
    manifest_path = input_root / f"vol_{volume:02d}.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_leaf: dict[int, list[str]] = {}
    for stem, text in _ordered_rich_views(input_root, reference_lineage, volume):
        leaf = canonical_leaf_id(stem, manifest)
        if leaf is None:
            continue
        # If two reference stems map to one leaf (1:N), concatenate their tokens.
        by_leaf.setdefault(leaf, []).extend(_tokens(text))
    return [(leaf, set(t for t in toks if len(t) >= 4), toks)
            for leaf, toks in sorted(by_leaf.items(), key=lambda t: t[0])]


def _best_match(
    aw: set[str],
    at: list[str],
    ref_words: list[set[str]],
    ref_tokens: list[list[str]],
    candidate_idx: range | list[int],
    *,
    top_k: int,
) -> tuple[float, int | None, float]:
    """Jaccard shortlist over ``candidate_idx`` then OCR-tolerant aligner re-score.

    Returns ``(best_score, best_idx_into_reference, second_best_score)``.
    """
    shortlist = sorted(
        (i for i in candidate_idx if ref_words[i]),
        key=lambda i: _jaccard(aw, ref_words[i]),
        reverse=True,
    )[:top_k]
    scored = sorted(
        ((page_similarity(at, ref_tokens[i]), i) for i in shortlist),
        reverse=True,
    )
    best_score, best_i = (scored[0] if scored else (0.0, None))
    second = scored[1][0] if len(scored) > 1 else 0.0
    return best_score, best_i, second


def align_by_content(
    alt_pages: list[tuple[str, str]],
    reference: list[tuple[int, set[str], list[str]]],
    *,
    lineage: str,
    volume: int,
    reference_lineage: str,
    threshold: float = DEFAULT_THRESHOLD,
    window: int = DEFAULT_WINDOW,
    back_slack: int = DEFAULT_BACK_SLACK,
    top_k: int = TOP_K,
    global_fallback: bool = False,
    primary_words: dict[int, set[str]] | None = None,
    global_threshold: float = GLOBAL_THRESHOLD,
    min_body_words: int = MIN_BODY_WORDS,
    primary_floor: float = PRIMARY_FLOOR,
    primary_match_floor: float = PRIMARY_MATCH_FLOOR,
) -> ContentAlignment:
    """Greedy monotone content alignment of alt leaves onto canonical leaves.

    Per alt leaf: a cheap word-set Jaccard shortlists the ``top_k`` candidate leaves in
    the monotone search band, then the OCR-tolerant text aligner re-scores the shortlist
    and the highest-scoring candidate is accepted if it clears ``threshold``. Word order
    in the aligner disambiguates adjacent same-article pages the set pre-filter ties.
    The band (``[last-back_slack, last+window]``) keeps the assignment monotone while
    absorbing duplicate (back-slack) and missing/plate (window) leaves; per-leaf scoring
    means each page is judged on its own content, not a volume-wide constant offset.

    When ``global_fallback`` is set, a SECOND pass runs over the leaves the monotone
    pass left unmapped: each mid-body leaf with enough words is searched against the
    WHOLE reference and recovered iff it clears ``global_threshold`` AND (where a
    ``primary_words`` map is supplied) overlaps the primary tesseract at the chosen leaf
    by ``primary_floor`` -- never stamping a leaf the primary contradicts (PIPE-29). Any
    leaf still unmapped after both passes is classified ``non-body`` (front/back band or
    too few words) or ``body-unrecoverable`` (mid-body, enough words, no clean home).
    """
    ref_words = [w for _leaf, w, _t in reference]
    ref_tokens = [t for _leaf, _w, t in reference]
    ref_leaves = [leaf for leaf, _w, _t in reference]
    n_ref = len(reference)

    pages: list[ContentPageAlignment] = []
    unmapped: list[str] = []
    last_idx = -1  # index into reference of the last accepted match
    word_sets: list[set[str]] = []  # per-page, parallel to ``pages`` (for the 2nd pass)
    token_lists: list[list[str]] = []

    for stem, text in alt_pages:
        aw = word_set(text)
        at = _tokens(text)
        word_sets.append(aw)
        token_lists.append(at)
        if len(aw) < MIN_WORDS:
            pages.append(ContentPageAlignment(stem, None, 0.0, 0.0, words=len(aw)))
            unmapped.append(stem)
            continue
        if last_idx < 0:
            candidates: range | list[int] = range(0, n_ref)  # not yet anchored
        else:
            candidates = range(max(0, last_idx - back_slack), min(n_ref, last_idx + 1 + window))
        best_score, best_i, second = _best_match(
            aw, at, ref_words, ref_tokens, candidates, top_k=top_k
        )
        if best_i is not None and best_score >= threshold:
            pages.append(
                ContentPageAlignment(stem, ref_leaves[best_i], best_score, second, words=len(aw))
            )
            last_idx = max(last_idx, best_i)
        else:
            pages.append(ContentPageAlignment(stem, None, best_score, second, words=len(aw)))
            unmapped.append(stem)

    pages, unmapped = _recover_and_classify(
        pages, unmapped, word_sets, token_lists, ref_words, ref_tokens, ref_leaves,
        global_fallback=global_fallback, primary_words=primary_words,
        global_threshold=global_threshold, min_body_words=min_body_words,
        primary_floor=primary_floor, primary_match_floor=primary_match_floor, top_k=top_k,
    )

    return ContentAlignment(
        lineage=lineage,
        volume=volume,
        reference=reference_lineage,
        pages=pages,
        unmapped=unmapped,
    )


def _recover_and_classify(
    pages: list[ContentPageAlignment],
    unmapped: list[str],
    word_sets: list[set[str]],
    token_lists: list[list[str]],
    ref_words: list[set[str]],
    ref_tokens: list[list[str]],
    ref_leaves: list[int],
    *,
    global_fallback: bool,
    primary_words: dict[int, set[str]] | None,
    global_threshold: float,
    min_body_words: int,
    primary_floor: float,
    primary_match_floor: float,
    top_k: int,
) -> tuple[list[ContentPageAlignment], list[str]]:
    """Global recovery of mid-body unmapped leaves, then classify what stays unmapped.

    ``mid-body`` = positioned between the first and last monotone-mapped leaf. Pages in
    the front/back band (before the first / after the last mapped leaf) are non-body by
    position; pages with < ``min_body_words`` are non-body (blank/plate). Only a mid-body
    page with enough words is a global-recovery candidate; if it cannot be recovered it
    is ``body-unrecoverable`` (a real residual worth surfacing).
    """
    mapped_pos = [i for i, p in enumerate(pages) if p.canonical_leaf_id is not None]
    if not mapped_pos:
        # No anchor at all (e.g. a wrong-volume cell): classify by word count only.
        out = []
        for p in pages:
            if p.canonical_leaf_id is None:
                cls = "non-body" if p.words < min_body_words else "body-unrecoverable"
                out.append(_with(p, classification=cls))
            else:
                out.append(p)
        return out, list(unmapped)

    first_m, last_m = mapped_pos[0], mapped_pos[-1]
    n_ref = len(ref_leaves)
    new_pages: list[ContentPageAlignment] = []
    new_unmapped: list[str] = []
    for pos, p in enumerate(pages):
        if p.canonical_leaf_id is not None:
            new_pages.append(p)
            continue
        mid_body = first_m < pos < last_m
        # Non-body by position (front/back band) or by emptiness (blank/plate).
        if not mid_body or p.words < min_body_words:
            new_pages.append(_with(p, classification="non-body"))
            new_unmapped.append(p.stem)
            continue
        if not global_fallback:
            new_pages.append(_with(p, classification="body-unrecoverable"))
            new_unmapped.append(p.stem)
            continue
        aw, at = word_sets[pos], token_lists[pos]
        best_score, best_i, second = _best_match(
            aw, at, ref_words, ref_tokens, range(0, n_ref), top_k=top_k
        )
        # First choice: recover against the ia-abbyy-v1 reference + primary cross-check.
        if best_i is not None and best_score >= global_threshold:
            leaf = ref_leaves[best_i]
            contradicted = False
            if primary_words is not None:
                pw = primary_words.get(leaf)
                if pw and _jaccard(aw, pw) < primary_floor:
                    contradicted = True  # PIPE-29: primary disagrees -> do not stamp
            if not contradicted:
                new_pages.append(_with(p, canonical_leaf_id=leaf, best_jaccard=best_score,
                                       runner_up_jaccard=second, recovered=True,
                                       recovered_via="reference"))
                continue
        # Fallback: the reference is missing this leaf (a gap in the canonical scan's
        # ABBYY OCR). Match directly against the PRIMARY tesseract, which covers it; a
        # high word-set overlap is the independent verification (PIPE-29-safe).
        pleaf, pscore = _best_primary_match(aw, primary_words)
        if pleaf is not None and pscore >= primary_match_floor:
            new_pages.append(_with(p, canonical_leaf_id=pleaf, best_jaccard=best_score,
                                   runner_up_jaccard=second, recovered=True,
                                   recovered_via="primary"))
            continue
        new_pages.append(_with(p, classification="body-unrecoverable",
                               best_jaccard=best_score, runner_up_jaccard=second))
        new_unmapped.append(p.stem)
    return new_pages, new_unmapped


def _best_primary_match(
    aw: set[str], primary_words: dict[int, set[str]] | None
) -> tuple[int | None, float]:
    """Leaf with the highest word-set Jaccard against the primary tesseract, and that
    Jaccard. Used only when the ia-abbyy-v1 reference is missing the leaf."""
    if not primary_words or not aw:
        return None, 0.0
    best_leaf, best = None, 0.0
    for leaf, pw in primary_words.items():
        j = _jaccard(aw, pw)
        if j > best:
            best, best_leaf = j, leaf
    return best_leaf, best


def _with(p: ContentPageAlignment, **changes) -> ContentPageAlignment:
    """Return a copy of a (frozen) page alignment with the given fields replaced."""
    return replace(p, **changes)


_PRIMARY_LINEAGE = "tesseract-py314-v1"
_S1_SIDECARS_ROOT = REPO_ROOT / "reports" / "s1-sidecars"


def load_primary_words(volume: int, s1_root: Path | None = None) -> dict[int, set[str]]:
    """Word-set per canonical leaf from the PRIMARY tesseract S1 store for a volume.

    Used as the independent cross-check for the global recovery pass: a recovered leaf
    must overlap the primary tesseract OCR at that leaf (the primary is a different
    engine from the ``ia-abbyy-v1`` reference, so agreement is non-circular). Returns
    ``{}`` when the volume has no primary cell (vols 6-9,12,13) -- the global pass then
    relies on the high floor alone for those volumes.
    """
    root = Path(s1_root) if s1_root is not None else _S1_SIDECARS_ROOT
    manifest_path = root / _PRIMARY_LINEAGE / f"vol_{volume:02d}" / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out: dict[int, set[str]] = {}
    for ref in manifest.get("pages", []):
        leaf = ref.get("canonical_leaf_id")
        if not isinstance(leaf, int):
            continue
        sp = ref.get("sidecar_page_path")
        if not sp:
            continue
        spath = (REPO_ROOT / sp) if not Path(sp).is_absolute() else Path(sp)
        try:
            rec = json.loads(spath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        toks = [
            w.get("source_raw", "")
            for b in rec.get("blocks", [])
            for ln in b.get("lines", [])
            for w in ln.get("words", [])
        ]
        out[leaf] = word_set(" ".join(toks))
    return out


def align_lineage_volume_by_content(
    input_root: Path,
    *,
    lineage: str,
    volume: int,
    reference_lineage: str = "ia-abbyy-v1",
    threshold: float = DEFAULT_THRESHOLD,
    window: int = DEFAULT_WINDOW,
    back_slack: int = DEFAULT_BACK_SLACK,
    global_fallback: bool = True,
    s1_root: Path | None = None,
) -> ContentAlignment:
    """File-driven wrapper: read reference + alt rich files and align by content.

    The global recovery pass (Task 1) is ON by default here -- this is the production
    leafmap path. The primary tesseract cross-check is loaded automatically for any
    volume that has a primary cell; volumes without one fall back to the high floor.
    """
    input_root = Path(input_root)
    reference = build_reference(
        input_root, reference_lineage=reference_lineage, volume=volume
    )
    alt_pages = _ordered_rich_views(input_root, lineage, volume)
    primary_words = load_primary_words(volume, s1_root) if global_fallback else None
    return align_by_content(
        alt_pages,
        reference,
        lineage=lineage,
        volume=volume,
        reference_lineage=reference_lineage,
        threshold=threshold,
        window=window,
        back_slack=back_slack,
        global_fallback=global_fallback,
        primary_words=primary_words,
    )


# --- leafmap persistence -------------------------------------------------------
# The content alignment is the authoritative stem -> canonical leaf map for an
# alternate scan; it is persisted so the normalizer consumes it (and never falls
# back to the wrong same-stem assumption) and so R6b can read the unmapped set.

def leafmap_path(input_root: Path, lineage: str, volume: int) -> Path:
    return Path(input_root) / f"vol_{volume:02d}.{lineage}.leafmap.json"


def write_leafmap(input_root: Path, alignment: ContentAlignment) -> Path:
    """Persist the content alignment as a stem -> canonical_leaf_id map + provenance.

    Only mapped stems are written under ``stem_to_leaf``; every unmapped stem is
    listed under ``unmapped`` so a consumer can tell "not in scope" from "absent".
    """
    out = {
        "lineage": alignment.lineage,
        "volume": alignment.volume,
        "reference_lineage": alignment.reference,
        "method": "content-jaccard-shortlist+text-aligner-monotone",
        "threshold": DEFAULT_THRESHOLD,
        "mapped_pages": alignment.mapped_pages,
        "recovered_pages": alignment.recovered_pages,
        "total_pages": len(alignment.pages),
        "mean_mapped_score": round(alignment.mean_mapped_jaccard, 4),
        "monotonic_violations": alignment.monotonic_violations,
        "stem_to_leaf": {
            p.stem: p.canonical_leaf_id
            for p in alignment.pages
            if p.canonical_leaf_id is not None
        },
        "recovered_via": {
            "reference": sum(1 for p in alignment.pages if p.recovered_via == "reference"),
            "primary": sum(1 for p in alignment.pages if p.recovered_via == "primary"),
        },
        "recovered_stems": [p.stem for p in alignment.pages if p.recovered],
        "unmapped": list(alignment.unmapped),
        # Task 4: every still-unmapped stem labelled non-body | body-unrecoverable so
        # R6b / R-final can exempt non-body by category and surface the rest.
        "unmapped_classified": alignment.unmapped_classified,
    }
    path = leafmap_path(input_root, alignment.lineage, alignment.volume)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_leafmap(input_root: Path, lineage: str, volume: int) -> dict[str, int] | None:
    """Return the persisted stem -> canonical_leaf_id map, or None if absent.

    A present leafmap is AUTHORITATIVE for an alternate scan: stems absent from it
    are unmapped by design (front/back matter, plates, scan defects), never same-stem.
    """
    path = leafmap_path(input_root, lineage, volume)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {stem: int(leaf) for stem, leaf in data.get("stem_to_leaf", {}).items()}


# --- CLI -----------------------------------------------------------------------


DEFAULT_INPUT_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"


def _alt_volumes(input_root: Path, lineage: str) -> list[int]:
    """Volumes of a lineage that have rich sidecars on disk."""
    suffix = _rich_suffix(lineage)
    found = []
    for vol in range(1, 14):
        vol_dir = input_root / f"vol_{vol:02d}"
        if vol_dir.exists() and any(vol_dir.glob(f"*.{suffix}")):
            found.append(vol)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lineage", required=True, help="alternate lineage id")
    parser.add_argument("--volume", type=int, default=None, help="single volume; omit for all")
    parser.add_argument("--reference-lineage", default="ia-abbyy-v1")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--write", action="store_true", help="persist the leafmap (default dry-run)")
    args = parser.parse_args(argv)

    vols = [args.volume] if args.volume is not None else _alt_volumes(args.input_root, args.lineage)
    rows = []
    for vol in vols:
        al = align_lineage_volume_by_content(
            args.input_root, lineage=args.lineage, volume=vol,
            reference_lineage=args.reference_lineage,
        )
        total = len(al.pages)
        rate = al.mapped_pages / total * 100 if total else 0.0
        action = "WROTE" if args.write else "dry-run"
        if args.write:
            write_leafmap(args.input_root, al)
        cls = al.unmapped_classified
        nonbody = sum(1 for v in cls.values() if v["class"] == "non-body")
        unrec = sum(1 for v in cls.values() if v["class"] == "body-unrecoverable")
        rows.append(
            f"{args.lineage} vol_{vol:02d}: mapped {al.mapped_pages}/{total} ({rate:.1f}%) "
            f"meanScore={al.mean_mapped_jaccard:.3f} mono_viol={al.monotonic_violations} "
            f"recovered={al.recovered_pages} unmapped={len(al.unmapped)} "
            f"(non-body={nonbody} body-unrec={unrec}) [{action}]"
        )
    sys.stdout.buffer.write(("\n".join(rows) + "\n").encode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
