"""Pin task-local PG66953 source and implementation bytes in its manifest."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei.jarena_lee_pg66953_oracle import _closure_sha


ROOT = Path(__file__).resolve().parents[2]
OUT = "sources/structured-text/jarena-lee-pg66953/source-manifest.json"
SOURCE = "raw/gutenberg/66953/html/pg66953-images.html"
CONVERTER = "build/tei/jarena_lee_pg66953_reconstruction.py"
ORACLE = "build/tei/jarena_lee_pg66953_oracle.py"


def _sha(path: str) -> str:
    return sha256((ROOT / path).read_bytes()).hexdigest()


def _authority(name: str, path: str, role: str) -> dict:
    return {"name": name, "path": path, "role": role,
            "bytes": (ROOT / path).stat().st_size, "sha256": _sha(path)}


def main() -> None:
    source = _authority("retained-source", SOURCE, "primary-source")
    authorities = [
        source,
        _authority("retained-package", "raw/gutenberg/66953/pg66953-h.zip", "supporting-package"),
        _authority("retained-cover", "raw/gutenberg/66953/html/images/cover.jpg", "unreferenced-support"),
        _authority("retained-frontispiece", "raw/gutenberg/66953/html/images/frontispiece.jpg", "referenced-body-image"),
        _authority("retained-title-detail", "raw/gutenberg/66953/html/images/titlepage-detail.jpg", "referenced-body-image"),
        _authority("reconstruction-profile", "sources/structured-text/jarena-lee-pg66953/profile.json", "complete-source-feature-profile"),
        _authority("validation-policy", "sources/structured-text/jarena-lee-pg66953/validation-policy.json", "independent-validation-policy"),
        _authority("source-readme", "sources/structured-text/jarena-lee-pg66953/README.source.md", "source-attribution-readme"),
        _authority("tei-p5-xsd", "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-validation-schema"),
        _authority("candidate-package-schema", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "candidate-package-schema"),
        _authority("producer-implementation", CONVERTER, "supporting-converter-implementation"),
        _authority("oracle-implementation", ORACLE, "supporting-validator-implementation"),
    ]
    record = {
        "contract": "ocd-source-manifest-v1",
        "source_id": "jarena-lee-pg66953-current-extracted-html",
        "work_id": "jarena-lee-religious-experience-and-journal",
        "external_library_root": "D:/Library/Open Christian Data",
        "scope": {
            "kind": "one-complete-retained-gutenberg-html-member",
            "title": "Religious Experience and Journal of Mrs. Jarena Lee",
            "source_url": "https://www.gutenberg.org/ebooks/66953",
            "candidate_status": "nonaccepted",
            "represented_body_elements": 823,
            "flattened_structural_wrappers": 0,
            "unrepresented_body_elements": 0,
            "package_cover_role": "unreferenced support",
            "body_image_occurrences": 3,
            "body_image_support_members": 2,
        },
        "source_bundle": {"members": 1, "bytes": source["bytes"], "sha256": source["sha256"]},
        "source_members": [{"name": "pg66953-images.html", "logical_name": "pg66953-images.html",
                            "path": SOURCE, "order": 1, "bytes": source["bytes"],
                            "sha256": source["sha256"]}],
        "authorities": authorities,
        "converter": {"id": "ocd-jarena-lee-pg66953-extracted-html-to-tei",
                      "version": "1", "callable": "_convert", "implementation_path": CONVERTER,
                      "implementation_sha256": _sha(CONVERTER)},
        "validator": {"id": "ocd-jarena-lee-pg66953-independent-html-oracle",
                      "version": "1", "callable": "_oracle", "implementation_path": ORACLE,
                      "implementation_sha256": _sha(ORACLE),
                      "import_closure_sha256": _closure_sha()},
        "package_schema": {"path": "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
                           "sha256": _sha("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")},
    }
    (ROOT / OUT).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
