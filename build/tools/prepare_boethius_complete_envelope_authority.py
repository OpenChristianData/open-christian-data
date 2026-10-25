"""Freeze the source-wide Boethius route without changing the legacy candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "sources/structured-text/boethius-theological-tractates"
DEST = BASE / "complete-envelope-v4"


def _bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write(path: Path, content: bytes) -> None:
    if path.exists() and path.read_bytes() != content:
        raise FileExistsError(f"refusing to replace frozen authority: {path}")
    path.write_bytes(content)


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    profile = {
        "contract": "ocd-boethius-complete-envelope-profile-v1",
        "profile_id": "boethius-tracts-complete-five-root-ccel-witness-v4",
        "source_member": {"path": "raw/ccel/boethius/tracts.xml", "bytes": 162005,
                          "sha256": "406487abffb39f63934771ce3b4d23b69ce4488d6bc1ccc6a6cad5b4b1e01de8"},
        "root_ids_in_order": ["i", "ii", "iii", "iv", "v"],
        "root_disposition": {"front": ["i", "ii", "iii"], "body": ["iv"], "back": ["v"]},
        "body_tractate_ids": ["iv.i", "iv.ii", "iv.iii", "iv.iv", "iv.v"],
        "element_count": 1119, "comment_count": 10, "internal_link_count": 136,
        "comment_disposition": "exact nontextual auto-index comments and whitespace tails retained in source accountability, not emitted as TEI reading text",
        "unclear_disposition": "nine source unclear readings represented as TEI seg type=source-unclear with exact source text and ID",
        "scope": "complete retained ThML.body, including source paratext and generated indexes",
        "human_acceptance": "absent",
    }
    policy = {
        "contract": "ocd-boethius-complete-envelope-validation-policy-v1",
        "policy_id": profile["profile_id"], "candidate_status": "nonaccepted",
        "required_member_names": ["manifest.json", "content.tei.xml", "source-accountability.json",
                                  "provenance.json", "unresolved.jsonl", "README.source.md"],
        "checks": ["exact-source-byte-and-hash", "complete-five-root-front-body-back",
                   "element-comment-attribute-text-tail-accounting", "all-local-links-resolve",
                   "independent-source-comparison", "comment-ledger-only-disposition",
                   "direct-tei-p5", "nonaccepted-boundary"],
        "oracle_import_closure": ["build/tei/boethius_complete_envelope_oracle.py"],
        "forbidden_oracle_imports": ["build.tei.boethius_complete_envelope"],
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": ["contract", "source", "root_ids_in_order", "root_disposition",
                     "source_body_text", "features", "feature_count", "comments", "comment_count"],
        "properties": {
            "contract": {"const": "ocd-boethius-complete-envelope-accountability-v1"},
            "source": {"type": "object", "required": ["path", "bytes", "sha256"]},
            "root_ids_in_order": {"const": ["i", "ii", "iii", "iv", "v"]},
            "root_disposition": {"type": "object", "required": ["front", "body", "back"]},
            "source_body_text": {"type": "string"},
            "features": {"type": "array", "minItems": 1119, "maxItems": 1119,
                         "items": {"type": "object", "required": ["ordinal", "source_tag", "source_attributes",
                                                                  "source_text", "source_tail", "tei_id", "tei_tag", "tei_attributes"]}},
            "feature_count": {"const": 1119},
            "comments": {"type": "array", "minItems": 10, "maxItems": 10,
                         "items": {"type": "object", "required": ["text", "tail", "after_feature", "disposition"]}},
            "comment_count": {"const": 10},
        },
    }
    artifacts = {
        "reconstruction-profile": ("complete-source-feature-profile", "reconstruction-profile.json", profile),
        "validation-policy": ("independent-validation-policy", "validation-policy.json", policy),
        "source-accountability-schema": ("complete-source-accountability-schema", "source-accountability.schema.json", schema),
    }
    for _, filename, value in artifacts.values():
        _write(DEST / filename, _bytes(value))
    manifest = json.loads((BASE / "boethius-theological-tractates.source-manifest.json").read_bytes())
    manifest["source_id"] = "ccel-boethius-tracts-complete-envelope-retained-xml-v4"
    for authority in manifest["authorities"]:
        name = authority["name"]
        if name == "source-local-attribution-readme":
            path = DEST / "README.source.md"
            content = path.read_bytes()
            authority.update(path=path.relative_to(ROOT).as_posix(),
                             bytes=len(content), sha256=_sha(content))
            continue
        if name not in artifacts:
            continue
        role, filename, _ = artifacts[name]
        path = DEST / filename
        content = path.read_bytes()
        authority.update(path=path.relative_to(ROOT).as_posix(), role=role,
                         bytes=len(content), sha256=_sha(content))
    for key, filename, callable_name, identity in (
        ("converter", "boethius_complete_envelope.py", "_convert", "ocd-boethius-complete-envelope-to-tei"),
        ("validator", "boethius_complete_envelope_oracle.py", "_oracle", "ocd-boethius-complete-envelope-independent-oracle"),
    ):
        path = ROOT / "build/tei" / filename
        content_sha = _sha(path.read_bytes())
        record = {"id": identity, "version": "1", "callable": callable_name,
                  "implementation_path": path.relative_to(ROOT).as_posix(),
                  "implementation_sha256": content_sha}
        if key == "validator":
            record["import_closure_sha256"] = content_sha
        manifest[key] = record
    _write(DEST / "source-manifest.json", _bytes(manifest))
    print(_sha((DEST / "source-manifest.json").read_bytes()))


if __name__ == "__main__":
    main()
