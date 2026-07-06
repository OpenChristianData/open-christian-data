"""Sequence alignment helpers for witness and OCR comparison tools."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal, TypeVar


AlignmentTag = Literal["equal", "replace", "delete", "insert"]
Range = tuple[int, int]
PUNCTUATION_TRANSLATION = str.maketrans("", "", string.punctuation)


@dataclass(frozen=True)
class BlockOp:
    tag: AlignmentTag
    canonical_range: Range
    witness_range: Range
    canonical_text: tuple[str, ...]
    witness_text: tuple[str, ...]


@dataclass(frozen=True)
class TokenOp:
    tag: AlignmentTag
    canonical_range: Range
    witness_range: Range
    canonical_text: tuple[str, ...]
    witness_text: tuple[str, ...]


OpT = TypeVar("OpT", BlockOp, TokenOp)


def align_blocks(canonical_blocks: list[str], witness_blocks: list[str]) -> list[BlockOp]:
    """Return opcode-style block alignment records."""
    matcher = SequenceMatcher(None, canonical_blocks, witness_blocks, autojunk=False)
    ops = [
        BlockOp(
            tag=tag,
            canonical_range=(canonical_start, canonical_end),
            witness_range=(witness_start, witness_end),
            canonical_text=tuple(canonical_blocks[canonical_start:canonical_end]),
            witness_text=tuple(witness_blocks[witness_start:witness_end]),
        )
        for tag, canonical_start, canonical_end, witness_start, witness_end in matcher.get_opcodes()
    ]
    return collapse_runs(ops)


def align_tokens(canonical_tokens: list[str], witness_tokens: list[str]) -> list[TokenOp]:
    """Return opcode-style token alignment records."""
    matcher = SequenceMatcher(None, canonical_tokens, witness_tokens, autojunk=False)
    ops = [
        TokenOp(
            tag=tag,
            canonical_range=(canonical_start, canonical_end),
            witness_range=(witness_start, witness_end),
            canonical_text=tuple(canonical_tokens[canonical_start:canonical_end]),
            witness_text=tuple(witness_tokens[witness_start:witness_end]),
        )
        for tag, canonical_start, canonical_end, witness_start, witness_end in matcher.get_opcodes()
    ]
    return collapse_runs(ops)


def collapse_runs(ops: list[OpT]) -> list[OpT]:
    """Merge adjacent equal or replace operations with contiguous ranges."""
    collapsed: list[OpT] = []
    for op in ops:
        if collapsed and _can_merge(collapsed[-1], op):
            collapsed[-1] = _merge_ops(collapsed[-1], op)
        else:
            collapsed.append(op)
    return collapsed


def looks_like_ocr_difference(canonical_text: str, witness_text: str) -> bool:
    """Return True when a replace looks like OCR character noise."""
    canonical_norm = _normalise_for_ocr(canonical_text)
    witness_norm = _normalise_for_ocr(witness_text)
    if not canonical_norm or not witness_norm or canonical_norm == witness_norm:
        return False

    ratio = SequenceMatcher(None, canonical_norm, witness_norm, autojunk=False).ratio()
    canonical_ocr = _ocr_skeleton(canonical_norm)
    witness_ocr = _ocr_skeleton(witness_norm)
    skeleton_ratio = SequenceMatcher(None, canonical_ocr, witness_ocr, autojunk=False).ratio()

    if canonical_ocr == witness_ocr and ratio >= 0.70:
        return True
    return ratio >= 0.75 and skeleton_ratio >= min(0.98, ratio + 0.08)


def _can_merge(left: OpT, right: OpT) -> bool:
    if type(left) is not type(right):
        return False
    if left.tag != right.tag or left.tag not in {"equal", "replace"}:
        return False
    return left.canonical_range[1] == right.canonical_range[0] and left.witness_range[1] == right.witness_range[0]


def _merge_ops(left: OpT, right: OpT) -> OpT:
    op_type = type(left)
    return op_type(
        tag=left.tag,
        canonical_range=(left.canonical_range[0], right.canonical_range[1]),
        witness_range=(left.witness_range[0], right.witness_range[1]),
        canonical_text=left.canonical_text + right.canonical_text,
        witness_text=left.witness_text + right.witness_text,
    )


def _normalise_for_ocr(text: str) -> str:
    text = text.replace("\u00ad", "")
    for source, replacement in {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "st",
        "\ufb06": "st",
    }.items():
        text = text.replace(source, replacement)
    return re.sub(r"\s+", " ", text).strip().lower().translate(PUNCTUATION_TRANSLATION)


def _ocr_skeleton(text: str) -> str:
    # Order is intentional: each OCR skeleton substitution runs on the output
    # of the previous one, so composed OCR confusions collapse predictably.
    replacements = {
        "0": "o",
        "1": "l",
        "2": "z",
        "3": "e",
        "4": "a",
        "5": "s",
        "6": "g",
        "7": "t",
        "8": "b",
        "9": "g",
        "i": "l",
        "rn": "m",
        "vv": "w",
        "cl": "d",
    }
    skeleton = text
    for source, replacement in replacements.items():
        skeleton = skeleton.replace(source, replacement)
    return skeleton
