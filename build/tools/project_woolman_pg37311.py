"""Project the exact accepted PG 37311 master through its source-native profile.

The temporary diagnostic view independently checks that structural adaptation
preserves the complete source text; the actual projection reads the master.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_document,
    verify_document,
)
from ocd_kernel.projection.categories.woolman_pg37311_source_profile import PROFILE
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "john-woolman-journal-other-writings"
FORM_ID = "english"
EDITION_ID = "everyman-402-1910-electronic"
ACQUISITION_ID = "gutenberg-37311"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
MASTER_SHA256 = "03d1cad51281dd3271b0f32139de2b6aa9265bde39a66a3cbb0a7a42c1f1dc3e"
ACCEPTANCE_SHA256 = "af870ac063be83343508aa1ccf7ee4f16c32c469bdbcd5081556e5f95f41b5c0"
SOURCE_SHA256 = "31b093b2e49a4ed732062bef521f2e545781b523b4066921b903e78ccf899926"
MANIFEST_SHA256 = "e4f08719e67b3f961d1c09a0236adf6a15277b1e3978cf08b52ead20c456293c"
REVISION = "john-woolman-pg37311-accepted-v1"
SOURCE_PATH = "raw/gutenberg/37311/html/pg37311-images.html"
OUTPUT = WORK / "integration/pg37311-html-v1/publication-v2"

NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
TEI_NS = f"{{{NS}}}"
EXPECTED_SOURCE_BLOCKS = {
    "source-p": 872,
    "source-hr": 54,
    "source-blockquote": 20,
    "source-div": 7,
    "source-header": 1,
    "source-footer": 1,
    "source-h1": 2,
    "source-h2": 12,
    "source-h3": 36,
    "source-pre": 2,
}
UNIT_IDS = [
    "pg37311-volume-front",
    "pg37311-abridged-journal",
    "pg37311-writings-introduction",
    "pg37311-pure-wisdom",
    "pg37311-on-labour",
    "pg37311-on-schools",
    "pg37311-outward-gifts",
    "pg37311-harmony",
    "pg37311-epistle",
    "pg37311-remarks",
    "pg37311-last-illness",
    "pg37311-provider-footer",
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _text_content(node: etree._Element) -> str:
    return "".join(node.itertext())


def _replace_tag(
    node: etree._Element,
    *,
    tag: str,
    attributes: dict[str, str],
) -> etree._Element:
    parent = node.getparent()
    if parent is None:
        raise PipelineError("source block unexpectedly has no parent")
    replacement = etree.Element(TEI_NS + tag)
    for name, value in attributes.items():
        replacement.set(name, value)
    replacement.text = node.text
    replacement.tail = node.tail
    for child in list(node):
        replacement.append(child)
    parent.replace(node, replacement)
    return replacement


def _remove_preserving_tail(node: etree._Element) -> None:
    parent = node.getparent()
    if parent is None:
        raise PipelineError("source marker unexpectedly has no parent")
    previous = node.getprevious()
    if previous is None:
        parent.text = (parent.text or "") + (node.tail or "")
    else:
        previous.tail = (previous.tail or "") + (node.tail or "")
    parent.remove(node)


def build_projection_view(master_bytes: bytes) -> tuple[bytes, dict[str, object]]:
    """Return a narrowly adapted projection view and a transformation audit."""
    if b"<!DOCTYPE" in master_bytes.upper() or b"<!ENTITY" in master_bytes.upper():
        raise PipelineError("Woolman projection view refuses DTD/entity declarations")
    try:
        parser = etree.XMLParser(
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            remove_comments=False,
            recover=False,
        )
        root = etree.fromstring(master_bytes, parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise PipelineError(f"cannot parse Woolman accepted master: {exc}") from exc
    if root.tag != TEI_NS + "TEI" or root.get(XML_ID) != WORK_ID:
        raise PipelineError("Woolman master envelope differs from the pinned edition")
    text = root.find(TEI_NS + "text")
    body = text.find(TEI_NS + "body") if text is not None else None
    if text is None or body is None:
        raise PipelineError("Woolman master lacks its text/body")

    units = [node for node in body if node.tag == TEI_NS + "div"]
    observed_unit_ids = [node.get(XML_ID) for node in units]
    if observed_unit_ids != UNIT_IDS:
        raise PipelineError("Woolman source-unit identity/order differs from the accepted master")

    before_text = _text_content(text)
    source_abs = [
        node
        for node in text.iter(TEI_NS + "ab")
        if (node.get("type") or "").startswith("source-")
    ]
    observed_counts: dict[str, int] = {}
    for node in source_abs:
        kind = node.get("type") or ""
        observed_counts[kind] = observed_counts.get(kind, 0) + 1
    if observed_counts != EXPECTED_SOURCE_BLOCKS:
        raise PipelineError(f"Woolman source block inventory differs: {observed_counts}")

    mappings: dict[str, int] = {}
    for node in list(source_abs):
        kind = node.get("type") or ""
        attributes = dict(node.attrib)
        if kind in {"source-p", "source-hr", "source-blockquote"}:
            attributes.pop("type", None)
            if kind == "source-p":
                target = "p"
            elif kind == "source-hr":
                target = "milestone"
                attributes["unit"] = "source-horizontal-rule"
            else:
                target = "quote"
                attributes["type"] = "source-html-blockquote"
        elif kind in {"source-div", "source-header", "source-footer"}:
            attributes["type"] = "source-block"
            attributes["subtype"] = kind
            target = "ab"
        else:
            # The native projector supports these source-preserving heading and
            # preformatted carriers without a transformation.
            continue
        _replace_tag(node, tag=target, attributes=attributes)
        mappings[kind] = mappings.get(kind, 0) + 1

    expected_mapping_counts = {
        "source-p": 872,
        "source-hr": 54,
        "source-blockquote": 20,
        "source-div": 7,
        "source-header": 1,
        "source-footer": 1,
    }
    if mappings != expected_mapping_counts:
        raise PipelineError(f"Woolman projection mapping counts differ: {mappings}")

    starts = text.xpath(".//tei:milestone[@unit='source-tbody-start']", namespaces={"tei": NS})
    ends = text.xpath(".//tei:milestone[@unit='source-tbody-end']", namespaces={"tei": NS})
    if len(starts) != 1 or len(ends) != 1:
        raise PipelineError("Woolman source table must have exactly one paired tbody marker")
    start, end = starts[0], ends[0]
    table = start.getparent()
    if (
        table is None
        or table.tag != TEI_NS + "table"
        or end.getparent() is not table
        or start.text
        or end.text
        or len(start)
        or len(end)
        or start.tail
        or end.tail
        or table.index(start) >= table.index(end)
    ):
        raise PipelineError("Woolman tbody markers are no longer the paired empty table boundaries")
    between = list(table)[table.index(start) + 1 : table.index(end)]
    if not between or any(node.tag != TEI_NS + "row" for node in between):
        raise PipelineError("Woolman tbody markers do not enclose only source rows")
    _remove_preserving_tail(start)
    _remove_preserving_tail(end)

    numbered_cells = text.xpath(".//tei:cell[@n]", namespaces={"tei": NS})
    if len(numbered_cells) != 18:
        raise PipelineError(f"Woolman table cell locator count differs: {len(numbered_cells)}")
    removed_cell_locators: list[dict[str, str]] = []
    for cell in numbered_cells:
        row = cell.getparent()
        if row is None or row.tag != TEI_NS + "row" or not row.get("n"):
            raise PipelineError("numbered Woolman table cell lacks its source row locator")
        sibling_cells = [child for child in row if child.tag == TEI_NS + "cell"]
        position = sibling_cells.index(cell) + 1
        expected_locator = f"{row.get('n')}.{position}"
        actual_locator = cell.get("n")
        if actual_locator != expected_locator or not cell.get(XML_ID):
            raise PipelineError(
                f"Woolman table cell locator is not positional: {actual_locator!r} != {expected_locator!r}"
            )
        removed_cell_locators.append(
            {"source_n": actual_locator, "xml_id": cell.get(XML_ID) or ""}
        )
        del cell.attrib["n"]

    after_text = _text_content(text)
    if before_text != after_text:
        raise PipelineError("Woolman projection view changed text subtree content")
    view_bytes = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    audit: dict[str, object] = {
        "contract": "ocd-woolman-pg37311-projection-view-v1",
        "unit_ids_in_order": observed_unit_ids,
        "source_ab_inventory": observed_counts,
        "source_element_mappings": mappings,
        "preserved_source_carriers": {
            "source-h1": 2,
            "source-h2": 12,
            "source-h3": 36,
            "source-pre": 2,
        },
        "removed_empty_table_markers": [
            {"unit": "source-tbody-start", "xml_id": start.get(XML_ID)},
            {"unit": "source-tbody-end", "xml_id": end.get(XML_ID)},
        ],
        "removed_cell_locator_attributes": removed_cell_locators,
        "source_text_characters": len(before_text),
        "source_text_sha256": _sha(before_text.encode("utf-8")),
        "view_text_characters": len(after_text),
        "view_text_sha256": _sha(after_text.encode("utf-8")),
        "text_subtree_unchanged": True,
        "view_sha256": _sha(view_bytes),
    }
    return view_bytes, audit


def _write_generation(root: Path, files: dict[str, bytes]) -> None:
    output = _io_path(root / OUTPUT)
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if not output.is_dir() or {path.name for path in output.iterdir()} != set(files):
            raise PipelineError(f"existing Woolman projection generation differs: {OUTPUT}")
        for name, payload in files.items():
            if _io_path(output / name).read_bytes() != payload:
                raise PipelineError(f"existing Woolman projection artifact differs: {OUTPUT / name}")
        return

    stage = Path(tempfile.mkdtemp(prefix=".woolman-projection-", dir=str(parent)))
    try:
        for name, payload in files.items():
            _io_path(stage / name).write_bytes(payload)
        _io_path(stage).replace(output)
    except Exception:
        try:
            shutil.rmtree(_io_path(stage))
        except OSError:
            pass
        raise


def run(root: Path = ROOT) -> dict[str, object]:
    root = Path(root).resolve(strict=True)
    # Validators compare canonical paths, so give them ordinary repo paths;
    # use _io_path only at the byte-I/O boundary for Windows long paths.
    master_path = root / EDITION / "master.tei.xml"
    acceptance_path = root / EDITION / "acceptance.json"
    state_path = root / WORK / "state.json"
    work_path = root / WORK / "work.json"
    acquisition_path = root / EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"

    master_bytes = _io_path(master_path).read_bytes()
    acceptance_bytes = _io_path(acceptance_path).read_bytes()
    if _sha(master_bytes) != MASTER_SHA256 or _sha(acceptance_bytes) != ACCEPTANCE_SHA256:
        raise PipelineError("pinned Woolman accepted master or acceptance record changed")
    acceptance = validate_acceptance(acceptance_path, root=root)
    state = validate_state(state_path, root=root)
    acquisition = validate_acquisition(acquisition_path, root=root)
    work = load_work(work_path)
    if acceptance["identity"] != {
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
    }:
        raise PipelineError("Woolman acceptance identity differs from the projection route")
    targets = [
        target
        for target in state["targets"]
        if target["target_type"] == "edition" and target["target_id"] == EDITION_ID
    ]
    if len(targets) != 1 or targets[0]["stage"] != "accepted":
        raise PipelineError("Woolman edition is not uniquely recorded as accepted")
    if acquisition["edition_id"] != EDITION_ID or acquisition["acquisition_id"] != ACQUISITION_ID:
        raise PipelineError("Woolman source acquisition does not bind the accepted edition")
    form = next(
        form for form in work["textual_forms"] if form["textual_form_id"] == FORM_ID
    )
    edition = next(
        item for item in form["editions"] if item["edition_id"] == EDITION_ID
    )
    if form["language"] != "en" or edition["language"] != "en":
        raise PipelineError("Woolman projection language differs from the canonical sidecar")

    source_path = resolve_repo_path(root, SOURCE_PATH)
    source_bytes = _io_path(source_path).read_bytes()
    if _sha(source_bytes) != SOURCE_SHA256 or acquisition["source_sha256"] != SOURCE_SHA256:
        raise PipelineError("retained Woolman source no longer matches its accepted binding")
    if acquisition["source_path"] != SOURCE_PATH:
        raise PipelineError("Woolman acquisition source path differs from the pinned route")
    manifest_binding = acceptance["source"]["source_manifest"]
    if (
        manifest_binding["sha256"] != MANIFEST_SHA256
        or _sha(_io_path(root / manifest_binding["path"]).read_bytes()) != MANIFEST_SHA256
    ):
        raise PipelineError("Woolman source manifest changed after acceptance")
    p5_errors = validate_file(master_path)
    if p5_errors:
        raise PipelineError(f"accepted Woolman master fails P5: {p5_errors[:5]}")

    view_bytes, audit = build_projection_view(master_bytes)
    if audit["view_sha256"] != _sha(view_bytes):
        raise PipelineError("Woolman projection view hash receipt differs")
    projected_view_sha = _sha(master_bytes)
    with tempfile.TemporaryDirectory(prefix="wlp-") as temporary:
        view_path = _io_path(Path(temporary) / "view.xml")
        view_path.write_bytes(view_bytes)
        view_errors = validate_file(view_path)
        if view_errors:
            raise PipelineError(f"adapted Woolman projection view fails P5: {view_errors[:5]}")
        identity = {
            "work_id": WORK_ID,
            "textual_form_id": FORM_ID,
            "edition_id": EDITION_ID,
        }
        projection = project_document(
            master_path,
            identity=identity,
            language="en",
            representation_revision=REVISION,
            edition_title=edition["title"],
            category="prose",
            projection_profile=PROFILE,
            _allow_acceptance_metadata=True,
        )
        independent_errors = verify_document(
            master_path,
            projection["rows"],
            projection["receipt"],
            identity=identity,
            language="en",
            representation_revision=REVISION,
            edition_title=edition["title"],
            category="prose",
            projection_profile=PROFILE,
            _allow_acceptance_metadata=True,
        )
    if independent_errors:
        raise PipelineError(f"independent Woolman projection check failed: {independent_errors[:5]}")
    rows = projection["rows"]
    if len(rows) != len(UNIT_IDS):
        raise PipelineError(f"Woolman projection row count differs: {len(rows)}")
    if any(row.get("work_id") != WORK_ID or row.get("edition_id") != EDITION_ID for row in rows):
        raise PipelineError("Woolman public rows do not bind the canonical work and edition")
    rows_bytes = b"".join(_json_bytes(row) for row in rows)
    engine_receipt_bytes = _json_bytes(projection["receipt"])
    receipt = {
        "contract": "ocd-work-projection-receipt-v2",
        "status": "pass",
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "category": "prose",
        "language": "en",
        "representation_revision": REVISION,
        "projector": "ocd_kernel.projection.categories.native_documents.project_document",
        "projector_profile": PROFILE,
        "master_path": (EDITION / "master.tei.xml").as_posix(),
        "master_sha256": _sha(master_bytes),
        "acceptance_path": (EDITION / "acceptance.json").as_posix(),
        "acceptance_sha256": _sha(acceptance_bytes),
        "source_path": SOURCE_PATH,
        "source_sha256": _sha(source_bytes),
        "source_manifest_path": manifest_binding["path"],
        "source_manifest_sha256": MANIFEST_SHA256,
        "projection_view_sha256": projected_view_sha,
        "view_audit": audit,
        "engine_receipt_sha256": _sha(engine_receipt_bytes),
        "rows": len(rows),
        "rows_sha256": _sha(rows_bytes),
        "independent_correspondence": "pass",
        "independent_errors": [],
        "rights": "not-cleared",
        "human_review": "partial; whole-volume visual and print collation remain open",
        "publication": "not-authorized",
    }
    correspondence = {
        "contract": "ocd-independent-projection-correspondence-v1",
        "status": "pass",
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "master_sha256": _sha(master_bytes),
        "acceptance_sha256": _sha(acceptance_bytes),
        "projection_view_sha256": projected_view_sha,
        "engine_receipt_sha256": _sha(engine_receipt_bytes),
        "rows_sha256": _sha(rows_bytes),
        "rows": len(rows),
        "errors": [],
    }
    files = {
        "prose.jsonl": rows_bytes,
        "projection-receipt.json": _json_bytes(receipt),
        "independent-correspondence.json": _json_bytes(correspondence),
    }
    _write_generation(root, files)
    return receipt


if __name__ == "__main__":
    print(_json_bytes(run()).decode("utf-8"), end="")
