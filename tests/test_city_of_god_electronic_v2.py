from __future__ import annotations

import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei import city_of_god_oracle_electronic_v2 as oracle
from build.tei import city_of_god_reconstruction_electronic_v2 as producer


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "sources/city-of-god/city-of-god.electronic-v2.reconstruction-profile.json"
SOURCE_FILES = (
    ROOT / "raw/standard_ebooks/augustine-of-hippo_the-city-of-god_marcus-dods_george-wilson_j-j-smith/src/epub/text/book-17.xhtml",
    ROOT / "raw/ccel/npnf1/npnf102.xml",
)


@pytest.mark.skipif(not all(path.is_file() for path in SOURCE_FILES), reason="City electronic witnesses unavailable")
@pytest.mark.parametrize(
    ("edition", "chapter_id", "source_reading", "print_substitution"),
    [
        ("dods-1871", "dods-chapter-17-16", "Zion", "Sion"),
        ("npnf-1887", "npnf-iv-X-2", "their blessed life, and the light of truth", "the blessed life, and the light of truth"),
    ],
)
def test_electronic_source_reading_rejects_print_substitution(
    edition: str, chapter_id: str, source_reading: str, print_substitution: str
) -> None:
    profile = json.loads(PROFILE.read_bytes())
    root = etree.fromstring(producer._tei(ROOT, edition, profile))
    chapter = root.xpath(
        ".//*[@xml:id=$chapter_id]",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
        chapter_id=chapter_id,
    )[0]
    chapter_text = " ".join("".join(chapter.itertext()).split())
    assert chapter_text.count(source_reading) == 2
    oracle._body_checks(root, edition, ROOT)

    carriers = [
        (node, field)
        for node in chapter.iter()
        for field in ("text", "tail")
        if source_reading in (getattr(node, field) or "")
    ]
    assert carriers
    node, field = carriers[0]
    setattr(node, field, (getattr(node, field) or "").replace(source_reading, print_substitution, 1))
    with pytest.raises(ValueError, match="electronic reading was changed"):
        oracle._body_checks(root, edition, ROOT)
