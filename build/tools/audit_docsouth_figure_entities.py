"""Audit actual retained DocSouth image bytes against figure entity declarations."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "plans/2026-09-22-source-preflight/docsouth-tei2-exact-source-shapes-20260927.json"
INVENTORY_SHA = "90f085ef14460c3a3d0351781c077502bf845e93dd2934a6afa344655d48341b"
OUTPUT = ROOT / "plans/2026-09-22-source-preflight/docsouth-figure-entity-retained-binary-audit-20260927.json"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".webp", ".bmp"}


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def main() -> None:
    if _io_path(OUTPUT).exists():
        raise ValueError("DocSouth figure audit output already exists")
    inventory_bytes = _io_path(INVENTORY).read_bytes()
    if _sha(inventory_bytes) != INVENTORY_SHA:
        raise ValueError("DocSouth exact source-shape inventory changed")
    inventory = json.loads(inventory_bytes)
    root_images = sorted(f.relative_to(ROOT).as_posix() for f in _io_path(ROOT / "raw/docsouth").rglob("*")
                         if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES)
    works = []
    for item in inventory["works"]:
        if not item["element_counts"].get("figure", 0):
            continue
        work_id = item["work_id"]
        source_path = Path(item["source_path"])
        source_bytes = _io_path(ROOT / source_path).read_bytes()
        if _sha(source_bytes) != item["source_sha256"]:
            raise ValueError(f"DocSouth source changed: {work_id}")
        parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
        source = etree.fromstring(source_bytes, parser)
        figures = source.findall(".//figure")
        entities = {entity.name: entity for entity in source.getroottree().docinfo.internalDTD.entities()}
        if (len(figures) != item["element_counts"]["figure"]
                or len(figures) != len(item["figure_entity_references"])):
            raise ValueError(f"DocSouth source figure inventory changed: {work_id}")
        acquisition = (ROOT / "library/works" / work_id / "forms" / item["textual_form_id"]
                       / "editions" / item["edition_id"] / "acquisitions" / (item["acquisition_id"] + ".json"))
        acquisition_data = json.loads(_io_path(acquisition).read_bytes())
        retained = acquisition_data["retained_files"]
        if len(retained) != 1 or retained[0]["path"] != item["source_path"]:
            raise ValueError(f"DocSouth acquisition is not XML-only: {work_id}")
        member_inventory = ROOT / source_path.parent / "member-inventory.tsv"
        member_bytes = _io_path(member_inventory).read_bytes()
        members = member_bytes.decode("utf-8").splitlines()
        if len(members) != 2 or not members[1].startswith(source_path.name + "\t"):
            raise ValueError(f"DocSouth extracted member inventory is not XML-only: {work_id}")
        bindings = []
        for index, figure in enumerate(figures):
            name = figure.get("entity")
            entity = entities.get(name or "")
            if not name or entity is None or not entity.system_url:
                raise ValueError(f"DocSouth figure entity absent: {work_id} #{index}")
            expected = (source_path.parent / entity.system_url).as_posix()
            actual = ROOT / expected
            image_bytes = _io_path(actual).read_bytes() if _io_path(actual).is_file() else None
            bindings.append(dict(figure_index=index, entity=name, declared_system_url=entity.system_url,
                                 expected_retained_path=expected,
                                 figure_c14n_sha256=_sha(etree.tostring(figure, method="c14n")),
                                 image_present=image_bytes is not None,
                                 image_sha256=_sha(image_bytes) if image_bytes is not None else None))
        works.append(dict(work_id=work_id, source_path=item["source_path"],
                          source_sha256=item["source_sha256"],
                          acquisition_path=acquisition.relative_to(ROOT).as_posix(),
                          acquisition_sha256=_sha(_io_path(acquisition).read_bytes()),
                          member_inventory_path=member_inventory.relative_to(ROOT).as_posix(),
                          member_inventory_sha256=_sha(member_bytes),
                          acquired_member_paths=[r["path"] for r in retained],
                          source_figure_count=len(figures), source_entity_bindings=bindings,
                          absent_image_count=sum(not b["image_present"] for b in bindings),
                          disposition="hold: image binaries absent from exact extracted source directory and acquisition"))
    result = dict(contract="ocd-docsouth-figure-entity-retained-binary-audit-v1",
                  status="read-only-hold", source_inventory=INVENTORY.relative_to(ROOT).as_posix(),
                  source_inventory_sha256=INVENTORY_SHA, figure_work_count=len(works),
                  figure_entity_binding_count=sum(len(w["source_entity_bindings"]) for w in works),
                  actual_image_paths_under_raw_docsouth=root_images, works=works)
    _io_path(OUTPUT).write_bytes(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps(dict(output=OUTPUT.as_posix(), output_sha256=_sha(_io_path(OUTPUT).read_bytes()),
                          figure_works=len(works), figure_bindings=result["figure_entity_binding_count"],
                          retained_image_files=len(root_images)), sort_keys=True))


if __name__ == "__main__":
    main()
