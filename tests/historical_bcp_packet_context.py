"""Exact historical catalog evidence for the four retained BCP packet routes."""
from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.lib.storage_topology import resolve_repo_path
from build.tools.library_exclusive_multi_binding import NOTICE_ROLES

HISTORICAL_CATALOG = {'bcp-1549': 'tests/fixtures/reconstruction-runtime/authorities/bcp-1549-original-catalog-evidence.json', 'bcp-1559': 'tests/fixtures/reconstruction-runtime/authorities/bcp-1559-original-catalog-evidence.json', 'bcp-1662': 'tests/fixtures/reconstruction-runtime/authorities/bcp-1662-original-catalog-evidence.json', 'bcp-1662-collects': 'tests/fixtures/reconstruction-runtime/authorities/bcp-1662-collects-original-catalog-evidence.json'}


def historical_bcp_packet_root(root: Path, rows: list[dict], destination: Path) -> Path:
    destination.mkdir()
    (destination / ".ocd-storage.json").write_bytes((root / ".ocd-storage.json").read_bytes())
    for row in rows:
        assert row["work_id"] in HISTORICAL_CATALOG
        references = [row[key] for key in ("source_manifest", "config", "source_profile") if key in row]
        manifest_raw = (root / row["source_manifest"]["path"]).read_bytes()
        assert sha256(manifest_raw).hexdigest() == row["source_manifest"]["sha256"]
        references += [ref for ref in json.loads(manifest_raw)["authorities"] if ref.get("role") in NOTICE_ROLES]
        for ref in references:
            if ref["path"].startswith("raw/"):
                continue
            raw = resolve_repo_path(root, ref["path"]).read_bytes()
            assert sha256(raw).hexdigest() == ref["sha256"], ref["path"]
            if "bytes" in ref:
                assert len(raw) == ref["bytes"]
            target = destination / ref["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                assert target.read_bytes() == raw
            else:
                target.write_bytes(raw)
        ref = row["metadata_evidence"]
        raw = (root / HISTORICAL_CATALOG[row["work_id"]]).read_bytes()
        assert sha256(raw).hexdigest() == ref["sha256"]
        target = destination / ref["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return destination
