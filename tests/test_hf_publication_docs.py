"""Protect verified data/notice wording while delivering usable public documents."""

import hashlib
import json
from pathlib import Path
import re

import pytest

from build.tools import prepare_hf_publication_docs as docs
from build.tools import upload_hf_release_v2 as uploader
from ocd_kernel.library._common import canonical_bytes, sha256_file


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "_languages", lambda release: ["en"])
    root = tmp_path
    release = root / "release"
    (release / "public/data/prose").mkdir(parents=True)
    source = f"sources/prose/{docs.SOURCE_WORKS[0]}/README.source.md"
    original = ("---\npretty_name: Open Christian Data\nconfigs:\n"
                "- config_name: prose\n  data_files: data/prose/train.jsonl\n---\n\n# Collection\n\n"
                f"## Source notices\n\nRequired license. [Source](../../../{source})\n")
    (release / "public/README.md").write_text(original, encoding="utf-8", newline="\n")
    (release / "public/data/prose/train.jsonl").write_bytes(b'{"text":"unchanged"}\n')
    for public, owning in docs._support_sources(docs.source_notices(original)).items():
        path = root / owning
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# Public guidance\n")
    (root / "docs/HUGGINGFACE_DATASET_CARD.md").write_text(
        original.replace("pretty_name: Open Christian Data\n", "pretty_name: Open Christian Data - v1.0.0\n"),
        encoding="utf-8", newline="\n")
    result = docs.prepare(root, release, {}, root / "delivery")
    return root, release, Path(result["manifest"]), result["manifest_sha256"]


def _repin(manifest, name, change):
    path = manifest.parent / name
    path.write_bytes(change(path.read_bytes()))
    record = json.loads(manifest.read_bytes())
    for entry in record["files"]:
        if entry["path"] == name:
            entry.update(size_bytes=path.stat().st_size, sha256=sha256_file(path))
    manifest.write_bytes(canonical_bytes(record))
    return sha256_file(manifest)


def test_documents_preserve_data_and_source_terms(prepared):
    root, release, manifest, digest = prepared
    payload = docs.check_documents(root, release, {}, manifest, digest)
    assert (release / "public/data/prose/train.jsonl").read_bytes() == b'{"text":"unchanged"}\n'
    assert b"Required license." in payload[docs.SOURCE_NOTICES]
    assert b"../../../sources" not in payload[docs.SOURCE_NOTICES]
    assert b"Required license." not in payload["README.md"]
    assert payload["LICENSE"] == payload["HF_DATA_LICENSE.md"]
    metadata, _ = docs._card(payload["README.md"].decode("utf-8"))
    assert re.fullmatch(r"[a-z0-9.-]+", metadata["license_name"])


@pytest.mark.parametrize("mutation", ["reader", "language", "notice", "private", "guide", "editorial"])
def test_repinned_documents_cannot_change_protected_content(prepared, mutation):
    root, release, manifest, digest = prepared
    if mutation == "editorial":
        (root / "docs/HUGGINGFACE_DATASET_CARD.md").write_text("Changed", encoding="utf-8")
    elif mutation == "guide":
        digest = _repin(manifest, "HF_DATA_GUIDE.md", lambda value: value + b"Unreviewed guidance\n")
    else:
        name = docs.SOURCE_NOTICES if mutation == "notice" else "README.md"
        replacements = {
            "reader": lambda b: b.replace(b"config_name: prose", b"config_name: altered"),
            "language": lambda b: b.replace(b"- en\n", b"- fr\n"),
            "notice": lambda b: b.replace(b"Required license.", b"License omitted."),
            "private": lambda b: b + b"C:/Users/private\n",
        }
        digest = _repin(manifest, name, replacements[mutation])
    with pytest.raises(docs.DocumentError):
        docs.check_documents(root, release, {}, manifest, digest)


def test_changed_document_and_wrong_selection_fail(prepared):
    root, release, manifest, digest = prepared
    with pytest.raises(docs.DocumentError, match="selection"):
        docs.check_documents(root, release, {"changed": True}, manifest, digest)
    (manifest.parent / "HF_DATA_GUIDE.md").write_bytes(b"changed\n")
    with pytest.raises(docs.DocumentError, match="document changed"):
        docs.check_documents(root, release, {}, manifest, digest)


def test_notice_repairs_leave_quoted_terms_verbatim():
    old = "../../../docs/sources/ccel-permission.md"
    text = f"## Source notices\n\n[Link]({old})\n\n```text\n[Literal]({old})\n```\n"
    repaired = docs.source_notices(text)
    assert f"[Literal]({old})" in repaired
    assert f"[Link]({docs.LINK_FIXES[old]})" in repaired


def test_baxter_sentence_removed_without_changing_boethius_or_quoted_terms():
    baxter = "The selected historical layer is Richard Baxter's Reformed Pastor. " + docs.BAXTER_CLAUSE + docs.BAXTER_MARKER
    boethius = "The selected historical layer is Boethius's five tracts. " + docs.BAXTER_CLAUSE
    original = f"## Source notices\n\n{baxter}\n\n{boethius}\n\n```text\n{baxter}\n```\n"
    corrected = docs.source_notices(original)
    assert docs.BAXTER_CLAUSE not in corrected.split("\n\n")[1]
    assert boethius in corrected
    assert "```text\n" + baxter + "\n```" in corrected


def test_baxter_notice_input_guard_rejects_other_wording_changes(tmp_path, monkeypatch):
    from ocd_kernel.library import rights

    monkeypatch.setattr(rights, "collect_rights", lambda *args: {"health": "valid"})
    before = "The selected historical layer is Richard Baxter's Reformed Pastor. " + docs.BAXTER_CLAUSE + docs.BAXTER_MARKER + "\n"
    after = before.replace(docs.BAXTER_CLAUSE, "")
    source, notice = "sources/prose/baxter-reformed-pastor/README.source.md", "data/prose/baxter-reformed-pastor/README.md"
    for name in (source, notice):
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(after.encode())
    acceptance = "library/works/baxter-reformed-pastor/acceptance.json"
    path = tmp_path / acceptance; path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"identity": {"work_id": "baxter-reformed-pastor", "textual_form_id": "en", "edition_id": "first"}}), encoding="utf-8")
    binding = {"source_path": source, "notice_path": notice,
               "source_sha256": hashlib.sha256(before.encode()).hexdigest(),
               "notice_sha256": hashlib.sha256(before.encode()).hexdigest()}
    selection = {"items": [{"work_id": "baxter-reformed-pastor", "acceptance_path": acceptance, "public_notices": [binding]}]}
    assert len(docs._notice_correction_inputs(tmp_path, selection, before)) == 2
    (tmp_path / notice).write_bytes((after + "Unreviewed license change.\n").encode())
    with pytest.raises(docs.DocumentError, match="beyond the authorized"):
        docs._notice_correction_inputs(tmp_path, selection, before)


def test_unexpected_file_set_and_bad_relative_link_fail(prepared):
    root, release, manifest, digest = prepared
    digest = _repin(manifest, "README.md", lambda b: b.replace(b"# Collection", b"# Collection\n[Missing](absent.md)"))
    with pytest.raises(docs.DocumentError, match="unresolved public link"):
        docs.check_documents(root, release, {}, manifest, digest)
    record = json.loads(manifest.read_bytes())
    record["files"].append({"path": "internal/private.json", "sha256": "0" * 64, "size_bytes": 0})
    manifest.write_bytes(canonical_bytes(record))
    with pytest.raises(docs.DocumentError, match="file set"):
        docs.check_documents(root, release, {}, manifest, sha256_file(manifest))


def test_uploader_reuses_verified_data_and_accounts_for_documents(prepared, monkeypatch):
    root, release, manifest, digest = prepared
    files = [{"path": p.relative_to(release / "public").as_posix(), "size_bytes": p.stat().st_size,
              "sha256": sha256_file(p)} for p in (release / "public").rglob("*") if p.is_file()]
    monkeypatch.setattr(uploader, "_verified_preview", lambda *a: {"status": "pass", "files": files})
    monkeypatch.setattr(uploader, "preview_release", lambda *a, **k: pytest.fail("data verifier repeated"))
    preview, payload = uploader._local_payload(root, release, {}, verified_manifest=root / "proof.json",
        manifest_sha256="a" * 64, publication_docs=manifest, publication_docs_sha256=digest)
    assert {e["path"] for e in preview["files"]} == set(payload)
    assert payload["data/prose/train.jsonl"].read_bytes() == b'{"text":"unchanged"}\n'
    assert preview["publication_documents_sha256"] == digest
    for entry in preview["files"]:
        content = payload[entry["path"]]
        raw = content.read_bytes() if isinstance(content, Path) else content
        assert len(raw) == entry["size_bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"]


def test_document_overlay_requires_pinned_data_proof(prepared):
    root, release, manifest, digest = prepared
    with pytest.raises(uploader.UploadError, match="pinned data proof"):
        uploader._local_payload(root, release, {}, publication_docs=manifest, publication_docs_sha256=digest)


def test_catalog_additions_are_checked_against_their_producer(prepared, monkeypatch):
    from build.tools import release_catalog

    root, release, _, _ = prepared
    fixture_catalog = {"WORK_CATALOG.md": b"# Selected catalog\n"}
    monkeypatch.setattr(release_catalog, "catalog_documents", lambda *args: fixture_catalog)
    (root / "docs/RELEASE_CATALOG.md").write_bytes(b"# Catalog guide\n")
    editorial = root / "docs/HUGGINGFACE_DATASET_CARD.md"
    editorial.write_text(editorial.read_text(encoding="utf-8").replace(
        "# Collection", "# Collection\n[Catalog](WORK_CATALOG.md)"), encoding="utf-8", newline="\n")
    result = docs.prepare(root, release, {}, root / "with-catalog", include_catalog=True)
    manifest = Path(result["manifest"])
    payload = docs.check_documents(root, release, {}, manifest, result["manifest_sha256"])
    assert payload["WORK_CATALOG.md"] == fixture_catalog["WORK_CATALOG.md"]
    digest = _repin(manifest, "WORK_CATALOG.md", lambda value: value + b"Unselected work\n")
    with pytest.raises(docs.DocumentError, match="catalog differs"):
        docs.check_documents(root, release, {}, manifest, digest)
