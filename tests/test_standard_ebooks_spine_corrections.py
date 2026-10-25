"""Focused checks for the staged Standard Ebooks source/accounting correction."""
from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
from hashlib import sha256

import build.tools.install_standard_ebooks_spine_corrections as installer

import pytest

from build.tools.install_standard_ebooks_spine_corrections import preflight
from build.tools.prepare_standard_ebooks_spine_corrections import IDS, PACKET_REL
from ocd_kernel.library._common import PipelineError, load_json, sha256_file
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[1]
STAGE = Path("C:/Scratch/Open Christian Data/standard-ebooks-four-spine-correction-stage-20260926")


FROZEN_RECEIPT_SHA256 = "839883b01fb914868748d86c939ea3856a74a5a953d580cbbb17b80bb82f747e"

HISTORICAL_CATALOGS = {'metadata/source-evidence/catalog/george-macdonald-unspoken-sermons.json': 'tests/fixtures/reconstruction-runtime/authorities/se-spine-george-macdonald-unspoken-sermons-original-catalog.json', 'metadata/source-evidence/catalog/heretics.json': 'tests/fixtures/reconstruction-runtime/authorities/se-spine-heretics-original-catalog.json', 'metadata/source-evidence/catalog/orthodoxy.json': 'tests/fixtures/reconstruction-runtime/authorities/se-spine-orthodoxy-original-catalog.json', 'metadata/source-evidence/catalog/the-everlasting-man.json': 'tests/fixtures/reconstruction-runtime/authorities/se-spine-the-everlasting-man-original-catalog.json'}


def _frozen_bytes(raw: bytes, digest: str) -> bytes:
    lf = raw.replace(b"\r\n", b"\n")
    for candidate in (raw, lf, lf.replace(b"\n", b"\r\n")):
        if sha256(candidate).hexdigest() == digest:
            return candidate
    raise AssertionError("Historical source authority differs from its complete frozen SHA")


def _acquired_context(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(resolve_repo_path(ROOT, "raw").parent)}),
        encoding="utf-8", newline="\n")
    receipt_bytes = (STAGE / "receipt.json").read_bytes()
    assert sha256(receipt_bytes).hexdigest() == FROZEN_RECEIPT_SHA256
    receipt = json.loads(receipt_bytes)
    packet_bytes = _frozen_bytes((ROOT / PACKET_REL).read_bytes(), receipt["packet_sha256"])
    packet = json.loads(packet_bytes)
    original = packet["original_packet"]
    authorities = {original["path"]: _frozen_bytes((ROOT / original["path"]).read_bytes(), original["sha256"]),
                   PACKET_REL: packet_bytes, installer.RECEIPT_REL: receipt_bytes}
    for row in packet["works"]:
        for relative, digest in row["before"].items():
            source = ROOT / "tests/fixtures/se-four-spine-preimages" / relative
            data = source.read_bytes()
            assert sha256(data).hexdigest() == digest
            authorities[relative] = data
        for reference in row["authority"].values():
            authorities[reference["path"]] = _frozen_bytes(
                (ROOT / HISTORICAL_CATALOGS.get(reference["path"], reference["path"])).read_bytes(), reference["sha256"])
    for relative, data in authorities.items():
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def test_exact_opf_spine_and_complete_support() -> None:
    packet = load_json(ROOT / PACKET_REL)
    expected = dict(zip(IDS, (49, 26, 16, 26), strict=True))
    for row in packet["works"]:
        source = row["ordered_text_members"]
        support = row["support_members"]
        assert len(source) == expected[row["work_id"]]
        assert all(item["path"].endswith(".xhtml") for item in source)
        assert not set(item["path"] for item in source) & set(item["path"] for item in support)
        assert len([item for item in support if item["path"].endswith(".svg")]) >= 3
        assert row["opf"]["path"] in {item["path"] for item in support}


def test_staged_or_installed_generation_is_exact(tmp_path: Path) -> None:
    root = _acquired_context(tmp_path)
    receipt = load_json(root / installer.RECEIPT_REL)
    for item in receipt["files"]:
        assert sha256_file(_io_path(STAGE / item["path"])) == item["proposed_sha256"]
    assert len(preflight(root, STAGE)["files"]) == 20
    assert len(preflight(root, STAGE, "heretics")["files"]) == 20


def test_current_accepted_generation_requires_its_dedicated_rebind() -> None:
    with pytest.raises(PipelineError, match="accepted TEI; dedicated acceptance rebind required"):
        preflight(ROOT, STAGE)


def test_unknown_work_fails_closed() -> None:
    with pytest.raises(PipelineError, match="unexpected work"):
        preflight(ROOT, STAGE, "unknown-work")


def test_install_rolls_back_complete_work_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, stage = tmp_path / "repo", tmp_path / "stage"
    rel = "library/works/heretics/work.json"
    current, proposed = root / rel, stage / rel
    current.parent.mkdir(parents=True)
    proposed.parent.mkdir(parents=True)
    current.write_text("before", encoding="utf-8")
    proposed.write_text("after", encoding="utf-8")
    receipt = {"files": [{"path": rel, "before_sha256": sha256_file(current),
                          "proposed_sha256": sha256_file(proposed)}]}
    monkeypatch.setattr(installer, "preflight", lambda *_: receipt)
    monkeypatch.setattr(installer, "acquire_jsonl_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(installer, "validate_state", lambda *_args, **_kwargs: (_ for _ in ()).throw(PipelineError("injected validation failure")))
    with pytest.raises(PipelineError, match="injected validation failure"):
        installer.install_one(root, stage, "heretics")
    assert current.read_text(encoding="utf-8") == "before"
    journals = list((root / "library/.sidecar-operations").glob("*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"
