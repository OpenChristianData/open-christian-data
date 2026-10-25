"""Prepare exact retained-source bindings for the four blocked SE candidates.

This authoring command does not validate, admit, accept, or publish a candidate.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from build.tei.se_candidate_oracle import ORACLE_ID, ORACLE_VERSION, _closure, _sha
from build.tei.se_candidate_reconstruction import CONVERTER_ID, CONVERTER_VERSION

WORKS = {
    "george-macdonald_unspoken-sermons": ("george-macdonald-unspoken-sermons", "LIB-085"),
    "g-k-chesterton_heretics": ("heretics", "LIB-086"),
    "g-k-chesterton_orthodoxy": ("orthodoxy", "LIB-086"),
    "g-k-chesterton_the-everlasting-man": ("the-everlasting-man", "LIB-086"),
}


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


def prepare(root: Path):
    oracle_sha, _ = _closure(root)
    producer_sha, producer_dependencies = _closure(root, root / "build/tei/se_candidate_reconstruction.py")
    prepared = []
    for slug, (work_id, ticket_id) in WORKS.items():
        source_root = root / "raw/standard_ebooks" / slug
        directory = root / "sources/standard-ebooks" / slug
        command = ["git", "-c", f"safe.directory={source_root.resolve().as_posix()}", "-C", str(source_root)]
        status = subprocess.run(command + ["status", "--porcelain"], capture_output=True, text=True, check=True).stdout
        if status:
            raise ValueError(f"Retained SE checkout is dirty: {slug}")
        revision = subprocess.run(command + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        tracked = subprocess.run(command + ["ls-files", "-z"], capture_output=True, check=True).stdout.decode("utf-8").split("\0")
        tracked = sorted(path for path in tracked if path)
        actual = sorted(path.relative_to(source_root).as_posix() for path in source_root.rglob("*") if path.is_file() and ".git" not in path.relative_to(source_root).parts)
        if actual != tracked:
            raise ValueError(f"Retained SE file envelope differs from tracked files: {slug}")
        authorities = []
        def bind(name, path, role):
            content = path.read_bytes()
            row = {"name": name, "path": path.relative_to(root).as_posix(), "role": role, "bytes": len(content), "sha256": _sha(content)}
            authorities.append(row)
            return row
        members = []
        for index, relative in enumerate(actual):
            path = source_root / relative
            disposition = "readable-text" if relative.startswith("src/epub/text/") and path.suffix == ".xhtml" else "embedded-image" if relative.startswith("src/epub/images/") else "support-evidence"
            if path.name == "toc.xhtml":
                disposition = "support-evidence"
            row = bind(f"source-member-{index:03d}", path, "primary-source" if disposition != "support-evidence" else "retained-support")
            members.append({"path": relative, "authority": row["name"], "bytes": row["bytes"], "sha256": row["sha256"], "disposition": disposition,
                            "reason": {"readable-text": "Source spine content reconstructed in TEI; XHTML document metadata remains retained support.", "embedded-image": "Exact retained EPUB image available for source-linked data-URI reconstruction.", "support-evidence": "Retained edition packaging, navigation, styling, artwork source, metadata, or repository support; not substituted for readable work text."}[disposition]})
        unresolved = [{"id": f"{work_id}-{kind}", "status": "unresolved", "detail": detail} for kind, detail in (
            ("metadata", "Local config identity claims require primary-source reconciliation before metadata completion."),
            ("rights", "Retained Standard Ebooks uncopyright statements do not establish worldwide rights or publication authorization."),
            ("acceptance", "Technical reconstruction does not establish human acceptance."),
        )]
        profile = {"contract": "ocd-standard-ebooks-reconstruction-profile-v1", "work_id": work_id,
                   "source_root": source_root.relative_to(root).as_posix(), "source_revision": revision,
                   "image_policy": "exact-bytes-data-uri", "members": members, "unresolved": unresolved}
        _write(directory / "reconstruction-profile.json", profile)
        _write(directory / "validation-policy.json", {"contract": "ocd-standard-ebooks-validation-policy-v1", "work_id": work_id,
            "image_policy": "exact-bytes-data-uri", "source_scope": "complete-retained-file-envelope", "readable_scope": "OPF spine except navigation-only toc.xhtml",
            "independence": "Oracle uses stdlib ElementTree and a separately implemented structural projection. Producer uses lxml; local schema validation shares lxml only.",
            "unresolved_metadata_is_not_acceptance": True})
        (directory / "README.source.md").write_text(f"# Retained Standard Ebooks source: {work_id}\n\nSource: https://standardebooks.org/ and https://github.com/standardebooks/{slug}\n\nRetained Git revision: {revision}. Exact file bytes are bound by the source manifest. Standard Ebooks' retained imprint, colophon, and uncopyright text remain in the readable TEI when present in the spine. Image bytes are embedded without alteration. Navigation and packaging files remain explicitly inventoried source support.\n\nThis is a nonaccepted reconstruction candidate. Metadata reconciliation, jurisdiction-specific rights, human acceptance, and publication authorization remain separate.\n", encoding="utf-8", newline="\n")
        for name, filename, role in (("work-config", "config.json", "work-configuration"), ("reconstruction-profile", "reconstruction-profile.json", "complete-source-feature-profile"), ("validation-policy", "validation-policy.json", "independent-validation-policy"), ("source-attribution-readme", "README.source.md", "source-attribution-readme")):
            bind(name, directory / filename, role)
        for name, relative in (("tei-p5-xsd", "ocd_kernel/tei/vendor/xsd/tei_all.xsd"), ("tei-p5-xsd-teix", "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"), ("tei-p5-xsd-xml", "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd"), ("candidate-package-schema", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")):
            bind(name, root / relative, "tei-validation-schema" if name == "tei-p5-xsd" else "candidate-package-schema" if name == "candidate-package-schema" else "schema-dependency")
        for index, dependency in enumerate(producer_dependencies):
            bind(f"producer-dependency-{index:03d}", root / dependency["path"], "implementation-dependency")
        schema = root / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
        record = {"contract": "ocd-source-manifest-v1", "work_id": work_id, "ticket_id": ticket_id,
                  "source_id": slug + "-retained-git", "retained_source_path": source_root.relative_to(root).as_posix(),
                  "authorities": authorities, "producer_import_closure_sha256": producer_sha,
                  "package_schema": {"path": schema.relative_to(root).as_posix(), "sha256": _sha(schema.read_bytes())},
                  "converter": {"id": CONVERTER_ID, "version": CONVERTER_VERSION, "callable": "_convert", "implementation_path": "build/tei/se_candidate_reconstruction.py", "implementation_sha256": _sha((root / "build/tei/se_candidate_reconstruction.py").read_bytes())},
                  "validator": {"id": ORACLE_ID, "version": ORACLE_VERSION, "callable": "_oracle", "implementation_path": "build/tei/se_candidate_oracle.py", "implementation_sha256": _sha((root / "build/tei/se_candidate_oracle.py").read_bytes()), "import_closure_sha256": oracle_sha}}
        path = directory / f"{work_id}.source-manifest.json"
        _write(path, record)
        prepared.append({"work_id": work_id, "manifest": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes()), "members": len(members)})
    return prepared


if __name__ == "__main__":
    print(json.dumps(prepare(Path(__file__).resolve().parents[2]), indent=2))
