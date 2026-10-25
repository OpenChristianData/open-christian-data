"""Exercise the retained semantic-inline route with its exact historical dependency."""

from hashlib import sha256
import importlib.util
from pathlib import Path
import sys

from lxml import etree
import pytest

from build.tei import l225_engwebpb_semantic_inline_oracle as oracle


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY = ROOT / (
    "tests/fixtures/reconstruction-runtime/l225_ebible_usfm.py"
)
POINTER = "source-usfm:engwebpb/01-GENengwebpb.usfm#line=3"


@pytest.fixture
def converter(monkeypatch):
    assert sha256(DEPENDENCY.read_bytes()).hexdigest() == (
        "68d72bd48ff27ba54b374339e52b7259fdd00bdfb41ae31e85c10c9296f17ccc"
    )
    name = "build.tei.l225_ebible_usfm"
    spec = importlib.util.spec_from_file_location(name, DEPENDENCY)
    dependency = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, dependency)
    spec.loader.exec_module(dependency)
    spec = importlib.util.spec_from_file_location(
        "retained_l225_semantic_inline", ROOT / "build/tei/l225_engwebpb_semantic_inline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_inline_route_preserves_words_notes_and_source_spans(converter):
    source = (
        r'In the \w beginning|strong="H7225"\w* '
        r'\wj God spoke\wj*\f + \fr 1:1 \ft retained note\f*.'
    )
    node = etree.Element(f"{{{oracle.TEI}}}ab", corresp=POINTER)
    counts = converter._parse_inline(node, source, POINTER)
    verified_counts = {}
    oracle._inline_check(node, source, POINTER, verified_counts)
    assert counts == verified_counts
    assert node.find(f"{{{oracle.TEI}}}w").get("n") == "H7225"
    note = node.find(f"{{{oracle.TEI}}}note")
    assert note.get("type") == "footnote"
    assert note.find(f"{{{oracle.TEI}}}label").text == "+"
    node.find(f"{{{oracle.TEI}}}w").set("n", "H9999")
    with pytest.raises(ValueError, match="lexical word/Strong's mapping"):
        oracle._inline_check(node, source, POINTER, {})


@pytest.mark.parametrize(
    ("source", "reason"),
    [(r"\w unclosed", "unclosed USFM inline scope"),
     (r"\w*", "unbalanced USFM inline marker"),
     (r"\unsupported text", "unsupported inline USFM marker")],
)
def test_retained_inline_route_rejects_unsupported_or_unbalanced_source(converter, source, reason):
    with pytest.raises(ValueError, match=reason):
        converter._parse_inline(etree.Element(f"{{{oracle.TEI}}}ab"), source, POINTER)
