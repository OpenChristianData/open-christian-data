"""Pin task-local PG50916 source and implementation bytes in its manifest."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei.evening_incense_pg50916_oracle import _closure_sha


ROOT = Path(__file__).resolve().parents[2]
OUT = "sources/structured-text/evening-incense-pg50916/source-manifest.json"
SOURCE = "raw/gutenberg/50916/html/pg50916-images.html"
CONVERTER = "build/tei/evening_incense_pg50916_reconstruction.py"
ORACLE = "build/tei/evening_incense_pg50916_oracle.py"


def _sha(path: str) -> str:
    return sha256((ROOT / path).read_bytes()).hexdigest()


def _authority(name: str, path: str, role: str) -> dict:
    return {"name": name, "path": path, "role": role,
            "bytes": (ROOT / path).stat().st_size, "sha256": _sha(path)}


def main() -> None:
    source = _authority("retained-source", SOURCE, "primary-source")
    authorities = [
        source,
        _authority("retained-package", "raw/gutenberg/50916/pg50916-h.zip", "supporting-package"),
        _authority("retained-cover", "raw/gutenberg/50916/html/images/cover.jpg", "head-favicon-support"),
        _authority("reconstruction-profile", "sources/structured-text/evening-incense-pg50916/profile.json", "complete-source-feature-profile"),
        _authority("validation-policy", "sources/structured-text/evening-incense-pg50916/validation-policy.json", "independent-validation-policy"),
        _authority("source-readme", "sources/structured-text/evening-incense-pg50916/README.source.md", "source-attribution-readme"),
        _authority("tei-p5-xsd", "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-validation-schema"),
        _authority("candidate-package-schema", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "candidate-package-schema"),
        _authority("producer-implementation", CONVERTER, "supporting-converter-implementation"),
        _authority("oracle-implementation", ORACLE, "supporting-validator-implementation"),
    ]
    record = {
        "contract": "ocd-source-manifest-v1",
        "source_id": "evening-incense-pg50916-current-extracted-html",
        "work_id": "evening-incense-macduff",
        "external_library_root": "D:/Library/Open Christian Data",
        "scope": {
            "kind": "one-complete-retained-gutenberg-html-member",
            "title": "Evening Incense",
            "source_url": "https://www.gutenberg.org/ebooks/50916",
            "candidate_status": "nonaccepted",
            "represented_body_elements": 1066,
            "flattened_structural_wrappers": 1,
            "unrepresented_body_elements": 0,
            "package_cover_role": "head favicon support",
        },
        "source_bundle": {"members": 1, "bytes": source["bytes"], "sha256": source["sha256"]},
        "source_members": [{"name": "pg50916-images.html", "logical_name": "pg50916-images.html",
                            "path": SOURCE, "order": 1, "bytes": source["bytes"],
                            "sha256": source["sha256"]}],
        "authorities": authorities,
        "converter": {"id": "ocd-evening-incense-pg50916-extracted-html-to-tei",
                      "version": "1", "callable": "_convert", "implementation_path": CONVERTER,
                      "implementation_sha256": _sha(CONVERTER)},
        "validator": {"id": "ocd-evening-incense-pg50916-independent-html-oracle",
                      "version": "1", "callable": "_oracle", "implementation_path": ORACLE,
                      "implementation_sha256": _sha(ORACLE),
                      "import_closure_sha256": _closure_sha()},
        "package_schema": {"path": "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
                           "sha256": _sha("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")},
    }
    (ROOT / OUT).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
