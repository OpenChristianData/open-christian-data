"""Contracts for bounded TEI evidence and visual-pair helpers."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from lxml import etree
from PIL import Image

from build.tei import anderson_1864_new_testament_evidence as anderson_evidence
from build.tei import aquinas_summa_theologica_four_parts_visual as aquinas_visual
from build.tei import brenton_septuagint_evidence as brenton_evidence
from build.tei import revised_version_with_apocrypha_evidence as revised_evidence


EVIDENCE_MODULES = (anderson_evidence, brenton_evidence, revised_evidence)


def _tei_namespace(module):
    return module.anderson if module is anderson_evidence else module.brenton if module is brenton_evidence else module.rv


def _sha(module, content: bytes) -> str:
    source = _tei_namespace(module)
    return source.base._sha(content) if module is anderson_evidence else source._sha(content)


def _tiny_png(color: str = "red", size: tuple[int, int] = (4, 3)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _projection_node(module) -> etree._Element:
    source = _tei_namespace(module)
    node = etree.Element(source._q("p"))
    node.text = "visible-"
    raw = etree.SubElement(node, source._q("note"), type="source-usfm-raw")
    raw.text = "\\p hidden-source-line"
    raw.tail = "tail-"
    hi = etree.SubElement(node, source._q("hi"))
    hi.text = "nested"
    hi.tail = "end"
    return node


@pytest.mark.parametrize("module", EVIDENCE_MODULES, ids=lambda item: item.__name__.split(".")[-1])
def test_evidence_projection_excludes_raw_note_but_keeps_visible_tail(module) -> None:
    node = _projection_node(module)
    assert module._projection(node) == "visible-tail-nestedend"


@pytest.mark.parametrize("module", EVIDENCE_MODULES, ids=lambda item: item.__name__.split(".")[-1])
def test_evidence_inventory_is_sorted_and_hashed(module, tmp_path: Path) -> None:
    (tmp_path / "z.bin").write_bytes(b"z")
    (tmp_path / "a.bin").write_bytes(b"aa")
    inventory = module._inventory(tmp_path)
    assert [item["name"] for item in inventory] == ["a.bin", "z.bin"]
    assert [item["bytes"] for item in inventory] == [2, 1]
    assert inventory[0]["sha256"] == _sha(module, b"aa")


@pytest.mark.parametrize(
    ("module", "file_name", "line_number"),
    [
        (anderson_evidence, "ENG[B1]Anderson1864[pd]USFM-00.sfm", 6),
        (brenton_evidence, "sample.usfm", 1),
        (revised_evidence, "sample.usfm", 1),
    ],
    ids=lambda item: item.__name__.split(".")[-1] if hasattr(item, "__name__") else str(item),
)
def test_evidence_spot_check_requires_one_pointer_and_raw_line(
    module, file_name: str, line_number: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _tei_namespace(module)
    if module is anderson_evidence:
        pointer = module.anderson._pointer(Path(file_name), line_number)
    else:
        pointer = f"{source.SOURCE_PREFIX}{file_name}#line={line_number}"
    root = etree.Element(source._q("TEI"), nsmap={None: source.TEI_NS})
    body = etree.SubElement(etree.SubElement(root, source._q("text")), source._q("body"))
    paragraph = etree.SubElement(body, source._q("p"), corresp=pointer)
    paragraph.text = "visible"
    raw = etree.SubElement(paragraph, source._q("note"), type="source-usfm-raw")
    raw.text = "\\p retained raw"
    raw.tail = " tail"
    candidate = tmp_path / "candidate.tei.xml"
    candidate.write_bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))
    monkeypatch.setattr(module, "SAMPLES", (("sample", file_name, line_number),))

    checks = module._spot_checks(candidate)
    assert checks == [
        {
            "label": "sample",
            "pointer": pointer,
            "source_usfm": "\\p retained raw",
            "tei_retained_usfm": "\\p retained raw",
            "exact": True,
            "tei_visible_projection": "visible tail",
        }
    ]

    raw.getparent().remove(raw)
    candidate.write_bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))
    with pytest.raises(ValueError, match="retained raw line"):
        module._spot_checks(candidate)


def test_evidence_renderers_emit_png_with_concrete_review_rows(tmp_path: Path) -> None:
    samples = [
        {
            "label": "sample",
            "source_usfm": "\\p source",
            "tei_visible_projection": "visible",
        }
    ]
    # Anderson's renderer intentionally uses the Windows Arial contract; the
    # other two are portable and cover the common Pillow rendering behavior.
    for module in (brenton_evidence, revised_evidence):
        payload = module._render_png(samples)
        image = Image.open(BytesIO(payload))
        assert image.format == "PNG"
        assert image.width == 1800 and image.height > 175


def test_aquinas_visual_helpers_normalize_capture_and_reject_bad_viewports() -> None:
    assert aquinas_visual._normalized("  one\n two\tthree ") == "one two three"

    class Page:
        def __init__(self, result, screenshot: bytes = b"png") -> None:
            self.result = result
            self.screenshot_bytes = screenshot
            self.seen = None

        def evaluate(self, script, xml_id):
            self.seen = (script, xml_id)
            return self.result

        def screenshot(self):
            return self.screenshot_bytes

    page = Page("  anchor\ntext ")
    text, screenshot = aquinas_visual._scroll_and_capture(page, "id-1")
    assert text == "anchor text" and screenshot == b"png"
    assert page.seen[1] == "id-1"
    with pytest.raises(RuntimeError, match="anchor not found"):
        aquinas_visual._scroll_and_capture(Page(None), "missing")

    left = _tiny_png("red")
    right = _tiny_png("blue")
    paired = aquinas_visual._pair(left, right, "pair")
    assert paired.size == (8, 75)
    with pytest.raises(RuntimeError, match="viewport mismatch"):
        aquinas_visual._pair(left, _tiny_png("blue", (5, 3)), "bad")
