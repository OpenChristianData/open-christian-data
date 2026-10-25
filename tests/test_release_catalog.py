"""The public catalog must describe the exact released copies and no private ones."""
import csv
import hashlib
import io
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from build.tools import release_catalog as catalog
from ocd_kernel.library._common import PipelineError, canonical_bytes, sha256_file
from tests.test_library_records import root, write


@pytest.fixture
def release(root):
    profile = "schemas/v2/metadata-labels.json"
    target = root / profile
    target.parent.mkdir(parents=True)
    target.write_bytes((Path(__file__).resolve().parents[1] / profile).read_bytes())
    work_path = root / "library/works/alpha/work.json"
    work = json.loads(work_path.read_bytes())
    work["textual_forms"][0]["editions"][0]["containing_source"] = {
        "title": "A larger collection", "locator": "raw/private/container.xml#part",
        "evidence": ["research/evidence.md"]}
    work["creators"] = [
        {"name": "A. Writer", "role": "author", "scope": {"kind": "work", "id": "alpha"}},
        {"name": "Other Translator", "role": "translator", "scope": {"kind": "edition", "id": "second"}},
        {"name": "A. Editor", "role": "editor", "scope": {"kind": "component", "id": "preface"}},
    ]
    write(work_path, work)
    acceptance_path = "library/works/alpha/forms/en/editions/first/acceptance.json"
    identity = {"work_id": "alpha", "edition_id": "first", "textual_form_id": "en"}
    write(root / acceptance_path, {"identity": dict(identity, acquisition_id="copy")})
    selection = {"items": [
        {"item_id": "first", "work_id": "alpha", "category": "prose", "license": "Public domain", "acceptance_path": acceptance_path},
        {"item_id": "second", "work_id": "alpha", "category": "prose", "exclude_reason": "Private"},
    ]}
    selected_sha = hashlib.sha256(canonical_bytes(selection)).hexdigest()
    release = root / "release"
    write(release / "internal/release-report.json", {"status": "pass", "selection_sha256": selected_sha,
          "configurations": [{"category": "prose", "row_count": 2}],
          "items": [{"item_id": "first", "status": "warned", "receipt_path": "internal/receipt.json",
                     "row_count": 2, "category": "prose"}, {"item_id": "second", "status": "excluded"}]})
    write(release / "internal/receipt.json", {"identity": {"work_id": "alpha", "edition_id": "first",
          "textual_form_id": "en"}, "row_count": 2})
    write(release / "internal/build-manifest.json", {"selection_sha256": selected_sha, "inputs": {
        "item_bindings": [{"item_id": "first", "files": [{"path": acceptance_path, "sha256": sha256_file(root / acceptance_path)}]}],
        "work_bindings": [{"work_id": "alpha", "files": [{"path": "library/works/alpha/work.json",
                           "sha256": sha256_file(work_path)}]}],
        "shared": [{"path": profile, "sha256": sha256_file(target)}]}})
    return root, release, selection


def test_exact_selected_copies_scoped_credits_and_shared_exports(release):
    root, package, selection = release
    rows = catalog.selected_records(root, package, selection)
    assert len(rows) == 1 and rows[0]["records"] == 2
    assert rows[0]["containing_source"] == {"title": "A larger collection"}
    assert [c["name"] for c in rows[0]["creators"]] == ["A. Writer", "A. Editor"]
    documents = catalog.render_catalog(rows)
    assert b"Other Translator" not in b"".join(documents.values())
    assert b"component: preface" in documents["WORK_CATALOG.md"]
    csv_rows = list(csv.DictReader(io.StringIO(documents["WORK_CATALOG.csv"].decode())))
    xml = ET.fromstring(documents["WORK_CATALOG.mods.xml"])
    assert len(csv_rows) == len(xml) == 1
    assert xml.findtext(f".//{{{catalog.MODS}}}identifier[@type='ocd-edition-id']") == csv_rows[0]["edition_id"]
    assert xml.findtext(f".//{{{catalog.MODS}}}roleTerm[@authority='marcrelator']") == "aut"
    assert catalog.catalog_documents(root, package, selection) == documents


def test_counts_use_the_public_report_after_private_row_filtering(release):
    root, package, selection = release
    path = package / "internal/receipt.json"
    acceptance_path = selection["items"][0]["acceptance_path"]
    write(path, {"row_count": 3, "authority": {"acceptance": {
        "path": acceptance_path, "sha256": sha256_file(root / acceptance_path)}}})
    rows = catalog.selected_records(root, package, selection)
    assert len(rows) == 1 and rows[0]["records"] == 2


def test_readable_bibliography_preserves_exact_exchange_values(release):
    root, package, selection = release
    rows = catalog.selected_records(root, package, selection)
    rows[0].update(edition_title="Retained CCEL ThML electronic witness", creators=[], license="Unlicense")
    documents = catalog.render_catalog(rows)
    readable = documents["WORK_CATALOG.md"].decode()
    assert "**Edition:**" not in readable
    assert "**Language:** English" in readable
    assert "Public-domain dedication (Unlicense)" in readable
    assert "No named responsibility recorded" not in readable
    assert "Anonymous" not in readable
    assert "Retained CCEL ThML electronic witness" in documents["WORK_CATALOG.csv"].decode()
    assert "Retained CCEL ThML electronic witness" in documents["WORK_CATALOG.mods.xml"].decode()
    qualified = "Public domain (United States); historical text only; provider restrictions apply"
    assert catalog.terms_display(qualified) == qualified
    assert catalog.edition_display("Revised electronic witness (abridged; 184?)") == "Revised digital text (abridged; 184?)"
    assert catalog.edition_display("Fourth edition, 1888; Project Gutenberg HTML ZIP witness") == "Fourth edition, 1888; Project Gutenberg digital text"
    assert catalog.edition_display("Open English Bible (US and Commonwealth witnesses)") == "Open English Bible (US and Commonwealth copies)"


def test_publication_statement_does_not_make_empty_mods_origin_or_duplicate_host(release):
    root, package, selection = release
    rows = catalog.selected_records(root, package, selection)
    rows[0]["publication"] = {"scope": "source-volume", "statement": "A source publication statement"}
    xml = ET.fromstring(catalog.render_catalog(rows)["WORK_CATALOG.mods.xml"])
    assert not xml.findall(f".//{{{catalog.MODS}}}originInfo")
    assert len(xml.findall(f".//{{{catalog.MODS}}}relatedItem[@type='host']")) == 1
    assert xml.findtext(f".//{{{catalog.MODS}}}note[@type='source publication']") == "A source publication statement"


@pytest.mark.parametrize("changed", ["work", "profile", "selection", "acceptance", "missing_edition", "duplicate", "counts"])
def test_drift_or_incomplete_join_fails(release, changed):
    root, package, selection = release
    if changed == "work":
        path = root / "library/works/alpha/work.json"
        work = json.loads(path.read_bytes()); work["title"] = "Changed"; write(path, work)
    elif changed == "profile":
        (root / "schemas/v2/metadata-labels.json").write_bytes(b"{}")
    elif changed in ("acceptance", "missing_edition"):
        path = root / selection["items"][0]["acceptance_path"]
        acceptance = json.loads(path.read_bytes())
        if changed == "acceptance": acceptance["identity"]["work_id"] = "wrong"
        else: acceptance["identity"]["edition_id"] = "missing"
        write(path, acceptance)
        if changed == "missing_edition":
            bound = package / "internal/build-manifest.json"
            manifest = json.loads(bound.read_bytes())
            manifest["inputs"]["item_bindings"][0]["files"][0]["sha256"] = sha256_file(path)
            write(bound, manifest)
    elif changed == "counts":
        path = package / "internal/release-report.json"
        report = json.loads(path.read_bytes()); report["items"][0]["row_count"] = 100; write(path, report)
    elif changed == "duplicate":
        path = package / "internal/release-report.json"
        report = json.loads(path.read_bytes()); report["items"].append(report["items"][0]); write(path, report)
    else:
        selection["items"][0]["category"] = "prayers"
    with pytest.raises(PipelineError):
        catalog.selected_records(root, package, selection)


def test_private_display_content_is_rejected(release):
    root, package, selection = release
    path = root / "library/works/alpha/work.json"
    work = json.loads(path.read_bytes()); work["title"] = "C:/Users/private/person"; write(path, work)
    bound = package / "internal/build-manifest.json"
    manifest = json.loads(bound.read_bytes())
    manifest["inputs"]["work_bindings"][0]["files"][0]["sha256"] = sha256_file(path)
    write(bound, manifest)
    with pytest.raises(PipelineError, match="private"):
        catalog.selected_records(root, package, selection)
