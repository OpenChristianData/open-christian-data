from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

import pytest

from build.tools.build_hf_release import main as build_release_main
from build.tools.build_library_views import main as build_views_main
from build.tools.check_hf_release import main as check_release_main
from ocd_kernel.library._common import canonical_bytes, sha256_bytes
from ocd_kernel.library.acquisitions import (
    acquisition_for_edition,
    load_acquisition,
    source_sha256,
)
from ocd_kernel.library.identities import discover_library, edition_by_id
from ocd_kernel.library.state import load_state, reconcile_state
from ocd_kernel.library.views import build_library_views
from ocd_kernel.projection.categories.prose import project_prose
from ocd_kernel.projection.envelope import make_row, row_text_hash
from ocd_kernel.projection.receipt import check_receipt_shape
from ocd_kernel.release.assemble import assemble_release
from ocd_kernel.release.check import check_release
from ocd_kernel.release.public_allowlist import check_public_allowlist
from ocd_kernel.release.selection import make_selection


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "library-pipeline"
WORK_ID = "athanasius-on-the-incarnation"
FORM_ID = "athanasius-on-the-incarnation-prose"
EDITION_ID = "ccel-npnf204"
ACQUISITION_ID = "ccel-npnf204-retained-xml"
SOURCE_URL = "https://www.ccel.org/ccel/schaff/npnf204.xml"
WHOLE_SOURCE_SHA256 = "bd625a0fa4f5ddd4b2fa13fcee753de8832ea4b316625e0e06454beb81cfa652"
RETAINED_MEMBER = "retained/npnf204.vii.ii.i.thml.xml"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {
        child: parent
        for parent in root.iter()
        for child in list(parent)
    }


def _normalise_text(element: ET.Element, *, exclude_notes: bool = False) -> str:
    pieces: list[str] = []

    def visit(node: ET.Element) -> None:
        if exclude_notes and _local(node.tag) == "note":
            if node.tail:
                pieces.append(node.tail)
            return
        if node.text:
            pieces.append(node.text)
        for child in list(node):
            visit(child)
        if node.tail:
            pieces.append(node.tail)

    visit(element)
    return " ".join("".join(pieces).split())


def _fixture_root(tmp_path: Path) -> Path:
    destination = tmp_path / "f"
    shutil.copytree(FIXTURE_ROOT, destination)
    return destination


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Use a short module-local temp leaf for Windows MAX_PATH coverage."""

    return tmp_path_factory.mktemp("p")


def _invoke(main: Callable[[list[str]], int], args: list[str]) -> int:
    try:
        result = main(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0 if result is None else int(result)


def _release(root: Path, output: Path) -> int:
    return _invoke(
        build_release_main,
        [
            "--root",
            str(root),
            "--output",
            str(output),
            "--release-id",
            "pipe-001-fixture",
            "--edition-id",
            EDITION_ID,
            "--category",
            "prose",
        ],
    )


def _release_subprocess(root: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "build.tools.build_hf_release",
            "--root",
            str(root),
            "--output",
            str(output),
            "--release-id",
            "pipe-001-fixture",
            "--edition-id",
            EDITION_ID,
            "--category",
            "prose",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _checker(root: Path, output: Path) -> int:
    return _invoke(
        check_release_main,
        ["--release", str(output), "--root", str(root)],
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _replace_public_hashes(value: object, digest: str) -> bool:
    changed = False
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "public_sha256":
                value[key] = digest
                changed = True
            else:
                changed = _replace_public_hashes(child, digest) or changed
    elif isinstance(value, list):
        for child in value:
            changed = _replace_public_hashes(child, digest) or changed
    return changed


def _reseal_public_hashes(output: Path) -> None:
    public_path = output / "public" / "data" / "prose" / "train.jsonl"
    digest = hashlib.sha256(public_path.read_bytes()).hexdigest()
    for path in sorted((output / "internal").rglob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if _replace_public_hashes(value, digest):
            _write_json(path, value)


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _master_path(root: Path) -> Path:
    return (
        root
        / "library"
        / "works"
        / WORK_ID
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
        / "master.tei.xml"
    )


def test_fixture_preserves_source_native_carriers_and_identity() -> None:
    source = ET.parse(FIXTURE_ROOT / RETAINED_MEMBER).getroot()
    master = ET.parse(
        FIXTURE_ROOT
        / "library"
        / "works"
        / WORK_ID
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
        / "master.tei.xml"
    ).getroot()

    assert source.tag == "div3"
    assert source.get("id") == "vii.ii.i"
    assert source.get("type") == "Section"
    selected = next(
        node
        for node in master.iter()
        if _local(node.tag) == "div" and node.get(XML_ID) == "vii.ii.i"
    )
    source_parents = _parent_map(source)
    tei_parents = _parent_map(master)
    assert selected.find(f"{{{TEI_NS}}}head").text == source.get("title")

    source_paragraphs = [node for node in source if node.tag == "p"]
    tei_paragraphs = [
        node for node in selected
        if _local(node.tag) == "p"
    ]
    assert [node.get("id") for node in source_paragraphs] == [
        node.get(XML_ID) for node in tei_paragraphs
    ]
    assert len(source_paragraphs) == len(tei_paragraphs) == 4
    for source_paragraph, tei_paragraph in zip(source_paragraphs, tei_paragraphs):
        assert _normalise_text(source_paragraph, exclude_notes=True) == _normalise_text(
            tei_paragraph, exclude_notes=True
        )

    source_notes = [node for node in source.iter() if node.tag == "note"]
    tei_notes = [node for node in selected.iter() if _local(node.tag) == "note"]
    assert [node.get("id") for node in source_notes] == [
        node.get(XML_ID) for node in tei_notes
    ]
    assert len(source_notes) == len(tei_notes) == 2
    for source_note, tei_note in zip(source_notes, tei_notes):
        assert _normalise_text(source_note) == _normalise_text(tei_note)
        assert source_note.get("place") == tei_note.get("place")
        assert source_note.get("n") == tei_note.get("n")
    assert [
        (source_note.get("id"), source_parents[source_note].get("id"))
        for source_note in source_notes
    ] == [
        ("vii.ii.i-p4.2", "vii.ii.i-p4"),
        ("vii.ii.i-p5.2", "vii.ii.i-p4"),
    ]
    assert [
        (tei_note.get(XML_ID), tei_parents[tei_note].get(XML_ID))
        for tei_note in tei_notes
    ] == [
        ("vii.ii.i-p4.2", "vii.ii.i-p4"),
        ("vii.ii.i-p5.2", "vii.ii.i-p4"),
    ]
    assert [node.get(XML_ID) for node in tei_paragraphs] == [
        "vii.ii.i-p1",
        "vii.ii.i-p2",
        "vii.ii.i-p3",
        "vii.ii.i-p4",
    ]
    assert all(_local(node.tag) == "p" for node in tei_paragraphs)

    acquisition = json.loads(
        (
            FIXTURE_ROOT
            / "library"
            / "works"
            / WORK_ID
            / "forms"
            / FORM_ID
            / "editions"
            / EDITION_ID
            / "acquisitions"
            / f"{ACQUISITION_ID}.json"
        ).read_text(encoding="utf-8")
    )
    retained = FIXTURE_ROOT / acquisition["retained_files"][0]["path"]
    assert retained.is_file()
    assert retained.stat().st_size == acquisition["retained_files"][0]["bytes"]
    assert hashlib.sha256(retained.read_bytes()).hexdigest() == acquisition["retained_files"][0]["sha256"]
    assert acquisition["source_path"] == "raw/ccel/npnf2/npnf204.xml"
    assert acquisition["source_sha256"] == WHOLE_SOURCE_SHA256
    assert acquisition["url"] == SOURCE_URL

    tei_source_desc = [
        node
        for node in master.iter()
        if _local(node.tag) == "idno" and node.get("type") in {"sha256", "source_sha256"}
    ]
    assert [(node.get("type"), node.text) for node in tei_source_desc] == [
        ("sha256", "d16a6d825621cde9b93c5ed54489521895b9b9e44098b38bd61c437b927faafa"),
        ("source_sha256", WHOLE_SOURCE_SHA256),
    ]


def test_direct_pipeline_apis_bind_identity_projection_and_allowlist(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    works = discover_library(root)
    assert [work.work_id for work in works] == [WORK_ID]
    work, edition = edition_by_id(root, EDITION_ID)
    assert work.work_id == WORK_ID
    assert edition.textual_form_id == FORM_ID
    assert edition.path == _master_path(root)

    state_path = root / "library" / "works" / WORK_ID / "state.json"
    state = load_state(state_path)
    assert state["work_id"] == WORK_ID
    state_facts = reconcile_state(root, work_id=WORK_ID, edition_id=EDITION_ID, master_path=edition.path)
    assert state_facts["status"] == "included"

    acquisition_path, acquisition = acquisition_for_edition(root, WORK_ID, EDITION_ID)
    assert load_acquisition(acquisition_path)["acquisition_id"] == ACQUISITION_ID
    assert source_sha256(acquisition, context=str(acquisition_path)) == WHOLE_SOURCE_SHA256

    view_output = tmp_path / "api-views"
    view_result = build_library_views(root, view_output)
    assert view_result["status"]["counts"]["included"] == 1
    selection = make_selection(
        release_id="pipe-001-api",
        category="prose",
        edition_id=EDITION_ID,
        status_report=view_result["status"],
    )
    assert selection["accounting"] == {
        "requested": 1,
        "selected": 1,
        "included": 1,
        "warned": 0,
        "failed": 0,
        "excluded": 0,
    }

    projection = project_prose(
        edition.path,
        work_id=WORK_ID,
        textual_form_id=FORM_ID,
        edition_id=EDITION_ID,
        acquisition_id=ACQUISITION_ID,
        edition_title=edition.title,
        language="en",
        representation_revision="pipe-001-fixture-v1",
        source_url=SOURCE_URL,
        accessed_at=None,
        source_sha256=WHOLE_SOURCE_SHA256,
        retained_sha256=acquisition["retained_files"][0]["sha256"],
    )
    assert len(projection.rows) == 4
    assert projection.source_binding["source_sha256"] == WHOLE_SOURCE_SHA256
    sample = make_row(
        record_id="sample",
        sequence=1,
        work_id=WORK_ID,
        textual_form_id=FORM_ID,
        edition_id=EDITION_ID,
        category="prose",
        language="en",
        text="sample",
        locator={"xml_id": "sample"},
        provenance={"acquisition_id": ACQUISITION_ID},
        representation_revision="pipe-001-fixture-v1",
    )
    assert sample["text"] == "sample"
    assert row_text_hash(sample["text"]) == hashlib.sha256(b"sample").hexdigest()
    assert canonical_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}\n'
    assert sha256_bytes(b"sample") == hashlib.sha256(b"sample").hexdigest()

    release = tmp_path / "api-release"
    report = assemble_release(
        root,
        release,
        release_id="pipe-001-api",
        edition_id=EDITION_ID,
        category="prose",
    )
    assert report["status"] == "pass"
    assert check_public_allowlist(release / "public") == []
    receipt = json.loads(
        (release / "internal" / "projection-receipts" / f"{EDITION_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert check_receipt_shape(receipt) == []


def test_ocr_outside_publishing_scope_is_not_selected() -> None:
    selection = make_selection(
        release_id="ocr-quarantine-boundary",
        category="prose",
        edition_id="ocr-edition",
        status_report={
            "items": [
                {
                    "work_id": "ocr-work",
                    "textual_form_id": "ocr-form",
                    "edition_id": "ocr-edition",
                    "status": "OCR / Outside Publishing Scope",
                    "reasons": ["uncorrected OCR"],
                }
            ]
        },
    )

    assert selection["items"][0]["status"] == "OCR / Outside Publishing Scope"
    assert selection["items"][0]["selected"] is False
    assert selection["accounting"]["selected"] == 0


@pytest.mark.parametrize("accessed_at", [None, "2026-09-06"])
def test_end_to_end_release_is_deterministic_and_keeps_private_evidence_private(
    tmp_path: Path, accessed_at: str | None,
) -> None:
    root = _fixture_root(tmp_path)
    if accessed_at is not None:
        acquisition_path = next((root / "library" / "works" / WORK_ID).rglob("acquisitions/*.json"))
        acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
        acquisition["accessed_at"] = accessed_at
        _write_json(acquisition_path, acquisition)
    first = tmp_path / "release-one"
    second = tmp_path / "release-two"

    first_run = _release_subprocess(root, first)
    second_run = _release_subprocess(root, second)
    assert first_run.returncode == 0, first_run.stderr
    assert second_run.returncode == 0, second_run.stderr
    assert _files(first) == _files(second)

    public = first / "public"
    internal = first / "internal"
    rows_path = public / "data" / "prose" / "train.jsonl"
    assert rows_path.is_file()
    assert (internal / "release-selection.json").is_file()
    assert (internal / "release-report.json").is_file()
    assert (internal / "projection-receipts" / f"{EDITION_ID}.json").is_file()

    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    assert [row["sequence"] for row in rows] == [1, 2, 3, 4]
    assert [row["locator"]["xml_id"] for row in rows] == [
        "vii.ii.i-p1",
        "vii.ii.i-p2",
        "vii.ii.i-p3",
        "vii.ii.i-p4",
    ]
    assert all(row["work_id"] == WORK_ID for row in rows)
    assert all(row["edition_id"] == EDITION_ID for row in rows)
    assert all(row["category"] == "prose" for row in rows)
    if accessed_at is None:
        assert all("accessed_at" not in row["provenance"] for row in rows)
    else:
        assert all(row["provenance"]["accessed_at"] == accessed_at for row in rows)
    assert rows[3]["notes"]

    receipt = json.loads(
        (internal / "projection-receipts" / f"{EDITION_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["identity"] == {
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
    }
    assert receipt["outputs"]["row_count"] == 4
    assert receipt["inputs"]["source_sha256"] == WHOLE_SOURCE_SHA256
    assert receipt["inputs"]["retained_sha256"] == (
        "d16a6d825621cde9b93c5ed54489521895b9b9e44098b38bd61c437b927faafa"
    )
    assert receipt["independent_check"]["status"] == "pass"
    private_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in internal.rglob("*")
        if path.is_file()
    )
    assert WHOLE_SOURCE_SHA256 in private_text
    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in public.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}
    )
    assert WHOLE_SOURCE_SHA256 not in public_text
    assert "raw/ccel/npnf2/npnf204.xml" not in public_text
    assert "retained/npnf204.vii.ii.i.thml.xml" not in public_text
    assert "source_sha256" not in public_text

    status = json.loads(
        (first / "reports" / "library" / "project-status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["counts"]["included"] == 1
    assert {"included", "warned", "failed", "excluded"}.issubset(status["counts"])
    assert _checker(root, first) == 0


def test_views_cli_exposes_status_and_source_binding(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    output = tmp_path / "views"
    assert _invoke(build_views_main, ["--root", str(root), "--output", str(output)]) == 0
    status = json.loads(
        (output / "reports" / "library" / "project-status.json").read_text(
            encoding="utf-8"
        )
    )
    item = status["items"][0]
    assert item["work_id"] == WORK_ID
    assert item["edition_id"] == EDITION_ID
    assert item["status"] == "included"
    assert item["source_url"] == SOURCE_URL
    assert item["source_sha256"] == WHOLE_SOURCE_SHA256


@pytest.mark.parametrize("status_name", ["warned", "failed", "excluded"])
def test_views_accounts_material_statuses(tmp_path: Path, status_name: str) -> None:
    root = _fixture_root(tmp_path)
    acquisition_path = (
        root
        / "library"
        / "works"
        / WORK_ID
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
        / "acquisitions"
        / f"{ACQUISITION_ID}.json"
    )
    state_path = root / "library" / "works" / WORK_ID / "state.json"
    if status_name == "warned":
        acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
        acquisition["warnings"] = ["fixture warning is accounted"]
        _write_json(acquisition_path, acquisition)
    elif status_name == "failed":
        retained = root / RETAINED_MEMBER
        retained.write_bytes(retained.read_bytes() + b"tampered")
    else:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["targets"][0]["stage"] = "review"
        _write_json(state_path, state)

    output = tmp_path / f"views-{status_name}"
    assert _invoke(build_views_main, ["--root", str(root), "--output", str(output)]) == 0
    status = json.loads(
        (output / "reports" / "library" / "project-status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["counts"][status_name] == 1
    assert status["items"][0]["status"] == status_name
    assert status["items"][0]["reasons"] or status_name == "warned"
    queue = json.loads(
        (output / "reports" / "library" / "acquisition-queue.json").read_text(
            encoding="utf-8"
        )
    )
    assert [item["status"] for item in queue["items"]] == [status_name]


@pytest.mark.parametrize("mutation", ["inline", "namespace", "outside-section"])
def test_release_rejects_unsupported_inline_structure(tmp_path: Path, mutation: str) -> None:
    root = _fixture_root(tmp_path)
    master = _master_path(root)
    content = master.read_text(encoding="utf-8")
    if mutation == "inline":
        content = content.replace(
            '<p xml:id="vii.ii.i-p4">',
            '<p xml:id="vii.ii.i-p4"><unsupported/>',
            1,
        )
    elif mutation == "namespace":
        content = content.replace(TEI_NS, "urn:unsupported", 1)
    else:
        content = content.replace("<body>", '<body><p xml:id="outside">Unaccounted text</p>', 1)
    master.write_text(content, encoding="utf-8", newline="\n")
    output = tmp_path / "release"
    assert _release(root, output) != 0
    report = json.loads((output / "internal" / "release-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert report["items"][0]["reasons"]


def test_release_rejects_state_evidence_that_does_not_bind_master(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    state_path = root / "library" / "works" / WORK_ID / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"][0]["evidence"] = [
        "forms/athanasius-on-the-incarnation-prose/editions/ccel-npnf204/missing.tei.xml"
    ]
    _write_json(state_path, state)
    output = tmp_path / "release"
    assert _release(root, output) != 0
    report_path = output / "internal" / "release-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert len(report["items"]) == 1
    item = report["items"][0]
    assert {
        key: item[key]
        for key in ("work_id", "textual_form_id", "edition_id", "status", "selected")
    } == {
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "status": "failed",
        "selected": False,
    }
    assert any("state evidence" in reason for reason in item["reasons"])
    assert not (output / "public" / "data" / "prose" / "train.jsonl").exists()


def test_release_requires_fresh_destination(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    output = tmp_path / "release"
    assert _release(root, output) == 0
    assert _release(root, output) != 0


@pytest.mark.parametrize(
    ("mutation", "error_fragment"),
    [
        ("tei-text", "accepted master hash mismatch"),
        ("tei-order", "public prose rows do not independently match accepted TEI"),
        ("row-text", "public prose rows do not independently match accepted TEI"),
        ("row-order", "public prose rows do not independently match accepted TEI"),
        ("note-move", "public prose rows do not independently match accepted TEI"),
        ("selection-edition", "selection"),
        ("duplicate-master", "canonical edition master"),
        ("public-readme", "public README"),
        ("public-extra", "public file is not allowlisted"),
    ],
)
def test_checker_rejects_text_order_and_public_tree_tampering(
    tmp_path: Path, mutation: str, error_fragment: str
) -> None:
    root = _fixture_root(tmp_path)
    output = tmp_path / "release"
    assert _release(root, output) == 0

    if mutation == "tei-text":
        master = _master_path(root)
        master.write_text(
            master.read_text(encoding="utf-8").replace("Whereas", "Whereas altered", 1),
            encoding="utf-8",
            newline="\n",
        )
    elif mutation == "tei-order":
        master = _master_path(root)
        tree = ET.parse(master)
        selected = next(
            node
            for node in tree.getroot().iter()
            if _local(node.tag) == "div" and node.get(XML_ID) == "vii.ii.i"
        )
        children = list(selected)
        paragraphs = [child for child in children if _local(child.tag) == "p"]
        first_index = children.index(paragraphs[0])
        paragraphs[0], paragraphs[1] = paragraphs[1], paragraphs[0]
        for paragraph in children:
            if _local(paragraph.tag) == "p":
                selected.remove(paragraph)
        for offset, paragraph in enumerate(paragraphs):
            selected.insert(first_index + offset, paragraph)
        tree.write(master, encoding="utf-8", xml_declaration=True)
    elif mutation == "row-text":
        path = output / "public" / "data" / "prose" / "train.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["text"] += " altered"
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
            newline="\n",
        )
        _reseal_public_hashes(output)
    elif mutation == "row-order":
        path = output / "public" / "data" / "prose" / "train.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[0], lines[1] = lines[1], lines[0]
        path.write_text("".join(lines), encoding="utf-8", newline="\n")
        _reseal_public_hashes(output)
    elif mutation == "note-move":
        master = _master_path(root)
        tree = ET.parse(master)
        selected = next(
            node
            for node in tree.getroot().iter()
            if _local(node.tag) == "div" and node.get(XML_ID) == "vii.ii.i"
        )
        paragraphs = [child for child in selected if _local(child.tag) == "p"]
        paragraph_three, paragraph_four = paragraphs[2], paragraphs[3]
        note = next(
            node for node in paragraph_four.iter() if node.get(XML_ID) == "vii.ii.i-p5.2"
        )
        previous_note = next(
            node for node in paragraph_four.iter() if node.get(XML_ID) == "vii.ii.i-p4.2"
        )
        previous_note.tail = (previous_note.tail or "") + (note.tail or "")
        note.tail = ""
        paragraph_four.remove(note)
        paragraph_three.append(note)
        tree.write(master, encoding="utf-8", xml_declaration=True)
        receipt_path = output / "internal" / "projection-receipts" / f"{EDITION_ID}.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["inputs"]["master_sha256"] = hashlib.sha256(master.read_bytes()).hexdigest()
        _write_json(receipt_path, receipt)
    elif mutation == "selection-edition":
        selection_path = output / "internal" / "release-selection.json"
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        selection["items"][0]["edition_id"] = "ccel-npnf204-other"
        _write_json(selection_path, selection)
    elif mutation == "duplicate-master":
        master = _master_path(root)
        duplicate = master.with_name("master-copy.tei.xml")
        duplicate.write_bytes(master.read_bytes())
        receipt_path = output / "internal" / "projection-receipts" / f"{EDITION_ID}.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["inputs"]["master_path"] = duplicate.relative_to(root).as_posix()
        _write_json(receipt_path, receipt)
    elif mutation == "public-readme":
        readme = output / "public" / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "source_sha256: private\n",
            encoding="utf-8",
            newline="\n",
        )
    else:
        extra = output / "public" / "private-leak.json"
        extra.write_text('{"source_sha256":"private"}\n', encoding="utf-8", newline="\n")

    code = _checker(root, output)
    result = check_release(root, output)
    assert code != 0
    assert result["status"] == "fail"
    assert any(error_fragment in error for error in result["errors"])
