import hashlib

from lxml import etree
import pytest

from build.tei.reviewed_text_spans import reconstruct, verify


def rows():
    return [{"target_xpath": "/TEI/p", "unit_sha256": hashlib.sha256(b"bad xx and yy").hexdigest(),
             "start": a, "end": b, "sic": s, "corr": c, "mode": "retained", "passage_review": "pass"}
            for a, b, s, c in [(4, 6, "xx", "á"), (11, 13, "yy", "£")]]


def test_multiple_readings_preserve_entire_preimage_and_other_choices():
    master = b'<TEI><p>bad xx and yy</p><note><choice><sic>old</sic><corr>new</corr></choice></note></TEI>'
    revised = reconstruct(master, rows())
    assert verify(master, revised, rows())["retained_readings_preserved"] == 2
    assert etree.fromstring(revised).xpath('string(p/*[1]/*[2])') == "á"
    with pytest.raises(ValueError, match="beyond reviewed spans"):
        verify(master, revised.replace(b'<note>', b'<note n="extra">'), rows())


def test_generated_repairs_are_explicit_and_do_not_claim_a_retained_reading():
    selected = rows()
    for row in selected:
        row["mode"] = "generated"
    revised = reconstruct(b'<TEI><p>bad xx and yy</p></TEI>', selected)
    assert etree.fromstring(revised).findtext('p') == "bad á and £"
    assert b'choice' not in revised


@pytest.mark.parametrize("mutation", ["unreviewed", "stale", "overlap", "inline", "bad_corr"])
def test_invalid_preimages_or_authority_fail_closed(mutation):
    selected = rows()
    master = b'<TEI><p>bad xx and yy</p></TEI>'
    if mutation == "unreviewed": selected[0]["passage_review"] = "unknown"
    if mutation == "stale": selected[0]["unit_sha256"] = "0" * 64
    if mutation == "overlap": selected[1]["start"] = 5
    if mutation == "inline": master = b'<TEI><p>bad xx and yy<hi/></p></TEI>'
    if mutation == "bad_corr": selected[0]["corr"] = ""
    with pytest.raises(ValueError): reconstruct(master, selected)
