"""ZIP payload counts and body image occurrences are different inventories."""
from zipfile import ZipFile
import json
import pytest
from build.lib.source_archive import inventory_zip
from build.tools.preflight_source import main


def archive(tmp_path, html):
    path = tmp_path / "source.zip"
    with ZipFile(path, "w") as z:
        z.writestr("book/", b"")
        z.writestr("book/main.html", html)
        z.writestr("book/images/cover.jpg", b"image")
        z.writestr("book/images/unused.jpg", b"support")
    return path


def test_referenced_and_unreferenced_images_distinct(tmp_path):
    path = archive(tmp_path, '<img src="images/cover.jpg" alt=""><img src="images/cover.jpg">')
    report = inventory_zip(path, html_member="book/main.html")
    assert report["status"] == "inventoried"
    assert (report["entries"], report["directories"], report["file_payloads"]) == (4, 1, 3)
    assert len(report["image_references"]) == 2
    assert report["image_references"][0]["alt"] == ""
    assert report["image_references"][1]["alt"] is None
    assert report["members"][-1]["role"] == "other-retained-member"
    assert report["visual_equivalence"] == "not-assessed"


def test_archive_cover_does_not_imply_body_occurrence(tmp_path):
    assert inventory_zip(archive(tmp_path, '<p>Text</p>'), html_member="book/main.html")["image_references"] == []


@pytest.mark.parametrize("src", ["missing.jpg", "../../outside.jpg", "/cover.jpg", "https://example.org/cover.jpg"])
def test_missing_and_outside_targets_block(tmp_path, src):
    report = inventory_zip(archive(tmp_path, f'<img src="{src}">'), html_member="book/main.html")
    assert report["status"] == "blocked"


def test_size_and_missing_html_are_accounted(tmp_path):
    report = inventory_zip(archive(tmp_path, "long text"), html_member="absent.html", max_bytes=2)
    assert report["status"] == "blocked" and report["file_payloads"] == 3


def test_topology_preflight_without_junction(tmp_path, capsys):
    repo = tmp_path / "repo"
    library = tmp_path / "library"
    repo.mkdir()
    library.mkdir()
    (library / "raw").mkdir()
    (repo / ".ocd-storage.json").write_text(json.dumps({"library_root": str(library)}))
    path = library / "raw/source.xml"
    path.write_text('<doc><p>Text</p></doc>')
    assert main(["raw/source.xml", "--repository-root", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["members"][0]["status"] == "inventoried"
    assert not (repo / "raw").exists()
    assert main(["../source.xml", "--repository-root", str(repo)]) == 2


def test_body_region_and_base_resolution_are_not_inferred(tmp_path):
    path = archive(tmp_path, '<head><img src="images/cover.jpg"></head><body><img src="images/cover.jpg"></body>')
    report = inventory_zip(path, html_member="book/main.html")
    assert [r["source_region"] for r in report["image_references"]] == ["outside-explicit-body", "body"]
    path = archive(tmp_path, '<base href="https://example.org/"><body><img src="images/cover.jpg"></body>')
    report = inventory_zip(path, html_member="book/main.html")
    assert report["status"] == "blocked"
    assert report["image_references"][0]["status"] == "unsupported-base-resolution"


def test_duplicate_archive_member_blocks_inventory(tmp_path):
    path = archive(tmp_path, '<img src="images/cover.jpg">')
    with pytest.warns(UserWarning), ZipFile(path, "a") as z:
        z.writestr("book/images/cover.jpg", b"other")
    report = inventory_zip(path, html_member="book/main.html")
    assert report["status"] == "blocked"
    assert any(d["code"] == "duplicate-member" for d in report["diagnostics"])
