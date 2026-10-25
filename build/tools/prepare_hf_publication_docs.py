"""Prepare and check public documents over an unchanged, verified HF dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

import yaml

from ocd_kernel.library._common import canonical_bytes, sha256_file
from ocd_kernel.release.public_allowlist import _is_link, _scan, public_files


CONTRACT = "ocd-hf-publication-documents-v1"
SOURCE_NOTICES = "HUGGINGFACE_SOURCE_NOTICES.md"
BAXTER_CLAUSE = ("Where applicable to Boethius, the companion Consolation is mentioned in the source "
                 "title matter but is not present in the selected five-tract text. ")
BAXTER_MARKER = "Existing named and unnamed contributor roles, source qualifications, and accepted scope remain authoritative."
BAXTER_WORKS = {"baxter-call-to-unconverted", "baxter-reformed-pastor", "baxter-saints-rest"}
DOCUMENT_SOURCES = {
    "HF_DATA_GUIDE.md": "docs/HF_DATA_GUIDE.md",
    "HF_DATA_LICENSE.md": "docs/HF_DATA_LICENSE.md",
    "LICENSE": "docs/HF_DATA_LICENSE.md",
    "releases/v1.0.0-migration.md": "docs/releases/v1.0.0-migration.md",
}
SOURCE_WORKS = (
    "severian-de-fide-et-lege-naturae",
    "john-of-ephesus-ecclesiastical-history",
    "anonymous-vita-sancti-cononis-bidanae",
)
LINK_FIXES = {
    "../../../docs/sources/ccel-permission.md": "https://github.com/OpenChristianData/open-christian-data/blob/main/docs/sources/ccel-permission.md",
    "www.onthewing.org/user/Creed_Council%20of%20Orange%20-%20Pelagianism.pdf": "https://www.onthewing.org/user/Creed_Council%20of%20Orange%20-%20Pelagianism.pdf",
    "/ccel/edwards/will/files/je_banner.jpg": "https://www.ccel.org/ccel/edwards/will/files/je_banner.jpg",
    **{f"../../../sources/prose/{w}/README.source.md": f"sources/prose/{w}/README.source.md" for w in SOURCE_WORKS},
}
EXTRA_METADATA = {
    "license": "other",
    "license_name": "per-item-source-terms",
    "tags": ["christian", "theology", "bible", "historical-texts"],
    "task_categories": ["text-generation", "question-answering"],
}


class DocumentError(ValueError):
    """Public documents differ from their pinned source or delivery contract."""


def _card(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n") or "\n---\n" not in text:
        raise DocumentError("dataset card requires YAML front matter")
    front, body = text[4:].split("\n---\n", 1)
    metadata = yaml.safe_load(front)
    if not isinstance(metadata, dict):
        raise DocumentError("dataset metadata must be an object")
    return metadata, body


def _read(root: Path, relative: str) -> bytes:
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(p in (".", "..") for p in parts) or "\\" in relative or ":" in relative:
        raise DocumentError("invalid document path")
    path = root
    for part in parts:
        path /= part
        if _is_link(path):
            raise DocumentError("document crosses a reparse point")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DocumentError(f"document unavailable: {relative}") from exc


def source_notices(original: str) -> str:
    if "## Source notices\n" not in original:
        raise DocumentError("verified card has no source notices")
    text = original[original.index("## Source notices\n"):]
    result, fenced = [], False
    # Only repair rendered links; quoted license/source blocks stay verbatim.
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced:
            for before, after in LINK_FIXES.items():
                line = line.replace("](" + before + ")", "](" + after + ")")
            if line.startswith("The selected historical layer is Richard Baxter's "):
                line = line.replace(BAXTER_CLAUSE, "")
        result.append(line)
    return "".join(result)


def _notice_correction_inputs(root: Path, selection: dict, original: str) -> list[dict]:
    """Bind the precise Baxter deletion to corrected owners and valid rights joins."""
    if not any(line.startswith("The selected historical layer is Richard Baxter's ") and BAXTER_CLAUSE in line
               for line in original.splitlines()):
        return []
    from ocd_kernel.library.record_read import RecordRead
    from ocd_kernel.library.rights import collect_rights

    bindings = {}
    for item in selection["items"]:
        if item["work_id"] not in BAXTER_WORKS or "exclude_reason" in item:
            continue
        for notice in item["public_notices"]:
            for path_key, hash_key in (("source_path", "source_sha256"), ("notice_path", "notice_sha256")):
                name = notice[path_key]
                corrected = _read(root, name).decode("utf-8")
                if BAXTER_CLAUSE in corrected or corrected.count(BAXTER_MARKER) != 1:
                    raise DocumentError("Baxter notice correction is missing or ambiguous")
                previous = corrected.replace(BAXTER_MARKER, BAXTER_CLAUSE + BAXTER_MARKER)
                if hashlib.sha256(previous.encode("utf-8")).hexdigest() != notice[hash_key]:
                    raise DocumentError("Baxter notice changed beyond the authorized sentence deletion")
                bindings[name] = hashlib.sha256(corrected.encode("utf-8")).hexdigest()
        identity = json.loads(_read(root, item["acceptance_path"]))["identity"]
        read = RecordRead(root)
        rights = collect_rights(read, identity["work_id"], identity["textual_form_id"], identity["edition_id"])
        if rights["health"] != "valid":
            raise DocumentError("corrected Baxter notice has stale rights bindings")
        for name, observed in read.inputs.items():
            if name.startswith(f"library/works/{item['work_id']}/"):
                bindings[name] = observed["sha256"]
    if not bindings:
        raise DocumentError("Baxter notice corrections have no selected owning records")
    return [{"path": name, "sha256": digest} for name, digest in sorted(bindings.items())]


def _support_sources(notices: str) -> dict[str, str]:
    result = dict(DOCUMENT_SOURCES)
    for work in SOURCE_WORKS:
        source = f"sources/prose/{work}/README.source.md"
        if "](" + source + ")" in notices:
            result[source] = source
            notice = f"data/prose/{work}/README.md"
            result[notice] = notice
    return result


def _languages(release: Path) -> list[str]:
    import pyarrow as pa

    codes = set()
    for path in sorted((release / "public/data").glob("*/train.arrow")):
        with pa.memory_map(str(path), "r") as handle:
            for batch in pa.ipc.open_stream(handle):
                codes.update(batch.column(batch.schema.get_field_index("language")).unique().to_pylist())
    if not codes or any(not isinstance(c, str) or not re.fullmatch(r"[a-z]{2,3}", c) for c in codes):
        raise DocumentError("invalid or absent public language labels")
    return sorted({"en" if c == "eng" else c for c in codes})


def _links(documents: dict[str, bytes], dataset_paths: set[str]) -> None:
    import posixpath
    from urllib.parse import unquote

    available = set(documents) | dataset_paths
    for name, content in documents.items():
        fenced = False
        for line in content.decode("utf-8").splitlines():
            if line.lstrip().startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if fenced:
                continue
            for target in re.findall(r"\]\(([^)]+)\)", line):
                if target.startswith(("https:", "http:", "mailto:", "#")):
                    continue
                path = unquote(target.split("#", 1)[0])
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
                if path.startswith("/") or resolved not in available:
                    raise DocumentError(f"unresolved public link in {name}: {target}")


def check_documents(root: Path, release: Path, selection: dict, manifest: Path,
                    digest: str) -> dict[str, bytes]:
    """Validate a pinned documentation overlay; never alter baseline data/proofs."""
    if sha256_file(manifest) != digest:
        raise DocumentError("publication-document manifest differs from pinned digest")
    record = json.loads(manifest.read_bytes())
    if record.get("contract") != CONTRACT or record.get("selection_sha256") != hashlib.sha256(canonical_bytes(selection)).hexdigest():
        raise DocumentError("publication-document selection or contract differs")
    original_bytes = (release / "public/README.md").read_bytes()
    if record.get("base_readme_sha256") != hashlib.sha256(original_bytes).hexdigest():
        raise DocumentError("verified source card differs")
    if record.get("editorial_sha256") != hashlib.sha256(_read(root, "docs/HUGGINGFACE_DATASET_CARD.md")).hexdigest():
        raise DocumentError("editorial source changed")
    if record.get("notice_correction_inputs", []) != _notice_correction_inputs(root, selection, original_bytes.decode("utf-8")):
        raise DocumentError("notice correction inputs changed")
    expected_notices = source_notices(original_bytes.decode("utf-8"))
    if record.get("reader_notices") is True:
        from build.tools.release_catalog import selected_records
        from build.tools.release_information import readable_notices

        expected_notices, _ = readable_notices(root, release, selection, selected_records(root, release, selection))
    sources = {**_support_sources(source_notices(original_bytes.decode("utf-8"))), **_support_sources(expected_notices)}
    catalog = {}
    if record.get("catalog") is True:
        from build.tools.release_catalog import catalog_documents

        catalog = catalog_documents(root, release, selection)
        sources["CATALOG_GUIDE.md"] = "docs/RELEASE_CATALOG.md"
    allowed = {"README.md", SOURCE_NOTICES} | set(sources) | set(catalog)
    entries = record.get("files", [])
    if len(entries) != len(allowed) or {e["path"] for e in entries} != allowed:
        raise DocumentError("publication-document file set differs")
    documents = {}
    for entry in entries:
        content = _read(manifest.parent.resolve(strict=True), entry["path"])
        if len(content) != entry["size_bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise DocumentError("publication document changed")
        try:
            text = content.decode("utf-8")
        except UnicodeError as exc:
            raise DocumentError("publication document is not UTF-8") from exc
        if not content or "\r" in text or _scan(text, entry["path"]):
            raise DocumentError("publication document violates the public boundary")
        documents[entry["path"]] = content
    if documents[SOURCE_NOTICES] != expected_notices.encode("utf-8"):
        raise DocumentError("required source notice wording or links changed")
    for public, source in sources.items():
        if documents[public] != _read(root, source):
            raise DocumentError("public guidance or support notice differs from owning source")
    if any(documents[name] != content for name, content in catalog.items()):
        raise DocumentError("public catalog differs from selected release and owning metadata")
    if catalog and "](WORK_CATALOG.md)" not in documents["README.md"].decode():
        raise DocumentError("public card must link the release catalog")
    before, _ = _card(original_bytes.decode("utf-8"))
    after, _ = _card(documents["README.md"].decode("utf-8"))
    expected = dict(before, pretty_name="Open Christian Data - v1.0.0",
                    language=_languages(release), **EXTRA_METADATA)
    if after != expected:
        raise DocumentError("reader or descriptive metadata changed")
    if len(documents["README.md"]) > 200000 or f"]({SOURCE_NOTICES})" not in documents["README.md"].decode():
        raise DocumentError("public card must be compact and link complete source notices")
    _links(documents, public_files(release / "public"))
    return documents


def prepare(root: Path, release: Path, selection: dict, output: Path, *, include_catalog: bool = False,
            reader_notices: bool = False) -> dict:
    root, release = root.resolve(strict=True), release.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=False)
    original = (release / "public/README.md").read_bytes()
    before, _ = _card(original.decode("utf-8"))
    editorial = _read(root, "docs/HUGGINGFACE_DATASET_CARD.md").decode("utf-8")
    front, body = _card(editorial)
    if front != dict(before, pretty_name="Open Christian Data - v1.0.0"):
        raise DocumentError("editorial source changed generated reader metadata")
    # The old editorial appendix stays retained; only its public delivery moves.
    body = body.split("## Source notices", 1)[0] + f"## Source notices\n\n[Complete source notices and license texts]({SOURCE_NOTICES}).\n"
    metadata = dict(front, language=_languages(release), **EXTRA_METADATA)
    header = editorial.split("\n---\n", 1)[0]
    additions = {k: v for k, v in metadata.items() if k not in front}
    documents = {"README.md": (header + "\n" + yaml.safe_dump(additions, sort_keys=False, allow_unicode=True) + "---\n" + body).encode("utf-8"),
                 SOURCE_NOTICES: source_notices(original.decode("utf-8")).encode("utf-8")}
    if reader_notices:
        from build.tools.release_catalog import selected_records
        from build.tools.release_information import readable_notices

        notice_text, audit = readable_notices(root, release, selection, selected_records(root, release, selection))
        documents[SOURCE_NOTICES] = notice_text.encode("utf-8")
        internal = output / "_internal"
        internal.mkdir()
        (internal / "notice-audit.json").write_bytes(canonical_bytes(audit))
    support = {**_support_sources(source_notices(original.decode("utf-8"))),
               **_support_sources(documents[SOURCE_NOTICES].decode())}
    for public, source in support.items():
        documents[public] = _read(root, source)
    if include_catalog:
        from build.tools.release_catalog import catalog_documents

        documents.update(catalog_documents(root, release, selection))
        documents["CATALOG_GUIDE.md"] = _read(root, "docs/RELEASE_CATALOG.md")
    for name, content in documents.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    record = {"contract": CONTRACT, "selection_sha256": hashlib.sha256(canonical_bytes(selection)).hexdigest(),
              "base_readme_sha256": hashlib.sha256(original).hexdigest(),
              "editorial_sha256": hashlib.sha256(editorial.encode("utf-8")).hexdigest(),
              "files": [{"path": name, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                        for name, content in sorted(documents.items())]}
    correction_inputs = _notice_correction_inputs(root, selection, original.decode("utf-8"))
    if correction_inputs:
        record["notice_correction_inputs"] = correction_inputs
    if include_catalog:
        record["catalog"] = True
    if reader_notices:
        record["reader_notices"] = True
    manifest = output / "publication-documents.json"
    manifest.write_bytes(canonical_bytes(record))
    check_documents(root, release, selection, manifest, sha256_file(manifest))
    return {"status": "pass", "manifest": str(manifest), "manifest_sha256": sha256_file(manifest),
            "readme_bytes": len(documents["README.md"]), "document_files": len(documents), "publication_performed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--catalog", action="store_true", help="Include the bound selected-work/edition catalog")
    parser.add_argument("--reader-notices", action="store_true", help="Render current source facts and terms without internal preparation history")
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.release, json.loads(args.selection.read_bytes()), args.output,
                             include_catalog=args.catalog, reader_notices=args.reader_notices)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
