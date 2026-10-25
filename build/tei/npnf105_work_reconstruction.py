"""Reconstruct one source-attested NPNF105 div1 as an independent TEI work."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from build.tei import npnf105_reconstruction as aggregate
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.writer import stamp_header, tei_el


CONVERTER_ID = "ocd-npnf105-work-div1-to-tei"
CONVERTER_VERSION = "1"
SOURCE_URL = "https://www.ccel.org/ccel/schaff/npnf105.xml"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("contract") != "ocd-npnf105-work-profile-v1":
        raise ValueError("NPNF105 work profile changed")
    source = manifest.authority_path("retained-thml")
    if _sha(source.read_bytes()) != aggregate.SOURCE_SHA256:
        raise ValueError("NPNF105 retained source changed")
    divisions = aggregate._source_divisions(aggregate._parse(source))
    scope, work_id = profile["div1_id"], profile["work_id"]
    assigned = dict(aggregate.ASSIGNED)
    if assigned.get(scope) != work_id or scope == "xi":
        raise ValueError("NPNF105 work identity or selected scope changed")
    index = [key for key, _ in aggregate.ASSIGNED].index(scope)
    selected = divisions[9 + index]
    if (selected.get("id") != scope
            or selected.get("title") != profile["source_title"]
            or _sha(etree.tostring(selected, method="c14n")) != profile["source_div1_c14n_sha256"]
            or len([node for node in selected.iter() if isinstance(node.tag, str)]) != profile["feature_count"]):
        raise ValueError("NPNF105 source work boundary changed")
    root = manifest.repository_root
    if (_sha(Path(_io_path(root / "library/works" / work_id / "work.json")).read_bytes()) != profile["work_sha256"]
            or _sha(Path(_io_path(root / profile["acquisition_path"])).read_bytes()) != profile["acquisition_sha256"]):
        raise ValueError("NPNF105 work or acquisition changed")
    document = tei_el("TEI", {"xml:id": f"npnf105-{work_id}-electronic"})
    document.append(stamp_header(
        title=profile["source_title"], author="Augustine of Hippo",
        contributors=[
            {"name": "Philip Schaff", "role": "retained volume editor"},
            {"name": profile["translator"], "role": "retained source translator"},
            {"name": "Benjamin B. Warfield", "role": "translation reviser and introduction author"},
        ],
        source_url=SOURCE_URL, source_sha256=aggregate.SOURCE_SHA256,
        print_source="New York: Christian Literature Publishing Co., 1886 (retained title page; no print collation).",
        rights_statement="Retained header states Public Domain. CCEL permits ThML parsing; do not sell CCEL files or derivatives of its formatting. Publication rights require separate review.",
    ))
    body = tei_el("body", {"xml:id": f"npnf105-{work_id}-body"})
    rows: list[dict[str, object]] = [{} for _ in range(profile["feature_offset"])]
    aggregate._append_source_node(selected, body, rows, None)
    text = tei_el("text")
    text.append(body)
    document.append(text)
    content = etree.tostring(document, encoding="UTF-8", xml_declaration=True)
    accounting = {
        "contract": "ocd-npnf105-work-accounting-v1", "work_id": work_id,
        "source_path": "raw/ccel/npnf1/npnf105.xml", "source_sha256": aggregate.SOURCE_SHA256,
        "div1_id": scope, "source_title": profile["source_title"],
        "feature_offset": profile["feature_offset"], "feature_count": profile["feature_count"],
        "source_div1_c14n_sha256": profile["source_div1_c14n_sha256"],
        "tei_div_c14n_sha256": _sha(etree.tostring(body[0], method="c14n")),
        "translator": profile["translator"], "translator_evidence_id": profile["translator_evidence_id"],
        "outside_scope": "Volume front matter, shared contents, sibling works, and back matter remain in the retained XML.",
    }
    provenance = {
        "contract": "ocd-npnf105-work-provenance-v1", "status": "nonaccepted",
        "work_id": work_id, "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"], "div1_id": scope,
        "canonical_ir_written": False, "publication": "not-ready",
    }
    unresolved = [
        {"status": "unresolved", "item": "Close visual and human review have not occurred."},
        {"status": "unresolved", "item": "Print collation, rights clearance, and publication remain separate."},
    ]
    readme = (
        f"# {profile['source_title']} — NPNF1-05 electronic witness\n\n"
        f"Source: `raw/ccel/npnf1/npnf105.xml` (SHA-256 `{aggregate.SOURCE_SHA256}`), "
        f"complete direct `div1` `{scope}`. The retained source credits "
        f"{profile['translator']} as translator (`{profile['translator_evidence_id']}`). "
        "Philip Schaff is volume editor; Benjamin B. Warfield revised the translation "
        "and wrote the introduction. Sourced via CCEL.org. The retained electronic "
        "header states Public Domain; CCEL permits parsing ThML and says not to sell "
        "its files or derivatives of its formatting. This candidate is nonaccepted.\n"
    ).encode()
    return {"content.tei.xml": content, "source-accountability.json": _json(accounting),
            "provenance.json": _json(provenance),
            "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
            "README.source.md": readme}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
