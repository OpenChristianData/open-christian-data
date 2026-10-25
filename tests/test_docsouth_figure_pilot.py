"""Source-bound regression for the first retained DocSouth figure cohort."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "g-w-offley-narrative-life-labors": (
        "l766-offley", "offley.xml", {
            "offlecv": ("offlecv.jpg", "0e4c4371012a1f7e2761743f62bb08414257004ff4c2260b86b530e41a857b6c"),
            "offletp": ("offletp.jpg", "92fea89f11d49c9aee86f85779b4613f6161deeb5c7c96f1674731fb185da297"),
        }),
    "richard-allen-life-experience-gospel-labours": (
        "l760-allen", "allen.xml", {
            "allentp": ("allentp.jpg", "80031128463ee534cdf34635e1b69b34766864b8e3d34d1fc18fb80da1a81096"),
        }),
    "samuel-ringgold-ward-autobiography-fugitive-negro": (
        "l765-wards", "ward.xml", {
            "wardfp": ("wardfp.jpg", "896c38efaba87300104c0b35708be3f95033296a0322e60bdeaf4f8a8fdc1712"),
            "wardtp": ("wardtp.jpg", "f5dc1005f788d1268c15bb263aa8829d91b6495d06a5c27ae9ae647d48d93ca0"),
        }),
}


def _digest(payload: bytes, expected: str) -> None:
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError("retained image bytes differ from exact pilot witness")


@pytest.mark.parametrize("work_id", EXPECTED)
def test_source_declared_images_are_exact_retained_members(work_id: str) -> None:
    source_dir, xml_name, images = EXPECTED[work_id]
    base = ROOT / "raw/docsouth" / source_dir
    source = io_path(base / xml_name).read_text(encoding="utf-8")
    declarations = dict(re.findall(r'<!ENTITY\s+([\w.-]+)\s+SYSTEM\s+"([^"]+\.jpg)"\s+NDATA\s+jpeg>', source))
    references = set(re.findall(r'<figure\b[^>]*\bentity="([^"]+)"', source))
    assert references == set(images)
    assert {name: declarations[name] for name in references} == {
        name: filename for name, (filename, _) in images.items()
    }

    receipt = json.loads(io_path(base / "acquisition-receipt.json").read_bytes())
    image_members = {member["entity"]: member for member in receipt["image_members"]}
    assert set(image_members) == set(images)
    assert receipt["verification"]["member_count"] == 1 + len(images)
    inventory = io_path(base / "member-inventory.tsv").read_bytes()
    assert hashlib.sha256(inventory).hexdigest() == receipt["verification"]["member_inventory_sha256"]
    rows = {row.split("\t")[0]: row.split("\t")[1:] for row in inventory.decode().splitlines()[1:]}
    assert set(rows) == {xml_name, *(filename for filename, _ in images.values())}

    sidecar = (ROOT / "library/works" / work_id / "forms" / f"{work_id}-docsouth-retained"
               / "editions" / f"{work_id}-docsouth-electronic" / "acquisitions"
               / f"{work_id}-docsouth-acquired.json")
    acquisition = validate_acquisition(sidecar, root=ROOT)
    retained = {item["path"]: item for item in acquisition["retained_files"]}
    assert len(retained) == 1 + len(images)
    for entity, (filename, digest) in images.items():
        payload = io_path(base / filename).read_bytes()
        _digest(payload, digest)
        path = f"raw/docsouth/{source_dir}/{filename}"
        assert rows[filename] == [str(len(payload)), digest]
        assert retained[path]["sha256"] == digest
        assert retained[path]["media_type"] == "image/jpeg"
        assert image_members[entity]["source_url"] == f"https://docsouth.unc.edu/neh/{source_dir.split('-', 1)[1]}/{filename}"


def test_changed_image_bytes_are_rejected() -> None:
    filename, digest = EXPECTED["g-w-offley-narrative-life-labors"][2]["offlecv"]
    payload = io_path(ROOT / "raw/docsouth/l766-offley" / filename).read_bytes()
    changed = bytearray(payload)
    changed[100] ^= 1
    with pytest.raises(ValueError, match="image bytes differ"):
        _digest(bytes(changed), digest)
