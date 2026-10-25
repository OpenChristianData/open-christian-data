"""Exact historical contexts for six retained guarded-install transactions."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from types import ModuleType
from ocd_kernel.tei.install_accepted import _files, _io_path


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def historical_guarded_install_context(route: ModuleType, destination: Path, *, preserved_before: Path | None = None) -> tuple[Path, Path, str]:
    """Reverse only documented fields; every complete before hash must agree."""
    raw = _io_path(route.RECEIPT).read_bytes()
    assert sha256(raw).hexdigest() == route.RECEIPT_SHA
    record = json.loads(raw)
    work_id = record["work_id"]
    allowed = {
        "hammon-address-to-the-negroes-of-new-york", "hodge-systematic-theology-vol-3",
        "gregory-of-nyssa-against-eunomius", "locke-reasonableness-christianity",
        "marrant-prince-hall-african-lodge-sermon", "wilberforce-practical-view",
        "ryle-holiness", "prayers-baths-for-cure",
    }
    assert work_id in allowed and record["status"] == "staged-only"
    assert _files(route.STAGE / route.WORK) == record["after"]
    for relative, expected in record["before"].items():
        payload = _io_path(route.STAGE / route.WORK / relative).read_bytes()
        assert sha256(payload).hexdigest() == record["after"][relative]
        if preserved_before is not None:
            payload = _io_path(preserved_before / relative).read_bytes()
            assert sha256(payload).hexdigest() == expected
        if sha256(payload).hexdigest() != expected:
            value = json.loads(payload)
            if relative == "work.json":
                form = value["textual_forms"][0]
                edition = form["editions"][0]
                assert edition.pop("category") == ("sermons" if work_id == "marrant-prince-hall-african-lodge-sermon" else "prose")
                if work_id == "wilberforce-practical-view":
                    assert edition.pop("language") == form.pop("language") == "en"
            elif relative == "state.json":
                edition = next(t for t in value["targets"] if t["target_type"] == "edition")
                acquisition = next(t for t in value["targets"] if t["target_type"] == "acquisition")
                assert edition["stage"] == "accepted"
                edition["stage"] = "acquired"
                edition.pop("reason")
                edition["updated_at"] = acquisition["updated_at"]
                assert edition["evidence"][-2].endswith("/master.tei.xml")
                assert edition["evidence"][-1].endswith("/acceptance.json")
                edition["evidence"] = edition["evidence"][:-2]
            elif work_id in {"gregory-of-nyssa-against-eunomius", "wilberforce-practical-view"}:
                assert relative.startswith("forms/") and "/acquisitions/" in relative
                for key in ("source_path", "source_scope", "source_bytes", "source_sha256"):
                    value.pop(key)
                if work_id == "gregory-of-nyssa-against-eunomius":
                    value["retained_files"][0]["scope"] = (
                        "CCEL NPNF2 volume 5 is a retained collection. Complete retained acquisition file raw/ccel/npnf2/npnf205.xml; "
                        "this work is associated by the pinned exclusive source manifest sources/structured-text/gregory-of-nyssa-against-eunomius/gregory-of-nyssa-against-eunomius.source-manifest.json. "
                        "This acquisition does not establish child-text extraction or TEI acceptance."
                    )
            else:
                raise AssertionError("Undocumented historical metadata transition")
            payload = _json(value)
        assert sha256(payload).hexdigest() == expected
        target = _io_path(destination / route.WORK / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    assert _files(destination / route.WORK) == record["before"]
    prefix = route.WORK.as_posix() + "/"
    for relative, digest in _files(route.STAGE).items():
        if relative.startswith(prefix) or relative == route.RECEIPT.name:
            continue
        payload = _io_path(route.STAGE / relative).read_bytes()
        assert sha256(payload).hexdigest() == digest
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    context = dict(record, canonical_root=destination.as_posix())
    restored = dict(context, canonical_root=record["canonical_root"])
    assert restored == record
    path = destination / route.RECEIPT.name
    payload = _json(context)
    path.write_bytes(payload)
    return destination, path, sha256(payload).hexdigest()
