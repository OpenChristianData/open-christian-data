"""Fail closed on config-free, exclusive source-manifest acquisition claims."""
from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest

from tests.runtime_candidate_baselines import historical_bound_bytes

from build.tools.library_exclusive_manifest_binding import bind_exclusive_manifest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/exclusive-single-manifest-21-sidecar-batch-20260926.json"


HISTORICAL_FILES = {'sources/bible-text/darby/darby.source-manifest.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-darby.source-manifest.json', 'sources/didache-prayers/didache-prayers.source-manifest.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-didache-prayers.source-manifest.json', 'sources/structured-text/donne-devotions-upon-emergent-occasions/LIB-068.source-manifest.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-donne-devotions-upon-emergent-occasions.source-manifest.json', 'sources/structured-text/donne-devotions-upon-emergent-occasions/LIB-068.README.source.md': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-donne.README.source.md'}
HISTORICAL_PINS = {'sources/bible-text/darby/darby.source-manifest.json': 'b42e3c7a58352aee37f8e898e3f9caf214b5bb9b91a840034d04631f8af74797', 'sources/didache-prayers/didache-prayers.source-manifest.json': '7cf00288bf391ffc7d1b54376cef07e107ff568dd536f6d68cd033e2c418fcdc', 'sources/structured-text/donne-devotions-upon-emergent-occasions/LIB-068.source-manifest.json': '16cff7100f7bc7c309e6202111800785c747904a0f6c8e43fdb77783fc78f52d', 'sources/structured-text/donne-devotions-upon-emergent-occasions/LIB-068.README.source.md': '4aeb7dd03b5845d23cb4eedcc8e891ce55753ab67b93e66c172f6f567774dcc9'}
HISTORICAL_WORKS = {"darby", "didache-prayers", "donne-devotions-upon-emergent-occasions"}
HISTORICAL_FILES.update({'metadata/source-evidence/catalog/darby.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-darby-original-catalog.json', 'metadata/source-evidence/catalog/didache-prayers.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-didache-prayers-original-catalog.json', 'metadata/source-evidence/catalog/eastons-bible-dictionary.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-eastons-bible-dictionary-original-catalog.json', 'metadata/source-evidence/catalog/hitchcocks-bible-names-dictionary.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-hitchcocks-bible-names-dictionary-original-catalog.json', 'metadata/source-evidence/catalog/schleitheim-confession-1527.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-schleitheim-confession-1527-original-catalog.json', 'metadata/source-evidence/catalog/smiths-bible-dictionary.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-smiths-bible-dictionary-original-catalog.json', 'metadata/source-evidence/catalog/sum-of-saving-knowledge.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-sum-of-saving-knowledge-original-catalog.json', 'metadata/source-evidence/catalog/torreys-topical-textbook.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-torreys-topical-textbook-original-catalog.json'})
HISTORICAL_PINS.update({'metadata/source-evidence/catalog/darby.json': '0a9785ebfb13b8810a6f53509132ab439c3db6472b0b30e82e6c1d6301ec91bb', 'metadata/source-evidence/catalog/didache-prayers.json': '74a4a1e6d15df763d1b8cb26ef596dfa97ca0bba145c59d47e9c2f356804f427', 'metadata/source-evidence/catalog/eastons-bible-dictionary.json': 'c0609dc4097be4a771baf1594b0fb0224a1435cd56225563189ae2150988bfe4', 'metadata/source-evidence/catalog/hitchcocks-bible-names-dictionary.json': '22808958528286cb83cd701f6b3665906e0817a986d23ba6e2bf95c0b7624f5f', 'metadata/source-evidence/catalog/schleitheim-confession-1527.json': '19664d304825210ae9fe92cfb30035c707dbd8e1d1bfc4a71e52381e01a9c558', 'metadata/source-evidence/catalog/smiths-bible-dictionary.json': '8709cf29750511ecd514c2d5b347d6e4a52cb0312d297506a3296218cc8299ee', 'metadata/source-evidence/catalog/sum-of-saving-knowledge.json': '5929f6aff9fbcc06e21bf7d4cae864b84103ac47a53bfe1e98298ab5c0075738', 'metadata/source-evidence/catalog/torreys-topical-textbook.json': 'b721f9be30ecea5f27743391091f62f2fcf8e16bf9465671dc204fee7e04436e'})
HISTORICAL_FILES.update({'metadata/source-evidence/catalog/baltimore-catechism-no-2.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-baltimore-catechism-no-2-original-catalog.json', 'metadata/source-evidence/catalog/catechism-for-young-children.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-catechism-for-young-children-original-catalog.json', 'metadata/source-evidence/catalog/donne-devotions-upon-emergent-occasions.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-donne-devotions-upon-emergent-occasions-original-catalog.json', 'metadata/source-evidence/catalog/newman-apologia-pro-vita-sua.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-newman-apologia-pro-vita-sua-original-catalog.json', 'metadata/source-evidence/catalog/schaff-history-vol-1.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-schaff-history-vol-1-original-catalog.json', 'metadata/source-evidence/catalog/schaff-history-vol-2.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-schaff-history-vol-2-original-catalog.json', 'metadata/source-evidence/catalog/schaff-history-vol-3.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-schaff-history-vol-3-original-catalog.json', 'metadata/source-evidence/catalog/schaff-history-vol-5.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-schaff-history-vol-5-original-catalog.json', 'metadata/source-evidence/catalog/schaff-history-vol-6.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-schaff-history-vol-6-original-catalog.json', 'metadata/source-evidence/catalog/schaff-history-vol-7.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-schaff-history-vol-7-original-catalog.json', 'metadata/source-evidence/catalog/schaff-history-vol-8.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-schaff-history-vol-8-original-catalog.json', 'metadata/source-evidence/catalog/westminster-larger-catechism.json': 'tests/fixtures/reconstruction-runtime/authorities/exclusive-westminster-larger-catechism-original-catalog.json'})
HISTORICAL_PINS.update({'metadata/source-evidence/catalog/baltimore-catechism-no-2.json': 'c43470bf34b95e1a819f300cd649265c9c6968e866762a3983892fa499a32653', 'metadata/source-evidence/catalog/catechism-for-young-children.json': 'f1b45436dca6681ef9c0b221ff0522a0d01117a69ef85a779239c1701278eb1a', 'metadata/source-evidence/catalog/donne-devotions-upon-emergent-occasions.json': 'ef2a879f3cd332707ae5f2c9082a9cb8eb15df694236737686bd865a0f241a69', 'metadata/source-evidence/catalog/newman-apologia-pro-vita-sua.json': '55d6711999315053124d21efca8c869c53768d95729bb019e2eff44394a002a3', 'metadata/source-evidence/catalog/schaff-history-vol-1.json': '9e386cbe35c0e1b552a38518a1142455248f7d6642e434c6a8df774212e0be5e', 'metadata/source-evidence/catalog/schaff-history-vol-2.json': '28ffa6357e7f62c4958c5890ff7a8f221ba041b4107837e547446ae512f4118b', 'metadata/source-evidence/catalog/schaff-history-vol-3.json': 'b7b9a15286fb594555ff2b93a7ef8dce067bb9c604f243632e683c199431fdaa', 'metadata/source-evidence/catalog/schaff-history-vol-5.json': '04697d8566002330a135992ccd12f12f554e380ebb95fcf72f55da12ccc05221', 'metadata/source-evidence/catalog/schaff-history-vol-6.json': '19d763085b14e582eeff0b1ddd441ebe1ae76c58ed3746a11730b88ee4b54df8', 'metadata/source-evidence/catalog/schaff-history-vol-7.json': '5d645c1e10bbf2f4ebba8a377ed94374908fe64e59dc18734ff45bb9282fd025', 'metadata/source-evidence/catalog/schaff-history-vol-8.json': 'd48a42166d9fbb921ac0a3c866530f27fe12416f96cfcbde8e542d7a7e623e7f', 'metadata/source-evidence/catalog/westminster-larger-catechism.json': 'e3e7435f5369ed8b93d2e69ed1dde2b368431c210e3a7b1505fe6d39b2687d5d'})
HISTORICAL_CONTEXT_WORKS = HISTORICAL_WORKS | {Path(path).stem for path in HISTORICAL_FILES
    if path.startswith("metadata/source-evidence/catalog/")}


@pytest.fixture(scope="module")
def historical_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("exclusive-original-manifests")
    (root / ".ocd-storage.json").write_bytes((ROOT / ".ocd-storage.json").read_bytes())

    def copy_binding(ref):
        relative = ref["path"]
        logical = Path(relative)
        assert not logical.is_absolute() and ".." not in logical.parts
        if logical.parts[0] in {"raw", "reports", "exports"}:
            return
        raw = historical_bound_bytes(ROOT / HISTORICAL_FILES.get(relative, relative), ref["sha256"])
        assert sha256(raw).hexdigest() == ref["sha256"], relative
        target = root / logical
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    for row in json.loads(PACKET.read_bytes())["entries"]:
        if row["work_id"] not in HISTORICAL_CONTEXT_WORKS:
            continue
        for field in ("source_manifest", "metadata_evidence", "url_evidence"):
            copy_binding(row[field])
        manifest = json.loads((root / row["source_manifest"]["path"]).read_bytes())
        for authority in manifest["authorities"]:
            if authority.get("role") in {"primary-source", "source-attribution-readme",
                                         "source-attribution", "rights-evidence"}:
                copy_binding(authority)
    return root


def test_original_fixture_bytes_preserve_packet_pins(historical_root):
    for relative, expected in HISTORICAL_PINS.items():
        assert sha256((historical_root / relative).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("work_id", sorted(HISTORICAL_WORKS))
def test_current_successor_manifest_rejects_historical_packet(work_id):
    row, work = _entry(work_id)
    with pytest.raises(PipelineError, match="source manifest missing or changed"):
        bind_exclusive_manifest(ROOT, row, work)


def _entry(work_id: str) -> tuple[dict, dict]:
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    row = next(item for item in packet["entries"] if item["work_id"] == work_id)
    return copy.deepcopy(row), load_work(ROOT / row["work"]["path"])


def test_all_21_sources_have_independent_exact_attestations(historical_root) -> None:
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    assert len(packet["entries"]) == 21
    for row in packet["entries"]:
        work = load_work(ROOT / row["work"]["path"])
        retained, fields, evidence, _ = bind_exclusive_manifest(
            historical_root if row["work_id"] in HISTORICAL_CONTEXT_WORKS else ROOT, row, work
        )
        assert len(retained) == 1
        assert fields["source_path"] == row["primary_source"]["path"]
        assert row["metadata_evidence"]["path"] in evidence


@pytest.mark.parametrize("change", ["source", "metadata", "url", "scope", "rights"])
def test_mutated_source_claim_is_rejected(change: str, historical_root) -> None:
    row, work = _entry("sum-of-saving-knowledge")
    if change == "source":
        row["primary_source"]["sha256"] = "0" * 64
    elif change == "metadata":
        row["metadata_evidence"]["sha256"] = "0" * 64
    elif change == "url":
        row["url"] = "https://example.invalid/other-source"
    elif change == "scope":
        row["source_scope"] = "complete print edition"
    else:
        row["warnings"] = []
    with pytest.raises(PipelineError):
        bind_exclusive_manifest(historical_root, row, work)


def test_zip_cannot_be_primary_source(historical_root) -> None:
    row, work = _entry("sum-of-saving-knowledge")
    row["primary_source"]["path"] = "raw/archive/package.zip"
    with pytest.raises(PipelineError):
        bind_exclusive_manifest(historical_root, row, work)


def test_held_catalog_byte_drift_is_rejected(historical_root):
    row, work = _entry("sum-of-saving-knowledge")
    bind_exclusive_manifest(historical_root, row, work)
    catalog = historical_root / row["metadata_evidence"]["path"]
    original = catalog.read_bytes()
    try:
        catalog.write_bytes(original + b"\n")
        with pytest.raises(PipelineError, match="metadata missing or changed"):
            bind_exclusive_manifest(historical_root, row, work)
    finally:
        catalog.write_bytes(original)
