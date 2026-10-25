"""Challenge the exact retained single-work shell adaptation."""
from pathlib import Path

import pytest
from lxml import etree

from build.tei.whole_duty_prayer_native_adapter import adapt_whole_duty_prayer, NS


def test_exact_source_preserves_complete_work_and_rejects_drift():
    original = (Path(__file__).resolve().parents[1] / "raw/tcp/high-range/A23804/A23804.xml").read_bytes()
    adapted, receipt = adapt_whole_duty_prayer(original)
    assert receipt["exact_byte_inverse"] == receipt["complete_work_subtree_c14n"] == "pass"
    assert adapted.split(b"</teiHeader>")[0] == original.split(b"</teiHeader>")[0]
    tree = etree.fromstring(adapted)
    assert [n.tag for n in tree.find(NS + "text")] == [NS + n for n in ("front", "body", "back")]
    assert len(tree.findall(".//" + NS + "gap")) == 27
    assert len(tree.findall(".//" + NS + "pb")) == 178
    with pytest.raises(ValueError, match="source hash differs"):
        adapt_whole_duty_prayer(original.replace(b'No absolute certainty', b'Absolute certainty', 1))
