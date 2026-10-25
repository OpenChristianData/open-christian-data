"""Package the source-specific Grammar of Assent converter as one exact candidate."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from build.tei.newman_grammar_of_assent import (
    SOURCE_LOGICAL_PATH, _build_document, _load_retained_source,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct


CONVERTER_ID = "ocd-newman-grammar-pg34022-extracted-html-v1"
CONVERTER_VERSION = "1"
SOURCE = SOURCE_LOGICAL_PATH


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    members = manifest.record["source_members"]
    if len(members) != 1 or members[0]["path"] != SOURCE:
        raise ValueError("PG34022 extracted HTML member binding differs")
    source, book_roots, census = _load_retained_source(SOURCE, manifest.repository_root)
    if source != manifest.authority_path("retained-source").read_bytes():
        raise ValueError("PG34022 extracted HTML authority differs")
    tree, accounting = _build_document(book_roots, census)
    content = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    account = {
        "contract": "ocd-newman-grammar-pg34022-accountability-v1",
        "source_path": SOURCE,
        "source_sha256": sha256(source).hexdigest(),
        "source_bytes": len(source),
        "candidate_sha256": sha256(content).hexdigest(),
        "edition_scope": "London 1874 title-page witness in PG34022 electronic HTML",
        "represented": ["title page", "contents", "dedication", "two parts", "ten chapters",
                        "twenty sections", "terminal note", "fifty-six linked endnotes"],
        "excluded": ["Project Gutenberg header", "Project Gutenberg footer"],
        "support": ["ZIP acquisition package", "cover favicon"],
        "converter_accounting": accounting,
    }
    provenance = {
        "contract": "ocd-newman-grammar-pg34022-provenance-v1",
        "work_id": "newman-grammar-of-assent",
        "source_sha256": sha256(source).hexdigest(),
        "candidate_status": "nonaccepted",
        "human_review": "not-recorded",
        "rights": "not-assessed-for-publication",
    }
    unresolved = {
        "id": "newman-grammar-pg34022-unresolved",
        "status": "unresolved",
        "items": ["Whole-work current CVW visual comparison is unrecorded.",
                  "Human acceptance and jurisdictional rights review remain separate."],
    }
    return {
        "content.tei.xml": content,
        "source-accountability.json": _canonical(account),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": _canonical(unresolved),
        "README.source.md": manifest.authority_path("source-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(manifest: SourceManifest, destination: str | Path) -> CandidatePackage:
    return reconstruct(manifest, destination, _convert)
