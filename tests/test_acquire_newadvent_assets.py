import hashlib
import io
import json
import urllib.error

import pytest

from build.tools.acquire_newadvent_assets import acquire
from build.tools.retain_newadvent_sources import retain
from tests.test_retain_newadvent_sources import Response


def setup_run(tmp_path):
    source = tmp_path / "source.html"
    source.write_bytes(b"source")
    record = {"contract": "ocd-newadvent-image-census-v1", "source_members": [
        {"url": "https://www.newadvent.org/cathen/01137a.htm", "path": str(source),
         "sha256": hashlib.sha256(b"source").hexdigest()}],
        "image_urls": ["https://www.newadvent.org/images/a.jpg", "https://www.newadvent.org/images/b.png"],
        "stylesheet_urls": ["https://www.newadvent.org/utility/site.css"], "unresolved": []}
    path = tmp_path / "census.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    article = tmp_path / "articles"
    article.mkdir()
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), article, tmp_path / "assets"


def transport_fetch(calls, status=None):
    class Transport:
        def open(self, request, timeout):
            calls.append(request.full_url)
            if status and request.full_url.endswith("a.jpg"):
                raise urllib.error.HTTPError(request.full_url, status, "failure", {}, io.BytesIO(b"exact error"))
            response = Response(b"asset")
            response.geturl = lambda: request.full_url
            return response
    def fetch(urls, destination, **flags):
        assert flags == {"allow_images": True, "allow_stylesheets": True}
        return retain(urls, destination, opener=Transport(), sleeper=lambda _: None, **flags)
    return fetch


def test_batches_resume_pin_sources_and_classification(tmp_path):
    args = setup_run(tmp_path)
    calls, delays = [], []
    result = acquire(*args, batch_size=2, fetch=transport_fetch(calls), sleeper=delays.append)
    assert result["images"] == {"declared": 2, "retained": 2}
    assert result["stylesheets"] == {"declared": 1, "retained": 1}
    assert len(result["receipts"]) == 2 and delays == [1.0]
    assert json.loads((args[3] / "run-plan.json").read_bytes())["source_members"][0]["bytes"] == 6
    acquire(*args, batch_size=2, fetch=transport_fetch(calls))
    assert len(calls) == 3
    assert len(list(args[3].glob("outcome-*.json"))) == 2
    assert not (args[2] / "acquisition.lock").exists()


@pytest.mark.parametrize("status,continued,expected", [(404, True, 3), (410, True, 3), (404, False, 1), (500, True, 1), (429, True, 1)])
def test_failure_evidence_and_resume_policy(tmp_path, status, continued, expected):
    args = setup_run(tmp_path)
    calls = []
    result = acquire(*args, continue_missing=continued, fetch=transport_fetch(calls, status), sleeper=lambda _: None)
    assert len(calls) == expected
    assert result["remaining"] >= 1
    error = args[3] / "batch-0001/000001.http-error.html"
    assert error.read_bytes() == b"exact error"
    acquire(*args, continue_missing=continued, fetch=transport_fetch(calls, status))
    assert len(calls) == expected
    error.write_bytes(b"mutated")
    with pytest.raises(ValueError, match="error response byte mismatch"):
        acquire(*args, continue_missing=continued, fetch=transport_fetch(calls, status))


def test_active_article_lock_refuses_without_mutation(tmp_path):
    args = setup_run(tmp_path)
    lock = args[2] / "acquisition.lock"
    lock.write_text("live article pid", encoding="utf-8")
    with pytest.raises(FileExistsError):
        acquire(*args)
    assert lock.read_text() == "live article pid"
    assert not args[3].exists()


@pytest.mark.parametrize("mutation", ["census", "source", "asset", "receipt", "duplicate"])
def test_binding_mutations_rejected_before_more_fetches(tmp_path, mutation):
    args = setup_run(tmp_path)
    calls = []
    acquire(*args, fetch=transport_fetch(calls))
    if mutation == "census":
        args[0].write_bytes(b"{}")
    elif mutation == "source":
        (tmp_path / "source.html").write_bytes(b"other")
    elif mutation == "asset":
        (args[3] / "batch-0001/000001.jpg").write_bytes(b"other")
    else:
        path = args[3] / "batch-0001/acquisition.json"
        receipt = json.loads(path.read_bytes())
        receipt["members"][0]["url"] = receipt["members"][1]["url"] if mutation == "duplicate" else "https://www.newadvent.org/images/outside.jpg"
        path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError):
        acquire(*args, fetch=transport_fetch(calls))
    assert len(calls) == 3
