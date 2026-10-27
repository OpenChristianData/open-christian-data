"""Three config-free work manifests bind extracted members and package evidence."""
from __future__ import annotations

import copy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from tests.runtime_candidate_baselines import historical_bound_bytes

from build.tools.library_config_free_multi_binding import bind_config_free_multi
from build.tools.prepare_library_sidecar_batch import prepare
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/config-free-multi-three-sidecar-batch-20260926.json"


PACKET_SHA256 = "9e6e2b4c30fbb330229555197b2f366daf38f47284c6799c0c4e98f7eae74278"
HISTORICAL_FILES = {
    "library/works/bcp-1928-collects/work.json": "tests/fixtures/reconstruction-runtime/authorities/config-free-bcp-1928-collects.work.json",
    "library/works/bcp-1928-collects/state.json": "tests/fixtures/reconstruction-runtime/authorities/config-free-bcp-1928-collects.state.json",
    "library/works/daily-light/work.json": "tests/fixtures/reconstruction-runtime/authorities/config-free-daily-light.work.json",
    "library/works/daily-light/state.json": "tests/fixtures/reconstruction-runtime/authorities/config-free-daily-light.state.json",
    "library/works/naves-topical-bible/work.json": "tests/fixtures/reconstruction-runtime/authorities/config-free-naves-topical-bible.work.json",
    "library/works/naves-topical-bible/state.json": "tests/fixtures/reconstruction-runtime/authorities/config-free-naves-topical-bible.state.json",
    "sources/devotionals/daily-light/daily-light.source-manifest.json": "tests/fixtures/reconstruction-runtime/authorities/config-free-daily-light.source-manifest.json"
}
HISTORICAL_FILES.update({'metadata/source-evidence/catalog/bcp-1928-collects.json': 'tests/fixtures/reconstruction-runtime/authorities/config-free-bcp-1928-collects-original-catalog.json', 'metadata/source-evidence/catalog/naves-topical-bible.json': 'tests/fixtures/reconstruction-runtime/authorities/config-free-naves-topical-bible-original-catalog.json'})

HISTORICAL_FILES.update({'metadata/source-evidence/catalog/daily-light.json': 'tests/fixtures/reconstruction-runtime/authorities/config-free-daily-light-original-catalog.json'})


def _packet() -> dict:
    raw = PACKET.read_bytes()
    assert sha256(raw).hexdigest() == PACKET_SHA256
    return json.loads(raw)


@pytest.fixture(scope="module")
def historical_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("config-free-historical")
    storage = json.loads((ROOT / ".ocd-storage.json").read_bytes())
    assert Path(storage["library_root"]).is_absolute()
    (root / ".ocd-storage.json").write_text(json.dumps(storage), encoding="utf-8")

    def copy_binding(relative, expected):
        logical = Path(relative)
        assert not logical.is_absolute() and ".." not in logical.parts
        if logical.parts[0] == "raw":
            return  # Actual retained source bytes use the declared storage topology.
        source = ROOT / HISTORICAL_FILES.get(relative, relative)
        raw = historical_bound_bytes(source, expected)
        assert sha256(raw).hexdigest() == expected, relative
        destination = root / logical
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)

    for row in _packet()["entries"]:
        for field in ("work", "state", "source_manifest", "source_profile", "url_evidence", "metadata_evidence"):
            ref = row[field]
            copy_binding(ref["path"], ref["sha256"])
        manifest = json.loads((root / row["source_manifest"]["path"]).read_bytes())
        for authority in manifest["authorities"]:
            if authority["role"] in {"source-attribution", "source-attribution-evidence", "source-support-metadata-rights"}:
                copy_binding(authority["path"], authority["sha256"])
    return root


def test_historical_metadata_preserves_every_packet_binding(historical_root):
    for row in _packet()["entries"]:
        for field in ("work", "state", "source_manifest", "source_profile", "url_evidence", "metadata_evidence"):
            ref = row[field]
            assert sha256((historical_root / ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
    current = (ROOT / "sources/devotionals/daily-light/daily-light.source-manifest.json").read_bytes()
    assert sha256(current).hexdigest() == "7bcbfa603339668ca03fc0164cc3a8d52a3ae8349e1dc6d0533cc4582e5680bf"
    assert current != (historical_root / "sources/devotionals/daily-light/daily-light.source-manifest.json").read_bytes()


def test_three_exact_extracted_member_sets(historical_root) -> None:
    packet = _packet()
    assert len(packet["entries"]) == 3
    for row in packet["entries"]:
        retained, fields, evidence, _ = bind_config_free_multi(
            historical_root, row, load_work(historical_root / row["work"]["path"])
        )
        assert fields["source_kind"] == "retained-member-set"
        assert [item["path"] for item in retained] == [item["path"] for item in row["primary_sources"]]
        assert all(not item["path"].lower().endswith(".zip") for item in retained)
        assert row["source_manifest"]["path"] in evidence
        if row["work_id"] == "naves-topical-bible":
            assert "raw/naves_topical/Nave.zip" in evidence


@pytest.mark.parametrize("change", ["drop", "hash", "zip", "url", "profile", "scope", "rights"])
def test_changed_extracted_source_claim_fails(change: str, historical_root) -> None:
    row = copy.deepcopy(_packet()["entries"][0])
    work = load_work(historical_root / row["work"]["path"])
    if change == "drop":
        row["primary_sources"].pop()
    elif change == "hash":
        row["primary_sources"][0]["sha256"] = "0" * 64
    elif change == "zip":
        row["primary_sources"][0]["path"] = "raw/package.zip"
    elif change == "url":
        row["url"] = "https://example.invalid/other"
    elif change == "profile":
        row["source_profile"]["sha256"] = "0" * 64
    elif change == "scope":
        row["source_scope"] = "complete print edition"
    else:
        row["warnings"] = []
    with pytest.raises(PipelineError):
        bind_config_free_multi(historical_root, row, work)


def test_guarded_stager_writes_four_sidecars_per_work(historical_root) -> None:
    result = prepare(historical_root, _packet(), "2026-09-26T00:00:00Z")
    assert len(result) == 3
    assert all(len(item["output"]) == 4 for item in result)


@pytest.mark.parametrize("work_id", ("bcp-1928-collects", "naves-topical-bible"))
def test_held_catalog_byte_drift_is_rejected(historical_root, work_id):
    row = next(item for item in _packet()["entries"] if item["work_id"] == work_id)
    work = load_work(historical_root / row["work"]["path"])
    bind_config_free_multi(historical_root, row, work)
    catalog = historical_root / row["metadata_evidence"]["path"]
    original = catalog.read_bytes()
    try:
        catalog.write_bytes(original + b"\n")
        with pytest.raises(PipelineError, match="catalog missing or changed"):
            bind_config_free_multi(historical_root, row, work)
    finally:
        catalog.write_bytes(original)
