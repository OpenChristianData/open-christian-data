"""Verify exact source-profile fallback for three historical manifest exceptions."""
from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest

from build.tools.library_exclusive_manifest_binding import bind_exclusive_manifest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/manifest-exception-three-sidecar-packet-20260926.json"


@pytest.fixture(scope="module")
def historical_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("original-manifest-exceptions")
    (root / ".ocd-storage.json").write_bytes((ROOT / ".ocd-storage.json").read_bytes())
    original = ROOT / "tests/fixtures/reconstruction-runtime/authorities/wesley-manifest-exception-original.source-manifest.json"
    historical_catalogs = {'metadata/source-evidence/catalog/john-wesley-sermons.json': 'tests/fixtures/reconstruction-runtime/authorities/wesley-exception-john-wesley-sermons-original-catalog.json'}
    historical_catalogs.update({
        f"metadata/source-evidence/catalog/{wid}.json":
            f"tests/fixtures/reconstruction-runtime/authorities/manifest-exception-{wid}-original-catalog.json"
        for wid in ("augustines-confessions", "luthers-large-catechism")
    })

    def copy_binding(ref):
        relative = Path(ref["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        if relative.parts[0] == "raw":
            return
        source = original if row["work_id"] == "john-wesley-sermons" and relative.as_posix() == row["source_manifest"]["path"] else ROOT / historical_catalogs.get(relative.as_posix(), relative)
        raw = source.read_bytes()
        assert sha256(raw).hexdigest() == ref["sha256"]
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    for row in json.loads(PACKET.read_bytes())["entries"]:
        for field in ("source_manifest", "metadata_evidence", "url_evidence"):
            copy_binding(row[field])
        manifest = json.loads((root / row["source_manifest"]["path"]).read_bytes())
        for authority in manifest["authorities"]:
            if authority.get("role") in {"complete-source-feature-profile", "source-attribution-readme",
                                         "source-attribution", "rights-evidence"}:
                copy_binding(authority)
    return root


def test_current_wesley_successor_rejects_original_packet():
    row, work = _case("john-wesley-sermons")
    with pytest.raises(PipelineError, match="source manifest missing or changed"):
        bind_exclusive_manifest(ROOT, row, work)


def _case(work_id: str) -> tuple[dict, dict]:
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    row = next(entry for entry in packet["entries"] if entry["work_id"] == work_id)
    return copy.deepcopy(row), load_work(ROOT / row["work"]["path"])


@pytest.mark.parametrize("work_id", [
    "augustines-confessions",
    "john-wesley-sermons",
    "luthers-large-catechism",
])
def test_exact_manifest_source_and_profile_are_bound(work_id: str, historical_root) -> None:
    row, work = _case(work_id)
    retained, source, evidence, stage_evidence = bind_exclusive_manifest(
        historical_root, row, work
    )
    assert source["source_path"] == row["primary_source"]["path"]
    assert retained[0]["sha256"] == row["primary_source"]["sha256"]
    assert any(path.endswith("reconstruction-profile.json") for path in evidence)
    assert any(path.endswith("reconstruction-profile.json") for path in stage_evidence)
    assert not source["source_path"].endswith(".zip")


def test_confessions_alternate_bom_witness_must_be_disclosed(historical_root) -> None:
    row, work = _case("augustines-confessions")
    row["warnings"] = row["warnings"][:1]
    with pytest.raises(PipelineError, match="alternate Gutenberg witness"):
        bind_exclusive_manifest(historical_root, row, work)


def test_manifest_source_mutation_fails_closed(historical_root) -> None:
    row, work = _case("john-wesley-sermons")
    row["primary_source"]["sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="exactly one manifest primary"):
        bind_exclusive_manifest(historical_root, row, work)

