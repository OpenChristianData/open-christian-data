import hashlib
import json

import pytest

from build.tools.census_newadvent_sources import Links, census


BASE = "https://www.newadvent.org/cathen/"


def cohort(tmp_path, html, url=BASE):
    folder = tmp_path / "retained"
    folder.mkdir()
    payload = html.encode("utf-8")
    (folder / "000001.html").write_bytes(payload)
    receipt = {"contract": "ocd-newadvent-retained-cohort-v1", "members": [{
        "url": url, "final_url": url, "http_status": 200,
        "status": "retained", "path": "000001.html", "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }]}
    (folder / "acquisition.json").write_text(json.dumps(receipt), encoding="utf-8")
    return folder


def test_census_preserves_occurrences_and_full_index_gap(tmp_path):
    folder = cohort(tmp_path, """<A HREF='../cathen/01001a.htm#part'>one</A>
    <a href="01001a.htm">again</a><a href=a-ce.htm>full index</a>
    <a href='17721a.htm'>supplement</a><a>anchor</a>
    <a href='https://example.org/?a=1&amp;b=2'>external</a>""")
    result = census([folder])
    assert len(result["links"]) == 6
    assert result["links"][0]["fragment"] == "part"
    assert result["links"][-1]["href"].endswith("?a=1&b=2")
    assert result["article_urls_in_first_occurrence_order"] == [BASE + "01001a.htm", BASE + "17721a.htm"]
    assert result["missing_linked_indexes"] == [BASE + "a-ce.htm"]
    assert result["printed_volume_membership_established"] is False
    assert result["work_completeness_established"] is False


def test_modified_retained_bytes_fail_binding(tmp_path):
    folder = cohort(tmp_path, "<a href='01001a.htm'>one</a>")
    (folder / "000001.html").write_bytes(b"modified")
    with pytest.raises(ValueError, match="byte binding"):
        census([folder])


def test_repeated_source_url_needs_witness_selection(tmp_path):
    folder = cohort(tmp_path, "text")
    with pytest.raises(ValueError, match="Duplicate retained URL"):
        census([folder, folder])


@pytest.mark.parametrize("html", ["<base href='https://other.example/'>", "<a href='a.htm' href='b.htm'>"])
def test_ambiguous_link_resolution_fails_closed(html):
    with pytest.raises(ValueError):
        Links().feed(html)


def test_invalid_utf8_is_not_silently_replaced(tmp_path):
    folder = cohort(tmp_path, "x")
    payload = b"\xff"
    (folder / "000001.html").write_bytes(payload)
    receipt = json.loads((folder / "acquisition.json").read_text("utf-8"))
    receipt["members"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
    (folder / "acquisition.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(UnicodeDecodeError):
        census([folder])


def test_failed_declared_members_remain_explicit(tmp_path):
    folder = cohort(tmp_path, "<a href='01001a.htm'>article</a>")
    receipt_path = folder / "acquisition.json"
    receipt = json.loads(receipt_path.read_text("utf-8"))
    receipt["members"].append({"url": BASE + "01001a.htm", "status": "failed", "http_status": 429})
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    result = census([folder])
    assert result["unretained_declared_members"][0]["http_status"] == 429
    assert result["unretained_article_urls"] == [BASE + "01001a.htm"]


def test_canonical_identity_targets_extend_frontier_without_becoming_anchors(tmp_path):
    folder = cohort(tmp_path, '<link rel="canonical" href="01002a.htm"><a href="01001a.htm">one</a>')
    result = census([folder])
    assert len(result["links"]) == 1
    assert result["canonical_links"][0]["resolved_url"] == BASE + "01002a.htm"
    assert result["unretained_article_urls"] == [BASE + "01001a.htm", BASE + "01002a.htm"]


def test_duplicate_canonical_href_fails_closed():
    with pytest.raises(ValueError, match="Duplicate href"):
        Links().feed('<link rel="canonical" href="a.htm" href="b.htm">')


def test_duplicate_relation_cannot_invent_a_canonical_identity():
    with pytest.raises(ValueError, match="Duplicate rel"):
        Links().feed('<link rel="stylesheet" rel="canonical" href="01001a.htm">')
