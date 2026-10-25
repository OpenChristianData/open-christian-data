"""Independently compare all DocSouth figure declarations with retained JPEGs."""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path
from urllib.parse import urljoin

from lxml import etree
from PIL import Image

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "plans/2026-09-22-source-preflight/docsouth-figure-entity-retained-binary-audit-20260927.json"
AUDIT_SHA256 = "a488ea6bc5dc9e2e648131fccec3e85cd9955437e8717d6789a49fa867ffc701"
DECLARATION = re.compile(rb'<!ENTITY\s+([A-Za-z0-9_.-]+)\s+SYSTEM\s+"([A-Za-z0-9_.-]+\.jpg)"\s+NDATA\s+jpeg>')


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    audit_bytes = io_path(AUDIT).read_bytes()
    if _sha(audit_bytes) != AUDIT_SHA256:
        raise ValueError("Pinned pre-acquisition audit changed")
    audit = json.loads(audit_bytes)
    all_paths = set()
    rights = {"No Copyright - United States": 0, "Copyright Not Evaluated": 0}
    total = 0
    for work in audit["works"]:
        work_id = work["work_id"]
        source_path = resolve_repo_path(ROOT, work["source_path"])
        source_bytes = io_path(source_path).read_bytes()
        if _sha(source_bytes) != work["source_sha256"]:
            raise ValueError(f"Source XML changed: {work_id}")
        declared = {name.decode(): filename.decode() for name, filename in DECLARATION.findall(source_bytes)}
        source = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, no_network=True,
                                                               remove_comments=False, huge_tree=True))
        figures = source.findall(".//figure")
        bindings = work["source_entity_bindings"]
        if len(figures) != len(bindings):
            raise ValueError(f"Figure count differs: {work_id}")
        availability = source.find(".//availability")
        if availability is None:
            raise ValueError(f"Rights availability absent: {work_id}")
        wording = " ".join("".join(availability.itertext()).split())
        labels = [label for label in rights if label in wording]
        if len(labels) != 1:
            raise ValueError(f"Rights label unknown or ambiguous: {work_id}")
        rights[labels[0]] += 1
        receipt = json.loads(io_path(source_path.parent / "acquisition-receipt.json").read_bytes())
        inventory_bytes = io_path(source_path.parent / "member-inventory.tsv").read_bytes()
        inventory = [line.split("\t") for line in inventory_bytes.decode().splitlines()]
        acquisition_path = ROOT / work["acquisition_path"]
        sidecar = validate_acquisition(acquisition_path, root=ROOT)
        members = {entry["path"]: entry for entry in sidecar["retained_files"]}
        image_members = {entry["path"]: entry for entry in receipt.get("image_members", [])}
        if (inventory[0] != ["path", "bytes", "sha256"]
                or len(inventory) != 2 + len(bindings)
                or inventory[1] != [source_path.name, str(len(source_bytes)), work["source_sha256"]]
                or receipt["verification"]["member_count"] != 1 + len(bindings)
                or receipt["verification"]["member_inventory_sha256"] != _sha(inventory_bytes)
                or len(members) != 1 + len(bindings)
                or len(image_members) != len(bindings)
                or sidecar["source_path"] != work["source_path"]
                or sidecar["source_bytes"] != len(source_bytes)
                or sidecar["source_sha256"] != work["source_sha256"]):
            raise ValueError(f"Acquisition envelope differs: {work_id}")
        for index, (figure, binding) in enumerate(zip(figures, bindings, strict=True), 2):
            name = binding["entity"]
            filename = binding["declared_system_url"]
            path = binding["expected_retained_path"]
            if (figure.get("entity") != name or declared.get(name) != filename
                    or path != (Path(work["source_path"]).parent / filename).as_posix()
                    or _sha(etree.tostring(figure, method="c14n")) != binding["figure_c14n_sha256"]
                    or path in all_paths):
                raise ValueError(f"Source figure/entity differs: {work_id} {name}")
            payload = io_path(resolve_repo_path(ROOT, path)).read_bytes()
            digest = _sha(payload)
            with Image.open(io.BytesIO(payload)) as image:
                if image.format != "JPEG":
                    raise ValueError(f"Image not JPEG: {path}")
                image.verify()
            if (members[path]["bytes"] != len(payload) or members[path]["sha256"] != digest
                    or members[path]["media_type"] != "image/jpeg"
                    or inventory[index] != [filename, str(len(payload)), digest]
                    or image_members[path]["bytes"] != len(payload)
                    or image_members[path]["sha256"] != digest
                    or image_members[path]["media_type"] != "image/jpeg"
                    or image_members[path]["source_url"] != urljoin(receipt["source_url"], filename)
                    or image_members[path]["figure_c14n_sha256"] != binding["figure_c14n_sha256"]):
                raise ValueError(f"Image evidence differs: {path}")
            all_paths.add(path)
            total += 1
    raw_root = io_path(ROOT / "raw/docsouth")
    actual = {"raw/docsouth/" + path.relative_to(raw_root).as_posix()
              for path in raw_root.rglob("*.jpg") if path.is_file()}
    if actual != all_paths or total != 503 or len(audit["works"]) != 22:
        raise ValueError(f"Image envelope differs: expected {total}, actual {len(actual)}")
    print(json.dumps({"status": "verified", "works": len(audit["works"]),
                      "source_declared_images": total, "retained_jpegs": len(actual),
                      "missing": 0, "extra": 0, "rights_labels": rights}, sort_keys=True))


if __name__ == "__main__":
    main()
