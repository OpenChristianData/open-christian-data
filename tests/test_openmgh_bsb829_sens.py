"""Source and boundary checks for the retained Bishops of Sens letter."""

from copy import deepcopy

from lxml import etree
import pytest

from build.tei.openmgh_bsb829_sens_oracle import TEI, check
from build.tools.prepare_openmgh_bsb829_sens import ROOT, SOURCE, make_candidate
from ocd_kernel.tei.install_accepted import _io_path


def test_exact_source_candidate_and_boundary_mutations() -> None:
    source = _io_path(ROOT / SOURCE).read_bytes()
    candidate, report = make_candidate(ROOT)
    assert report == check(source, candidate)
    assert report["selected_child_count"] == 268
    assert report["outside_fragment_target_count"] == 0

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    document = etree.fromstring(candidate, parser)
    ab = document.find(f"{TEI}text/{TEI}body")[0][0]

    missing_heading = deepcopy(document)
    missing_heading.find(f"{TEI}text/{TEI}body")[0][0].remove(
        missing_heading.find(f"{TEI}text/{TEI}body")[0][0][1]
    )
    with pytest.raises(ValueError, match="body does not match"):
        check(source, etree.tostring(missing_heading))

    changed_closing = deepcopy(document)
    changed_closing.find(f"{TEI}text/{TEI}body")[0][0][-1].tail = "Altered closing.\n"
    with pytest.raises(ValueError, match="body does not match"):
        check(source, etree.tostring(changed_closing))

    added_reply = deepcopy(document)
    extra = etree.SubElement(added_reply.find(f"{TEI}text/{TEI}body")[0][0], f"{TEI}lb")
    extra.tail = "2.\n"
    with pytest.raises(ValueError, match="body does not match"):
        check(source, etree.tostring(added_reply))

    assert len(ab) == 268
