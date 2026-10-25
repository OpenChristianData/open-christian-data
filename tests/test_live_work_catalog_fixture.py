from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from time import sleep

import pytest

from tests.live_work_catalog_fixture import _shared_catalog_record, live_work_catalog


def test_workers_share_one_fresh_build_and_readers_receive_independent_copies(tmp_path):
    path = tmp_path / "one-run.json"
    calls = []

    def build():
        calls.append(True)
        sleep(0.05)
        return SimpleNamespace(summary={"work_units": 1}, works=[{"routes": ["verified"]}])

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda _: _shared_catalog_record(path, build), range(4)))
    assert len(calls) == 1
    assert all(record == records[0] for record in records)
    first = live_work_catalog.__wrapped__(records[0])
    second = live_work_catalog.__wrapped__(records[0])
    first.works[0]["routes"].clear()
    first.summary["work_units"] = 0
    assert second.works == [{"routes": ["verified"]}]
    assert second.summary == {"work_units": 1}
    _shared_catalog_record(tmp_path / "another-run.json", build)
    assert len(calls) == 2


def test_failed_build_is_not_saved_as_a_baseline(tmp_path):
    path = tmp_path / "failed-run.json"

    def fail():
        raise ValueError("source drift")

    with pytest.raises(ValueError, match="source drift"):
        _shared_catalog_record(path, fail)
    assert not path.exists()
    recovered = _shared_catalog_record(
        path, lambda: SimpleNamespace(summary={"work_units": 0}, works=[]),
    )
    assert recovered == {"summary": {"work_units": 0}, "works": []}


def test_retained_audit_reuse_preserves_results_and_refuses_changed_inputs():
    from copy import deepcopy
    from tests.live_work_catalog_fixture import reuse_retained_witness_gaps

    original = {"work_id": "one", "metadata_fields": {"provenance.source_hash": ["bound"]},
                "retained_witness_gaps": [{"missing_member_sample": ["raw/one"]}]}
    baseline = SimpleNamespace(works=[deepcopy(original)])
    current = [{key: deepcopy(value) for key, value in original.items()
                if key != "retained_witness_gaps"}]
    reuse_retained_witness_gaps(current, baseline)
    assert current == [original]
    current[0]["retained_witness_gaps"][0]["missing_member_sample"].clear()
    assert baseline.works == [original]
    current[0]["metadata_fields"]["provenance.source_hash"] = ["changed"]
    with pytest.raises(ValueError, match="metadata changed: one"):
        reuse_retained_witness_gaps(current, baseline)
    with pytest.raises(ValueError, match="same complete work set"):
        reuse_retained_witness_gaps([], baseline)


def test_retained_audit_reuse_refuses_a_different_repository(tmp_path, monkeypatch):
    from build.tools import count_dataset_records
    from tests.live_work_catalog_fixture import reuse_live_retained_witness_audit

    baseline = SimpleNamespace(works=[])
    reuse_live_retained_witness_audit.__wrapped__(monkeypatch, baseline)
    with pytest.raises(ValueError, match="original repository"):
        count_dataset_records._attach_retained_witness_gaps([], tmp_path)
