"""Split the ten source-attested NPNF104 div2 works into separate TEI candidates."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from build.tei import npnf104_lib038_reconstruction as aggregate
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.writer import stamp_header, tei_el


CONVERTER_ID = "ocd-npnf104-work-div2-to-tei"
CONVERTER_VERSION = "1"


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("contract") != "ocd-npnf104-work-profile-v1":
        raise ValueError("NPNF104 work profile changed")
    source = manifest.authority_path("retained-thml")
    tree = aggregate._parse(source)
    _top, selected = aggregate._structure(tree)
    pairs = dict(aggregate.ASSIGNED)
    scope = profile["div2_id"]
    work_id = profile["work_id"]
    if pairs.get(scope) != work_id:
        raise ValueError("NPNF104 work/division identity differs")
    index = [key for key, _ in aggregate.ASSIGNED].index(scope)
    node = selected[index]
    offset = sum(len(list(prior.iter())) for prior in selected[:index])
    if (offset != profile["feature_offset"]
            or len(list(node.iter())) != profile["feature_count"]
            or node.get("title") != profile["source_title"]
            or _sha(etree.tostring(node, method="c14n")) != profile["source_div2_c14n_sha256"]):
        raise ValueError("NPNF104 work source boundary differs")
    work = Path("library/works") / work_id / "work.json"
    acquisition = Path(profile["acquisition_path"])
    if (_sha(Path(_io_path(manifest.repository_root / work)).read_bytes()) != profile["work_sha256"]
            or _sha(Path(_io_path(manifest.repository_root / acquisition)).read_bytes())
               != profile["acquisition_sha256"]):
        raise ValueError("NPNF104 work/acquisition authority differs")
    root = tei_el("TEI", {"xml:id": f"npnf104-{work_id}-electronic"})
    root.append(stamp_header(
        title=profile["source_title"], author="Augustine of Hippo",
        contributors=[{"name": "Philip Schaff", "role": "retained volume editor"}],
        source_url="https://www.ccel.org/ccel/schaff/npnf104.xml",
        source_sha256=aggregate.SOURCE_SHA256,
        print_source="Retained NPNF1-04 CCEL XML electronic witness; no print collation.",
        rights_statement="The retained CCEL header states Public Domain. CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting. Human acceptance and publication remain absent.",
    ))
    body = tei_el("body", {"xml:id": f"npnf104-{work_id}-body"})
    # Keep the aggregate's stable feature numbering, allowing direct comparison
    # with its independently validated work subtree.
    rows: list[dict[str, object]] = [{} for _ in range(offset)]
    aggregate._append(node, body, rows, None, work_id, root_of_assigned_scope=True)
    text = tei_el("text")
    text.append(body)
    root.append(text)
    content = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    accounting = {
        "contract": "ocd-npnf104-work-accounting-v1", "work_id": work_id,
        "div2_id": scope, "source_path": aggregate.SOURCE_PATH,
        "source_sha256": aggregate.SOURCE_SHA256,
        "source_title": profile["source_title"], "feature_offset": offset,
        "feature_count": profile["feature_count"],
        "source_div2_c14n_sha256": profile["source_div2_c14n_sha256"],
        "tei_div_c14n_sha256": _sha(etree.tostring(body[0], method="c14n")),
        "outside_scope": "Volume front matter, wrapper headings, indexes, and nine sibling works remain in the retained source and aggregate accounting.",
    }
    provenance = {
        "contract": "ocd-npnf104-work-provenance-v1", "status": "nonaccepted",
        "work_id": work_id, "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"], "div2_id": scope,
        "aggregate_candidate_sha256": profile["aggregate_candidate_sha256"],
        "canonical_ir_written": False, "publication": "not-ready",
    }
    unresolved = [
        {"status": "unresolved", "item": "Close visual and human review have not occurred."},
        {"status": "unresolved", "item": "Shared volume matter stays outside this work; print collation, rights, and publication require separate review."},
    ]
    readme = (
        f"# {profile['source_title']} — NPNF1-04 source-bounded candidate\n\n"
        f"Source: `{aggregate.SOURCE_PATH}` (SHA-256 `{aggregate.SOURCE_SHA256}`), direct div2 `{scope}`.\n"
        "The volume title page credits Philip Schaff as editor. Work-level translator credits remain in the retained work heading and aggregate source-accounting evidence.\n"
        "Sourced via CCEL.org. The retained CCEL header states Public Domain; CCEL permits ThML parsing and says not to sell its files or derivatives of its formatting.\n"
    ).encode()
    return {"content.tei.xml": content, "source-accountability.json": _json(accounting),
            "provenance.json": _json(provenance),
            "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
            "README.source.md": readme}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
