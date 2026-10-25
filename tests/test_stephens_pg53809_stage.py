"""Focused source and guard checks for the PG53809 frozen review stage."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.stephens_pg53809_native import DIRECT, SOURCE_SHA256, adapt, source_bindings
from build.tei.stephens_pg53809_oracle import check
from build.tools import install_stephens_pg53809 as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _io_path


TEI = "{http://www.tei-c.org/ns/1.0}"


def _candidate() -> bytes:
    return adapt(_io_path(DIRECT).read_bytes())


def test_exact_source_and_full_oracle() -> None:
    support = source_bindings()
    assert len(support) == 4
    assert support[1]["sha256"] == SOURCE_SHA256
    assert support[2]["scope"] == "Unreferenced extracted cover support."
    result = check(_candidate())
    assert (result["body_children"], result["html_elements"], result["links"],
            result["internal_links"], result["table_cells"]) == (1457, 11904, 3553, 3548, 74)


def test_oracle_rejects_body_text_and_link_mutations() -> None:
    candidate = _candidate()
    root = etree.fromstring(candidate)
    paragraph = next(root.find(TEI + "text").iter(TEI + "p"))
    paragraph.text = "invented " + (paragraph.text or "")
    with pytest.raises(ValueError, match="text"):
        check(etree.tostring(root, encoding="UTF-8", xml_declaration=True))
    root = etree.fromstring(candidate)
    link = next(root.find(TEI + "text").iter(TEI + "ref"))
    link.set("target", "https://example.invalid/altered")
    with pytest.raises(ValueError, match="hyperlink"):
        check(etree.tostring(root, encoding="UTF-8", xml_declaration=True))
    root = etree.fromstring(candidate)
    local = next(ref for ref in root.find(TEI + "text").iter(TEI + "ref")
                 if (ref.get("target") or "").startswith("#src-"))
    original = local.get("target")
    local.set("target", "#src-00001" if original != "#src-00001" else "#src-00002")
    with pytest.raises(ValueError, match="local hyperlink/TEI target"):
        check(etree.tostring(root, encoding="UTF-8", xml_declaration=True))


def test_oracle_rejects_source_ancestry_and_support_role_mutations() -> None:
    root = etree.fromstring(_candidate())
    cell = next(root.find(TEI + "text").iter(TEI + "cell"))
    cell.set("ana", "source-role:heading")
    with pytest.raises(ValueError, match="cell role"):
        check(etree.tostring(root, encoding="UTF-8", xml_declaration=True))
    root = etree.fromstring(_candidate())
    graphic = next(root.find(TEI + "text").iter(TEI + "graphic"))
    graphic.set("url", "images/cover.jpg")
    with pytest.raises(ValueError, match="image target"):
        check(etree.tostring(root, encoding="UTF-8", xml_declaration=True))


def test_read_only_guard_pins_immutable_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from hashlib import sha256
    from build.tools import install_stephens_pg53809 as frozen_installer
    from ocd_kernel.library._common import PipelineError as FrozenPreimageError
    from ocd_kernel.tei.install_accepted import _files as frozen_files

    raw = (frozen_installer.STAGE / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "d78a350ef2a6c37dd57f944e4c96d114dac47d92e67dba3294fcaaf5b20adc5c"
    record = json.loads(raw)
    before = frozen_files(frozen_installer.ROOT / frozen_installer.WORK)
    assert frozen_files(frozen_installer.STAGE / frozen_installer.WORK) == record["after"]
    if before != record["before"]:
        with pytest.raises(FrozenPreimageError, match=r"PG53809 (current preimage or staged generation differs|frozen dependency changed: (build/tei/stephens_pg53809_native\.py|schemas/v2/native-content\.schema\.json))"):
            frozen_installer.preflight()
        assert frozen_files(frozen_installer.ROOT / frozen_installer.WORK) == before
    else:
        assert installer.preflight()["installation"] == "not-performed"
    # Isolate the receipt-pin guard after proving that historical dependencies reject current code.
    monkeypatch.setattr(installer, "DEPENDENCIES", {
        relative: sha256(_io_path(installer.ROOT / relative).read_bytes()).hexdigest()
        for relative in installer.DEPENDENCIES
    })
    monkeypatch.setattr(installer, "RECEIPT_SHA256", sha256(b"changed").hexdigest())
    with pytest.raises(PipelineError, match="receipt"):
        installer.preflight()
