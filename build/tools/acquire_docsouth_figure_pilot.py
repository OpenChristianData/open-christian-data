"""Retain the five source-declared DocSouth figure files for the first pilot.

The dated figure audit is the fixed request envelope.  A read-only run checks
its preimages; --apply fetches every image before changing any retained file.
This does not accept TEI, clear worldwide rights, or authorize publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition


ROOT = Path(__file__).resolve().parents[2]
AUDIT = Path("plans/2026-09-22-source-preflight/docsouth-figure-entity-retained-binary-audit-20260927.json")
AUDIT_SHA256 = "a488ea6bc5dc9e2e648131fccec3e85cd9955437e8717d6789a49fa867ffc701"
PILOT = {
    "g-w-offley-narrative-life-labors": ("offlecv.jpg", "offletp.jpg"),
    "richard-allen-life-experience-gospel-labours": ("allentp.jpg",),
    "samuel-ringgold-ward-autobiography-fugitive-negro": ("wardfp.jpg", "wardtp.jpg"),
}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _preflight() -> list[dict]:
    audit_bytes = (ROOT / AUDIT).read_bytes()
    if _sha(audit_bytes) != AUDIT_SHA256:
        raise ValueError("Pinned DocSouth figure audit changed")
    audit = json.loads(audit_bytes)
    selected = [work for work in audit["works"] if work["work_id"] in PILOT]
    if len(selected) != len(PILOT):
        raise ValueError("Pilot work set differs from pinned audit")
    for work in selected:
        source = resolve_repo_path(ROOT, work["source_path"])
        source_bytes = source.read_bytes()
        if _sha(source_bytes) != work["source_sha256"]:
            raise ValueError(f"Source XML changed: {work['work_id']}")
        declared = {entity.name: entity.system_url for entity in etree.fromstring(
            source_bytes, etree.XMLParser(resolve_entities=False, no_network=True)
        ).getroottree().docinfo.internalDTD.entities()}
        bindings = work["source_entity_bindings"]
        if tuple(binding["declared_system_url"] for binding in bindings) != PILOT[work["work_id"]]:
            raise ValueError(f"Image census differs: {work['work_id']}")
        for binding in bindings:
            if declared.get(binding["entity"]) != binding["declared_system_url"]:
                raise ValueError(f"Image declaration changed: {work['work_id']}")
            expected = (Path(work["source_path"]).parent / binding["declared_system_url"]).as_posix()
            if binding["expected_retained_path"] != expected or io_path(resolve_repo_path(ROOT, expected)).exists():
                raise ValueError(f"Image path changed or already exists: {expected}")
        for key in ("acquisition", "member_inventory"):
            path = resolve_repo_path(ROOT, work[f"{key}_path"])
            if _sha(io_path(path).read_bytes()) != work[f"{key}_sha256"]:
                raise ValueError(f"Pinned {key} changed: {work['work_id']}")
        receipt = source.parent / "acquisition-receipt.json"
        original = json.loads(receipt.read_bytes())
        sidecar = json.loads(io_path(ROOT / work["acquisition_path"]).read_bytes())
        if (original.get("schema") != "ocd-acquisition-source-receipt-v1"
                or original.get("member", {}).get("sha256") != work["source_sha256"]
                or original.get("verification", {}).get("member_count") != 1
                or original.get("verification", {}).get("member_inventory_sha256") != work["member_inventory_sha256"]
                or len(sidecar["retained_files"]) != 1
                or sidecar["source_path"] != work["source_path"]
                or sidecar["source_sha256"] != work["source_sha256"]
                or original["source_url"] != sidecar["url"]):
            raise ValueError(f"XML-only acquisition preimage differs: {work['work_id']}")
        if urlsplit(original["source_url"]).hostname != "docsouth.unc.edu":
            raise ValueError(f"Unexpected provider host: {work['work_id']}")
        work["_receipt_path"] = receipt
        work["_receipt"] = original
        work["_sidecar"] = sidecar
    return selected


class _DocSouthRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname != "docsouth.unc.edu":
            raise ValueError(f"Redirect left official DocSouth HTTPS host: {newurl}")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _fetch(selected: list[dict]) -> dict[str, tuple[bytes, dict]]:
    opener = urllib.request.build_opener(_DocSouthRedirects())
    images = {}
    for work in selected:
        for binding in work["source_entity_bindings"]:
            filename = binding["declared_system_url"]
            url = urljoin(work["_receipt"]["source_url"], filename)
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname != "docsouth.unc.edu"
                    or Path(parsed.path).name != filename or parsed.query or parsed.fragment):
                raise ValueError(f"Unsafe image URL: {url}")
            with opener.open(urllib.request.Request(url, headers={"User-Agent": "OpenChristianData/1.0"}), timeout=30) as response:
                payload = response.read()
                content_type = response.headers.get_content_type()
                final_url = response.geturl()
                status = response.status
            if (status != 200 or final_url != url or content_type != "image/jpeg"
                    or len(payload) < 4 or not payload.startswith(b"\xff\xd8\xff")
                    or not payload.endswith(b"\xff\xd9")):
                raise ValueError(f"DocSouth response is not the declared JPEG: {url}")
            images[binding["expected_retained_path"]] = (
                payload, {"path": binding["expected_retained_path"], "source_url": url,
                          "http_status": status, "media_type": content_type,
                          "bytes": len(payload), "sha256": _sha(payload),
                          "entity": binding["entity"],
                          "figure_c14n_sha256": binding["figure_c14n_sha256"]})
    if len(images) != 5:
        raise ValueError("Five distinct pilot images required")
    return images


def _updates(selected: list[dict], images: dict[str, tuple[bytes, dict]]) -> dict[Path, bytes]:
    updates = {}
    for work in selected:
        source_path = Path(work["source_path"])
        image_records = [images[b["expected_retained_path"]][1] for b in work["source_entity_bindings"]]
        inventory = ("path\tbytes\tsha256\n" + "\n".join(
            f"{Path(item['path']).name}\t{item['bytes']}\t{item['sha256']}"
            for item in [work["_receipt"]["member"], *image_records]) + "\n").encode("utf-8")
        receipt = work["_receipt"]
        receipt["image_members"] = image_records
        receipt["image_rights_scope"] = (
            "The source electronic edition states No Copyright - United States and makes no "
            "determination for other countries. Image scans are source-declared electronic "
            "edition files; worldwide rights and publication remain unreviewed."
        )
        receipt["verification"]["member_count"] = 1 + len(image_records)
        receipt["verification"]["member_inventory_sha256"] = _sha(inventory)
        receipt["verification"]["image_entity_count"] = len(image_records)
        sidecar = work["_sidecar"]
        sidecar["retained_files"].extend({
            "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"],
            "media_type": item["media_type"],
            "scope": f"Source-declared {item['entity']} figure image for {source_path.name}; "
                     "image bytes are retained support evidence, not the XML text source.",
        } for item in image_records)
        updates[work["_receipt_path"]] = _json(receipt)
        updates[resolve_repo_path(ROOT, work["member_inventory_path"])] = inventory
        updates[ROOT / work["acquisition_path"]] = _json(sidecar)
    for relative, (payload, _) in images.items():
        updates[resolve_repo_path(ROOT, relative)] = payload
    return updates


def _apply(updates: dict[Path, bytes]) -> None:
    lock = resolve_repo_path(ROOT, "raw/docsouth/docsouth-figure-pilot.lock")
    with io_path(lock).open("x", encoding="utf-8") as stream:
        stream.write(f"pid={os.getpid()} utc={datetime.now(timezone.utc).isoformat()}\n")
    staged = {}
    original = {}
    changed = []
    try:
        for path, payload in updates.items():
            target = io_path(path)
            original[path] = target.read_bytes() if target.exists() else None
            with tempfile.NamedTemporaryFile(dir=io_path(path.parent), prefix=".docsouth-pilot-", delete=False) as stream:
                stream.write(payload)
                staged[path] = Path(stream.name)
        for path, temporary in staged.items():
            target = io_path(path)
            if target.exists() and target.read_bytes() != original[path]:
                raise ValueError(f"Concurrent target change: {path}")
            if not target.exists() and original[path] is not None:
                raise ValueError(f"Concurrent target removal: {path}")
            os.replace(io_path(temporary), target)
            changed.append(path)
    except Exception:
        for path in reversed(changed):
            if original[path] is None:
                io_path(path).unlink()
            else:
                io_path(path).write_bytes(original[path])
        raise
    finally:
        for temporary in staged.values():
            io_path(temporary).unlink(missing_ok=True)
        io_path(lock).unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Fetch and retain the five pinned JPEGs")
    args = parser.parse_args()
    selected = _preflight()
    if not args.apply:
        print(json.dumps({"status": "preflight-only", "works": len(selected), "images": 5,
                          "audit_sha256": AUDIT_SHA256}))
        return 0
    images = _fetch(selected)
    updates = _updates(selected, images)
    _apply(updates)
    for work in selected:
        validate_acquisition(ROOT / work["acquisition_path"], root=ROOT)
    print(json.dumps({"status": "pilot-retained", "images": [record for _, record in images.values()]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
