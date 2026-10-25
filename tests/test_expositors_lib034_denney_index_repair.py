"""Source and accepted-master semantics for Denney's two index corrections."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib034_readable_denney_index_v2_oracle import check
from build.tools.stage_expositors_lib034_denney_index_repair import ROWS, _source_only_delta
from ocd_kernel.tei.install_accepted import _files, _io_path


CANDIDATES = Path("D:/Library/Open Christian Data/candidate-reviews/expositors-lib034-denney-index-v2-candidates-20260928-v1")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/expositors-lib034-denney-index-repair-stage-20260928-v3")
WORK = Path("library/works/expositors-bible--james-denney")
NS = "{http://www.tei-c.org/ns/1.0}"


@pytest.mark.parametrize("member", ROWS)
def test_source_oracle_and_two_node_delta(member: str) -> None:
    detail = ROWS[member]
    result = check(member, CANDIDATES / member, formal=True)
    assert (result["source_elements"], result["source_comments"], result["native_rows"]) == (
        detail["elements"], detail["comments"], detail["native_rows"])
    old = _io_path(WORK / "integration" / (member + "-readable-electronic-v1")
                   / "inputs/package/content.tei.xml").read_bytes()
    new = (CANDIDATES / member / "content.tei.xml").read_bytes()
    assert [row["tei_id"] for row in _source_only_delta(old, new, detail["index_ids"])] == detail["index_ids"]


@pytest.mark.parametrize("member", ROWS)
def test_source_oracle_rejects_index_as_quote(member: str, tmp_path: Path) -> None:
    for name in ("content.tei.xml", "source-accountability.json"):
        shutil.copy2(CANDIDATES / member / name, tmp_path / name)
    path = tmp_path / "content.tei.xml"
    tree = etree.parse(str(path))
    index = tree.find(f".//{NS}div[@type='source-index']")
    assert index is not None
    index.tag = NS + "quote"
    index.set("type", "source-div")
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="TEI tag differs"):
        check(member, tmp_path, formal=True)


@pytest.mark.parametrize("member", ROWS)
def test_staged_accepted_text_changes_only_at_indexes(member: str) -> None:
    relative = next(path for path in _files(WORK) if path.endswith("/master.tei.xml") and member in path)
    detail = ROWS[member]
    prior = _io_path(WORK / "integration" / (member + "-readable-electronic-v1") / "candidate.tei.xml").read_bytes()
    assert sha256(prior).hexdigest() == detail["old_master_sha"]
    delta = _source_only_delta(prior,
                               _io_path(STAGE / WORK / relative).read_bytes(), detail["index_ids"])
    assert len(delta) == 2
