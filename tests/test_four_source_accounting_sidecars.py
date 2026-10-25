"""Check four-work retained-source boundaries and guarded rollback."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from build.tools import install_four_source_accounting_sidecars as installer
from build.tools import prepare_four_source_accounting_sidecars as four
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-09-26T00:00:00Z"

HISTORICAL_ORIGINALS = {
    'metadata/source-evidence/catalog/westminster-shorter-catechism.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-westminster-shorter-catechism-original-catalog.json', '66f9a2993c23dc66343814ecfc5f3091160119dfd654a353e9bc76574966f636'),
    'library/works/drc/state.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-before-drc.state.json', '0cd22ede713b327aa24f658defdcad2a161013f004c7b84e23d358163d6cdae8'),
    'library/works/drc/work.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-before-drc.work.json', '49c34c83e472215125d7e481ead11399aeafe8b94f71ab57e29ea89b4d3dc2e8'),
    'library/works/maclaren-expositions/state.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-before-maclaren-expositions.state.json', '927b562a5f7973e5ee892263440a796537137f8095e47822431c396a9d0d7ce5'),
    'library/works/maclaren-expositions/work.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-before-maclaren-expositions.work.json', 'f8bf1240ace07f3e436fcf1bdc5dfbdbd4976d26b502199efa427a25fc98c6c2'),
    'library/works/robertson-word-pictures-vol1/state.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-before-robertson-word-pictures-vol1.state.json', '2e810af1cfb517257d2438b7741134bdd954b52572b33b9b514b9f4b9f85272a'),
    'library/works/robertson-word-pictures-vol1/work.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-before-robertson-word-pictures-vol1.work.json', 'cd9466b04c6180f27729857c0d86fbdf8ad99799e39832cb0bc88c948bf8c8b0'),
    'library/works/westminster-shorter-catechism/state.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-before-westminster-shorter-catechism.state.json', 'cf22f0ed243265dd6c224fe517fbe694219c5e3418b554c14a49d6ba8f9289b7'),
    'library/works/westminster-shorter-catechism/work.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-before-westminster-shorter-catechism.work.json', '0241f8661fa1491de5fc39a811fb3cba5887e6010211568e8f4be5c2f17beb8b'),
    'sources/commentaries/robertson-word-pictures-vol1/README.source.md': ('tests/fixtures/reconstruction-runtime/authorities/four-source-before-robertson.README.source.md', '3f806b6d24d489ac0a57934ad8a5fd3142fd3dc2e93357618d5f36405bd6fd49'),
}
HISTORICAL_ORIGINALS.update({'metadata/source-evidence/catalog/drc.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-drc-original-catalog.json', 'ca3f9411bacca73055acda4701deca1915b4018339aac87a39df23d7321db7f4'), 'metadata/source-evidence/catalog/maclaren-expositions.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-maclaren-expositions-original-catalog.json', 'e30be198a6566156a159a2acc3764fe28f136d949daf65877242829c69096389'), 'metadata/source-evidence/catalog/robertson-word-pictures-vol1.json': ('tests/fixtures/reconstruction-runtime/authorities/four-source-robertson-word-pictures-vol1-original-catalog.json', 'e4e44b658e8acbac7866dc5c99085a241074496ae66389d380a39feb4e28d5dc')})


@pytest.fixture
def historical_root(tmp_path: Path) -> Path:
    """Use the exact original identity-only generation in a private supplied-root mirror."""
    root = tmp_path / "historical-root"
    root.mkdir()
    library = resolve_repo_path(ROOT, "raw").parent
    (root / ".ocd-storage.json").write_bytes(
        (json.dumps({"library_root": str(library)}) + "\n").encode())
    packet = json.loads((ROOT / four.PACKET_REL).read_bytes())
    copied = {}
    for route in packet["works"].values():
        for ref in route["evidence"] + list(route["before"].values()):
            relative = ref["path"]
            path = Path(relative)
            assert not path.is_absolute() and ".." not in path.parts
            if path.parts[0] in {"raw", "reports", "exports"}:
                continue
            if relative in HISTORICAL_ORIGINALS:
                fixture, digest = HISTORICAL_ORIGINALS[relative]
                raw = (ROOT / fixture).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == digest
            else:
                raw = (ROOT / relative).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == ref["sha256"]
            if relative in copied:
                assert copied[relative] == raw
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            copied[relative] = raw
    assert set(HISTORICAL_ORIGINALS) <= set(copied)
    assert four.evidence(root) == packet
    return root


def test_four_source_boundaries_and_proposed_forms(historical_root: Path) -> None:
    packet = four.evidence(historical_root)
    outputs = four.proposed(historical_root, packet, NOW)
    assert {wid: len(files) for wid, files in outputs.items()} == {
        "drc": 4, "maclaren-expositions": 18,
        "robertson-word-pictures-vol1": 5, "westminster-shorter-catechism": 6,
    }
    for wid, route in packet["works"].items():
        assert all(not item["path"].lower().endswith(".zip") for item in route["sources"]), wid
    assert [Path(s["path"]).name for s in packet["works"]["drc"]["sources"]] == ["DRC.json"]
    assert len(packet["works"]["maclaren-expositions"]["sources"]) == 15
    assert [s["url"] for s in packet["works"]["robertson-word-pictures-vol1"]["sources"]] == [
        "https://www.ccel.org/ccel/robertson_at/wp_matt.xml",
        "https://www.ccel.org/ccel/robertson_at/wp_mark.xml",
    ]
    wsc = json.loads(outputs["westminster-shorter-catechism"][
        "library/works/westminster-shorter-catechism/work.json"])
    assert len(wsc["textual_forms"]) == 3
    assert len({f["textual_form_id"] for f in wsc["textual_forms"]}) == 3
    assert all(len(f["editions"]) == 1 and len(f["editions"][0]["acquisition_ids"]) == 1
               for f in wsc["textual_forms"])
    wsc_acquisitions = [json.loads(raw) for rel, raw in outputs["westminster-shorter-catechism"].items()
                        if "/acquisitions/" in rel]
    assert len({item["rights"] for item in wsc_acquisitions}) == 3
    assert all("rights" in item and len(item["retained_files"]) == 1 for item in wsc_acquisitions)


def test_changed_provider_url_cannot_reuse_packet(historical_root: Path) -> None:
    packet = copy.deepcopy(four.evidence(historical_root))
    packet["works"]["drc"]["sources"][0]["url"] = "https://example.invalid/drc.json"
    with pytest.raises(PipelineError, match="differs from reviewed packet"):
        four.proposed(historical_root, packet, NOW)


def test_post_swap_validation_failure_restores_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, historical_root: Path) -> None:
    wid = "drc"
    packet = four.evidence(historical_root)
    outputs = four.proposed(historical_root, packet, NOW)[wid]
    prefix = Path("library/works") / wid
    target = tmp_path / prefix
    staged_work = tmp_path / "stage" / prefix
    target.parent.mkdir(parents=True)
    staged_work.parent.mkdir(parents=True)
    shutil.copytree(_io_path(historical_root / prefix), _io_path(target))
    shutil.copytree(_io_path(historical_root / prefix), _io_path(staged_work))
    before = _files(target)
    items = []
    for rel, raw in outputs.items():
        staged = _io_path(tmp_path / "stage" / rel)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(raw)
        original = historical_root / rel
        items.append({"path": rel,
                      "before_sha256": hashlib.sha256(original.read_bytes()).hexdigest() if original.is_file() else None,
                      "proposed_sha256": hashlib.sha256(raw).hexdigest()})

    def fail_validation(*_args: object, **_kwargs: object) -> None:
        raise PipelineError("injected post-swap validation failure")

    monkeypatch.setattr(installer, "validate_acquisition", fail_validation)
    with pytest.raises(PipelineError, match="injected post-swap"):
        installer._install_one(tmp_path, tmp_path / "stage", {"work_id": wid, "files": items})
    assert _files(target) == before
    journals = list((tmp_path / "library/.sidecar-operations").glob("four-source-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"
