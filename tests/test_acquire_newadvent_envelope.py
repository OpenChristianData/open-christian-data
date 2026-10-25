import hashlib
import json

import pytest

from build.tools.acquire_newadvent_envelope import acquire
from build.tools.retain_newadvent_sources import retain
from tests.test_retain_newadvent_sources import Response, Transport


BASE = "https://www.newadvent.org/cathen/"


def graph(tmp_path):
    source = tmp_path / "index.html"
    source.write_bytes(b"index")
    payload = {"contract": "ocd-newadvent-link-census-v1", "missing_linked_indexes": [], "article_urls_in_first_occurrence_order": [BASE + f"0100{i}a.htm" for i in range(1, 4)], "members": [{"path": str(source), "bytes": 5, "sha256": hashlib.sha256(b"index").hexdigest()}]}
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(urls, destination):
    class ExactTransport:
        def open(self, request, timeout):
            response = Response(b"source")
            response.geturl = lambda: request.full_url
            return response
    return retain(urls, destination, opener=ExactTransport(), sleeper=lambda _: None)


def test_batches_reconcile_and_resume_without_refetching(tmp_path):
    path, sha = graph(tmp_path)
    destination = tmp_path / "complete"
    calls = []
    def capture(urls, target):
        calls.append(urls)
        return fetch(urls, target)
    result = acquire(path, sha, [], destination, 2, fetch=capture, sleeper=lambda _: None)
    assert result["remaining"] == 0
    assert [len(batch) for batch in calls] == [2, 1]
    assert not (destination / "acquisition.lock").exists()
    result = acquire(path, sha, [], destination, 2, fetch=capture, sleeper=lambda _: None)
    assert len(calls) == 2
    assert result["retained"] == 3


def test_changed_index_bytes_block_before_network(tmp_path):
    path, sha = graph(tmp_path)
    (tmp_path / "index.html").write_bytes(b"other")
    with pytest.raises(ValueError, match="Index source binding"):
        acquire(path, sha, [], tmp_path / "complete", fetch=fetch)


def test_changed_graph_digest_blocks_before_destination(tmp_path):
    path, _ = graph(tmp_path)
    with pytest.raises(ValueError, match="digest mismatch"):
        acquire(path, "0" * 64, [], tmp_path / "complete", fetch=fetch)
    assert not (tmp_path / "complete").exists()


def test_missing_source_is_recorded_once_while_other_targets_continue(tmp_path):
    import io
    import urllib.error
    path, sha = graph(tmp_path)
    calls = []
    class MissingTransport:
        def open(self, request, timeout):
            calls.append(request.full_url)
            if request.full_url.endswith("01001a.htm"):
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b"missing source response"))
            response = Response(b"source")
            response.geturl = lambda: request.full_url
            return response
    def capture(urls, target):
        return retain(urls, target, opener=MissingTransport(), sleeper=lambda _: None)
    destination = tmp_path / "complete"
    result = acquire(path, sha, [], destination, 3, fetch=capture, sleeper=lambda _: None, continue_missing=True)
    assert result["status"] == "declared-envelope-accounted-with-unavailable-members"
    assert result["retained"] == 2 and result["remaining"] == 1
    assert len(calls) == 3
    assert (destination / "batch-0001/000001.http-error.html").read_bytes() == b"missing source response"
    acquire(path, sha, [], destination, 3, fetch=capture, sleeper=lambda _: None, continue_missing=True)
    assert len(calls) == 3
    (destination / "batch-0001/000001.http-error.html").write_bytes(b"changed error response")
    with pytest.raises(ValueError, match="error response byte mismatch"):
        acquire(path, sha, [], destination, 3, fetch=capture, sleeper=lambda _: None, continue_missing=True)
    assert len(calls) == 3
