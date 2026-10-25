"""Stage and promote exact source-declared DocSouth JPEGs, one work at a time.

Each source-order network batch is at most 20 images. Batch attempts are
immutable durable evidence; a complete work is promoted transactionally only
after all its batches verify. This tool does not publish or accept TEI.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from lxml import etree
from PIL import Image

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "plans/2026-09-22-source-preflight/docsouth-figure-entity-retained-binary-audit-20260927.json"
AUDIT_SHA256 = "a488ea6bc5dc9e2e648131fccec3e85cd9955437e8717d6789a49fa867ffc701"
STAGE = resolve_repo_path(ROOT, "reports/_logs/docsouth-image-acquisition-20260927")
PILOT = {"g-w-offley-narrative-life-labors", "richard-allen-life-experience-gospel-labours",
         "samuel-ringgold-ward-autobiography-fugitive-negro"}
BATCH_SIZE = 20


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read(path: Path) -> bytes:
    return io_path(path).read_bytes()


def _write_new(path: Path, content: bytes) -> None:
    with io_path(path).open("xb") as stream:
        stream.write(content)


def _work(work_id: str) -> dict:
    if _sha(_read(AUDIT)) != AUDIT_SHA256:
        raise ValueError("Pinned DocSouth figure audit changed")
    audit = json.loads(_read(AUDIT))
    found = [item for item in audit["works"] if item["work_id"] == work_id]
    if len(found) != 1 or work_id in PILOT:
        raise ValueError(f"Work is not in the remaining figure cohort: {work_id}")
    item = found[0]
    source_path = resolve_repo_path(ROOT, item["source_path"])
    source_bytes = _read(source_path)
    if _sha(source_bytes) != item["source_sha256"]:
        raise ValueError(f"Retained XML changed: {work_id}")
    source = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, no_network=True,
                                                           remove_comments=False, huge_tree=True))
    declarations = {e.name: e.system_url for e in source.getroottree().docinfo.internalDTD.entities()}
    figures = source.findall(".//figure")
    bindings = item["source_entity_bindings"]
    if len(figures) != len(bindings) or len(bindings) > 0 and len(bindings) != item["source_figure_count"]:
        raise ValueError(f"Source figure count changed: {work_id}")
    paths = set()
    for figure, binding in zip(figures, bindings, strict=True):
        name = binding["entity"]
        filename = binding["declared_system_url"]
        expected = (Path(item["source_path"]).parent / filename).as_posix()
        if (figure.get("entity") != name or declarations.get(name) != filename
                or Path(filename).name != filename or not filename.endswith(".jpg")
                or not filename.isascii() or not all(c.isalnum() or c in "._-" for c in filename)
                or expected != binding["expected_retained_path"]
                or _sha(etree.tostring(figure, method="c14n")) != binding["figure_c14n_sha256"]
                or expected in paths):
            raise ValueError(f"Source figure/entity/path differs: {work_id} {name}")
        paths.add(expected)
    availability = source.find(".//availability")
    if availability is None or not "".join(availability.itertext()).strip():
        raise ValueError(f"Source rights statement absent: {work_id}")
    rights = " ".join("".join(availability.itertext()).split())
    receipt_path = source_path.parent / "acquisition-receipt.json"
    inventory_path = source_path.parent / "member-inventory.tsv"
    acquisition_path = ROOT / item["acquisition_path"]
    receipt = json.loads(_read(receipt_path))
    sidecar = json.loads(_read(acquisition_path))
    inventory = _read(inventory_path)
    if (receipt.get("schema") != "ocd-acquisition-source-receipt-v1"
            or receipt.get("member", {}).get("sha256") != item["source_sha256"]
            or receipt.get("source_url") != sidecar.get("url")
            or sidecar.get("source_path") != item["source_path"]
            or sidecar.get("source_sha256") != item["source_sha256"]
            or urlsplit(receipt["source_url"]).scheme != "https"
            or urlsplit(receipt["source_url"]).hostname != "docsouth.unc.edu"):
        raise ValueError(f"Source/acquisition identity differs: {work_id}")
    promoted = len(sidecar["retained_files"]) > 1
    if promoted:
        validate_acquisition(acquisition_path, root=ROOT)
        if ({entry["path"] for entry in sidecar["retained_files"][1:]} != paths
                or len(receipt.get("image_members", [])) != len(bindings)):
            raise ValueError(f"Promoted image envelope differs: {work_id}")
    else:
        if (len(sidecar["retained_files"]) != 1
                or _sha(_read(acquisition_path)) != item["acquisition_sha256"]
                or _sha(inventory) != item["member_inventory_sha256"]
                or receipt.get("verification", {}).get("member_inventory_sha256") != item["member_inventory_sha256"]
                or receipt.get("verification", {}).get("member_count") != 1):
            raise ValueError(f"XML-only acquisition preimage differs: {work_id}")
        for path in paths:
            if io_path(resolve_repo_path(ROOT, path)).exists():
                raise ValueError(f"Unreceipted image already exists: {path}")
    item.update(_source=source_path, _receipt_path=receipt_path, _inventory_path=inventory_path,
                _acquisition_path=acquisition_path, _receipt=receipt, _sidecar=sidecar,
                _rights=rights, _rights_c14n_sha256=_sha(etree.tostring(availability, method="c14n")),
                _promoted=promoted)
    return item


def _batches(item: dict) -> list[list[dict]]:
    bindings = item["source_entity_bindings"]
    return [bindings[start:start + BATCH_SIZE] for start in range(0, len(bindings), BATCH_SIZE)]


def _url(item: dict, binding: dict) -> str:
    filename = binding["declared_system_url"]
    url = urljoin(item["_receipt"]["source_url"], filename)
    original = urlsplit(item["_receipt"]["source_url"])
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "docsouth.unc.edu"
            or parsed.path != str(Path(original.path).parent / filename).replace("\\", "/")
            or parsed.query or parsed.fragment):
        raise ValueError(f"Unsafe DocSouth image URL: {url}")
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError(f"DocSouth image redirected: {request.full_url} -> {newurl}")


def _attempts(batch_home: Path) -> list[Path]:
    return sorted(io_path(batch_home).glob("attempt-[0-9][0-9][0-9][0-9]")) if io_path(batch_home).exists() else []


def _checked_attempt(item: dict, batch: list[dict], attempt: Path) -> dict:
    receipt = json.loads(_read(attempt / "receipt.json"))
    if (receipt.get("contract") != "ocd-docsouth-image-batch-v1"
            or receipt.get("work_id") != item["work_id"]
            or receipt.get("source_sha256") != item["source_sha256"]
            or receipt.get("audit_sha256") != AUDIT_SHA256
            or len(receipt.get("members", [])) != len(batch)):
        raise ValueError(f"Staged attempt identity differs: {attempt}")
    for binding, member in zip(batch, receipt["members"], strict=True):
        if (member.get("path") != binding["expected_retained_path"]
                or member.get("url") != _url(item, binding)
                or member.get("entity") != binding["entity"]):
            raise ValueError(f"Staged member identity differs: {attempt}")
        if member["status"] == "retained":
            content = _read(attempt / member["payload_file"])
            if len(content) != member["bytes"] or _sha(content) != member["sha256"]:
                raise ValueError(f"Staged member bytes differ: {attempt}")
        elif member["status"] not in {"failed", "not-attempted"}:
            raise ValueError(f"Unsupported staged member status: {attempt}")
    return receipt


def fetch_batch(item: dict, index: int) -> dict:
    if item["_promoted"]:
        return {"status": "already-promoted", "work_id": item["work_id"], "batch": index}
    batches = _batches(item)
    if index < 1 or index > len(batches):
        raise ValueError(f"Batch outside declared work envelope: {index}")
    batch = batches[index - 1]
    batch_home = STAGE / item["work_id"] / f"batch-{index:04d}"
    io_path(batch_home).mkdir(parents=True, exist_ok=True)
    attempts = _attempts(batch_home)
    prior_success: dict[str, tuple[Path, dict]] = {}
    for attempt in attempts:
        prior = _checked_attempt(item, batch, attempt)
        if prior["status"] == "complete":
            return {"status": "already-staged", "work_id": item["work_id"], "batch": index,
                    "members": len(batch), "attempt": str(attempt)}
        for member in prior["members"]:
            if member["status"] != "retained":
                continue
            previous = prior_success.get(member["path"])
            if previous is not None and previous[1]["sha256"] != member["sha256"]:
                raise ValueError(f"Conflicting successful response bytes: {member['path']}")
            prior_success[member["path"]] = attempt, member
    attempt = batch_home / f"attempt-{len(attempts) + 1:04d}"
    io_path(attempt).mkdir(exist_ok=False)
    members = [{"path": b["expected_retained_path"], "entity": b["entity"],
                "figure_c14n_sha256": b["figure_c14n_sha256"], "url": _url(item, b),
                "status": "not-attempted"} for b in batch]
    receipt = {"contract": "ocd-docsouth-image-batch-v1", "work_id": item["work_id"],
               "batch_index": index, "audit_sha256": AUDIT_SHA256,
               "source_path": item["source_path"], "source_sha256": item["source_sha256"],
               "acquisition_preimage_sha256": item["acquisition_sha256"],
               "member_inventory_preimage_sha256": item["member_inventory_sha256"],
               "source_rights_text": item["_rights"],
               "source_rights_c14n_sha256": item["_rights_c14n_sha256"],
               "started_utc": datetime.now(timezone.utc).isoformat(),
               "status": "partial", "members": members}
    opener = urllib.request.build_opener(_NoRedirect())
    for ordinal, member in enumerate(members, 1):
        previous = prior_success.get(member["path"])
        if previous is not None:
            prior_attempt, prior_member = previous
            filename = f"{ordinal:04d}.jpg"
            _write_new(attempt / filename, _read(prior_attempt / prior_member["payload_file"]))
            member.update({key: value for key, value in prior_member.items()
                           if key not in {"path", "entity", "figure_c14n_sha256", "url"}})
            member["payload_file"] = filename
            member["reused_from_attempt"] = str(prior_attempt)
            continue
        if ordinal > 1:
            time.sleep(1.0)
        try:
            with opener.open(urllib.request.Request(member["url"], headers={"User-Agent": "OpenChristianData/1.0"}), timeout=30) as response:
                payload = response.read(20_000_001)
                status = response.status
                content_type = response.headers.get_content_type()
                final_url = response.geturl()
            if (status != 200 or content_type != "image/jpeg" or final_url != member["url"]
                    or len(payload) > 20_000_000 or not payload.startswith(b"\xff\xd8\xff")
                    or not payload.endswith(b"\xff\xd9")):
                raise ValueError("Response is not an exact HTTP 200 JPEG from the declared URL")
            with Image.open(io.BytesIO(payload)) as image:
                if image.format != "JPEG":
                    raise ValueError("Decoded image is not JPEG")
                dimensions = list(image.size)
                image.verify()
            filename = f"{ordinal:04d}.jpg"
            _write_new(attempt / filename, payload)
            member.update(status="retained", payload_file=filename, http_status=status,
                          final_url=final_url, media_type=content_type, bytes=len(payload),
                          sha256=_sha(payload), dimensions=dimensions,
                          retrieved_utc=datetime.now(timezone.utc).isoformat())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            member.update(status="failed", error_type=type(exc).__name__, error=str(exc),
                          failed_utc=datetime.now(timezone.utc).isoformat())
            if isinstance(exc, urllib.error.HTTPError):
                member["http_status"] = exc.code
                error_body = exc.read(100_001)
                if error_body:
                    _write_new(attempt / f"{ordinal:04d}.http-error", error_body)
                    member["error_response"] = {"bytes": len(error_body), "sha256": _sha(error_body)}
            break
    receipt["status"] = "complete" if all(m["status"] == "retained" for m in members) else "failed"
    receipt["completed_utc"] = datetime.now(timezone.utc).isoformat()
    _write_new(attempt / "receipt.json", _json(receipt))
    return {"status": receipt["status"], "work_id": item["work_id"], "batch": index,
            "retained": sum(m["status"] == "retained" for m in members), "declared": len(members),
            "attempt": str(attempt),
            "failures": [m for m in members if m["status"] == "failed"]}


def _complete_members(item: dict) -> list[tuple[dict, bytes, dict]]:
    retained = []
    for index, batch in enumerate(_batches(item), 1):
        batch_home = STAGE / item["work_id"] / f"batch-{index:04d}"
        successful = []
        for attempt in _attempts(batch_home):
            receipt = _checked_attempt(item, batch, attempt)
            if receipt["status"] == "complete":
                successful.append((attempt, receipt))
        if len(successful) != 1:
            raise ValueError(f"Work batch lacks one complete immutable attempt: {item['work_id']} #{index}")
        attempt, receipt = successful[0]
        retained.extend((binding, _read(attempt / member["payload_file"]), member)
                        for binding, member in zip(batch, receipt["members"], strict=True))
    if len(retained) != len(item["source_entity_bindings"]):
        raise ValueError(f"Staged work coverage differs: {item['work_id']}")
    return retained


def _commit(updates: dict[Path, bytes], lock: Path, *, validate) -> None:
    with io_path(lock).open("x", encoding="utf-8") as stream:
        stream.write(f"pid={os.getpid()} utc={datetime.now(timezone.utc).isoformat()}\n")
    old = {}
    staged = {}
    changed = []
    try:
        for path, content in updates.items():
            target = io_path(path)
            old[path] = target.read_bytes() if target.exists() else None
            with tempfile.NamedTemporaryFile(dir=io_path(path.parent), prefix=".docsouth-image-", delete=False) as stream:
                stream.write(content)
                staged[path] = Path(stream.name)
        for path, temporary in staged.items():
            target = io_path(path)
            if (target.read_bytes() if target.exists() else None) != old[path]:
                raise ValueError(f"Concurrent canonical change: {path}")
            os.replace(io_path(temporary), target)
            changed.append(path)
        validate()
    except Exception:
        for path in reversed(changed):
            if old[path] is None:
                io_path(path).unlink()
            else:
                io_path(path).write_bytes(old[path])
        raise
    finally:
        for temporary in staged.values():
            io_path(temporary).unlink(missing_ok=True)
        io_path(lock).unlink()


def promote(item: dict) -> dict:
    if item["_promoted"]:
        return {"status": "already-promoted", "work_id": item["work_id"]}
    staged = _complete_members(item)
    inventory = ("path\tbytes\tsha256\n" + "\n".join(
        f"{Path(row['path']).name}\t{row['bytes']}\t{row['sha256']}"
        for row in [item["_receipt"]["member"], *(member for _, _, member in staged)]) + "\n").encode()
    receipt = item["_receipt"]
    receipt["image_members"] = [{"path": member["path"], "source_url": member["url"],
                                 "http_status": member["http_status"], "media_type": member["media_type"],
                                 "bytes": member["bytes"], "sha256": member["sha256"],
                                 "entity": member["entity"],
                                 "figure_c14n_sha256": member["figure_c14n_sha256"],
                                 "retrieved_utc": member["retrieved_utc"]}
                                for _, _, member in staged]
    receipt["image_source_availability"] = item["_rights"]
    receipt["image_source_availability_c14n_sha256"] = item["_rights_c14n_sha256"]
    receipt["verification"]["member_count"] = 1 + len(staged)
    receipt["verification"]["member_inventory_sha256"] = _sha(inventory)
    receipt["verification"]["image_entity_count"] = len(staged)
    sidecar = item["_sidecar"]
    sidecar["retained_files"].extend({"path": member["path"], "bytes": member["bytes"],
                                      "sha256": member["sha256"], "media_type": member["media_type"],
                                      "scope": f"Source-declared {member['entity']} figure image for "
                                               f"{Path(item['source_path']).name}; retained support evidence, "
                                               "not the XML text source."}
                                     for _, _, member in staged)
    updates = {item["_receipt_path"]: _json(receipt), item["_inventory_path"]: inventory,
               item["_acquisition_path"]: _json(sidecar)}
    updates.update({resolve_repo_path(ROOT, member["path"]): payload for _, payload, member in staged})
    _commit(updates, item["_source"].parent / ".image-acquisition.lock",
            validate=lambda: validate_acquisition(item["_acquisition_path"], root=ROOT))
    return {"status": "promoted", "work_id": item["work_id"], "images": len(staged),
            "receipt_sha256": _sha(_read(item["_receipt_path"])),
            "inventory_sha256": _sha(_read(item["_inventory_path"]))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--fetch-batch", type=int)
    action.add_argument("--promote", action="store_true")
    action.add_argument("--run-work", action="store_true", help="Run bounded batches, then promote this work")
    args = parser.parse_args()
    item = _work(args.work_id)
    if args.preflight:
        result = {"status": "preflight", "work_id": args.work_id,
                  "images": len(item["source_entity_bindings"]), "batches": len(_batches(item)),
                  "rights": item["_rights"], "promoted": item["_promoted"]}
    elif args.fetch_batch is not None:
        result = fetch_batch(item, args.fetch_batch)
    elif args.run_work:
        if item["_promoted"]:
            result = {"status": "already-promoted", "work_id": args.work_id}
        else:
            result = {"status": "staging", "work_id": args.work_id}
            for index in range(1, len(_batches(item)) + 1):
                result = fetch_batch(item, index)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if result["status"] == "failed":
                    break
            if result["status"] != "failed":
                result = promote(_work(args.work_id))
    else:
        result = promote(item)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] not in {"failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
