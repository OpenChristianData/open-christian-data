import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.text_alignment import (  # noqa: E402
    BlockOp,
    align_blocks,
    align_tokens,
    collapse_runs,
    looks_like_ocr_difference,
)


def _blocks(count: int = 10) -> list[str]:
    return [f"Paragraph {index} has stable representative commentary text." for index in range(count)]


def test_align_blocks_identical_inputs_are_equal_only():
    ops = align_blocks(_blocks(), _blocks())

    assert [op.tag for op in ops] == ["equal"]
    assert ops[0].canonical_range == (0, 10)
    assert ops[0].witness_range == (0, 10)


def test_align_blocks_single_deleted_paragraph_does_not_cascade():
    canonical = _blocks()
    witness = canonical[:5] + canonical[6:]

    ops = align_blocks(canonical, witness)

    delete_ops = [op for op in ops if op.tag == "delete"]
    equal_block_count = sum(op.canonical_range[1] - op.canonical_range[0] for op in ops if op.tag == "equal")
    assert len(delete_ops) == 1
    assert delete_ops[0].canonical_range == (5, 6)
    assert equal_block_count == 9
    assert {op.tag for op in ops} == {"equal", "delete"}


def test_align_blocks_single_inserted_paragraph_does_not_cascade():
    canonical = _blocks()
    witness = canonical[:3] + ["Inserted witness paragraph."] + canonical[3:]

    ops = align_blocks(canonical, witness)

    insert_ops = [op for op in ops if op.tag == "insert"]
    assert len(insert_ops) == 1
    assert insert_ops[0].canonical_range == (3, 3)
    assert insert_ops[0].witness_range == (3, 4)
    assert {op.tag for op in ops} == {"equal", "insert"}


def test_align_blocks_single_reworded_paragraph_is_one_replace():
    canonical = _blocks()
    witness = canonical.copy()
    witness[5] = "Paragraph five has deliberately reworded commentary text."

    ops = align_blocks(canonical, witness)

    replace_ops = [op for op in ops if op.tag == "replace"]
    assert len(replace_ops) == 1
    assert replace_ops[0].canonical_range == (5, 6)
    assert replace_ops[0].witness_range == (5, 6)
    assert {op.tag for op in ops} == {"equal", "replace"}


def test_align_tokens_single_deleted_token_does_not_cascade():
    canonical = "Grace mercy and peace be multiplied".split()
    witness = "Grace and peace be multiplied".split()

    ops = align_tokens(canonical, witness)

    delete_ops = [op for op in ops if op.tag == "delete"]
    assert len(delete_ops) == 1
    assert delete_ops[0].canonical_text == ("mercy",)
    assert {op.tag for op in ops} == {"equal", "delete"}


def test_looks_like_ocr_difference_marks_digit_letter_swaps_only():
    assert looks_like_ocr_difference("THE0L0GY", "THEOLOGY") is True
    assert looks_like_ocr_difference("the cat", "a dog") is False


def test_collapse_runs_merges_adjacent_equal_blocks():
    ops = [
        BlockOp(
            tag="equal",
            canonical_range=(0, 1),
            witness_range=(0, 1),
            canonical_text=("A",),
            witness_text=("A",),
        ),
        BlockOp(
            tag="equal",
            canonical_range=(1, 2),
            witness_range=(1, 2),
            canonical_text=("B",),
            witness_text=("B",),
        ),
    ]

    collapsed = collapse_runs(ops)

    assert collapsed == [
        BlockOp(
            tag="equal",
            canonical_range=(0, 2),
            witness_range=(0, 2),
            canonical_text=("A", "B"),
            witness_text=("A", "B"),
        )
    ]
