"""Acquisition integrity tests; fixtures do not establish retained work authority."""

import hashlib
import io
import json
import urllib.error

import pytest

from build.tools.retain_newadvent_sources import _BoundRedirects, checked_url, retain


URL = "https://www.newadvent.org/cathen/"


def test_stylesheet_routes_require_explicit_scope():
    url = "https://www.newadvent.org/utility/screen6.css"
    with pytest.raises(ValueError):
        checked_url(url)
    assert checked_url(url, allow_stylesheets=True) == url
    with pytest.raises(ValueError):
        checked_url("https://www.newadvent.org/utility/program.js", allow_stylesheets=True)


class Response(io.BytesIO):
    status = 200
    headers = {"Content-Type": "text/html; charset=windows-1252"}

    def geturl(self):
        return URL


class Transport:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request.full_url)
        result = next(self.outcomes)
        if isinstance(result, Exception):
            raise result
        return Response(result)


def test_exact_bytes_and_explicit_scope(tmp_path):
    payload = b"<html>\x96\xff\r\nUnmodified</html>"
    target = tmp_path / "cohort"
    transport = Transport([payload, b"second"])
    delays = []
    receipt = retain([URL, URL + "a.htm"], target, opener=transport, sleeper=delays.append)
    assert (target / "000001.html").read_bytes() == payload
    assert receipt["members"][0]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["status"] == "declared-urls-retained"
    assert receipt["work_or_volume_completeness_established"] is False
    assert receipt["historical_source_claims_reconciled"] is False
    assert delays == [1.0]
    assert json.loads((target / "acquisition.json").read_text("utf-8")) == receipt


@pytest.mark.parametrize("code", [403, 429, 404, 500])
def test_http_failure_stops_without_silently_skipping(tmp_path, code):
    transport = Transport([b"first", urllib.error.HTTPError(URL, code, "blocked", {}, None), b"never"])
    target = tmp_path / "cohort"
    receipt = retain([URL, URL + "a.htm", URL + "b.htm"], target, opener=transport, sleeper=lambda _: None)
    assert [m["status"] for m in receipt["members"]] == ["retained", "failed", "not-attempted"]
    assert receipt["members"][1]["http_status"] == code
    assert receipt["status"] == "partial"
    assert len(transport.calls) == 2
    assert not (target / "000002.html").exists()


def test_existing_destination_cannot_be_overwritten(tmp_path):
    target = tmp_path / "cohort"
    target.mkdir()
    original = target / "000001.html"
    original.write_bytes(b"original")
    transport = Transport([])
    with pytest.raises(FileExistsError):
        retain([URL], target, opener=transport)
    assert original.read_bytes() == b"original"
    assert transport.calls == []


@pytest.mark.parametrize("url", ["http://www.newadvent.org/cathen/", "https://other.example/cathen/", URL + "../x", URL + "%2e%2e/x", URL + "a.htm?x=1"])
def test_out_of_scope_urls_fail_before_acquisition(url):
    with pytest.raises(ValueError):
        checked_url(url)


def test_out_of_scope_redirect_is_rejected_before_following():
    with pytest.raises(ValueError):
        _BoundRedirects().redirect_request(None, None, 302, "Found", {}, "https://other.example/")


def test_duplicate_urls_cannot_claim_distinct_members(tmp_path):
    with pytest.raises(ValueError, match="distinct"):
        retain([URL, URL], tmp_path / "cohort", opener=Transport([]))
    assert not (tmp_path / "cohort").exists()


def test_image_retention_is_explicit_and_scoped(tmp_path):
    url = "https://www.newadvent.org/images/01001abt.jpg"
    with pytest.raises(ValueError):
        checked_url(url)
    assert checked_url(url, allow_images=True) == url
    with pytest.raises(ValueError):
        checked_url("https://www.newadvent.org/utility/private.json", allow_images=True)
    class ImageTransport:
        def open(self, request, timeout):
            response = Response(b"\xff\xd8\xffexact")
            response.geturl = lambda: url
            return response
    target = tmp_path / "images"
    receipt = retain([url], target, opener=ImageTransport(), allow_images=True)
    assert (target / "000001.jpg").read_bytes() == b"\xff\xd8\xffexact"
    assert receipt["members"][0]["path"] == "000001.jpg"
    events = [json.loads(line) for line in (target / "acquisition.events.jsonl").read_text("utf-8").splitlines()]
    assert events[0]["sha256"] == receipt["members"][0]["sha256"]
    assert json.loads((target / "request-plan.json").read_text("utf-8"))["urls"] == [url]
