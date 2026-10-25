from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from lxml import html


REPO_ROOT = Path(__file__).resolve().parents[1]

UNSPOKEN_SOURCE = (
    REPO_ROOT
    / "raw"
    / "standard_ebooks"
    / "george-macdonald_unspoken-sermons"
    / "src"
    / "epub"
    / "text"
    / "chapter-1-1.xhtml"
)
UNSPOKEN_OUTPUT = REPO_ROOT / "data" / "sermons" / "george-macdonald-unspoken-sermons.json"
BCP_1928_SOURCE = REPO_ROOT / "raw" / "bcp-1928" / "asaints.html"
BCP_1928_OUTPUT = REPO_ROOT / "data" / "prayers" / "bcp-1928" / "collects.json"

XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"

UNSPOKEN_EPIGRAPH = (
    "And he came to Capernaum: and, being in the house, he asked them, What was it that ye "
    "disputed among yourselves by the way? But they held their peace: for by the way they had "
    "disputed among themselves who should be the greatest. And he sat down, and called the "
    "twelve, and saith unto them, If any man desire to be first, the same shall be last of all, "
    "and servant of all. And he took a child, and set him in the midst of them: and when he had "
    "taken him in his arms, he said unto them, Whosoever shall receive one of such children in "
    "my name, receiveth me; and whosoever shall receive me, receiveth not me, but him that sent me."
)

BCP_FIRST_COLLECT = (
    "ALMIGHTY and everlasting God, who dost enkindle the name of thy love in the hearts of the "
    "Saints; Grant to us, thy humble servants, the same faith and power of love; that, as we "
    "rejoice in their triumphs, we may profit by their examples; through Jesus Christ our Lord. "
    "Amen."
)
BCP_ALTERNATIVE_COLLECT = (
    "O ALMIGHTY God, who hast called us to faith in thee, and hast compassed us about with so "
    "great a cloud of witnesses; Grant that we, encouraged by the good examples of thy Saints, "
    "and especially of thy servant [Saint_____], may persevere in running the race that is set "
    "before us, until at length, through thy mercy, we, with them, attain to thine eternal joy; "
    "through him who is the author and finisher of our faith, thy Son Jesus Christ our Lord. Amen."
)
BCP_EPISTLE = (
    "SEEING we also are compassed about with so great a cloud of witnesses, let us lay aside every "
    "weight, and the sin which doth so easily beset us, and let us run with patience the race that "
    "is set before us, looking unto Jesus the author and finisher of our faith; who for the joy "
    "that was set before him endured the cross, despising the shame, and is set down at the right "
    "hand of the throne of God."
)
BCP_GOSPEL = (
    "WHEN the Son of man shall come in his glory, and all the holy angels with him, then shall he "
    "sit upon the throne of his glory: and before him shall be gathered all nations: and he shall "
    "separate them one from another, as a shepherd divideth his sheep from the goats: and he shall "
    "set the sheep on his right hand, but the goats on the left. Then shall the King say unto them "
    "on his right hand, Come, ye blessed of my Father, inherit the kingdom prepared for you from "
    "the foundation of the world: for I was an hungred, and ye gave me meat: I was thirsty, and ye "
    "gave me drink: I was a stranger, and ye took me in: naked, and ye clothed me: I was sick, and "
    "ye visited me: I was in prison, and ye came unto me. Then shall the righteous answer him, "
    "saying, Lord, when saw we thee an hungred, and fed thee? or thirsty, and gave thee drink? "
    "When saw we thee a stranger, and took thee in? or naked, and clothed thee? Or when saw we thee "
    "sick, or in prison, and came unto thee? And the King shall answer and say unto them, Verily I "
    "say unto you, Inasmuch as ye have done it unto one of the least of these my brethren, ye have "
    "done it unto me."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _load_data(path: Path) -> list[dict[str, object]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return document["data"]


def test_unspoken_sermon_source_preserves_full_epigraph_role_and_target() -> None:
    assert _sha256(UNSPOKEN_SOURCE) == "d869f6f6923ee790ead3560114fa11639d1e356c23bde5356cf14c93e32b1ff7"

    root = ET.fromstring(UNSPOKEN_SOURCE.read_bytes())
    namespace = {"xhtml": XHTML_NS}
    section = root.find(".//xhtml:section[@id='chapter-1-1']", namespace)
    assert section is not None
    epigraph = section.find("./xhtml:header/xhtml:blockquote", namespace)
    assert epigraph is not None
    passage = epigraph.find("./xhtml:p", namespace)
    citation = epigraph.find("./xhtml:cite", namespace)
    assert passage is not None
    assert citation is not None

    source_fact = {
        "sermon_id": section.attrib["id"].removeprefix("chapter-"),
        "role": epigraph.attrib[EPUB_TYPE],
        "text": _normalized_text(passage),
        "scripture_target": _normalized_text(citation).replace("\u2060–\u2060", "-"),
        "relationship": "sermon-targets-scripture",
    }
    assert source_fact == {
        "sermon_id": "1-1",
        "role": "epigraph",
        "text": UNSPOKEN_EPIGRAPH,
        "scripture_target": "Mark 9:33-37",
        "relationship": "sermon-targets-scripture",
    }

    ordinary = next(item for item in _load_data(UNSPOKEN_OUTPUT) if item["sermon_id"] == "1-1")
    assert ordinary["primary_reference"] == {"raw": "Mark 9:33-37", "osis": []}
    assert ordinary["primary_reference_text"] is None
    assert UNSPOKEN_EPIGRAPH not in ordinary["content_blocks"]


def test_bcp_1928_saints_day_source_preserves_alternatives_and_readings() -> None:
    assert _sha256(BCP_1928_SOURCE) == "138159e22d5ec3c1cc0c6a5cffe167d0f7012c92959a70abd52b63e4af433600"

    source = html.fromstring(BCP_1928_SOURCE.read_text(encoding="latin-1"))
    source_text = " ".join(source.text_content().split())
    expected_sequence = [
        BCP_FIRST_COLLECT,
        "¶ Or this.",
        BCP_ALTERNATIVE_COLLECT,
        "The Epistle. Hebrews xii. 1.",
        BCP_EPISTLE,
        "The Gospel. St. Matthew xxv. 31.",
        BCP_GOSPEL,
    ]
    positions = [source_text.index(unit) for unit in expected_sequence]
    assert positions == sorted(positions)

    source_fact = {
        "occasion": "A Saint's Day",
        "collect_alternative_group": {
            "members": [BCP_FIRST_COLLECT, BCP_ALTERNATIVE_COLLECT],
            "source_rubric": "¶ Or this.",
        },
        "supplied_readings": [
            {"role": "epistle", "reference": "Hebrews xii. 1.", "text": BCP_EPISTLE},
            {"role": "gospel", "reference": "St. Matthew xxv. 31.", "text": BCP_GOSPEL},
        ],
    }
    assert source_fact["collect_alternative_group"]["source_rubric"] == "¶ Or this."
    assert [reading["role"] for reading in source_fact["supplied_readings"]] == ["epistle", "gospel"]

    ordinary_records = [item for item in _load_data(BCP_1928_OUTPUT) if item["prayer_id"] == "asaints"]
    assert len(ordinary_records) == 1
    assert ordinary_records[0]["content_blocks"] == [BCP_FIRST_COLLECT]
    assert ordinary_records[0]["scripture_references"] == []
    assert BCP_ALTERNATIVE_COLLECT not in ordinary_records[0]["content_blocks"]
