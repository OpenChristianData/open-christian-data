"""Package the pinned complete N18328 electronic witness for nonaccepted review."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from build.tei import convicts_visitor_n18328_candidate, convicts_visitor_n18328_check
from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-convicts-n18328-complete-electronic"
CONVERTER_VERSION = "1"
SOURCE_ID = "tcp-N18328"
WORK_ID = "convicts-visitor"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    if manifest.record.get("source_id") != SOURCE_ID or manifest.record.get("work_id") != WORK_ID:
        raise ValueError("N18328 package source/work identity differs")
    if not manifest.authority_path("candidate-generator").samefile(Path(convicts_visitor_n18328_candidate.__file__)):
        raise ValueError("N18328 candidate generator binding differs")
    if not manifest.authority_path("source-comparison").samefile(Path(convicts_visitor_n18328_check.__file__)):
        raise ValueError("N18328 source comparison binding differs")

    source = manifest.authority_path("retained-tei-p5").read_bytes()
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_text(encoding="utf-8"))
    policy = json.loads(manifest.authority_path("validation-policy").read_text(encoding="utf-8"))
    acquisition = json.loads(manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8"))
    if (profile.get("contract") != "ocd-convicts-n18328-complete-xml-profile-v1"
            or profile.get("source_sha256") != _sha(source)
            or profile.get("source_bytes") != len(source)
            or profile.get("source_path") != acquisition.get("member", {}).get("path")
            or acquisition.get("member", {}).get("bytes") != len(source)
            or acquisition.get("member", {}).get("sha256") != _sha(source)
            or policy.get("contract") != "ocd-convicts-n18328-complete-xml-policy-v1"
            or policy.get("provenance", {}).get("source_sha256") != _sha(source)):
        raise ValueError("N18328 source profile, policy, or acquisition differs")

    candidate = convicts_visitor_n18328_candidate.generate()
    if (_sha(candidate) != profile.get("candidate_sha256")
            or candidate != convicts_visitor_n18328_check.CANDIDATE.read_bytes()):
        raise ValueError("N18328 packaged TEI differs from the pinned candidate")
    suffix = source.split(b"</teiHeader>", 1)
    if len(suffix) != 2 or _sha(suffix[1]) != profile.get("source_text_suffix_sha256"):
        raise ValueError("N18328 source text boundary differs")

    account = {
        "contract": "ocd-convicts-n18328-source-accountability-v1",
        "source_path": profile["source_path"],
        "source_bytes": len(source),
        "source_sha256": _sha(source),
        "candidate_bytes": len(candidate),
        "candidate_sha256": _sha(candidate),
        "selection": "/TEI/text",
        "source_header_tree_sha256": profile["source_header_tree_sha256"],
        "source_text_tree_sha256": profile["source_text_tree_sha256"],
        "source_text_suffix_sha256": _sha(suffix[1]),
        "text_element_counts": profile["text_element_counts"],
        "acquisition_receipt_sha256": _sha(manifest.authority_path("acquisition-receipt").read_bytes()),
        "member_inventory_sha256": _sha(manifest.authority_path("member-inventory").read_bytes()),
    }
    return {
        "README.source.md": manifest.authority_path("source-credit").read_bytes(),
        "content.tei.xml": candidate,
        "provenance.json": _json(policy["provenance"]),
        "source-accountability.json": _json(account),
        "unresolved.jsonl": b"".join(_json(item) for item in policy["unresolved"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
