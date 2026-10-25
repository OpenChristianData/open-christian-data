"""Pin task-local PG11959 source and implementation bytes in its manifest."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei.eliza_southall_pg11959_oracle import _closure_sha


ROOT = Path(__file__).resolve().parents[2]
OUT = "sources/structured-text/eliza-southall-pg11959/source-manifest.json"
SOURCE = "raw/gutenberg/11959/html/pg11959-images.html"
CONVERTER = "build/tei/eliza_southall_pg11959_reconstruction.py"
ORACLE = "build/tei/eliza_southall_pg11959_oracle.py"


def _sha(path: str) -> str:
    return sha256((ROOT / path).read_bytes()).hexdigest()


def _authority(name: str, path: str, role: str) -> dict:
    return {"name": name, "path": path, "role": role,
            "bytes": (ROOT / path).stat().st_size, "sha256": _sha(path)}


def main() -> None:
    source = _authority("retained-source", SOURCE, "primary-source")
    authorities = [
        source,
        _authority("retained-package", "raw/gutenberg/11959/pg11959-h.zip", "supporting-package"),
        _authority("retained-cover", "raw/gutenberg/11959/html/11959-cover.png", "unreferenced-support"),
        _authority("reconstruction-profile", "sources/structured-text/eliza-southall-pg11959/profile.json", "complete-source-feature-profile"),
        _authority("validation-policy", "sources/structured-text/eliza-southall-pg11959/validation-policy.json", "independent-validation-policy"),
        _authority("source-readme", "sources/structured-text/eliza-southall-pg11959/README.source.md", "source-attribution-readme"),
        _authority("tei-p5-xsd", "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-validation-schema"),
        _authority("candidate-package-schema", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "candidate-package-schema"),
        _authority("producer-implementation", CONVERTER, "supporting-converter-implementation"),
        _authority("oracle-implementation", ORACLE, "supporting-validator-implementation"),
    ]
    record = {
        "contract": "ocd-source-manifest-v1",
        "source_id": "eliza-southall-pg11959-current-extracted-html",
        "work_id": "eliza-southall-brief-memoir",
        "external_library_root": "D:/Library/Open Christian Data",
        "scope": {
            "kind": "one-complete-retained-gutenberg-html-member",
            "title": "A Brief Memoir with Portions of the Diary, Letters, and Other Remains of Eliza Southall",
            "source_url": "https://www.gutenberg.org/ebooks/11959",
            "candidate_status": "nonaccepted",
            "represented_body_elements": 1362,
            "flattened_structural_wrappers": 0,
            "unrepresented_body_elements": 0,
            "package_cover_role": "unreferenced support",
        },
        "source_bundle": {"members": 1, "bytes": source["bytes"], "sha256": source["sha256"]},
        "source_members": [{"name": "pg11959-images.html", "logical_name": "pg11959-images.html",
                            "path": SOURCE, "order": 1, "bytes": source["bytes"],
                            "sha256": source["sha256"]}],
        "authorities": authorities,
        "converter": {"id": "ocd-eliza-southall-pg11959-extracted-html-to-tei",
                      "version": "1", "callable": "_convert", "implementation_path": CONVERTER,
                      "implementation_sha256": _sha(CONVERTER)},
        "validator": {"id": "ocd-eliza-southall-pg11959-independent-html-oracle",
                      "version": "1", "callable": "_oracle", "implementation_path": ORACLE,
                      "implementation_sha256": _sha(ORACLE),
                      "import_closure_sha256": _closure_sha()},
        "package_schema": {"path": "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
                           "sha256": _sha("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")},
    }
    (ROOT / OUT).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
