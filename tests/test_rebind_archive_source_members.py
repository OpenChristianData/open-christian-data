import copy
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from build.tools.rebind_archive_source_members import apply_staged, prepare, stage
from ocd_kernel.library._common import PipelineError, io_path, write_json


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path):
    root = tmp_path / "repo"
    durable = tmp_path / "durable"
    root.mkdir(parents=True)
    write_json(root / ".ocd-storage.json", {"library_root": str(durable)})
    records = []
    for wid, family, source_id, title in (
        ("alpha", "openmgh", "bsb123", "Alpha"),
        ("beta", "gutenberg", "12345", "Beta"),
    ):
        work_root = root / "library/works" / wid
        work_root.mkdir(parents=True)
        source_root = durable / "raw" / family / source_id
        source_root.mkdir(parents=True)
        if family == "openmgh":
            member = "bsb123.xml"
            extracted_rel = "raw/openmgh/bsb123/tei/bsb123.xml"
            extracted = source_root / "tei" / member
            archive_rel = "raw/openmgh/bsb123/bsb123.zip"
            url = "https://data.mgh.de/openmgh/bsb123.zip"
            content = b"<TEI xml:id='x'>Alpha</TEI>"
            image = None
        else:
            member = "pg12345-images.html"
            extracted_rel = "raw/gutenberg/12345/html/pg12345-images.html"
            extracted = source_root / "html" / member
            archive_rel = "raw/gutenberg/12345/pg12345-h.zip"
            url = "https://www.gutenberg.org/cache/epub/12345/pg12345-h.zip"
            content = b"<html><title>Beta</title></html>"
            image = source_root / "html/images/cover.jpg"
        extracted.parent.mkdir(parents=True)
        extracted.write_bytes(content)
        if image:
            image.parent.mkdir(parents=True)
            image.write_bytes(b"cover")
        archive = source_root / Path(archive_rel).name
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr(member, content)
            if image:
                handle.writestr("images/cover.jpg", b"cover")
        package = {"path": archive_rel, "bytes": archive.stat().st_size, "sha256": _sha(archive),
                   "media_type": "application/zip", "scope": "Original package."}
        text = {"path": extracted_rel, "bytes": len(content), "sha256": _sha(extracted),
                "media_type": "application/tei+xml" if family == "openmgh" else "text/html",
                "scope": "Extracted source."}
        retained = [package, text]
        if image:
            retained.append({"path": "raw/gutenberg/12345/html/images/cover.jpg", "bytes": 5,
                             "sha256": _sha(image), "media_type": "image/jpeg", "scope": "Support image."})
        receipt_rel = f"raw/{family}/{source_id}/acquisition-receipt.json"
        if family == "openmgh":
            locator = extracted_rel + "#x"
            containing = {"title": title, "locator": locator,
                          "evidence": [receipt_rel, archive_rel, locator]}
            scope = ("Complete acquired containing-source package and its extracted TEI member; "
                     f"existing work association locators: {locator}. These locators are evidence "
                     "for accounting, not an adopted complete child extraction or TEI acceptance.")
            receipt = {"schema": "ocd-acquisition-source-receipt-v1", "source_id": source_id,
                       "work_edition": title, "source_url": url,
                       "package": {key: package[key] for key in ("path", "bytes", "sha256")},
                       "verification": {"member_count": 1}}
            evidence = [receipt_rel, archive_rel, locator]
        else:
            containing = None
            scope = (f"Complete original Project Gutenberg ZIP {archive_rel} and all 2 "
                     "exactly matching extracted archive members under raw/gutenberg/12345/html/, "
                     f"including principal HTML {extracted_rel} and support images. "
                     "The acquisition establishes this source witness for the existing work, "
                     "not TEI reconstruction, acceptance, or publication clearance.")
            receipt = {"schema": "ocd-acquisition-source-receipt-v1", "ebook_id": source_id,
                       "source_url": "https://www.gutenberg.org/ebooks/12345",
                       "package_url": url,
                       "package": {key: package[key] for key in ("path", "bytes", "sha256")},
                       "html": {key: text[key] for key in ("path", "bytes", "sha256")},
                       "rights": "Provider rights require review.",
                       "verification": {"member_count": 2, "primary_html": member}}
            evidence = [receipt_rel, archive_rel, extracted_rel]
        write_json(source_root / "acquisition-receipt.json", receipt)
        form_id = wid + "-form"
        edition_id = wid + "-edition"
        acquisition_id = wid + "-acquired"
        edition = {"edition_id": edition_id, "title": title, "acquisition_ids": [acquisition_id]}
        if containing:
            edition["containing_source"] = containing
        work = {"schema_version": "2.0", "work_id": wid, "title": title, "evidence": evidence,
                "textual_forms": [{"textual_form_id": form_id, "editions": [edition]}]}
        acquisition_rel = f"library/works/{wid}/forms/{form_id}/editions/{edition_id}/acquisitions/{acquisition_id}.json"
        state = {"schema_version": "2.0", "work_id": wid, "targets": [
            {"target_id": acquisition_id, "target_type": "acquisition", "stage": "acquired",
             "updated_at": "2026-09-25T00:00:00Z", "evidence": [acquisition_rel]},
            {"target_id": edition_id, "target_type": "edition", "stage": "acquired",
             "updated_at": "2026-09-25T00:00:00Z", "evidence": [acquisition_rel]}]}
        acquisition = {"schema_version": "2.0", "acquisition_id": acquisition_id,
                       "edition_id": edition_id, "provider": family, "url": url,
                       "retained_files": retained, "source_path": archive_rel,
                       "source_bytes": package["bytes"], "source_sha256": package["sha256"],
                       "source_scope": scope}
        if family == "gutenberg":
            acquisition["warnings"] = [receipt["rights"]]
        write_json(work_root / "work.json", work)
        write_json(work_root / "state.json", state)
        path = root / acquisition_rel
        write_json(path, acquisition)
        records.append((path, extracted, source_root / "acquisition-receipt.json"))
    return root, records


def test_stage_rebinds_only_source_fields_and_preserves_package(tmp_path):
    root, records = _fixture(tmp_path)
    before = {str(path): _sha(path) for path, _, _ in records}
    work_state = {str(p): _sha(p) for wid in ("alpha", "beta")
                  for p in (root / "library/works" / wid / "work.json",
                            root / "library/works" / wid / "state.json")}
    manifest = stage(root, tmp_path / "stage", expected_families={"openmgh": 1, "gutenberg": 1})
    assert len(manifest["entries"]) == 2
    for path, extracted, _ in records:
        rel = path.relative_to(root)
        old = json.loads(path.read_text(encoding="utf-8"))
        new = json.loads((tmp_path / "stage" / rel).read_text(encoding="utf-8"))
        assert new["source_path"].endswith(extracted.name)
        assert new["source_sha256"] == _sha(extracted)
        assert len(new["retained_files"]) == len(old["retained_files"])
        for original_member, proposed_member in zip(old["retained_files"], new["retained_files"]):
            if proposed_member["path"] == new["source_path"]:
                assert proposed_member["scope"] == new["source_scope"]
                assert {k: v for k, v in proposed_member.items() if k != "scope"} == {
                    k: v for k, v in original_member.items() if k != "scope"}
            else:
                assert proposed_member == original_member
        changed = {"source_path", "source_bytes", "source_sha256", "source_scope", "retained_files"}
        assert {k: v for k, v in new.items() if k not in changed} == {
            k: v for k, v in old.items() if k not in changed}
        assert _sha(path) == before[str(path)]
    assert all(_sha(Path(p)) == digest for p, digest in work_state.items())


def test_rejects_changed_member_and_receipt(tmp_path):
    root, records = _fixture(tmp_path)
    records[0][1].write_bytes(b"changed")
    with pytest.raises(PipelineError, match="extracted source member missing or changed"):
        prepare(root, expected_families={"openmgh": 1, "gutenberg": 1})
    root, records = _fixture(tmp_path / "second")
    receipt_path = records[1][2]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["html"]["sha256"] = "0" * 64
    write_json(receipt_path, receipt)
    with pytest.raises(PipelineError, match="Gutenberg source/receipt identity differs"):
        prepare(root, expected_families={"openmgh": 1, "gutenberg": 1})


def test_rejects_ambiguous_text_member(tmp_path):
    root, records = _fixture(tmp_path)
    acquisition_path = records[1][0]
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    acquisition["retained_files"].append({"path": "raw/gutenberg/12345/html/other.html",
                                           "bytes": 1, "sha256": "0" * 64,
                                           "media_type": "text/html", "scope": "Other text."})
    write_json(acquisition_path, acquisition)
    with pytest.raises(PipelineError, match="retained extracted member inventory differs"):
        prepare(root, expected_families={"openmgh": 1, "gutenberg": 1})


def test_apply_rejects_stale_or_tampered_stage(tmp_path):
    root, records = _fixture(tmp_path)
    stage(root, tmp_path / "stage", expected_families={"openmgh": 1, "gutenberg": 1})
    staged = tmp_path / "stage" / records[0][0].relative_to(root)
    staged.write_bytes(staged.read_bytes() + b" ")
    with pytest.raises(PipelineError, match="stage/current sidecar changed"):
        apply_staged(root, tmp_path / "stage", expected_families={"openmgh": 1, "gutenberg": 1})
    assert not (tmp_path / "stage/operation.json").exists()
    assert json.loads(records[0][0].read_text(encoding="utf-8"))["source_path"].endswith(".zip")


def test_apply_installs_and_validates_extracted_source(tmp_path):
    root, records = _fixture(tmp_path)
    stage(root, tmp_path / "stage", expected_families={"openmgh": 1, "gutenberg": 1})
    result = apply_staged(root, tmp_path / "stage", expected_families={"openmgh": 1, "gutenberg": 1})
    assert len(result["installed"]) == 2
    for path, extracted, _ in records:
        acquisition = json.loads(path.read_text(encoding="utf-8"))
        assert acquisition["source_path"].endswith(extracted.name)
    assert json.loads((tmp_path / "stage/operation.json").read_text(encoding="utf-8"))["phase"] == "complete"


def test_apply_rolls_back_after_post_validation_failure(tmp_path, monkeypatch):
    import build.tools.rebind_archive_source_members as tool
    root, records = _fixture(tmp_path)
    before = {str(path): _sha(path) for path, _, _ in records}
    stage(root, tmp_path / "stage", expected_families={"openmgh": 1, "gutenberg": 1})
    original = tool.validate_state
    calls = 0
    def fail_second(path, *, root):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PipelineError("injected post-validation failure")
        return original(path, root=root)
    monkeypatch.setattr(tool, "validate_state", fail_second)
    with pytest.raises(PipelineError, match="injected post-validation failure"):
        apply_staged(root, tmp_path / "stage", expected_families={"openmgh": 1, "gutenberg": 1})
    assert all(_sha(Path(path)) == digest for path, digest in before.items())
    assert json.loads((tmp_path / "stage/operation.json").read_text(encoding="utf-8"))["phase"] == "rolled-back"


def test_long_windows_acquisition_path_rebind(tmp_path):
    deep = tmp_path / ("x" * 100)
    root, records = _fixture(deep)
    assert max(len(str(path)) for path, _, _ in records) > 260
    destination = tmp_path / "long-stage"
    stage(root, destination, expected_families={"openmgh": 1, "gutenberg": 1})
    result = apply_staged(root, destination, expected_families={"openmgh": 1, "gutenberg": 1})
    assert len(result["installed"]) == 2
    assert all(json.loads(io_path(path).read_text(encoding="utf-8"))["source_path"].endswith((".xml", ".html"))
               for path, _, _ in records)


def test_legacy_reader_does_not_relax_current_acquisition_loading(tmp_path):
    from ocd_kernel.library.acquisitions import load_acquisition

    root, records = _fixture(tmp_path)
    for path, _, _ in records:
        with pytest.raises(PipelineError, match="source_path cannot identify a ZIP package"):
            load_acquisition(path)
    destination = tmp_path / "stage"
    manifest = stage(root, destination, expected_families={"openmgh": 1, "gutenberg": 1})
    assert len(manifest["entries"]) == 2
    for entry in manifest["entries"]:
        current = load_acquisition(destination / entry["path"])
        assert current["source_path"] == entry["source_path"]
        assert not current["source_path"].endswith(".zip")


@pytest.mark.parametrize("mutation", [
    "unsafe-acquisition-id", "unsafe-retained-path", "duplicate-retained-path",
    "invalid-retained-hash", "boolean-retained-size", "negative-source-size",
])
def test_legacy_migration_preserves_other_acquisition_guards(tmp_path, mutation):
    root, records = _fixture(tmp_path)
    path = records[0][0]
    record = json.loads(path.read_bytes())
    if mutation == "unsafe-acquisition-id":
        record["acquisition_id"] = "../alpha"
    elif mutation == "unsafe-retained-path":
        record["retained_files"][0]["path"] = "../outside.zip"
    elif mutation == "duplicate-retained-path":
        record["retained_files"].append(copy.deepcopy(record["retained_files"][0]))
    elif mutation == "invalid-retained-hash":
        record["retained_files"][0]["sha256"] = "g" * 64
    elif mutation == "boolean-retained-size":
        record["retained_files"][0]["bytes"] = True
    else:
        record["source_bytes"] = -1
    write_json(path, record)
    destination = tmp_path / "stage"
    before = {str(p): _sha(p) for p, _, _ in records}
    with pytest.raises(PipelineError):
        stage(root, destination, expected_families={"openmgh": 1, "gutenberg": 1})
    assert not destination.exists()
    assert {str(p): _sha(p) for p, _, _ in records} == before
