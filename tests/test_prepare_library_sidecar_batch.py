import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from build.tools.prepare_library_sidecar_batch import apply_staged, prepare, stage
from ocd_kernel.library._common import PipelineError, write_json


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, *, collision: bool = False):
    root = tmp_path / "repo"
    work_dir = root / "library/works/alpha"
    work_dir.mkdir(parents=True)
    work = {"schema_version": "2.0", "work_id": "alpha", "title": "Alpha", "evidence": ["sources/alpha/source-manifest.json"], "textual_forms": []}
    state = {"schema_version": "2.0", "work_id": "alpha", "targets": []}
    write_json(work_dir / "work.json", work)
    write_json(work_dir / "state.json", state)
    source_dir = root / "sources/alpha"
    source_dir.mkdir(parents=True)
    durable = tmp_path / "durable"
    write_json(root / ".ocd-storage.json", {"library_root": str(durable)})
    raw = durable / "raw/alpha.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("exact source\n", encoding="utf-8")
    config_path = source_dir / "config.json"
    write_json(config_path, {"resource_id": "alpha", "source_url": "https://example.org/alpha", "language": "en"})
    manifest_path = source_dir / "source-manifest.json"
    source = {"name": "source", "role": "primary-source", "path": "raw/alpha.txt", "bytes": raw.stat().st_size, "sha256": _sha(raw)}
    write_json(manifest_path, {"contract": "ocd-source-manifest-v1", "work_id": "alpha", "authorities": [source, {"name": "config", "role": "work-config", "path": "sources/alpha/config.json", "bytes": config_path.stat().st_size, "sha256": _sha(config_path)}]})
    if collision:
        beta = root / "library/works/beta"
        beta.mkdir()
        write_json(beta / "work.json", {"schema_version": "2.0", "work_id": "beta", "title": "Beta", "evidence": ["sources/alpha/source-manifest.json"], "textual_forms": [{"textual_form_id": "alpha-english", "editions": []}]})
        write_json(beta / "state.json", {"schema_version": "2.0", "work_id": "beta", "targets": []})
    row = {"work_id": "alpha", "work": {"path": "library/works/alpha/work.json", "sha256": _sha(work_dir / "work.json")},
        "state": {"path": "library/works/alpha/state.json", "sha256": _sha(work_dir / "state.json")},
        "source_manifest": {"path": "sources/alpha/source-manifest.json", "sha256": _sha(manifest_path)},
        "config": {"path": "sources/alpha/config.json", "sha256": _sha(config_path)}, "primary_source": source,
        "textual_form_id": "alpha-english", "edition_id": "alpha-electronic", "acquisition_id": "alpha-source",
        "edition_title": "Retained electronic witness", "provider": "Example", "url": "https://example.org/alpha",
        "language": "en", "media_type": "text/plain", "source_scope": "Complete retained test file."}
    packet_path = tmp_path / "packet.json"
    write_json(packet_path, {"contract": "ocd-library-sidecar-batch-v1", "entries": [row]})
    return root, packet_path, raw


def test_stages_and_validates_without_canonical_mutation(tmp_path):
    root, packet, _ = _fixture(tmp_path)
    before = _sha(root / "library/works/alpha/work.json")
    receipt = stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert len(receipt["entries"]) == 1
    assert len(receipt["entries"][0]["files"]) == 3
    assert _sha(root / "library/works/alpha/work.json") == before
    assert not (root / "library/works/alpha/forms").exists()


@pytest.mark.parametrize("extension", [".zip", ".ZIP"])
def test_manifest_branch_rejects_zip_primary_source(tmp_path, extension):
    root, packet, _ = _fixture(tmp_path)
    archive = tmp_path / "durable/raw" / f"alpha{extension}"
    archive.write_bytes(b"retained package")
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    source = dict(row["primary_source"], path=f"raw/alpha{extension}",
                  bytes=archive.stat().st_size, sha256=_sha(archive))
    row["primary_source"] = source
    row["media_type"] = "application/zip"
    manifest_path = root / row["source_manifest"]["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["authorities"][0] = source
    write_json(manifest_path, manifest)
    row["source_manifest"]["sha256"] = _sha(manifest_path)
    write_json(packet, value)

    with pytest.raises(PipelineError, match="ZIP package cannot be a primary source"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_changed_member_fails_before_stage_write(tmp_path):
    root, packet, raw = _fixture(tmp_path)
    raw.write_text("changed", encoding="utf-8")
    with pytest.raises(PipelineError, match="primary source bytes/hash differ"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_global_identity_collision_fails_before_stage_write(tmp_path):
    root, packet, _ = _fixture(tmp_path, collision=True)
    with pytest.raises(PipelineError, match="duplicate global forms ID"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_stale_work_rejected_before_apply(tmp_path):
    root, packet, _ = _fixture(tmp_path)
    staged = tmp_path / "stage"
    stage(root, packet, staged, "2026-09-25T00:00:00Z")
    work_path = root / "library/works/alpha/work.json"
    changed = json.loads(work_path.read_text(encoding="utf-8"))
    changed["title"] = "Changed"
    write_json(work_path, changed)
    with pytest.raises(PipelineError, match="missing or changed"):
        apply_staged(root, packet, staged)
    assert not (root / "library/works/alpha/forms").exists()


def test_joint_stage_and_receipt_tamper_rejected(tmp_path):
    root, packet, _ = _fixture(tmp_path)
    staged = tmp_path / "stage"
    stage(root, packet, staged, "2026-09-25T00:00:00Z")
    acq = staged / "library/works/alpha/forms/alpha-english/editions/alpha-electronic/acquisitions/alpha-source.json"
    changed = json.loads(acq.read_text(encoding="utf-8"))
    changed["provider"] = "Altered"
    write_json(acq, changed)
    receipt_path = staged / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["entries"][0]["files"][2]["proposed_sha256"] = _sha(acq)
    write_json(receipt_path, receipt)
    with pytest.raises(PipelineError, match="differs from reviewed packet"):
        apply_staged(root, packet, staged)
    assert not (root / "library/works/alpha/forms").exists()


def test_guarded_apply_installs_validated_sidecars(tmp_path):
    root, packet, _ = _fixture(tmp_path)
    staged = tmp_path / "stage"
    stage(root, packet, staged, "2026-09-25T00:00:00Z")
    result = apply_staged(root, packet, staged)
    assert [item["work_id"] for item in result["installed"]] == ["alpha"]
    assert (root / "library/works/alpha/forms/alpha-english/editions/alpha-electronic/acquisitions/alpha-source.json").is_file()
    assert json.loads((root / "library/works/alpha/state.json").read_text(encoding="utf-8"))["targets"][0]["stage"] == "acquired"


def test_first_rename_failure_keeps_original_work(tmp_path, monkeypatch):
    root, packet, _ = _fixture(tmp_path)
    staged = tmp_path / "stage"
    stage(root, packet, staged, "2026-09-25T00:00:00Z")
    target = root / "library/works/alpha"
    before = {name: _sha(target / name) for name in ("work.json", "state.json")}
    original_rename = Path.rename
    def fail_first_rename(path, target_path):
        if path == target:
            raise OSError("injected first rename failure")
        return original_rename(path, target_path)
    monkeypatch.setattr(Path, "rename", fail_first_rename)
    with pytest.raises(OSError, match="injected first rename failure"):
        apply_staged(root, packet, staged)
    assert target.is_dir()
    assert {name: _sha(target / name) for name in before} == before
    assert not (target / "forms").exists()


def test_post_swap_validation_failure_restores_original(tmp_path, monkeypatch):
    import build.tools.prepare_library_sidecar_batch as batch
    root, packet, _ = _fixture(tmp_path)
    staged = tmp_path / "stage"
    stage(root, packet, staged, "2026-09-25T00:00:00Z")
    target = root / "library/works/alpha"
    before = {name: _sha(target / name) for name in ("work.json", "state.json")}
    original_validate = batch.validate_state
    def fail_live(path, *, root):
        if Path(root).name == "repo":
            raise PipelineError("injected live validation failure")
        return original_validate(path, root=root)
    monkeypatch.setattr(batch, "validate_state", fail_live)
    with pytest.raises(PipelineError, match="injected live validation failure"):
        apply_staged(root, packet, staged)
    assert target.is_dir()
    assert {name: _sha(target / name) for name in before} == before
    assert not (target / "forms").exists()


def test_live_apply_validates_deep_windows_acquisition_path(tmp_path):
    deep = tmp_path / ("deep" * 25)
    deep.mkdir()
    root, packet, _ = _fixture(deep)
    staged = deep / "stage"
    stage(root, packet, staged, "2026-09-25T00:00:00Z")
    acquisition = root / "library/works/alpha/forms/alpha-english/editions/alpha-electronic/acquisitions/alpha-source.json"
    assert len(str(acquisition)) > 260
    result = apply_staged(root, packet, staged)
    assert len(result["installed"]) == 1
    assert batch_acquisition_exists(acquisition)
    from ocd_kernel.library.identities import discover_library
    from ocd_kernel.library.state import validate_state
    assert [item.work_id for item in discover_library(root)] == ["alpha"]
    assert validate_state(root / "library/works/alpha/state.json", root=root)["work_id"] == "alpha"

def batch_acquisition_exists(path):
    from ocd_kernel.tei.install_accepted import _io_path
    return _io_path(path).is_file()


def _receipt_fixture(tmp_path):
    root, packet, _ = _fixture(tmp_path)
    durable = tmp_path / "durable"
    source_dir = durable / "raw/openmgh/vol1"
    (source_dir / "tei").mkdir(parents=True)
    xml = source_dir / "tei/vol1.xml"
    xml.write_bytes(b"<TEI xml:id='x1'>exact</TEI>")
    archive = source_dir / "vol1.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("vol1.xml", xml.read_bytes())
    receipt_path = source_dir / "acquisition-receipt.json"
    receipt = {"schema": "ocd-acquisition-source-receipt-v1", "source_id": "vol1",
        "work_edition": "Test Volume", "source_url": "https://example.org/vol1.zip",
        "package": {"path": "raw/openmgh/vol1/vol1.zip", "bytes": archive.stat().st_size, "sha256": _sha(archive)},
        "verification": {"member_count": 1}}
    write_json(receipt_path, receipt)
    work_path = root / "library/works/alpha/work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    locator = "raw/openmgh/vol1/tei/vol1.xml#x1"
    work["evidence"] = ["raw/openmgh/vol1/vol1.zip", locator, "raw/openmgh/vol1/acquisition-receipt.json"]
    write_json(work_path, work)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    row = packet_doc["entries"][0]
    for key in ("source_manifest", "config", "language"):
        row.pop(key)
    row["work"]["sha256"] = _sha(work_path)
    row["acquisition_receipt"] = {"path": "raw/openmgh/vol1/acquisition-receipt.json", "sha256": _sha(receipt_path)}
    row["primary_source"] = {"name": "retained-openmgh-tei", "role": "primary-source", "path": "raw/openmgh/vol1/tei/vol1.xml", "bytes": xml.stat().st_size, "sha256": _sha(xml)}
    row["archive_member"] = "vol1.xml"
    row["url"] = "https://example.org/vol1.zip"
    row["containing_source"] = {"title": "Test Volume", "locator": locator, "evidence": [locator, "raw/openmgh/vol1/vol1.zip", "raw/openmgh/vol1/acquisition-receipt.json"]}
    row["source_scope"] = ("Complete acquired containing-source package and its extracted TEI member; "
                           f"existing work association locators: {locator}. These locators are evidence "
                           "for accounting, not an adopted complete child extraction or TEI acceptance.")
    write_json(packet, packet_doc)
    return root, packet, xml, archive, receipt_path


def test_receipt_branch_binds_archive_member_and_locator(tmp_path):
    root, packet, xml, archive, _ = _receipt_fixture(tmp_path)
    receipt = stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    acq_rel = receipt["entries"][0]["files"][2]["path"]
    acquisition = json.loads((tmp_path / "stage" / acq_rel).read_text(encoding="utf-8"))
    assert acquisition["source_path"] == "raw/openmgh/vol1/tei/vol1.xml"
    assert acquisition["source_bytes"] == xml.stat().st_size
    assert acquisition["source_sha256"] == _sha(xml)
    assert acquisition["source_scope"].startswith("Extracted TEI XML raw/openmgh/vol1/tei/vol1.xml is the retained text source")
    assert "Complete acquired containing-source package" not in acquisition["source_scope"]
    assert "raw/openmgh/vol1/tei/vol1.xml#x1" in acquisition["source_scope"]
    assert "not an adopted complete child extraction or TEI acceptance" in acquisition["source_scope"]
    assert len(acquisition["retained_files"]) == 2
    assert acquisition["retained_files"][0]["path"] == "raw/openmgh/vol1/vol1.zip"
    assert acquisition["retained_files"][0]["sha256"] == _sha(archive)
    assert "package" in acquisition["retained_files"][0]["scope"]
    assert acquisition["retained_files"][1]["scope"] == acquisition["source_scope"]


def test_receipt_branch_rejects_package_centered_scope_drift(tmp_path):
    root, packet, _, _, _ = _receipt_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    value["entries"][0]["source_scope"] = "Complete ZIP and XML without an exact member declaration."
    write_json(packet, value)
    with pytest.raises(PipelineError, match="openMGH source scope differs"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_receipt_branch_rejects_archive_member_drift(tmp_path):
    root, packet, xml, archive, receipt_path = _receipt_fixture(tmp_path)
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("vol1.xml", b"different")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["package"] = {"path": "raw/openmgh/vol1/vol1.zip", "bytes": archive.stat().st_size, "sha256": _sha(archive)}
    write_json(receipt_path, receipt)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    packet_doc["entries"][0]["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    write_json(packet, packet_doc)
    with pytest.raises(PipelineError, match="extracted XML differs from archive member"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_receipt_branch_rejects_dangling_existing_locator(tmp_path):
    root, packet, _, _, _ = _receipt_fixture(tmp_path)
    work_path = root / "library/works/alpha/work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["evidence"] = [item.replace("#x1", "#missing") for item in work["evidence"]]
    write_json(work_path, work)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    row = packet_doc["entries"][0]
    row["work"]["sha256"] = _sha(work_path)
    row["containing_source"]["locator"] = row["containing_source"]["locator"].replace("#x1", "#missing")
    row["containing_source"]["evidence"] = [item.replace("#x1", "#missing") for item in row["containing_source"]["evidence"]]
    write_json(packet, packet_doc)
    with pytest.raises(PipelineError, match="source locator must resolve uniquely"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_normal_root_discovers_very_long_acquisition_path(tmp_path):
    from ocd_kernel.library.identities import discover_library
    from ocd_kernel.library.state import validate_state
    from ocd_kernel.library._common import io_path
    root = tmp_path / "repo"
    wid = "long-work-" + "a" * 65
    form_id, edition_id, acq_id = wid + "-form", wid + "-edition", wid + "-acquired"
    work_root = root / "library/works" / wid
    source = root / "raw/source.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    acq_rel = f"library/works/{wid}/forms/{form_id}/editions/{edition_id}/acquisitions/{acq_id}.json"
    acquisition = root / acq_rel
    assert len(str(acquisition)) > 350
    write_json(work_root / "work.json", {"schema_version": "2.0", "work_id": wid, "title": "Long work", "evidence": ["raw/source.txt"], "textual_forms": [{"textual_form_id": form_id, "editions": [{"edition_id": edition_id, "title": "Electronic witness", "acquisition_ids": [acq_id]}]}]})
    write_json(acquisition, {"schema_version": "2.0", "acquisition_id": acq_id, "edition_id": edition_id, "provider": "Example", "url": "https://example.org/source", "retained_files": [{"path": "raw/source.txt", "bytes": 6, "sha256": _sha(source), "media_type": "text/plain"}]})
    write_json(work_root / "state.json", {"schema_version": "2.0", "work_id": wid, "targets": [{"target_id": acq_id, "target_type": "acquisition", "stage": "acquired", "updated_at": "2026-09-25T00:00:00Z", "evidence": [acq_rel]}]})
    assert io_path(acquisition).is_file()
    assert [item.work_id for item in discover_library(root)] == [wid]
    assert validate_state(work_root / "state.json", root=root)["work_id"] == wid


def _direct_member_fixture(tmp_path):
    root, packet, _ = _fixture(tmp_path)
    durable = tmp_path / "durable"
    source_dir = durable / "raw/docsouth/l001-alpha"
    source_dir.mkdir(parents=True)
    xml = source_dir / "alpha.xml"
    xml.write_bytes(b"<TEI.2><teiHeader><fileDesc><titleStmt><title>Alpha: Electronic Edition.</title><author>Alpha Author</author></titleStmt></fileDesc></teiHeader><text><body><p>Exact text.</p></body></text></TEI.2>")
    receipt_path = source_dir / "acquisition-receipt.json"
    member_rel = "raw/docsouth/l001-alpha/alpha.xml"
    receipt_rel = "raw/docsouth/l001-alpha/acquisition-receipt.json"
    rights = "Provider rights statement retained without a clearance claim."
    receipt = {"schema": "ocd-acquisition-source-receipt-v1", "source_id": "docsouth-alpha",
               "manifest_row": "L001", "work": "Alpha", "author": "Alpha Author",
               "source_url": "https://example.org/alpha.xml",
               "member": {"path": member_rel, "bytes": xml.stat().st_size, "sha256": _sha(xml)},
               "rights": rights}
    write_json(receipt_path, receipt)
    work_path = root / "library/works/alpha/work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["evidence"] = [member_rel, receipt_rel, "research/MANIFEST.md#L001"]
    write_json(work_path, work)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    row = packet_doc["entries"][0]
    for key in ("source_manifest", "config", "language"):
        row.pop(key)
    row["work"]["sha256"] = _sha(work_path)
    row["acquisition_receipt"] = {"path": receipt_rel, "sha256": _sha(receipt_path)}
    row["primary_source"] = {"name": "retained-docsouth-xml", "role": "primary-source",
                             "path": member_rel, "bytes": xml.stat().st_size, "sha256": _sha(xml)}
    row["url"] = receipt["source_url"]
    row["media_type"] = "application/xml"
    row["warnings"] = [rights]
    write_json(packet, packet_doc)
    return root, packet, xml, receipt_path


def test_direct_member_stage_binds_source_and_rights_without_container(tmp_path):
    root, packet, _, _ = _direct_member_fixture(tmp_path)
    receipt = stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    acquisition_rel = receipt["entries"][0]["files"][2]["path"]
    acquisition = json.loads((tmp_path / "stage" / acquisition_rel).read_text(encoding="utf-8"))
    assert acquisition["source_path"] == "raw/docsouth/l001-alpha/alpha.xml"
    assert acquisition["source_sha256"] == acquisition["retained_files"][0]["sha256"]
    assert len(acquisition["retained_files"]) == 1
    assert acquisition["warnings"] == ["Provider rights statement retained without a clearance claim."]
    work = json.loads((tmp_path / "stage/library/works/alpha/work.json").read_text(encoding="utf-8"))
    assert "containing_source" not in work["textual_forms"][0]["editions"][0]
    assert not (root / acquisition_rel).exists()


def test_direct_member_rejects_changed_retained_bytes(tmp_path):
    root, packet, xml, _ = _direct_member_fixture(tmp_path)
    xml.write_bytes(b"<TEI.2>changed</TEI.2>")
    with pytest.raises(PipelineError, match="retained XML bytes/hash differ"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_direct_member_rejects_receipt_url_and_warning_drift(tmp_path):
    root, packet, _, _ = _direct_member_fixture(tmp_path)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    packet_doc["entries"][0]["url"] = "https://example.org/other.xml"
    with pytest.raises(PipelineError, match="receipt source URL mismatch"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")
    packet_doc["entries"][0]["url"] = "https://example.org/alpha.xml"
    packet_doc["entries"][0]["warnings"] = ["Reworded rights claim"]
    with pytest.raises(PipelineError, match="proposed warnings differ"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")


def test_direct_member_rejects_competing_archive_route(tmp_path):
    root, packet, _, _ = _direct_member_fixture(tmp_path)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    packet_doc["entries"][0]["archive_member"] = "alpha.xml"
    with pytest.raises(PipelineError, match="direct member cannot have archive"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")


def test_direct_member_misdescribed_receipt_requires_header_identity_warning(tmp_path):
    root, packet, xml, receipt_path = _direct_member_fixture(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["work"] = "Another work"
    write_json(receipt_path, receipt)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    row = packet_doc["entries"][0]
    row["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    with pytest.raises(PipelineError, match="proposed warnings differ"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")
    row["warnings"].append(
        "Receipt description: Another work / Alpha Author; retained XML header: "
        "Alpha: Electronic Edition. / Alpha Author. Canonical work identity follows "
        "the XML header; receipt description is not adopted."
    )
    assert prepare(root, packet_doc, "2026-09-25T00:00:00Z")[0]["work_id"] == "alpha"
    xml.write_bytes(xml.read_bytes().replace(b"Alpha: Electronic Edition.", b"Different: Electronic Edition."))
    receipt["member"] = {"path": receipt["member"]["path"], "bytes": xml.stat().st_size, "sha256": _sha(xml)}
    write_json(receipt_path, receipt)
    row["primary_source"].update({"bytes": xml.stat().st_size, "sha256": _sha(xml)})
    row["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    with pytest.raises(PipelineError, match="retained XML header title differs"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")


def _existing_form_packet(tmp_path, *, direct_member=False):
    if direct_member:
        root, packet, _, _ = _direct_member_fixture(tmp_path)
    else:
        root, packet, _ = _fixture(tmp_path)
    stage(root, packet, tmp_path / "first-stage", "2026-09-25T00:00:00Z")
    apply_staged(root, packet, tmp_path / "first-stage")
    work_path = root / "library/works/alpha/work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    form = work["textual_forms"][0]
    form["title"] = "Source-attested form"
    form["category"] = "prose"
    write_json(work_path, work)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    row = packet_doc["entries"][0]
    row["work"]["sha256"] = _sha(work_path)
    row["state"]["sha256"] = _sha(root / "library/works/alpha/state.json")
    row["append_to_existing_form"] = True
    row["edition_id"] = "alpha-second-electronic"
    row["acquisition_id"] = "alpha-second-source"
    row["edition_title"] = "Second retained electronic witness"
    write_json(packet, packet_doc)
    return root, packet, work


def test_append_existing_form_preserves_fields_and_first_edition(tmp_path):
    root, packet, original_work = _existing_form_packet(tmp_path)
    receipt = stage(root, packet, tmp_path / "second-stage", "2026-09-25T01:00:00Z")
    staged_work = json.loads((tmp_path / "second-stage/library/works/alpha/work.json").read_text(encoding="utf-8"))
    assert len(staged_work["textual_forms"]) == 1
    original_form = original_work["textual_forms"][0]
    staged_form = staged_work["textual_forms"][0]
    assert {key: value for key, value in staged_form.items() if key != "editions"} == {
        key: value for key, value in original_form.items() if key != "editions"}
    assert staged_form["editions"][0] == original_form["editions"][0]
    assert staged_form["editions"][1]["edition_id"] == "alpha-second-electronic"
    assert len(receipt["entries"][0]["files"]) == 3
    assert len(json.loads((root / "library/works/alpha/work.json").read_text(encoding="utf-8"))["textual_forms"][0]["editions"]) == 1
    result = apply_staged(root, packet, tmp_path / "second-stage")
    assert len(result["installed"]) == 1
    installed = json.loads((root / "library/works/alpha/work.json").read_text(encoding="utf-8"))
    assert installed == staged_work


def test_append_existing_form_requires_explicit_marker_and_local_parent(tmp_path):
    root, packet, _ = _existing_form_packet(tmp_path)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    row = packet_doc["entries"][0]
    del row["append_to_existing_form"]
    with pytest.raises(PipelineError, match="duplicate global forms ID"):
        prepare(root, packet_doc, "2026-09-25T01:00:00Z")
    row["append_to_existing_form"] = True
    row["textual_form_id"] = "other-work-form"
    other_dir = root / "library/works/other-work"
    other_dir.mkdir()
    write_json(other_dir / "work.json", {"schema_version": "2.0", "work_id": "other-work",
                                        "title": "Other work", "evidence": ["sources/alpha/source-manifest.json"],
                                        "textual_forms": [{"textual_form_id": "other-work-form", "editions": []}]})
    write_json(other_dir / "state.json", {"schema_version": "2.0", "work_id": "other-work", "targets": []})
    with pytest.raises(PipelineError, match="existing textual form is absent"):
        prepare(root, packet_doc, "2026-09-25T01:00:00Z")


def test_append_existing_form_rejects_edition_and_acquisition_collisions(tmp_path):
    root, packet, _ = _existing_form_packet(tmp_path)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    row = packet_doc["entries"][0]
    row["edition_id"] = "alpha-electronic"
    with pytest.raises(PipelineError, match="duplicate global editions ID"):
        prepare(root, packet_doc, "2026-09-25T01:00:00Z")
    row["edition_id"] = "alpha-second-electronic"
    row["acquisition_id"] = "alpha-source"
    with pytest.raises(PipelineError, match="duplicate global acquisitions ID"):
        prepare(root, packet_doc, "2026-09-25T01:00:00Z")


def test_append_existing_form_rejects_language_conflict(tmp_path):
    root, packet, _ = _existing_form_packet(tmp_path, direct_member=True)
    work_path = root / "library/works/alpha/work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["textual_forms"][0]["language"] = "en"
    write_json(work_path, work)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    row = packet_doc["entries"][0]
    row["work"]["sha256"] = _sha(work_path)
    row["language"] = "fr"
    with pytest.raises(PipelineError, match="edition language conflicts"):
        prepare(root, packet_doc, "2026-09-25T01:00:00Z")


def _alternate_direct_member_fixture(tmp_path, provider):
    root, packet, xml, receipt_path = _direct_member_fixture(tmp_path)
    parts = {
        "tcp": ("raw/tcp/high-range/A12345", "A12345.xml", "tcp-A12345"),
        "wikisource": ("raw/wikisource/alpha", "wikisource-export.xml", "wikisource-alpha"),
        "dbnl": ("raw/dbnl/alpha", "alpha.xml", "DBNL-alpha"),
    }
    source_dir, member_name, source_id = parts[provider]
    new_dir = tmp_path / "durable" / source_dir
    new_dir.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.rename(new_dir)
    new_xml = new_dir / "alpha.xml"
    if member_name != "alpha.xml":
        renamed = new_dir / member_name
        new_xml.rename(renamed)
        new_xml = renamed
    if provider == "tcp":
        new_xml.write_bytes(b"<TEI><teiHeader><fileDesc><titleStmt><title>Alpha: Electronic Edition.</title><title>Other catalog title</title></titleStmt></fileDesc></teiHeader><text><body>Exact text.</body></text></TEI>")
    else:
        new_xml.write_bytes(b"<export><page>Exact text.</page></export>")
    receipt_path = new_dir / "acquisition-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_id"] = source_id
    receipt["work"] = "Short Alpha" if provider == "tcp" else "Alpha"
    receipt["member"] = {"path": f"{source_dir}/{member_name}", "bytes": new_xml.stat().st_size, "sha256": _sha(new_xml)}
    write_json(receipt_path, receipt)
    work_path = root / "library/works/alpha/work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["evidence"] = [receipt["member"]["path"], f"{source_dir}/acquisition-receipt.json", "research/MANIFEST.md#L001"]
    write_json(work_path, work)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    row = packet_doc["entries"][0]
    row["work"]["sha256"] = _sha(work_path)
    row["acquisition_receipt"] = {"path": f"{source_dir}/acquisition-receipt.json", "sha256": _sha(receipt_path)}
    row["primary_source"] = {"name": f"retained-{provider}-xml", "role": "primary-source", **receipt["member"]}
    if provider == "tcp":
        row["warnings"].append(
            "Receipt work label 'Short Alpha' is shorthand and differs from the canonical work title. "
            "Exactly one retained XML titleStmt/title matches the canonical title; the receipt label is not adopted. "
            "Other retained titleStmt/title entries remain part of the source witness."
        )
    write_json(packet, packet_doc)
    return root, packet, new_xml, receipt_path


@pytest.mark.parametrize("provider", ["tcp", "wikisource", "dbnl"])
def test_provider_direct_member_stages_exact_receipt_and_rights(tmp_path, provider):
    root, packet, _, _ = _alternate_direct_member_fixture(tmp_path, provider)
    receipt = stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    acquisition_rel = receipt["entries"][0]["files"][2]["path"]
    acquisition = json.loads((tmp_path / "stage" / acquisition_rel).read_text(encoding="utf-8"))
    assert acquisition["retained_files"][0]["sha256"] == acquisition["source_sha256"]
    assert acquisition["warnings"] == json.loads(packet.read_text(encoding="utf-8"))["entries"][0]["warnings"]
    assert not (root / acquisition_rel).exists()


def test_provider_direct_member_rejects_wrong_member_and_url(tmp_path):
    root, packet, _, receipt_path = _alternate_direct_member_fixture(tmp_path, "tcp")
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    packet_doc["entries"][0]["url"] = "https://example.org/wrong.xml"
    with pytest.raises(PipelineError, match="receipt source URL mismatch"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["member"]["path"] = "raw/tcp/high-range/A12345/other.xml"
    write_json(receipt_path, receipt)
    row = packet_doc["entries"][0]
    row["url"] = receipt["source_url"]
    row["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    row["primary_source"]["path"] = receipt["member"]["path"]
    with pytest.raises(PipelineError, match="TCP receipt/member identity mismatch"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")


def test_provider_direct_member_rejects_wrong_tcp_title_and_shorthand_warning(tmp_path):
    root, packet, xml, receipt_path = _alternate_direct_member_fixture(tmp_path, "tcp")
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    row = packet_doc["entries"][0]
    row["warnings"] = row["warnings"][:1]
    with pytest.raises(PipelineError, match="proposed warnings differ"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")
    row["warnings"] = json.loads(packet.read_text(encoding="utf-8"))["entries"][0]["warnings"]
    xml.write_bytes(xml.read_bytes().replace(b"Alpha: Electronic Edition.", b"Different: Electronic Edition."))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["member"].update({"bytes": xml.stat().st_size, "sha256": _sha(xml)})
    write_json(receipt_path, receipt)
    row["primary_source"].update({"bytes": xml.stat().st_size, "sha256": _sha(xml)})
    row["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    with pytest.raises(PipelineError, match="header title must uniquely match"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")


@pytest.mark.parametrize("provider", ["wikisource", "dbnl"])
def test_provider_direct_member_rejects_wrong_work_title_and_rights(tmp_path, provider):
    root, packet, _, receipt_path = _alternate_direct_member_fixture(tmp_path, provider)
    packet_doc = json.loads(packet.read_text(encoding="utf-8"))
    packet_doc["entries"][0]["warnings"] = ["Different rights claim"]
    with pytest.raises(PipelineError, match="proposed warnings differ"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    original_rights = receipt["rights"]
    receipt["rights"] = "Changed provider rights"
    write_json(receipt_path, receipt)
    row = packet_doc["entries"][0]
    row["warnings"] = [original_rights]
    row["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    with pytest.raises(PipelineError, match="proposed warnings differ"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")
    receipt["rights"] = original_rights
    receipt["work"] = "Other Work"
    write_json(receipt_path, receipt)
    row["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    with pytest.raises(PipelineError, match="receipt work title differs"):
        prepare(root, packet_doc, "2026-09-25T00:00:00Z")


def _shared_xml_fixture(tmp_path: Path):
    root = tmp_path / "repo"
    durable = tmp_path / "durable"
    write_json(root / ".ocd-storage.json", {"library_root": str(durable)})
    xml = durable / "raw/shared/volume.xml"
    xml.parent.mkdir(parents=True)
    xml.write_text(
        '<ThML><ThML.body><div1 title="Alpha Source" id="a"><p>Alpha</p></div1>'
        '<div1 title="Beta Source" id="b"><p>Beta</p></div1></ThML.body></ThML>',
        encoding="utf-8",
    )
    source = {"name": "retained-thml", "role": "primary-source", "path": "raw/shared/volume.xml",
              "bytes": xml.stat().st_size, "sha256": _sha(xml)}
    manifest_path = root / "sources/shared/source-manifest.json"
    authorities = [source]
    for wid in ("alpha", "beta"):
        work_path = root / f"library/works/{wid}/work.json"
        metadata_rel = f"metadata/source-evidence/catalog/{wid}.json"
        write_json(work_path, {"schema_version": "2.0", "work_id": wid, "title": wid.title(),
                               "evidence": [metadata_rel], "textual_forms": []})
        write_json(work_path.parent / "state.json", {"schema_version": "2.0", "work_id": wid, "targets": []})
        config_path = root / f"sources/shared/{wid}/config.json"
        write_json(config_path, {"resource_id": wid, "source_file": source["path"],
                                 "source_hash": f"sha256:{source['sha256']}",
                                 "source_url": "https://example.org/volume.xml", "language": "en",
                                 "source_edition": "Shared Test Volume"})
        authorities.append({"name": f"{wid}-config", "role": "local-metadata-claim-evidence",
                            "path": f"sources/shared/{wid}/config.json",
                            "bytes": config_path.stat().st_size, "sha256": _sha(config_path)})
        tag = f'<div1 title="{wid.title()} Source" id="{wid[0]}">'
        write_json(root / metadata_rel, {
            "subject": {"id": wid, "kind": "catalog"},
            "dimensions": {"work": {"fields": [{"evidence": {"bindings": [
                {"path": source["path"], "sha256": source["sha256"],
                 "locator": {"expected": tag}}
            ]}}]}}
        })
    write_json(manifest_path, {"contract": "ocd-source-manifest-v1", "source_id": "shared",
                               "authorities": authorities})
    work_rel = "library/works/alpha/work.json"
    state_rel = "library/works/alpha/state.json"
    config_rel = "sources/shared/alpha/config.json"
    metadata_rel = "metadata/source-evidence/catalog/alpha.json"
    locator = "raw/shared/volume.xml#a"
    row = {"work_id": "alpha",
           "work": {"path": work_rel, "sha256": _sha(root / work_rel)},
           "state": {"path": state_rel, "sha256": _sha(root / state_rel)},
           "source_manifest": {"path": "sources/shared/source-manifest.json", "sha256": _sha(manifest_path)},
           "config": {"path": config_rel, "sha256": _sha(root / config_rel)},
           "metadata_evidence": {"path": metadata_rel, "sha256": _sha(root / metadata_rel)},
           "primary_source": source, "textual_form_id": "alpha-retained-text",
           "edition_id": "alpha-shared-electronic", "acquisition_id": "alpha-shared-acquired",
           "edition_title": "Shared electronic witness", "provider": "Example",
           "url": "https://example.org/volume.xml", "language": "en", "media_type": "application/xml",
           "source_scope": (f"Complete acquired XML volume {source['path']}; work-specific locator {locator} "
                            "is recorded in edition.containing_source and does not establish accepted child text."),
           "containing_source": {"title": "Shared Test Volume", "locator": locator,
                                 "evidence": [metadata_rel, locator]}}
    packet = tmp_path / "shared-packet.json"
    write_json(packet, {"contract": "ocd-library-sidecar-batch-v1", "entries": [row]})
    return root, packet, xml


def test_shared_xml_child_stages_whole_volume_and_exact_locator(tmp_path):
    root, packet, xml = _shared_xml_fixture(tmp_path)
    before = _sha(root / "library/works/alpha/work.json")
    receipt = stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    staged = tmp_path / "stage"
    work = json.loads((staged / "library/works/alpha/work.json").read_text(encoding="utf-8"))
    edition = work["textual_forms"][0]["editions"][0]
    acquisition = json.loads((staged / receipt["entries"][0]["files"][2]["path"]).read_text(encoding="utf-8"))
    assert edition["containing_source"]["locator"] == "raw/shared/volume.xml#a"
    assert acquisition["retained_files"][0]["sha256"] == _sha(xml)
    assert acquisition["retained_files"][0]["path"] == "raw/shared/volume.xml"
    assert acquisition["source_path"] == "raw/shared/volume.xml"
    assert acquisition["source_sha256"] == _sha(xml)
    assert _sha(root / "library/works/alpha/work.json") == before
    assert not (root / "library/works/alpha/forms").exists()


def test_shared_xml_rejects_other_work_child_even_when_locator_exists(tmp_path):
    root, packet, _ = _shared_xml_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    row["containing_source"]["locator"] = "raw/shared/volume.xml#b"
    row["containing_source"]["evidence"][1] = "raw/shared/volume.xml#b"
    row["source_scope"] = row["source_scope"].replace("volume.xml#a", "volume.xml#b")
    write_json(packet, value)
    with pytest.raises(PipelineError, match="source-hash-bound metadata"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_shared_xml_rejects_metadata_binding_to_other_source_hash(tmp_path):
    root, packet, _ = _shared_xml_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    metadata = root / row["metadata_evidence"]["path"]
    record = json.loads(metadata.read_text(encoding="utf-8"))
    record["dimensions"]["work"]["fields"][0]["evidence"]["bindings"][0]["sha256"] = "0" * 64
    write_json(metadata, record)
    row["metadata_evidence"]["sha256"] = _sha(metadata)
    write_json(packet, value)
    with pytest.raises(PipelineError, match="source-hash-bound metadata"):
        prepare(root, value, "2026-09-25T00:00:00Z")


def test_shared_xml_rejects_config_url_drift_even_when_manifest_rebound(tmp_path):
    root, packet, _ = _shared_xml_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    config = root / row["config"]["path"]
    config_doc = json.loads(config.read_text(encoding="utf-8"))
    config_doc["source_url"] = "https://example.org/other.xml"
    write_json(config, config_doc)
    row["config"]["sha256"] = _sha(config)
    manifest = root / row["source_manifest"]["path"]
    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    matching = [entry for entry in manifest_doc["authorities"] if entry["path"] == row["config"]["path"]]
    assert len(matching) == 1
    matching[0]["bytes"] = config.stat().st_size
    matching[0]["sha256"] = _sha(config)
    write_json(manifest, manifest_doc)
    row["source_manifest"]["sha256"] = _sha(manifest)
    with pytest.raises(PipelineError, match="URL differs from bound config"):
        prepare(root, value, "2026-09-25T00:00:00Z")


def test_shared_manifest_still_requires_explicit_child_evidence(tmp_path):
    root, packet, _ = _shared_xml_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    value["entries"][0].pop("metadata_evidence")
    with pytest.raises(PipelineError, match="not exclusive"):
        prepare(root, value, "2026-09-25T00:00:00Z")



def _augustine_npnf105_fixture(tmp_path):
    root, packet, xml = _shared_xml_fixture(tmp_path)
    xml.write_text(
        '<ThML><ThML.body><div1 title="Alpha Source" id="a">'
        '<p id="a.i-p1">Alpha Source</p></div1>'
        '<div1 title="Beta Source" id="b"><p id="b.i-p1">Beta Source</p></div1>'
        '</ThML.body></ThML>', encoding="utf-8")
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    source = row["primary_source"]
    source["bytes"], source["sha256"] = xml.stat().st_size, _sha(xml)
    config = root / row["config"]["path"]
    config_doc = json.loads(config.read_text(encoding="utf-8"))
    config_doc["source_hash"] = f"sha256:{source['sha256']}"
    write_json(config, config_doc)
    row["config"]["sha256"] = _sha(config)
    metadata = root / row["metadata_evidence"]["path"]
    record = json.loads(metadata.read_text(encoding="utf-8"))
    record["dimensions"] = {"parts": {"fields": [{
        "claim_id": "parts:assigned_div1_scope",
        "evidence": {"classification": "supported", "bindings": [{
            "path": source["path"], "bytes": source["bytes"],
            "sha256": source["sha256"],
            "locator": {"kind": "xml_id", "value": "a.i-p1",
                        "expected": "Alpha Source"}
        }]}
    }]}}
    write_json(metadata, record)
    row["metadata_evidence"]["sha256"] = _sha(metadata)
    manifest = root / row["source_manifest"]["path"]
    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_doc["authorities"][0] = source
    bound_config = next(item for item in manifest_doc["authorities"]
                        if item["path"] == row["config"]["path"])
    bound_config["bytes"], bound_config["sha256"] = config.stat().st_size, _sha(config)
    target = root / "sources/structured-text/augustine-npnf105/npnf105.source-manifest.json"
    write_json(target, manifest_doc)
    row["source_manifest"] = {"path": target.relative_to(root).as_posix(),
                              "sha256": _sha(target)}
    write_json(packet, value)
    return root, packet


def test_augustine_npnf105_accepts_hash_bound_heading_inside_child(tmp_path):
    root, packet = _augustine_npnf105_fixture(tmp_path)
    receipt = stage(root, packet, tmp_path / "stage", "2026-09-26T00:00:00Z")
    assert len(receipt["entries"]) == 1
    assert not (root / "library/works/alpha/forms").exists()


def test_augustine_npnf105_rejects_sibling_heading_even_with_rebound_metadata(tmp_path):
    root, packet = _augustine_npnf105_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    metadata = root / row["metadata_evidence"]["path"]
    record = json.loads(metadata.read_text(encoding="utf-8"))
    binding = record["dimensions"]["parts"]["fields"][0]["evidence"]["bindings"][0]
    binding["locator"]["value"] = "b.i-p1"
    binding["locator"]["expected"] = "Beta Source"
    write_json(metadata, record)
    row["metadata_evidence"]["sha256"] = _sha(metadata)
    write_json(packet, value)
    with pytest.raises(PipelineError, match="heading does not belong"):
        stage(root, packet, tmp_path / "stage", "2026-09-26T00:00:00Z")


def test_augustine_npnf105_rejects_resealed_wrong_heading_text(tmp_path):
    root, packet = _augustine_npnf105_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    metadata = root / row["metadata_evidence"]["path"]
    record = json.loads(metadata.read_text(encoding="utf-8"))
    record["dimensions"]["parts"]["fields"][0]["evidence"]["bindings"][0]["locator"]["expected"] = "Invented"
    write_json(metadata, record)
    row["metadata_evidence"]["sha256"] = _sha(metadata)
    write_json(packet, value)
    with pytest.raises(PipelineError, match="source heading differs"):
        stage(root, packet, tmp_path / "stage", "2026-09-26T00:00:00Z")


def _gutenberg_receipt_fixture(tmp_path, *, title_receipt=False):
    root, packet, _ = _fixture(tmp_path)
    source_dir = tmp_path / "durable/raw/gutenberg/12345"
    extracted_dir = source_dir / "html"
    (extracted_dir / "images").mkdir(parents=True)
    html_bytes = b"<html><title>Alpha</title><body>Exact source</body></html>"
    cover_bytes = b"exact image bytes"
    html_path = extracted_dir / "pg12345-images.html"
    cover_path = extracted_dir / "images/cover.jpg"
    html_path.write_bytes(html_bytes)
    cover_path.write_bytes(cover_bytes)
    archive = source_dir / "pg12345-h.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("pg12345-images.html", html_bytes)
        handle.writestr("images/cover.jpg", cover_bytes)
    receipt_rel = "raw/gutenberg/12345/acquisition-receipt.json"
    package_rel = "raw/gutenberg/12345/pg12345-h.zip"
    html_rel = "raw/gutenberg/12345/html/pg12345-images.html"
    receipt_path = source_dir / "acquisition-receipt.json"
    rights = "Project Gutenberg rights require review."
    receipt = {"schema": "ocd-acquisition-source-receipt-v1", "ebook_id": "12345",
        "source_url": "https://www.gutenberg.org/ebooks/12345",
        "package_url": "https://www.gutenberg.org/cache/epub/12345/pg12345-h.zip",
        "package": {"path": package_rel, "bytes": archive.stat().st_size, "sha256": _sha(archive)},
        "html": {"path": html_rel, "bytes": html_path.stat().st_size, "sha256": _sha(html_path)},
        "rights": rights, "verification": {"member_count": 2, "primary_html": "pg12345-images.html"}}
    if title_receipt:
        receipt["title"] = "Alpha"
        receipt["verification"]["identity_evidence"] = "Official Project Gutenberg record: Alpha."
    else:
        receipt["manifest_rows"] = ["L001"]
    write_json(receipt_path, receipt)
    work_path = root / "library/works/alpha/work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["evidence"] = [receipt_rel, package_rel, html_rel, "research/MANIFEST.md#L001"]
    write_json(work_path, work)
    doc = json.loads(packet.read_text(encoding="utf-8"))
    row = doc["entries"][0]
    for key in ("source_manifest", "config", "language"):
        row.pop(key)
    row["work"]["sha256"] = _sha(work_path)
    row["acquisition_receipt"] = {"path": receipt_rel, "sha256": _sha(receipt_path)}
    row["primary_source"] = {"name": "retained-gutenberg-html", "role": "primary-source", **receipt["html"]}
    row["archive_member"] = "pg12345-images.html"
    row["provider"] = "Project Gutenberg"
    row["url"] = receipt["package_url"]
    row["media_type"] = "text/html"
    row["source_scope"] = (
        f"Complete original Project Gutenberg ZIP {package_rel} and all 2 exactly matching "
        f"extracted archive members under raw/gutenberg/12345/html/, including principal HTML "
        f"{html_rel} and support images. The acquisition establishes this source witness for "
        "the existing work, not TEI reconstruction, acceptance, or publication clearance."
    )
    row["warnings"] = [rights]
    write_json(packet, doc)
    return root, packet, archive, html_path, cover_path, receipt_path


@pytest.mark.parametrize("title_receipt", [False, True])
def test_gutenberg_zip_stages_full_package_and_extracted_members(tmp_path, title_receipt):
    root, packet, archive, html, _, _ = _gutenberg_receipt_fixture(tmp_path, title_receipt=title_receipt)
    result = stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    acquisition_rel = result["entries"][0]["files"][2]["path"]
    acquisition = json.loads((tmp_path / "stage" / acquisition_rel).read_text(encoding="utf-8"))
    assert acquisition["source_path"] == "raw/gutenberg/12345/html/pg12345-images.html"
    assert acquisition["source_bytes"] == html.stat().st_size
    assert acquisition["source_sha256"] == _sha(html)
    assert acquisition["source_scope"].startswith("Principal extracted HTML raw/gutenberg/12345/html/pg12345-images.html is the retained text source")
    assert "Complete original Project Gutenberg ZIP" not in acquisition["source_scope"]
    assert "not TEI reconstruction, acceptance, or publication clearance" in acquisition["source_scope"]
    assert [item["path"] for item in acquisition["retained_files"]] == [
        "raw/gutenberg/12345/pg12345-h.zip",
        "raw/gutenberg/12345/html/pg12345-images.html",
        "raw/gutenberg/12345/html/images/cover.jpg"]
    assert acquisition["retained_files"][0]["sha256"] == _sha(archive)
    assert "package" in acquisition["retained_files"][0]["scope"]
    assert acquisition["retained_files"][1]["scope"] == acquisition["source_scope"]
    assert "supporting member" in acquisition["retained_files"][2]["scope"]
    assert acquisition["warnings"] == ["Project Gutenberg rights require review."]


def test_gutenberg_zip_rejects_package_centered_scope_drift(tmp_path):
    root, packet, _, _, _, _ = _gutenberg_receipt_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    value["entries"][0]["source_scope"] = value["entries"][0]["source_scope"].replace(
        "and all 2 exactly matching extracted archive members",
        "and some extracted archive members",
    )
    write_json(packet, value)
    with pytest.raises(PipelineError, match="Gutenberg source scope differs"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize(("field", "expected"), [
    ("url", "provider/package URL mismatch"),
    ("archive_member", "principal archive member mismatch"),
    ("warnings", "rights warning differs"),
])
def test_gutenberg_zip_rejects_packet_identity_drift(tmp_path, field, expected):
    root, packet, _, _, _, _ = _gutenberg_receipt_fixture(tmp_path)
    doc = json.loads(packet.read_text(encoding="utf-8"))
    doc["entries"][0][field] = ["Altered rights"] if field == "warnings" else "wrong"
    write_json(packet, doc)
    with pytest.raises(PipelineError, match=expected):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_gutenberg_zip_rejects_receipt_title_and_source_member_drift(tmp_path):
    root, packet, _, _, cover, receipt_path = _gutenberg_receipt_fixture(tmp_path, title_receipt=True)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["title"] = "Wrong title"
    write_json(receipt_path, receipt)
    doc = json.loads(packet.read_text(encoding="utf-8"))
    doc["entries"][0]["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    write_json(packet, doc)
    with pytest.raises(PipelineError, match="receipt title/identity evidence mismatch"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    receipt["title"] = "Alpha"
    write_json(receipt_path, receipt)
    doc["entries"][0]["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    write_json(packet, doc)
    cover.write_bytes(b"changed image bytes")
    with pytest.raises(PipelineError, match="extracted member differs from archive"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")


def test_gutenberg_zip_rejects_changed_principal_html(tmp_path):
    root, packet, _, html, _, _ = _gutenberg_receipt_fixture(tmp_path)
    html.write_bytes(b"<html>Changed principal text</html>")
    with pytest.raises(PipelineError, match="extracted member differs from archive"):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def _repin_shared_config(root: Path, row: dict):
    config = root / row["config"]["path"]
    row["config"]["sha256"] = _sha(config)
    manifest = root / row["source_manifest"]["path"]
    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    authorities = [item for item in manifest_doc["authorities"] if item["path"] == row["config"]["path"]]
    assert len(authorities) == 1
    authorities[0]["bytes"] = config.stat().st_size
    authorities[0]["sha256"] = _sha(config)
    write_json(manifest, manifest_doc)
    row["source_manifest"]["sha256"] = _sha(manifest)


def test_shared_xml_accepts_absent_source_file_with_exact_manifest_and_digest(tmp_path):
    root, packet, _ = _shared_xml_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    config = root / row["config"]["path"]
    config_doc = json.loads(config.read_text(encoding="utf-8"))
    del config_doc["source_file"]
    write_json(config, config_doc)
    _repin_shared_config(root, row)
    write_json(packet, value)
    receipt = stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert len(receipt["entries"]) == 1
    assert not (root / "library/works/alpha/forms").exists()


@pytest.mark.parametrize("source_file", ["raw/shared/other.xml", None])
def test_shared_xml_rejects_contradictory_present_source_file(tmp_path, source_file):
    root, packet, _ = _shared_xml_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    config = root / row["config"]["path"]
    config_doc = json.loads(config.read_text(encoding="utf-8"))
    config_doc["source_file"] = source_file
    write_json(config, config_doc)
    _repin_shared_config(root, row)
    with pytest.raises(PipelineError, match="config identity/source binding mismatch"):
        prepare(root, value, "2026-09-25T00:00:00Z")


def test_shared_xml_rejects_wrong_source_digest_with_absent_source_file(tmp_path):
    root, packet, _ = _shared_xml_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    config = root / row["config"]["path"]
    config_doc = json.loads(config.read_text(encoding="utf-8"))
    del config_doc["source_file"]
    config_doc["source_hash"] = "sha256:" + "0" * 64
    write_json(config, config_doc)
    _repin_shared_config(root, row)
    with pytest.raises(PipelineError, match="config identity/source binding mismatch"):
        prepare(root, value, "2026-09-25T00:00:00Z")


def _member_set_fixture(tmp_path):
    root, packet, _ = _fixture(tmp_path)
    doc = json.loads(packet.read_text(encoding="utf-8"))
    row = doc["entries"][0]
    raw_root = tmp_path / "durable/raw/pkg"
    extracted = raw_root / "Test"
    extracted.mkdir(parents=True)
    files = {}
    for name, content in (("a.czs", b"index"), ("b.czv", b"verse"), ("c.czz", b"content"),
                          ("mods.d/test.conf", b"Description=Test Notes\nVersion=1.1\nLang=en\nDistributionLicense=Public Domain\nSwordVersionDate=2002-01-01\n")):
        target = extracted / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        files[name] = target
    archive = raw_root / "Test.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, path in files.items():
            zipped.write(path, name)
    def authority(path, role, name):
        return {"name": name, "role": role, "path": "raw/pkg/" + path.relative_to(raw_root).as_posix(),
                "bytes": path.stat().st_size, "sha256": _sha(path)}
    members = [authority(files[name], "primary-source", name) for name in ("a.czs", "b.czv", "c.czz")]
    support = [authority(files["mods.d/test.conf"], "source-description", "module-config")]
    package = authority(archive, "acquisition-container", "package")
    manifest_path = root / row["source_manifest"]["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_id"] = "test-sword-v1.1"
    manifest["authorities"] = [package, *members, *support, manifest["authorities"][1]]
    write_json(manifest_path, manifest)
    row["source_manifest"]["sha256"] = _sha(manifest_path)
    config_path = root / row["config"]["path"]
    write_json(config_path, {"resource_id": "alpha", "source_url": "https://example.org/Test.zip", "language": "en"})
    row["config"]["sha256"] = _sha(config_path)
    manifest["authorities"][-1].update(bytes=config_path.stat().st_size, sha256=_sha(config_path))
    write_json(manifest_path, manifest)
    row["source_manifest"]["sha256"] = _sha(manifest_path)
    receipt_rel = "sources/alpha/acquisition-receipt.json"
    receipt_path = root / receipt_rel
    module = {"path": support[0]["path"], "description": "Test Notes", "version": "1.1", "language": "en",
              "distribution_license": "Public Domain", "sword_version_date": "2002-01-01"}
    receipt = {"schema": "ocd-member-set-acquisition-receipt-v1", "work_id": "alpha", "source_id": "test-sword-v1.1",
               "source_manifest": row["source_manifest"], "config": row["config"], "provider": "CrossWire",
               "package_url": "https://example.org/Test.zip", "package": package, "members": members,
               "support": support, "sword_module": module}
    write_json(receipt_path, receipt)
    row.pop("primary_source")
    row.update(source_receipt={"path": receipt_rel, "sha256": _sha(receipt_path)}, primary_sources=members,
               edition_title="Test Notes — CrossWire SWORD module v1.1", provider="CrossWire",
               url="https://example.org/Test.zip", media_type="application/octet-stream",
               source_scope="Coordinated source " + ", ".join(item["path"] for item in members) +
                            "; package " + package["path"] + "; support " + support[0]["path"],
               warnings=["Retained SWORD module declares DistributionLicense=Public Domain; independent rights clearance and publication authorization are not established."])
    write_json(packet, doc)
    return root, packet, archive, files


def test_member_set_stage_has_three_sources_and_ancillary_package_evidence(tmp_path):
    from ocd_kernel.library.acquisitions import source_member_set_bytes
    root, packet, archive, _ = _member_set_fixture(tmp_path)
    before = [_sha(root / f"library/works/alpha/{name}.json") for name in ("work", "state")]
    staged = tmp_path / "stage"
    receipt = stage(root, packet, staged, "2026-09-25T00:00:00Z")
    assert len(receipt["entries"][0]["files"]) == 4
    acq_rel = receipt["entries"][0]["files"][2]["path"]
    acq = json.loads((staged / acq_rel).read_text(encoding="utf-8"))
    assert acq["source_kind"] == "retained-member-set"
    assert [item["path"] for item in acq["retained_files"]] == [
        "raw/pkg/Test/a.czs", "raw/pkg/Test/b.czv", "raw/pkg/Test/c.czz"]
    assert archive.name not in acq["source_path"]
    assert (staged / acq["source_path"]).read_bytes() == source_member_set_bytes(acq)
    work = json.loads((staged / "library/works/alpha/work.json").read_text(encoding="utf-8"))
    assert "raw/pkg/Test.zip" in work["evidence"]
    assert "raw/pkg/Test/mods.d/test.conf" in work["evidence"]
    assert before == [_sha(root / f"library/works/alpha/{name}.json") for name in ("work", "state")]
    assert not (root / "library/works/alpha/forms").exists()


@pytest.mark.parametrize("mutation", ["reorder", "omit", "hash", "package"])
def test_member_set_mutations_fail_before_stage(tmp_path, mutation):
    root, packet, archive, files = _member_set_fixture(tmp_path)
    if mutation in {"reorder", "omit"}:
        doc = json.loads(packet.read_text(encoding="utf-8"))
        members = doc["entries"][0]["primary_sources"]
        if mutation == "reorder":
            members.reverse()
        else:
            members.pop()
        write_json(packet, doc)
    elif mutation == "hash":
        files["b.czv"].write_bytes(b"changed verse")
    else:
        archive.write_bytes(archive.read_bytes() + b"changed")
    with pytest.raises(PipelineError):
        stage(root, packet, tmp_path / "stage", "2026-09-25T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_member_set_apply_rollback_after_live_validation_failure(tmp_path, monkeypatch):
    import build.tools.prepare_library_sidecar_batch as batch
    root, packet, _, _ = _member_set_fixture(tmp_path)
    staged = tmp_path / "stage"
    stage(root, packet, staged, "2026-09-25T00:00:00Z")
    target = root / "library/works/alpha"
    before = {name: _sha(target / name) for name in ("work.json", "state.json")}
    original_validate = batch.validate_state
    def fail_live(path, *, root):
        if Path(root).name == "repo":
            raise PipelineError("injected member-set live failure")
        return original_validate(path, root=root)
    monkeypatch.setattr(batch, "validate_state", fail_live)
    with pytest.raises(PipelineError, match="injected member-set live failure"):
        apply_staged(root, packet, staged)
    assert {name: _sha(target / name) for name in before} == before
    assert not (target / "forms").exists()


def _gutenberg_record_only_fixture(tmp_path):
    root, packet, archive, html_path, cover, receipt_path = _gutenberg_receipt_fixture(tmp_path)
    html_bytes = (
        b'<html lang="en"><head><title>Alpha | Project Gutenberg</title>'
        b'<meta name="dc.rights" content="Public domain in the USA."></head>'
        b'<body><a href="https://www.gutenberg.org/ebooks/12345">record</a>'
        b'Exact source</body></html>'
    )
    html_path.write_bytes(html_bytes)
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("pg12345-images.html", html_bytes)
        handle.writestr("images/cover.jpg", cover.read_bytes())
    with zipfile.ZipFile(archive) as handle:
        members = [
            {"name": item.filename, "bytes": item.file_size,
             "sha256": hashlib.sha256(handle.read(item)).hexdigest(),
             "crc32": f"{item.CRC:08x}"}
            for item in handle.infolist()
        ]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["schema"] = "ocd-acquisition-source-receipt-v2"
    receipt["work_id"] = "alpha"
    receipt["title"] = "Alpha"
    receipt["retained_html_title"] = "Alpha | Project Gutenberg"
    receipt["package_download_url_status"] = "unknown-not-retained"
    receipt.pop("package_url")
    receipt.pop("manifest_rows")
    receipt["package"] = {"path": receipt["package"]["path"], "bytes": archive.stat().st_size, "sha256": _sha(archive)}
    receipt["html"] = {"path": receipt["html"]["path"], "bytes": html_path.stat().st_size, "sha256": _sha(html_path)}
    receipt["members"] = members
    receipt["rights_claim"] = {
        "source": receipt["html"]["path"] + "#meta[name=dc.rights]",
        "text": "Public domain in the USA.",
    }
    receipt["rights"] = "Retained HTML claims public domain in the USA; rights review remains open."
    receipt["source_scope"] = (
        "Principal extracted HTML raw/gutenberg/12345/html/pg12345-images.html is the retained text source; "
        "ZIP raw/gutenberg/12345/pg12345-h.zip is the retained acquisition package with all 2 members "
        "matched to extracted files. No TEI acceptance or publication clearance is implied."
    )
    write_json(receipt_path, receipt)
    work_path = root / "library/works/alpha/work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["evidence"].remove("raw/gutenberg/12345/acquisition-receipt.json")
    write_json(work_path, work)
    doc = json.loads(packet.read_text(encoding="utf-8"))
    row = doc["entries"][0]
    row["work"]["sha256"] = _sha(work_path)
    row["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    row["primary_source"] = {"name": "retained-gutenberg-html", "role": "primary-source", **receipt["html"]}
    row["url"] = receipt["source_url"]
    row["source_scope"] = receipt["source_scope"]
    row["warnings"] = [receipt["rights"]]
    write_json(packet, doc)
    return root, packet, archive, html_path, cover, receipt_path


def test_gutenberg_record_only_stages_extracted_html_without_download_url(tmp_path):
    root, packet, archive, html_path, _, _ = _gutenberg_record_only_fixture(tmp_path)
    result = stage(root, packet, tmp_path / "stage", "2026-09-26T00:00:00Z")
    acquisition_rel = result["entries"][0]["files"][2]["path"]
    staged = tmp_path / "stage"
    acquisition = json.loads((staged / acquisition_rel).read_text(encoding="utf-8"))
    work = json.loads((staged / "library/works/alpha/work.json").read_text(encoding="utf-8"))
    assert acquisition["url"] == "https://www.gutenberg.org/ebooks/12345"
    assert acquisition["source_path"] == "raw/gutenberg/12345/html/pg12345-images.html"
    assert acquisition["source_sha256"] == _sha(html_path)
    assert acquisition["retained_files"][0]["sha256"] == _sha(archive)
    assert acquisition["retained_files"][1]["scope"] == acquisition["source_scope"]
    assert "raw/gutenberg/12345/acquisition-receipt.json" in work["evidence"]
    assert "textual_forms" in json.loads((root / "library/works/alpha/work.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("mutation", ["invented_download_url", "wrong_member_hash", "wrong_rights", "wrong_record_url"])
def test_gutenberg_record_only_rejects_receipt_drift(tmp_path, mutation):
    root, packet, _, _, _, receipt_path = _gutenberg_record_only_fixture(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "invented_download_url":
        receipt["package_url"] = "https://www.gutenberg.org/cache/epub/12345/pg12345-h.zip"
    elif mutation == "wrong_member_hash":
        receipt["members"][1]["sha256"] = "0" * 64
    elif mutation == "wrong_rights":
        receipt["rights_claim"]["text"] = "Cleared everywhere."
    else:
        receipt["source_url"] = "https://www.gutenberg.org/ebooks/99999"
    write_json(receipt_path, receipt)
    doc = json.loads(packet.read_text(encoding="utf-8"))
    doc["entries"][0]["acquisition_receipt"]["sha256"] = _sha(receipt_path)
    write_json(packet, doc)
    with pytest.raises(PipelineError):
        stage(root, packet, tmp_path / "stage", "2026-09-26T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_gutenberg_record_only_rejects_changed_extracted_support(tmp_path):
    root, packet, _, _, cover, _ = _gutenberg_record_only_fixture(tmp_path)
    cover.write_bytes(b"changed")
    with pytest.raises(PipelineError, match="extracted member"):
        stage(root, packet, tmp_path / "stage", "2026-09-26T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def test_gutenberg_record_only_rejects_unaccounted_extracted_file(tmp_path):
    root, packet, _, html_path, _, _ = _gutenberg_record_only_fixture(tmp_path)
    (html_path.parent / "extra.txt").write_text("unaccounted", encoding="utf-8")
    with pytest.raises(PipelineError, match="unaccounted files"):
        stage(root, packet, tmp_path / "stage", "2026-09-26T00:00:00Z")
    assert not (tmp_path / "stage").exists()


def _gregory_shared_volume_fixture(tmp_path: Path):
    root, packet_path, xml = _shared_xml_fixture(tmp_path)
    xml.write_text(
        '<ThML><ThML.body><div1 title="Family" id="family">'
        '<div2 title="Alpha Source" id="a"><p>Alpha</p></div2>'
        '<div2 title="Beta Source" id="b"><p>Beta</p></div2>'
        '</div1></ThML.body></ThML>', encoding="utf-8")
    value = json.loads(packet_path.read_text(encoding="utf-8"))
    row = value["entries"][0]
    row.pop("source_manifest")
    row["primary_source"]["bytes"] = xml.stat().st_size
    row["primary_source"]["sha256"] = _sha(xml)
    config_path = root / row["config"]["path"]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["title"] = "Alpha"
    config["source_hash"] = f"sha256:{_sha(xml)}"
    write_json(config_path, config)
    row["config"]["sha256"] = _sha(config_path)
    metadata_path = root / row["metadata_evidence"]["path"]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    binding = metadata["dimensions"]["work"]["fields"][0]["evidence"]["bindings"][0]
    binding["sha256"] = _sha(xml)
    binding["locator"]["expected"] = '<div2 title="Alpha Source" id="a">'
    write_json(metadata_path, metadata)
    row["metadata_evidence"]["sha256"] = _sha(metadata_path)
    report_rel = "plans/2026-09-22-source-preflight/gregory-nyssa-shared-volume-accounting-evidence-20260925.json"
    report_path = root / report_rel
    report_path.parent.mkdir(parents=True)
    report = {
        "report_type": "gregory-nyssa-shared-volume-source-accounting-evidence",
        "retained_volume": {name: row["primary_source"][name] for name in ("path", "bytes", "sha256")},
        "source_url": row["url"],
        "works": [{
            "work_id": "alpha",
            "work": {**row["work"], "bytes": (root / row["work"]["path"]).stat().st_size},
            "state": {**row["state"], "bytes": (root / row["state"]["path"]).stat().st_size},
            "config": {**row["config"], "bytes": config_path.stat().st_size},
            "metadata_evidence": {**row["metadata_evidence"], "bytes": metadata_path.stat().st_size},
            "source_root": {"locator": row["containing_source"]["locator"],
                            "xml_element": "div2", "source_title": "Alpha Source", "match_count": 1},
            "source_url": row["url"], "language": "en", "config_title": "Alpha"
        }] + [{"work_id": f"other-{i}"} for i in range(11)]
    }
    write_json(report_path, report)
    row["shared_volume_evidence"] = {"path": report_rel, "sha256": _sha(report_path)}
    write_json(packet_path, value)
    return root, packet_path, xml


def test_gregory_shared_volume_div2_stage_and_locator_mutations(tmp_path):
    root, packet_path, xml = _gregory_shared_volume_fixture(tmp_path)
    staged = tmp_path / "stage"
    receipt = stage(root, packet_path, staged, "2026-09-26T00:00:00Z")
    acquisition_path = next(
        item["path"] for item in receipt["entries"][0]["files"]
        if "/acquisitions/" in item["path"] and item["path"].endswith(".json"))
    acquisition = json.loads((staged / acquisition_path).read_text(encoding="utf-8"))
    assert acquisition["source_path"] == "raw/shared/volume.xml"
    assert acquisition["source_sha256"] == _sha(xml)
    assert acquisition["retained_files"][0]["path"] == acquisition["source_path"]
    assert not (root / acquisition_path).exists()

    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    row = packet["entries"][0]
    row["containing_source"]["locator"] = "raw/shared/volume.xml#b"
    row["containing_source"]["evidence"][1] = "raw/shared/volume.xml#b"
    row["source_scope"] = row["source_scope"].replace("volume.xml#a", "volume.xml#b")
    with pytest.raises(PipelineError, match="shared volume source, locator"):
        prepare(root, packet, "2026-09-26T00:00:00Z")
    row["containing_source"]["locator"] = "raw/shared/volume.xml#a"
    row["containing_source"]["evidence"][1] = "raw/shared/volume.xml#a"
    row["source_scope"] = row["source_scope"].replace("volume.xml#b", "volume.xml#a")
    row["config"]["sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="config missing or changed"):
        prepare(root, packet, "2026-09-26T00:00:00Z")


def test_shared_xml_direct_div2_child_stages_and_rejects_wrong_element(tmp_path):
    root, packet, xml = _shared_xml_fixture(tmp_path)
    xml.write_text(xml.read_text(encoding="utf-8").replace("<div1", "<div2").replace("</div1>", "</div2>"), encoding="utf-8")
    value = json.loads(packet.read_text(encoding="utf-8"))
    row = value["entries"][0]
    source = row["primary_source"]
    source["bytes"] = xml.stat().st_size
    source["sha256"] = _sha(xml)
    config_path = root / row["config"]["path"]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["source_hash"] = f"sha256:{source['sha256']}"
    write_json(config_path, config)
    row["config"]["sha256"] = _sha(config_path)
    metadata_path = root / row["metadata_evidence"]["path"]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    binding = metadata["dimensions"]["work"]["fields"][0]["evidence"]["bindings"][0]
    binding["sha256"] = source["sha256"]
    binding["locator"]["expected"] = '<div2 title="Alpha Source" id="a">'
    write_json(metadata_path, metadata)
    row["metadata_evidence"]["sha256"] = _sha(metadata_path)
    manifest_path = root / row["source_manifest"]["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["authorities"][0] = source
    for authority in manifest["authorities"]:
        if authority.get("path") == row["config"]["path"]:
            authority["bytes"] = config_path.stat().st_size
            authority["sha256"] = row["config"]["sha256"]
    write_json(manifest_path, manifest)
    row["source_manifest"]["sha256"] = _sha(manifest_path)
    row["source_child_element"] = "div2"
    write_json(packet, value)
    receipt = stage(root, packet, tmp_path / "div2-stage", "2026-09-26T00:00:00Z")
    assert receipt["entries"][0]["work_id"] == "alpha"
    assert not (root / "library/works/alpha/forms").exists()
    row.pop("source_child_element")
    with pytest.raises(PipelineError, match="shared XML child must resolve uniquely"):
        prepare(root, value, "2026-09-26T00:00:00Z")


def test_shared_xml_multi_volume_manifest_selects_exact_member(tmp_path):
    root, packet, xml = _shared_xml_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    manifest_path = root / value["entries"][0]["source_manifest"]["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    other = tmp_path / "durable/raw/shared/other.xml"
    other.write_text('<ThML><ThML.body><div1 title="Other" id="x"/></ThML.body></ThML>', encoding="utf-8")
    manifest["authorities"].append({"name": "other-volume", "role": "primary-source",
                                    "path": "raw/shared/other.xml", "bytes": other.stat().st_size,
                                    "sha256": _sha(other)})
    write_json(manifest_path, manifest)
    value["entries"][0]["source_manifest"]["sha256"] = _sha(manifest_path)
    write_json(packet, value)

    receipt = stage(root, packet, tmp_path / "stage", "2026-09-26T00:00:00Z")
    acq_path = next(item["path"] for item in receipt["entries"][0]["files"]
                    if "/acquisitions/" in item["path"])
    acq = json.loads((tmp_path / "stage" / acq_path).read_text(encoding="utf-8"))
    assert acq["source_path"] == "raw/shared/volume.xml"
    assert acq["source_sha256"] == _sha(xml)
    assert len(acq["retained_files"]) == 1


def test_shared_xml_support_image_must_be_bound_and_unchanged(tmp_path):
    root, packet, _ = _shared_xml_fixture(tmp_path)
    value = json.loads(packet.read_text(encoding="utf-8"))
    manifest_path = root / value["entries"][0]["source_manifest"]["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    image = tmp_path / "durable/raw/ccel/npnf2/npnf212/files/fig1.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    support = {"name": "image", "role": "primary-source", "path": "raw/ccel/npnf2/npnf212/files/fig1.png",
               "bytes": image.stat().st_size, "sha256": _sha(image), "work_ids": ["alpha"]}
    manifest["authorities"].append(support)
    write_json(manifest_path, manifest)
    row = value["entries"][0]
    row["source_manifest"]["sha256"] = _sha(manifest_path)
    with pytest.raises(PipelineError, match="support-source assignment mismatch"):
        prepare(root, value, "2026-09-26T00:00:00Z")
    row["support_source"] = support
    write_json(packet, value)
    receipt = stage(root, packet, tmp_path / "stage", "2026-09-26T00:00:00Z")
    acq_path = next(item["path"] for item in receipt["entries"][0]["files"]
                    if "/acquisitions/" in item["path"])
    acq = json.loads((tmp_path / "stage" / acq_path).read_text(encoding="utf-8"))
    assert [item["path"] for item in acq["retained_files"]] == [
        "raw/shared/volume.xml", support["path"]]
    image.write_bytes(b"changed image")
    with pytest.raises(PipelineError, match="support bytes/hash differ"):
        prepare(root, value, "2026-09-26T00:00:00Z")
