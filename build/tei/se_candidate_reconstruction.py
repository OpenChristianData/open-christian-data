"""Source-bound Standard Ebooks producer for the flat reconstruction seam.

The source profile declares the complete retained file envelope and each file's
disposition. This producer inventory is accounting, not independent validation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

from lxml import etree

from build.tei.se_to_tei import convert_se_to_tei
from ocd_kernel.reconstruction.contract import SourceManifest

CONVERTER_ID = "ocd-standard-ebooks-retained-source-to-tei"
CONVERTER_VERSION = "1"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _inventory(source_manifest: SourceManifest, profile: dict) -> list[dict]:
    root = (source_manifest.repository_root / profile["source_root"]).resolve(strict=True)
    expected = profile["members"]
    names = [item["path"] for item in expected]
    if names != sorted(set(names)):
        raise ValueError("SE profile member paths must be unique and sorted")
    observed = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts)
    if observed != names:
        raise ValueError("SE retained file envelope differs from the bound profile")
    authorities = {item["name"]: item for item in source_manifest.record["authorities"]}
    rows = []
    for item in expected:
        logical = Path(item["path"])
        if logical.is_absolute() or ".." in logical.parts:
            raise ValueError("SE member path escapes its retained root")
        path = (root / logical).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError("SE member resolves outside its retained root")
        authority = authorities[item["authority"]]
        if source_manifest.authority_path(item["authority"]) != path:
            raise ValueError("SE member authority binds a different file")
        content = path.read_bytes()
        if item["sha256"] != _sha(content) or item["bytes"] != len(content):
            raise ValueError("SE profile member content drifted")
        if authority["sha256"] != item["sha256"]:
            raise ValueError("SE profile and source authority disagree")
        if item["disposition"] not in {"readable-text", "embedded-image", "support-evidence"} or not item["reason"]:
            raise ValueError("SE member requires an explicit source disposition")
        row = dict(item)
        if path.suffix.lower() in {".xhtml", ".opf", ".xml", ".svg"}:
            tree = etree.fromstring(content, parser=etree.XMLParser(resolve_entities=False, remove_blank_text=False))
            row["xml_carriers"] = []
            pending = [(tree, "/1")]
            while pending:
                node, pointer = pending.pop()
                row["xml_carriers"].append({"path": pointer, "tag": node.tag,
                    "attributes": dict(sorted(node.attrib.items())), "text": node.text, "tail": node.tail})
                children = [child for child in node if isinstance(child.tag, str)]
                pending.extend((child, f"{pointer}/{index}") for index, child in reversed(list(enumerate(children, 1))))
        rows.append(row)
    return rows


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("contract") != "ocd-standard-ebooks-reconstruction-profile-v1":
        raise ValueError("SE reconstruction profile contract mismatch")
    if profile["work_id"] != source_manifest.record["work_id"] or profile["image_policy"] != "exact-bytes-data-uri":
        raise ValueError("SE work or embedded-image policy mismatch")
    inventory = _inventory(source_manifest, profile)
    config_path = source_manifest.authority_path("work-config")
    config = json.loads(config_path.read_bytes())
    if config.get("source_revision") not in {None, profile["source_revision"]}:
        raise ValueError("SE config disagrees with the profile's retained revision")
    config["source_revision"] = profile["source_revision"]
    with tempfile.TemporaryDirectory(prefix="ocd-se-") as temporary:
        output = Path(temporary) / "content.tei.xml"
        effective_config = Path(temporary) / "effective-config.json"
        effective_config.write_bytes(_json(config))
        result = convert_se_to_tei(source_manifest.repository_root / profile["source_root"], effective_config, output, embed_assets=True)
        if result.asset_paths or sorted(path.name for path in Path(temporary).iterdir()) != ["content.tei.xml", "effective-config.json"]:
            raise ValueError("SE embedded producer emitted an external dependency")
        tei = output.read_bytes()
    provenance = {"contract": "ocd-standard-ebooks-candidate-provenance-v1", "work_id": profile["work_id"],
                  "source_manifest_sha256": source_manifest.sha256, "source_revision": profile["source_revision"],
                  "profile_sha256": _sha(source_manifest.authority_path("reconstruction-profile").read_bytes()),
                  "image_policy": profile["image_policy"], "status": "nonaccepted", "publication_authorized": False}
    return {
        "content.tei.xml": tei,
        "source-accountability.json": _json({"contract": "ocd-standard-ebooks-source-accountability-v1", "members": inventory}),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"".join(_json(item) for item in profile["unresolved"]),
        "README.source.md": source_manifest.authority_path("source-attribution-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
