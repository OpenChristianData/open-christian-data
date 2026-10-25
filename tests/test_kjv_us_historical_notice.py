"""Focused KJV complete-license notice and safe Markdown regression tests."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.public_allowlist import _safe_notice_markdown, render_dataset_card


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ("library/works/kjv/forms/kjv-english/editions/"
              "kjv-retained-electronic-witness/acceptance.json")
SOURCE_NOTE = "sources/bible-kjv-current/kjv/README.source.md"
DATA_NOTE = "data/bible/kjv/README.md"
SOURCE_SHA = "436cc56f5d214d12d5049193d750c282566dac6070d2a6387b90ef69c9d6ef6b"
DATA_SHA = "f5e57c19f2d7369f6a2700647e568a89edfa0621bfe5f37227e81482fa3582a5"
GPL_SHA = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"


def test_actual_full_gpl_notice_and_dataset_card() -> None:
    source = (ROOT / SOURCE_NOTE).read_bytes()
    data = (ROOT / DATA_NOTE).read_bytes()
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA
    assert hashlib.sha256(data).hexdigest() == DATA_SHA
    license_text = data.decode("utf-8").split("```text\n", 1)[1].rsplit("```\n", 1)[0]
    assert hashlib.sha256(license_text.encode("utf-8")).hexdigest() == GPL_SHA
    assert _safe_notice_markdown(data.decode("utf-8"))
    selected = {
        "item_id": "kjv--kjv-retained-electronic-witness", "category": "bible",
        "acceptance_path": ACCEPTANCE,
        "public_notices": [{"source_path": SOURCE_NOTE, "source_sha256": SOURCE_SHA,
                            "notice_path": DATA_NOTE, "notice_sha256": DATA_SHA}],
    }
    notices = notice_texts_for_item(ROOT, selected, ROOT / ACCEPTANCE)
    assert notices == [data.decode("utf-8")]
    card = render_dataset_card([
        {"category": "bible", "path": "public/data/bible/train.jsonl", "row_count": 31102}
    ], notices=notices)
    assert card.count(license_text) == 1


@pytest.mark.parametrize("notice,expected", [
    ("Ordinary historical notice.\n", True),
    ("```text\n<https://fsf.org/>\n```\n", True),
    ("<https://fsf.org/>\n", False),
    ("<script>alert(1)</script>\n", False),
    ("```text\n<license>\n", False),
    ("```text\n<license>\n```\n<script>x</script>\n", False),
    ("```text\n<license>\n````\n<script>x</script>\n", False),
    ("```text\n<license>\n   ```\n<script>x</script>\n", False),
    ("```text\nraw/private/source.xml\n```\n", False),
    ("```text\n" + "a" * 64 + "\n```\n", False),
    ("```text\n" + base64.b64encode(b"raw/private/source.xml").decode("ascii") + "\n```\n", False),
])
def test_literal_fence_keeps_all_private_scans(notice: str, expected: bool) -> None:
    assert _safe_notice_markdown(notice) is expected
