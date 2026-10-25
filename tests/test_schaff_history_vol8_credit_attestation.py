from copy import deepcopy

from lxml import etree
import pytest

from build.tei.schaff_history_vol8_current_oracle import NS, verify_credits, verify_notice


def credit_fixture():
    source = etree.fromstring('<ThML><p id="credit">PHILIP SCHAFF; Fréderic Godet; The Electronic Bible\nSociety</p></ThML>'.encode())
    credit = {"name": "Philip Schaff; Fréderic Godet; The Electronic Bible Society",
              "role": "credited in source", "source_selector": "//*[@id='credit']",
              "literal_text": "".join(source[0].itertext())}
    header = etree.Element(NS + "teiHeader")
    statement = etree.SubElement(etree.SubElement(etree.SubElement(header, NS + "fileDesc"), NS + "titleStmt"), NS + "respStmt")
    etree.SubElement(statement, NS + "resp").text = credit["role"]
    etree.SubElement(statement, NS + "name").text = credit["name"]
    return source, [credit], header


def test_source_credits_allow_case_and_line_wrapping():
    source, credits, header = credit_fixture()
    verify_credits(source, credits, header)
    verify_notice(credits, credits[0]["name"])


@pytest.mark.parametrize("replacement", ["FrÃ©deric", "Frédéric", "Unattested"])
def test_coherently_corrupted_profile_and_header_fail_source_attestation(replacement):
    source, credits, header = credit_fixture()
    credits[0]["name"] = credits[0]["name"].replace("Fréderic", replacement)
    header.find(".//" + NS + "name").text = credits[0]["name"]
    with pytest.raises(ValueError, match="not attested"):
        verify_credits(source, credits, header)


def test_notice_and_header_cannot_drop_or_corrupt_bound_credit():
    source, credits, header = credit_fixture()
    with pytest.raises(ValueError, match="visible attribution"):
        verify_notice(credits, credits[0]["name"].replace("Fréderic", "FrÃƒÂ©dÃƒÂ©ric"))
    damaged = deepcopy(header)
    damaged.find(".//" + NS + "name").text = "Philip Schaff"
    with pytest.raises(ValueError, match="header credit"):
        verify_credits(source, credits, damaged)
