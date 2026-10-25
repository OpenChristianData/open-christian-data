"""Reconstruct one complete NPNF206 treatise from its retained div2."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from build.tei import npnf2_lib048_reconstruction as aggregate
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.writer import stamp_header, tei_el


CONVERTER_ID = "ocd-npnf206-treatise-div2-to-tei"
CONVERTER_VERSION = "1"
SOURCE_SHA256 = aggregate.SOURCES[0][3]


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("contract") != "ocd-npnf206-treatise-profile-v1":
        raise ValueError("NPNF206 treatise profile changed")
    scope, work_id = profile["div2_id"], profile["work_id"]
    assigned = {(key, root): work for key, root, work in aggregate.ASSIGNED if key == "npnf206" and root.startswith("vi.")}
    if assigned.get(("npnf206", scope)) != work_id:
        raise ValueError("NPNF206 treatise identity changed")
    source_path = manifest.authority_path("retained-thml")
    source = source_path.read_bytes()
    if _sha(source) != SOURCE_SHA256:
        raise ValueError("NPNF206 retained source changed")
    tree = aggregate._parse(source_path)
    matches = tree.xpath("//*[@id=$source_id]", source_id=scope)
    if len(matches) != 1 or matches[0].tag != "div2" or matches[0].getparent().get("id") != "vi":
        raise ValueError("NPNF206 source-native treatise boundary changed")
    node = matches[0]
    if (len(list(node.iter())) != profile["feature_count"]
            or node.get("title") != profile["source_title"]
            or _sha(etree.tostring(node, method="c14n")) != profile["source_div2_c14n_sha256"]):
        raise ValueError("NPNF206 source subtree changed")
    work_rel = Path("library/works") / work_id / "work.json"
    acquisition_rel = Path(profile["acquisition_path"])
    if (_sha(Path(_io_path(manifest.repository_root / work_rel)).read_bytes()) != profile["work_sha256"]
            or _sha(Path(_io_path(manifest.repository_root / acquisition_rel)).read_bytes()) != profile["acquisition_sha256"]):
        raise ValueError("NPNF206 work or acquisition authority changed")
    policy = json.loads(manifest.authority_path("aggregate-validation-policy").read_bytes())
    exceptions = aggregate._reference_exception_map(policy)
    root = tei_el("TEI", {"xml:id": f"npnf206-{work_id}-electronic"})
    root.append(stamp_header(
        title=profile["source_title"], author="Jerome",
        contributors=[{"name": "Philip Schaff", "role": "retained volume series editor"},
                      {"name": "Henry Wace", "role": "retained volume series editor"}],
        source_url="https://www.ccel.org/ccel/schaff/npnf206.xml",
        source_sha256=SOURCE_SHA256,
        print_source="Retained NPNF2-06 CCEL XML electronic witness; no print collation.",
        rights_statement="The retained CCEL header states Public Domain. Human acceptance, rights clearance, and publication remain separate.",
    ))
    text = tei_el("text")
    body = tei_el("body", {"xml:id": f"npnf206-{work_id}-body"})
    rows: list[dict] = [{} for _ in range(profile["feature_offset"])]
    aggregate._append(node, body, "npnf206", rows, None, work_id, exceptions, scope)
    text.append(body)
    root.append(text)
    content = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    accounting = {
        "contract": "ocd-npnf206-treatise-accounting-v1", "work_id": work_id,
        "div2_id": scope, "source_path": aggregate.SOURCES[0][1], "source_sha256": SOURCE_SHA256,
        "source_title": profile["source_title"], "feature_offset": profile["feature_offset"],
        "feature_count": profile["feature_count"],
        "source_div2_c14n_sha256": profile["source_div2_c14n_sha256"],
        "tei_div_c14n_sha256": _sha(etree.tostring(body[0], method="c14n")),
        "outside_scope": "Title pages, translator's preface, prolegomena, 150 distinct letters, treatise wrapper, sibling treatises, prefaces, and indexes remain in retained source and aggregate accounting.",
    }
    provenance = {
        "contract": "ocd-npnf206-treatise-provenance-v1", "status": "nonaccepted",
        "work_id": work_id, "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"], "div2_id": scope,
        "aggregate_candidate_sha256": profile["aggregate_candidate_sha256"],
        "canonical_ir_written": False, "publication": "not-ready",
    }
    unresolved = [
        {"status": "unresolved", "item": "Close visual and human review have not occurred."},
        {"status": "unresolved", "item": "The 150 separately numbered Letters need constituent identities; shared volume matter, print collation, rights, and publication remain separate."},
    ]
    readme = (
        f"# {profile['source_title']} — NPNF2-06 source-bounded candidate\n\n"
        f"Source: `{aggregate.SOURCES[0][1]}` (SHA-256 `{SOURCE_SHA256}`), direct div2 `{scope}`.\n"
        "The retained title page and translator's preface supply volume-level credits; no unsupported constituent allocation is inferred.\n"
        "Sourced via CCEL.org. The retained CCEL header states Public Domain; this is not a rights or publication decision.\n"
    ).encode()
    return {"content.tei.xml": content, "source-accountability.json": _json(accounting),
            "provenance.json": _json(provenance),
            "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
            "README.source.md": readme}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
