"""Focused correspondence checks for the accepted Smyrnaeans public rows."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from build.tools import project_pg77576_ignatius_smyrnaeans as projection
from ocd_kernel.release.notices import notice_texts_for_item


def test_actual_master_projects_both_readings_and_structured_endnotes():
    prepared = projection.prepare()
    rows = prepared["rows"]

    for credit in (projection._source_credit(), projection._source_note()):
        credit_text = credit.decode("utf-8")
        assert "Roberts and James Donaldson as editors" in credit_text or "Roberts and James Donaldson as" in credit_text
        assert "translated by the Editors" in credit_text
        assert "does not identify which editor translated this epistle" in credit_text or (
            "does not say which editor translated this epistle" in credit_text
        )

    assert prepared["errors"] == []
    assert len(rows) == 2
    assert [row["locator"]["text_part"] for row in rows] == ["body", "back"]
    assert rows[0]["text"].count("Shorter.") == 14
    assert rows[0]["text"].count("Longer.") == 14
    assert "Chap. i.—Thanks to God for your faith." in rows[0]["text"]
    assert "Chap.Chapter" not in rows[0]["text"]
    assert len(rows[0]["source_references"]) == 176
    assert rows[1]["text"] == ""
    assert len(rows[1]["source_references"]) == 88
    assert prepared["note_numbers"] == [str(number) for number in range(1230, 1318)]

    root = prepared["root"]
    notice_binding = {
        "source_path": projection.SOURCE_NOTE.as_posix(),
        "source_sha256": sha256((root / projection.SOURCE_NOTE).read_bytes()).hexdigest(),
        "notice_path": projection.PUBLIC_NOTICE.as_posix(),
        "notice_sha256": sha256((root / projection.PUBLIC_NOTICE).read_bytes()).hexdigest(),
    }
    visible = notice_texts_for_item(
        root,
        {"work_id": projection.WORK_ID, "public_notices": [notice_binding]},
        root / projection.ACCEPTANCE,
    )
    assert len(visible) == 1
    assert "[Project Gutenberg™ License](https://www.gutenberg.org/policy/license.html)" in visible[0]
    assert "[Project Gutenberg eBook 77576](https://www.gutenberg.org/ebooks/77576)" in visible[0]

    corrupted = deepcopy(rows)
    corrupted[0]["text"] += " altered"
    assert projection.verify_rows(corrupted, prepared["native_receipt"], root=prepared["root"])
