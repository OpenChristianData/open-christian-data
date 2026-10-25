"""One fresh, unchanged catalog baseline per pytest run, including xdist workers."""

from copy import deepcopy
import json
from pathlib import Path

from filelock import FileLock
import pytest


def _shared_catalog_record(path, build):
    # The complete source audit can exceed an hour on a busy hard disk.
    with FileLock(str(path) + ".lock", timeout=7200):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        catalog = build()
        record = {"summary": catalog.summary, "works": catalog.works}
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return record


@pytest.fixture(scope="session")
def _live_work_catalog_record(tmp_path_factory, worker_id, testrun_uid):
    from build.tools.count_dataset_records import collect_work_catalog

    shared = tmp_path_factory.getbasetemp()
    if worker_id != "master":
        shared = shared.parent
    path = shared / f"live-work-catalog-{testrun_uid}.json"
    root = Path(__file__).resolve().parents[1]
    return _shared_catalog_record(path, lambda: collect_work_catalog(root / "data"))


@pytest.fixture
def live_work_catalog(_live_work_catalog_record):
    from build.tools.count_dataset_records import WorkCatalog

    record = deepcopy(_live_work_catalog_record)
    return WorkCatalog(summary=record["summary"], works=record["works"])


def reuse_retained_witness_gaps(works, baseline):
    """Reuse this run's complete retained audit for unchanged catalog inputs."""
    previous = {work["work_id"]: work for work in baseline.works}
    if len(works) != len(previous) or {work["work_id"] for work in works} != set(previous):
        raise ValueError("retained audit reuse requires the same complete work set")
    for work in works:
        retained = previous[work["work_id"]]
        if work["metadata_fields"] != retained["metadata_fields"]:
            raise ValueError(f"retained audit metadata changed: {work['work_id']}")
        work["retained_witness_gaps"] = deepcopy(retained["retained_witness_gaps"])


@pytest.fixture
def reuse_live_retained_witness_audit(monkeypatch, live_work_catalog):
    from build.tools import count_dataset_records

    root = Path(__file__).resolve().parents[1]

    def attach(works, repository_root):
        if repository_root != root:
            raise ValueError("retained audit reuse requires its original repository")
        reuse_retained_witness_gaps(works, live_work_catalog)

    monkeypatch.setattr(count_dataset_records, "_attach_retained_witness_gaps", attach)
