"""Convert the retained ASV JSON to a source-bound reviewed-header TEI candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build.tei.asv_reconstruction import convert as _base_convert
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header

_BASE_TEI_SHA256 = "8ce811960861d254fd384403508ceb4af52772a0453f04a4256a161c0120150e"
_SCOPE = "complete retained ASV JSON electronic witness; no claim to complete physical 1901 print"
_IDENTITY = {"work_id": "asv", "textual_form_id": "english-asv", "edition_id": "retained-json", "acquisition_id": "scrollmapper-retained-json"}
_REVISION = {"id": "asv-reviewed-header-v1", "date": "2026-09-24", "note": "Acceptance identity and retained JSON source bindings added; original TEI text bytes are unchanged."}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _place_historical_description_in_bibl(derived: bytes, original: bytes) -> bytes:
    """Keep sourceDesc valid under the vendored P5 content model."""
    opening = b"<sourceDesc><p>"
    boundary = b"</p></sourceDesc>"
    bibl_open = b'<bibl xmlns="http://www.tei-c.org/ns/1.0">'
    if original.count(opening) != 1 or original.count(boundary) != 1 or derived.count(opening) != 1 or derived.count(bibl_open) != 1:
        raise ValueError("ASV source description is not the expected single paragraph and bibl")
    paragraph = original.split(opening, 1)[1].split(boundary, 1)[0]
    if b"<" in paragraph or b"&" in paragraph:
        raise ValueError("ASV historical source description needs explicit mixed-content handling")
    replaced = derived.replace(opening + paragraph + b"</p><bibl", b"<sourceDesc><bibl", 1)
    replaced = replaced.replace(bibl_open, bibl_open + b'<note type="historical-source-description">' + paragraph + b"</note>", 1)
    if replaced == derived or replaced.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("ASV reviewed header transform changed content outside the header")
    return replaced


def convert(manifest):
    manifest.verify()
    members = _base_convert(manifest)
    base = members["content.tei.xml"]
    if _sha(base) != _BASE_TEI_SHA256:
        raise ValueError("ASV base reconstruction differs from the source-reviewed TEI bytes")
    source_member = next(item for item in manifest.record["authorities"] if item["name"] == "asv-source")
    source = {"source_path": source_member["path"], "source_sha256": source_member["sha256"], "source_bytes": source_member["bytes"]}
    acquisition = json.loads(manifest.authority_path("asv-acquisition").read_bytes())
    if acquisition["retained_files"][0]["path"] != source["source_path"] or acquisition["retained_files"][0]["sha256"] != source["source_sha256"] or acquisition["retained_files"][0]["bytes"] != source["source_bytes"]:
        raise ValueError("ASV acquisition does not bind the exact primary source")
    bound = bind_reviewed_header(
        base,
        expected_sha256=_BASE_TEI_SHA256,
        identity=_IDENTITY,
        source=source,
        source_url=acquisition["url"],
        declared_scope=_SCOPE,
        revision=_REVISION,
    )
    members["content.tei.xml"] = _place_historical_description_in_bibl(bound, base)
    return members


convert.converter_id = "ocd-lib223-asv-reviewed-header-json-to-tei"
convert.converter_version = "2"
