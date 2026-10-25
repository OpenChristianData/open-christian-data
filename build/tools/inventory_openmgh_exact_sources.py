"""Read-only openMGH acquisition inventory by retained XML and work-div ownership."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _volume(source_bytes: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    if source.getroottree().docinfo.doctype or source.tag != f"{TEI}TEI":
        raise ValueError("entity-free TEI required")
    ns = {"t": TEI[1:-1]}
    volume = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volume) != 1:
        raise ValueError("one TEI volume div required")
    return volume[0]


def inventory(root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for work_path in sorted((root / "library/works").glob("*/work.json")):
        work = _read(work_path)
        for form in work.get("textual_forms", []):
            for edition in form.get("editions", []):
                locator = (edition.get("containing_source") or {}).get("locator", "")
                if not locator.startswith("raw/openmgh/") or "tei/" not in locator:
                    continue
                edition_path = (work_path.parent / "forms" / form["textual_form_id"]
                                / "editions" / edition["edition_id"])
                accepted = Path(_io_path(edition_path / "master.tei.xml")).is_file()
                for acquisition_id in edition.get("acquisition_ids", []):
                    acquisition_path = edition_path / "acquisitions" / f"{acquisition_id}.json"
                    acquired = _read(acquisition_path)
                    source_path = acquired.get("source_path", "")
                    if not (source_path.startswith("raw/openmgh/") and source_path.endswith(".xml")):
                        continue
                    retained = acquired.get("retained_files", [])
                    packages = [item for item in retained if item.get("path", "").endswith(".zip")]
                    if len(packages) != 1:
                        raise ValueError(f"one ZIP package required: {work['work_id']}")
                    locators = [part.split("#", 1)[1] for part in locator.split("; ")]
                    if not locators or len(locators) != len(set(locators)):
                        raise ValueError(f"distinct source locators required: {work['work_id']}")
                    groups[(source_path, acquired["source_sha256"])].append({
                        "work_id": work["work_id"], "title": work["title"],
                        "accepted_master_present": accepted,
                        "work_path": work_path.relative_to(root).as_posix(),
                        "work_sha256": _sha(work_path),
                        "acquisition_path": acquisition_path.relative_to(root).as_posix(),
                        "acquisition_sha256": _sha(acquisition_path),
                        "catalog_locator_ids": locators,
                        "package_path": packages[0]["path"],
                    })
    results = []
    for (source_path, expected_sha), records in sorted(groups.items()):
        source_file = root / source_path
        if _sha(source_file) != expected_sha:
            raise ValueError(f"acquisition source hash changed: {source_path}")
        volume = _volume(Path(_io_path(source_file)).read_bytes())
        children = list(volume)
        owner: dict[str, int] = {}
        duplicates: set[str] = set()
        for index, child in enumerate(children):
            for node in child.iter():
                identity = node.get(XML_ID)
                if identity:
                    if identity in owner:
                        duplicates.add(identity)
                    owner[identity] = index
        if duplicates:
            raise ValueError(f"duplicate source XML IDs: {source_path}")
        owner_counts: Counter[int] = Counter()
        for record in records:
            owners = [owner.get(identity) for identity in record["catalog_locator_ids"]]
            record["top_work_div_indexes"] = sorted({i for i in owners if i is not None})
            record["unresolved_locator_ids"] = [identity for identity, i in zip(
                record["catalog_locator_ids"], owners, strict=True) if i is None]
            if len(set(owners)) == 1 and owners[0] is not None:
                owner_counts[owners[0]] += 1
        for record in records:
            indexes = record["top_work_div_indexes"]
            index = indexes[0] if len(indexes) == 1 else None
            exclusive = (index is not None and not record["unresolved_locator_ids"]
                         and owner_counts[index] == 1 and children[index].tag == f"{TEI}div"
                         and children[index].get("type") == "work")
            record["exclusive_top_work_div"] = index if exclusive else None
            record["source_shape"] = (
                "exclusive-top-work-div" if exclusive else "shared-or-ambiguous-source-ownership"
            )
        packages = sorted({record["package_path"] for record in records})
        package_pins = [{"path": path, "sha256": _sha(root / path)} for path in packages]
        unaccepted = [record for record in records if not record["accepted_master_present"]]
        results.append({"source_path": source_path, "source_sha256": expected_sha,
                        "source_bytes": source_file.stat().st_size,
                        "package_pins": package_pins,
                        "volume_child_count": len(children),
                        "volume_work_div_count": sum(child.tag == f"{TEI}div"
                                                     and child.get("type") == "work" for child in children),
                        "volume_other_child_indexes": [i for i, child in enumerate(children)
                                                       if child.tag != f"{TEI}div"
                                                       or child.get("type") != "work"],
                        "catalog_work_count": len(records),
                        "unaccepted_work_count": len(unaccepted),
                        "unaccepted_exclusive_top_div_count": sum(
                            record["exclusive_top_work_div"] is not None for record in unaccepted),
                        "works": records})
    unaccepted_ids = [record["work_id"] for group in results for record in group["works"]
                      if not record["accepted_master_present"]]
    return {"contract": "ocd-openmgh-exact-source-inventory-v1",
            "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "read-only-snapshot", "source_group_count": len(results),
            "unaccepted_work_count": len(unaccepted_ids),
            "unaccepted_source_membership_count": len(unaccepted_ids),
            "unaccepted_distinct_work_count": len(set(unaccepted_ids)),
            "groups": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inventory()
    data = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    if args.output:
        output = args.output.absolute()
        Path(_io_path(output)).parent.mkdir(parents=True, exist_ok=True)
        Path(_io_path(output)).write_bytes(data)
    print(json.dumps({"groups": result["source_group_count"],
                      "unaccepted_memberships": result["unaccepted_source_membership_count"],
                      "unaccepted_distinct_works": result["unaccepted_distinct_work_count"],
                      "output": str(args.output) if args.output else None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
