"""Freeze independent source authority for Denney's two separate editions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "sources/commentaries/expositors-bible/readable-denney-pair-v4"
DETAILS = {
    "denney-expositor2cor": {
        "work_id": "expositors-bible--james-denney",
        "source": "raw/ccel/expositors-bible/denney_expositor2cor.xml",
        "sha256": "afdf1cb907eb7d79f2f20582dd8d5e96a84614c253bb193903cc1cac76d16bc7",
        "title": "The Expositor's Bible: The Second Epistle to the Corinthians",
        "author": "James Denney", "url": "https://www.ccel.org/ccel/denney/expositor2cor.html",
        "elements": 2536, "comments": 10,
        "front": ["i", "ii"], "back": ["xxxi"],
    },
    "denney-expositorthess": {
        "work_id": "expositors-bible--james-denney",
        "source": "raw/ccel/expositors-bible/denney_expositorthess.xml",
        "sha256": "47417f9447e9558951594ba2bd35eb5958be1293041e83b1af6e990ee8d2fffc",
        "title": "The Expositor's Bible: The Epistles to the Thessalonians",
        "author": "James Denney", "url": "https://www.ccel.org/ccel/denney/expositorthess.html",
        "elements": 1576, "comments": 10,
        "front": ["i"], "back": ["iv"],
    },
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write(path: Path, content: bytes) -> None:
    if path.exists() and path.read_bytes() != content:
        raise FileExistsError(f"refusing to change frozen Expositor authority: {path}")
    path.write_bytes(content)


def _authority(name: str, path: Path, role: str) -> dict[str, object]:
    content = path.read_bytes()
    return {"name": name, "path": path.relative_to(ROOT).as_posix(), "role": role,
            "bytes": len(content), "sha256": _sha(content)}


def main() -> None:
    converter = ROOT / "build/tei/expositors_bible_lib034_readable_denney_pair.py"
    oracle = ROOT / "build/tei/expositors_bible_lib034_readable_denney_pair_oracle.py"
    xsd = ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
    package_schema = ROOT / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
    for member_id, detail in DETAILS.items():
        dest = BASE / member_id
        dest.mkdir(parents=True, exist_ok=True)
        raw = (ROOT / detail["source"]).read_bytes()
        if _sha(raw) != detail["sha256"]:
            raise ValueError(f"{member_id} exact retained XML differs")
        profile = {
            "contract": "ocd-expositors-lib034-readable-denney-pair-profile-v1",
            "member_id": member_id, "work_id": detail["work_id"],
            "source": {"path": detail["source"], "bytes": len(raw), "sha256": detail["sha256"]},
            "source_title": detail["title"], "source_author": detail["author"],
            "root_disposition": {"front": detail["front"], "back": detail["back"],
                                 "body": "all other direct ThML.body div1 roots in original order"},
            "element_count": detail["elements"], "comment_count": detail["comments"],
            "scope": "complete one retained CCEL electronic edition with title, chapters, and indexes",
            "comment_disposition": "nontextual CCEL auto-index comments retained exactly in accounting ledger",
            "broken_local_links": ([{"source_id": "iv-p8.1", "href": "#Footnote_4_4",
                                    "disposition": "text retained without invented TEI target"}]
                                   if member_id == "denney-expositor2cor" else []),
            "human_acceptance": "absent",
        }
        policy = {
            "contract": "ocd-expositors-lib034-readable-denney-pair-validation-policy-v1",
            "member_id": member_id, "candidate_status": "nonaccepted",
            "required_member_names": ["manifest.json", "content.tei.xml", "source-accountability.json",
                                      "provenance.json", "unresolved.jsonl", "README.source.md"],
            "checks": ["retained-source-hash", "complete-root-disposition", "source-element-order-hierarchy-attributes-text-tail",
                       "comment-order-and-disposition", "resolved-local-links", "tei-p5", "stock-native-projection-and-independent-verification"],
            "oracle_import_closure": ["build/tei/expositors_bible_lib034_readable_denney_pair_oracle.py"],
            "forbidden_oracle_imports": ["build.tei.expositors_bible_lib034_readable_denney_pair"],
        }
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
            "additionalProperties": False,
            "required": ["contract", "member_id", "source", "root_ids_in_order", "root_disposition",
                         "source_body_text", "features", "feature_count", "comments", "comment_count",
                         "broken_local_links"],
            "properties": {
                "contract": {"const": "ocd-expositors-lib034-readable-denney-pair-accounting-v1"},
                "member_id": {"const": member_id}, "source": {"type": "object", "required": ["path", "bytes", "sha256"]},
                "root_ids_in_order": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                "root_disposition": {"type": "object", "required": ["front", "body", "back"]},
                "source_body_text": {"type": "string"},
                "features": {"type": "array", "minItems": detail["elements"], "maxItems": detail["elements"],
                             "items": {"type": "object", "required": ["ordinal", "source_tag", "source_attributes",
                                                                      "source_text", "source_tail", "tei_id", "tei_tag", "tei_attributes"]}},
                "feature_count": {"const": detail["elements"]},
                "comments": {"type": "array", "minItems": detail["comments"], "maxItems": detail["comments"],
                             "items": {"type": "object", "required": ["text", "tail", "after_feature", "disposition"]}},
                "comment_count": {"const": detail["comments"]},
                "broken_local_links": {"type": "array", "minItems": 1 if member_id == "denney-expositor2cor" else 0,
                                       "maxItems": 1 if member_id == "denney-expositor2cor" else 0},
            },
        }
        readme = (f"# {detail['title']}\n\n"
                  f"This readable nonaccepted TEI candidate represents the complete retained `{detail['source']}` "
                  "electronic edition, including its title matter, commentary chapters, and indexes. "
                  "It does not represent another author's or companion volume's edition.\n\n"
                  f"Sourced via CCEL.org: <{detail['url']}>. CCEL permits parsing its ThML; "
                  "do not sell CCEL files or derivatives of its formatting. The underlying print text's "
                  "rights, human acceptance, print collation, and public release require separate review. "
                  "A future public dataset README/card must visibly mention `sourced via CCEL.org`.\n").encode("utf-8")
        if member_id == "denney-expositor2cor":
            readme += ("\nThe retained XML has one unresolved local footnote link `#Footnote_4_4`. "
                       "Its literal anchor text remains in the readable candidate without an invented target; "
                       "the exact source attribute and disposition remain in source accounting.\n").encode("utf-8")
        for filename, value in (("reconstruction-profile.json", _json(profile)),
                                ("validation-policy.json", _json(policy)),
                                ("source-accountability.schema.json", _json(schema)),
                                ("README.source.md", readme)):
            _write(dest / filename, value)
        authorities = [
            _authority("retained-thml", ROOT / detail["source"], "primary-source"),
            _authority("source-local-attribution-readme", dest / "README.source.md", "source-attribution-readme"),
            _authority("reconstruction-profile", dest / "reconstruction-profile.json", "complete-source-feature-profile"),
            _authority("validation-policy", dest / "validation-policy.json", "independent-validation-policy"),
            _authority("source-accountability-schema", dest / "source-accountability.schema.json", "complete-source-accountability-schema"),
            _authority("tei-p5-xsd", xsd, "tei-validation-schema"),
            _authority("candidate-package-schema", package_schema, "candidate-package-schema"),
        ]
        manifest = {
            "contract": "ocd-source-manifest-v1",
            "source_id": f"ccel-expositors-lib034-readable-{member_id}-v4",
            "work_id": detail["work_id"],
            "authorities": authorities,
            "converter": {"id": "ocd-expositors-lib034-readable-denney-pair-to-tei", "version": "1", "callable": "_convert",
                          "implementation_path": converter.relative_to(ROOT).as_posix(),
                          "implementation_sha256": _sha(converter.read_bytes())},
            "validator": {"id": "ocd-expositors-lib034-readable-denney-pair-independent-oracle", "version": "1", "callable": "_oracle",
                          "implementation_path": oracle.relative_to(ROOT).as_posix(),
                          "implementation_sha256": _sha(oracle.read_bytes()),
                          "import_closure_sha256": _sha(oracle.read_bytes())},
            "package_schema": {"path": package_schema.relative_to(ROOT).as_posix(),
                               "sha256": _sha(package_schema.read_bytes())},
        }
        path = dest / "source-manifest.json"
        _write(path, _json(manifest))
        print(member_id, _sha(path.read_bytes()))


if __name__ == "__main__":
    main()
