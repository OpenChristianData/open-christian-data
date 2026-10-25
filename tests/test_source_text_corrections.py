import hashlib

from lxml import etree
import pytest

from build.tei.source_text_corrections import reconstruct, verify, TEI


SOURCE = '<ThML><ThML.body><p>before Ã© and �<hi>inline</hi> after Ã¦ end</p></ThML.body></ThML>'.encode()
MASTER = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
          '<p xml:id="member-feature-00003">before Ã© and �<hi xml:id="member-feature-00004">inline</hi> after Ã¦ end</p>'
          '</body></text></TEI>').encode()


def corrections():
    rows = []
    for selector, field, value, old, new in [
        ("/ThML[1]/ThML.body[1]/p[1]", "text", "before Ã© and �", "Ã©", "é"),
        ("/ThML[1]/ThML.body[1]/p[1]", "text", "before Ã© and �", "�", "Ω"),
        ("/ThML[1]/ThML.body[1]/p[1]/hi[1]", "tail", " after Ã¦ end", "Ã¦", "æ"),
    ]:
        rows.append(dict(member_id="member", source_selector=selector, source_field=field,
                         source_value_sha256=hashlib.sha256(value.encode()).hexdigest(),
                         start=value.index(old), end=value.index(old) + len(old), sic=old, corr=new,
                         passage_review="pass"))
    return rows


def test_source_readings_and_inline_attachment_survive(tmp_path):
    result = reconstruct(MASTER, {"member": SOURCE}, corrections())
    proof = verify(MASTER, result, {"member": SOURCE}, corrections())
    assert proof["corrections"] == 3
    assert proof["preserved_replacement_characters"] == 1
    tree = etree.fromstring(result)
    assert tree.xpath('//*[local-name()="sic"]/text()') == ["Ã©", "�", "Ã¦"]
    assert tree.xpath('//*[local-name()="corr"]/text()') == ["é", "Ω", "æ"]
    assert result == reconstruct(MASTER, {"member": SOURCE}, corrections())


@pytest.mark.parametrize("mutation", ["reading", "sic", "attachment", "unrelated", "extra"])
def test_independent_inverse_rejects_corruption(mutation):
    tree = etree.fromstring(reconstruct(MASTER, {"member": SOURCE}, corrections()))
    choice = tree.find(".//" + TEI + "choice")
    if mutation == "reading":
        choice[1].text = "invented"
    elif mutation == "sic":
        choice[0].text = "lost"
    elif mutation == "attachment":
        parent = choice.getparent()
        parent.remove(choice)
        parent.append(choice)
    elif mutation == "unrelated":
        tree.find(".//" + TEI + "hi").text = "lost inline text"
    else:
        etree.SubElement(tree.find(".//" + TEI + "body"), TEI + "choice")
    with pytest.raises(ValueError):
        verify(MASTER, etree.tostring(tree), {"member": SOURCE}, corrections())


@pytest.mark.parametrize("mutation", ["unreviewed", "source", "offset", "overlap"])
def test_unreviewed_changed_or_overlapping_source_spans_fail(mutation):
    rows = corrections()
    if mutation == "unreviewed":
        rows[0]["passage_review"] = "needs_review"
    elif mutation == "source":
        rows[0]["source_value_sha256"] = "0" * 64
    elif mutation == "offset":
        rows[0]["start"] += 1
    else:
        rows.append(dict(rows[0]))
    with pytest.raises(ValueError):
        reconstruct(MASTER, {"member": SOURCE}, rows)
