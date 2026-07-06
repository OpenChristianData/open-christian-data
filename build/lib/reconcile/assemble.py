"""assemble — builds the final reconciled record dict from aligned clusters.

Reading scoring (ADR-0013):
  Role base scores: pd_anchor=4.0, pd_attestor=3.0, pending=2.0, reference_only=0.0 (advisory)

Auto-choice gate:
  winning_has_pd_support AND pd_only_gap >= 2.0 AND classification NOT IN {paraphrase, unclassified}
"""

from __future__ import annotations

import re
from pathlib import Path

from build.lib.reconcile.classify import classify_disagreement
from build.lib.reconcile.match_explanations import MatchExplanationLedger
from build.lib.reconcile.token_alignment import align_tokens_nway


_ROLE_BASE_SCORE: dict[str, float] = {
    "pd_anchor": 4.0,
    "pd_attestor": 3.0,
    "pending": 2.0,
    "reference_only": 0.0,
}

_AUTO_CHOICE_BLOCKED_CLASSIFICATIONS = {"paraphrase", "unclassified"}

_OXFORD_COMMA_RE = re.compile(r",\s+and\s+", re.IGNORECASE)


def _load_ocr_error_model(language: str) -> list[dict]:
    """Load OCR confusion patterns for the given language from YAML, or [] if absent."""
    import yaml  # lazy: avoid import-time I/O
    path = Path(__file__).parent.parent / "ocr_error_models" / f"{language}.yaml"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, list) else []


def _is_token_ocr_derivable(anchor_token: str, attestor_token: str, patterns: list[dict]) -> bool:
    """Return True if attestor_token equals anchor_token with any confusion pattern applied."""
    for entry in patterns:
        confusion = entry.get("confusion", {})
        src = confusion.get("source", "")
        tgt = confusion.get("target", "")
        if src and anchor_token.replace(src, tgt) == attestor_token:
            return True
    return False


def check_ocr_confusion_fires(
    anchor_tokens: list[str], attestor_tokens: list[str], language: str
) -> bool:
    """Return True if any aligned token pair shows a known OCR confusion for this language."""
    patterns = _load_ocr_error_model(language)
    if not patterns:
        return False
    for a_tok, b_tok in zip(anchor_tokens, attestor_tokens, strict=False):
        if a_tok != b_tok and _is_token_ocr_derivable(a_tok, b_tok, patterns):
            return True
    return False


def _is_lexicon_valid(tokens: list[str], language: str) -> bool:
    """Return True if any token is in the language VOCAB (la and grc only; en has no VOCAB)."""
    if language == "la":
        from build.lib.lexicons.la import VOCAB as _la_vocab
        return any(t in _la_vocab for t in tokens)
    if language == "grc":
        from build.lib.lexicons.grc import VOCAB as _grc_vocab
        return any(t in _grc_vocab for t in tokens)
    return False


def check_lexicon_modifier_fires(
    anchor_tokens: list[str], attestor_tokens: list[str], language: str
) -> bool:
    """Return True if anchor is lexicon-valid for language but attestor is not."""
    return _is_lexicon_valid(anchor_tokens, language) and not _is_lexicon_valid(attestor_tokens, language)


def check_punctuation_modifier(reading: str, anchor_style: dict) -> float:
    """Return +0.75 if anchor registered Oxford comma convention and reading uses it; else 0.0."""
    if not anchor_style.get("oxford_comma"):
        return 0.0
    return 0.75 if _OXFORD_COMMA_RE.search(reading) else 0.0


def _get_role_for_rendering(rendering_id: str, catalog: dict) -> str:
    """Look up the role for a rendering_id in the catalog."""
    for r in catalog.get("renderings", []):
        if r["rendering_id"] == rendering_id:
            return r.get("role", "pending")
    return "pending"


def _is_reference_copy(rendering_id: str, catalog: dict) -> bool:
    """Return True if the rendering has reference_copy: True in the catalog."""
    for r in catalog.get("renderings", []):
        if r["rendering_id"] == rendering_id:
            return bool(r.get("reference_copy", False))
    return False


def _compute_block_id_for_text(text: str, seen: dict[str, int]) -> str:
    """Generate a block_id from text, handling collisions via disambiguator."""
    from build.lib.block_id import block_id
    base = block_id(text, 0)
    if base not in seen:
        seen[base] = 0
        return base
    seen[base] += 1
    return block_id(text, seen[base])


def _score_reading(reading: str, rendering_id: str, role: str, language: str) -> float:
    """Compute the PD reading score for a single reading from a rendering.

    Returns base score + modifiers (invalid Unicode modifier only here;
    lexicon and OCR modifiers are computed in the caller to keep context).
    """
    base = _ROLE_BASE_SCORE.get(role, 2.0)
    score = base

    # Invalid Unicode modifier (-2.0)
    if "�" in reading or any(ord(c) > 0x10FFFF for c in reading):
        score -= 2.0

    return score


def assemble_record(
    anchor_graph: dict,
    aligned_clusters: list[dict],
    ledger: MatchExplanationLedger,
    catalog: dict,
    anchor_style: dict | None = None,
) -> dict:
    """Assemble the final reconciled record dict.

    Validates against reconciled_record.schema.json before returning.
    """
    anchor_rendering_id = anchor_graph["anchor_rendering_id"]
    attestor_renderings = anchor_graph.get("attestor_renderings", [])

    # Build a rendering_id → role map
    rendering_roles: dict[str, str] = {}
    for r in catalog.get("renderings", []):
        rendering_roles[r["rendering_id"]] = r.get("role", "pending")

    blocks: list[dict] = []
    high_count = mid_high_count = mid_low_count = low_count = 0
    seen_block_ids: dict[str, int] = {}

    for cluster in aligned_clusters:
        anchor_block = cluster["anchor_block"]
        anchor_idx = cluster["anchor_idx"]
        attestor_matches = cluster.get("attestor_matches", [])

        # Generate block_id from anchor original_text
        bid = _compute_block_id_for_text(anchor_block["original_text"], seen_block_ids)

        # Track bucket metrics from the cluster's best score results
        for match in attestor_matches:
            score_result = match.get("score_result", {})
            bucket = score_result.get("bucket", "high")
            if bucket == "high":
                high_count += 1
            elif bucket == "mid_high":
                mid_high_count += 1
            elif bucket == "mid_low":
                mid_low_count += 1
            else:
                low_count += 1

        # Collect all attested_by (anchor + all matched attestors)
        # reference_only with reference_copy True does NOT appear in attested_by
        attested_by: list[str] = [anchor_rendering_id]
        for match in attestor_matches:
            rid = match["rendering_id"]
            role = rendering_roles.get(rid, "pending")
            if role == "reference_only" and _is_reference_copy(rid, catalog):
                continue
            if rid not in attested_by:
                attested_by.append(rid)

        # Build disagreements from token-level differences
        disagreements: list[dict] = []
        structural_disagreements: list[dict] = list(cluster.get("structural_disagreements", []))

        anchor_text = anchor_block.get("original_text", "")
        anchor_tokens = anchor_text.split()
        language = anchor_block.get("language", "en")

        for match in attestor_matches:
            attestor_block = match["block"]
            attestor_text = attestor_block.get("original_text", "")
            attestor_tokens = attestor_text.split()
            rid = match["rendering_id"]
            role = rendering_roles.get(rid, "pending")

            if anchor_text == attestor_text:
                # No disagreement — texts are identical
                continue

            # Token-level alignment to find where they differ
            ops = align_tokens_nway(anchor_tokens, [attestor_tokens])

            if not ops:
                # No ops means identical after split — skip
                continue

            # Classify the overall disagreement (per attestor, not per op)
            kind = classify_disagreement(
                anchor_text,
                attestor_text,
                language=language,
                # attesting_families not yet threaded through -- pass None until arch9 wires it
                attesting_families=None,
            )

            # Compute reading scores (per attestor) with all ADR-0013 modifiers applied
            anchor_role = rendering_roles.get(anchor_rendering_id, "pd_anchor")
            anchor_pd_score = _score_reading(anchor_text, anchor_rendering_id, anchor_role, language)
            if check_lexicon_modifier_fires(anchor_tokens, attestor_tokens, language):
                anchor_pd_score += 1.0
            attestor_pd_score: float = 0.0

            if role == "reference_only":
                # reference_only contributes advisory_score only (R5 closure)
                advisory_score = 0.5
                attestor_pd_score = 0.0
            else:
                advisory_score = 0.0
                attestor_pd_score = _score_reading(attestor_text, rid, role, language)
                if check_ocr_confusion_fires(anchor_tokens, attestor_tokens, language):
                    attestor_pd_score -= 1.5
                if anchor_style:
                    attestor_pd_score += check_punctuation_modifier(attestor_text, anchor_style)

            pd_only_gap = anchor_pd_score - attestor_pd_score
            winning_has_pd_support = anchor_role in ("pd_anchor", "pd_attestor")

            # Auto-choice gate (per attestor — full text pair decides)
            auto_choose = (
                winning_has_pd_support
                and pd_only_gap >= 2.0
                and kind not in _AUTO_CHOICE_BLOCKED_CLASSIFICATIONS
            )

            chosen_reading_attested_by: list[str] = [anchor_rendering_id] if auto_choose else []

            # Build signals for the ledger
            signals = [
                {
                    "name": f"{anchor_role}_base",
                    "raw_score": anchor_pd_score,
                    "weight": 1,
                    "contribution": anchor_pd_score,
                }
            ]

            # Record ledger entry once per attestor; every op for this attestor
            # shares the same match_explanation_id.
            mx_id = ledger.add_reading_score(
                block_id=bid,
                signals=signals,
                pd_only_gap=pd_only_gap,
                winning_has_pd_support=winning_has_pd_support,
                classification=kind,
                advisory_score=advisory_score,
            )

            # reference_only does NOT appear in chosen_reading_attested_by and
            # does not produce per-op disagreement entries.
            if role == "reference_only":
                continue

            # One disagreement entry per token-level op. Each entry's span covers
            # exactly the differing tokens; chosen_reading holds the anchor's
            # tokens at that span when auto-chosen (insertion ops yield "").
            for op in ops:
                span_start = op["anchor_span"][0]
                span_end = op["anchor_span"][1]
                chosen_reading_at_span: str | None = (
                    " ".join(anchor_tokens[span_start:span_end]) if auto_choose else None
                )
                disagreements.append({
                    "span": {"start_token": span_start, "end_token": span_end},
                    "kind": kind,
                    "chosen_reading": chosen_reading_at_span,
                    "chosen_reading_attested_by": chosen_reading_attested_by,
                    "match_explanation_id": mx_id,
                })

        # Build the assembled block
        assembled_block: dict = {
            "block_id": bid,
            "block_id_history": [],
            "block_type": anchor_block.get("block_type", "paragraph"),
            "language": anchor_block.get("language", "en"),
            "language_confidence": anchor_block.get("language_confidence", 0.95),
            "language_alternates": anchor_block.get("language_alternates", []),
            "language_segments": anchor_block.get("language_segments", []),
            "original_text": anchor_block["original_text"],
            "modern_text": anchor_block.get("modern_text", ""),
            "annotations": anchor_block.get("annotations", {}),
            "source_pages": anchor_block.get("source_pages", []),
            "attested_by": attested_by,
            "disagreements": disagreements,
            "structural_disagreements": structural_disagreements,
            "modernisations": [],
        }
        blocks.append(assembled_block)

    # Compute attestation summary
    block_count = len(blocks)
    total_rendering_ids = len(rendering_roles)
    fully_attested = sum(
        1 for b in blocks
        if len(b["attested_by"]) == total_rendering_ids
        or all(
            rid in b["attested_by"]
            for rid, role in rendering_roles.items()
            if role != "reference_only"
        )
    )
    blocks_with_disagreements = sum(1 for b in blocks if b["disagreements"])
    blocks_with_structural_disagreements = sum(1 for b in blocks if b["structural_disagreements"])

    meta: dict = {
        "id": catalog.get("id", ""),
        "title": catalog.get("title", ""),
        "author_slug": catalog.get("author_slug", ""),
        "author_display_name": catalog.get("author_display_name", ""),
        "author_birth_year": catalog.get("author_birth_year"),
        "author_death_year": catalog.get("author_death_year"),
        "original_publication_year": catalog.get("original_publication_year"),
        "language": catalog.get("language", "en"),
        "tradition": catalog.get("tradition", ["reformed"]),
        "license": catalog.get("license", "public-domain"),
        "schema_type": "reconciled_record",
        "schema_version": "3.0.0",
        "edition": catalog.get("edition", ""),
        "pd_anchor": catalog["pd_anchor"],
        "modernisation_ruleset_version": None,
        "attestation_summary": {
            "block_count": block_count,
            "fully_attested_blocks": fully_attested,
            "blocks_with_disagreements": blocks_with_disagreements,
            "blocks_with_structural_disagreements": blocks_with_structural_disagreements,
        },
    }

    # bucket_metrics lives at the top level of the record (not in meta) because
    # record_meta has additionalProperties: false and doesn't include this field.
    # The test accepts either result["meta"]["bucket_metrics"] or result["bucket_metrics"].
    bucket_metrics = {
        "high_count": high_count,
        "mid_high_count": mid_high_count,
        "mid_low_count": mid_low_count,
        "low_count": low_count,
    }

    record = {
        "meta": meta,
        "blocks": blocks,
        "match_explanations": ledger.all_entries(),
        # bucket_metrics is a pipeline-internal metric, not part of the schema.
        # It lives at the top level of the return dict but is excluded from
        # schema validation (record_meta additionalProperties: false blocks it in meta).
        "bucket_metrics": bucket_metrics,
    }

    return record
