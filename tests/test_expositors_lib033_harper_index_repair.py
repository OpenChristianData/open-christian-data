"""Exact source and accepted-master semantics for Harper's index repair."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib033_readable_harper_index_v2_oracle import check
from build.tools.stage_expositors_lib033_harper_index_repair import _source_only_delta
from ocd_kernel.tei.install_accepted import _files, _io_path


MEMBER = "harper-expositordeut"
CANDIDATE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "expositors-lib033-harper-index-v2-candidate-20260928-v1/harper-expositordeut"
)
STAGE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "expositors-lib033-harper-index-repair-stage-20260928-v1"
)
WORK = Path("library/works/expositors-bible--andrew-harper")
NS = "{http://www.tei-c.org/ns/1.0}"


def test_source_oracle_and_two_node_delta() -> None:
    result = check(MEMBER, CANDIDATE, formal=True)
    assert (result["source_elements"], result["source_comments"], result["native_rows"]) == (2919, 14, 29)
    old = _io_path(
        WORK / "integration/harper-expositordeut-readable-electronic-v1/inputs/package/content.tei.xml"
    ).read_bytes()
    new = (CANDIDATE / "content.tei.xml").read_bytes()
    delta = _source_only_delta(old, new)
    assert {item["tei_id"] for item in delta} == {
        "harper-expositordeut-feature-002376",
        "harper-expositordeut-feature-002400",
        "harper-expositordeut-feature-002423",
    }


def test_source_oracle_rejects_index_as_quote(tmp_path: Path) -> None:
    for name in ("content.tei.xml", "source-accountability.json"):
        shutil.copy2(CANDIDATE / name, tmp_path / name)
    path = tmp_path / "content.tei.xml"
    tree = etree.parse(str(path))
    index = tree.find(f".//{NS}div[@type='source-index']")
    assert index is not None
    index.tag = NS + "quote"
    index.set("type", "source-div")
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="TEI tag differs"):
        check(MEMBER, tmp_path, formal=True)


def test_source_oracle_preserves_poem_stanza_quote(tmp_path: Path) -> None:
    for name in ("content.tei.xml", "source-accountability.json"):
        shutil.copy2(CANDIDATE / name, tmp_path / name)
    path = tmp_path / "content.tei.xml"
    tree = etree.parse(str(path))
    carrier = tree.find(f".//{NS}quote[@type='source-div']")
    assert carrier is not None
    carrier.set("type", "source-index")
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source div class carrier differs"):
        check(MEMBER, tmp_path, formal=True)


def test_staged_accepted_text_changes_only_at_indexes() -> None:
    relative = next(path for path in _files(WORK) if path.endswith("/master.tei.xml"))
    old_master = WORK / "integration" / (MEMBER + "-readable-electronic-v1") / "candidate.tei.xml"
    prior = _io_path(old_master).read_bytes()
    assert sha256(prior).hexdigest() == "5965be42874d90aa2c89b8b81801a76e95b41d284a7f44f4188b1a152f512eec"
    new_master = STAGE / WORK / relative
    delta = _source_only_delta(prior, _io_path(new_master).read_bytes())
    assert len(delta) == 3
