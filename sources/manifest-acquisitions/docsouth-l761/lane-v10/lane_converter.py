from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Mapping
from build.tei.docsouth_l761_l762 import _convert as _base_convert
from ocd_kernel.reconstruction.contract import SourceManifest
CONVERTER_ID = "ocd-docsouth-l761-lane-v10-current-worklist-one-work-one-tei"
CONVERTER_VERSION = "1"
def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _json(value: object) -> bytes: return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    produced = dict(_base_convert(manifest))
    account = json.loads(produced["source-accountability.json"])
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    receipt = manifest.authority_path("acquisition-receipt").read_bytes()
    inventory = manifest.authority_path("member-inventory").read_bytes()
    account.update({"retained_support_members": profile["retained_support_members"], "acquisition_receipt_sha256": _sha(receipt), "member_inventory_sha256": _sha(inventory), "one_root": True, "manifest_sha256": profile["manifest_sha256"], "worklist_sha256": profile["worklist_sha256"], "manifest_row_text_sha256": profile["manifest_row_text_sha256"], "worklist_row_text_sha256": profile["worklist_row_text_sha256"]})
    produced["source-accountability.json"] = _json(account)
    return produced
_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
