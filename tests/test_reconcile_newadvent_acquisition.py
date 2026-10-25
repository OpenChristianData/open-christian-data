import json
import io
import urllib.error
import hashlib

import pytest

from build.tools.acquire_newadvent_envelope import acquire
from build.tools.reconcile_newadvent_acquisition import reconcile
from build.tools.retain_newadvent_sources import retain
from tests.test_acquire_newadvent_envelope import fetch, graph


def test_complete_frontier_is_not_work_completeness(tmp_path):
    path, sha = graph(tmp_path)
    run = tmp_path / "run"
    acquire(path, sha, [], run, 2, fetch=fetch, sleeper=lambda _: None)
    result = reconcile(run)
    assert result["retained"] == 3 and result["declared_frontier_retained"]
    assert not result["work_completeness_established"]
    assert len(result["members"]) == 3
    (run / "acquisition.lock").write_text("123", encoding="utf-8")
    with pytest.raises(ValueError, match="lock exists"):
        reconcile(run)


def test_request_plan_drift_is_rejected(tmp_path):
    path, sha = graph(tmp_path)
    run = tmp_path / "run"
    acquire(path, sha, [], run, 2, fetch=fetch, sleeper=lambda _: None)
    request = run / "batch-0001/request-plan.json"
    data = json.loads(request.read_bytes())
    data["urls"].reverse()
    request.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="identity drift"):
        reconcile(run)


def test_unaccounted_payload_is_rejected(tmp_path):
    path, sha = graph(tmp_path)
    run = tmp_path / "run"
    acquire(path, sha, [], run, 2, fetch=fetch, sleeper=lambda _: None)
    (run / "batch-0001/extra.html").write_bytes(b"unaccounted")
    with pytest.raises(ValueError, match="Unaccounted"):
        reconcile(run)


def test_earlier_cohort_uses_existing_pinned_census_selection_without_fabricating_plan(tmp_path):
    path, _ = graph(tmp_path)
    record = json.loads(path.read_bytes())
    record["selected_acquisition_urls"] = record["article_urls_in_first_occurrence_order"]
    path.write_text(json.dumps(record), encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    prior = tmp_path / "prior"
    fetch(record["selected_acquisition_urls"], prior)
    (prior / "request-plan.json").unlink()
    run = tmp_path / "run"
    acquire(path, sha, [prior], run, fetch=fetch, sleeper=lambda _: None)
    result = reconcile(run)
    assert result["source_receipts"][0]["request_declaration"]["kind"] == "pinned-link-census-selection"
    assert not (prior / "request-plan.json").exists()


@pytest.mark.parametrize("status", [404, 403])
def test_missing_response_and_access_failure_remain_distinct(tmp_path, status):
    path, sha = graph(tmp_path)
    run = tmp_path / "run"
    class FailedTransport:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, "failure", {}, io.BytesIO(b"exact failure"))
    def failed_fetch(urls, destination):
        return retain(urls, destination, opener=FailedTransport(), sleeper=lambda _: None)
    acquire(path, sha, [], run, 3, fetch=failed_fetch, sleeper=lambda _: None, continue_missing=status == 404)
    result = reconcile(run)
    assert not result["declared_frontier_retained"]
    assert result["declared_frontier_accounted"] is (status == 404)
    assert len(result["unavailable_urls"]) == (3 if status == 404 else 0)
    assert len(result["pending_urls"]) == (0 if status == 404 else 3)
    (run / "batch-0001/000001.http-error.html").write_bytes(b"changed")
    with pytest.raises(ValueError, match="error response byte mismatch"):
        reconcile(run)
