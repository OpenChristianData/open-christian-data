"""Reconcile only existing retained Green source/candidate/receipt authorities."""

from collections import Counter
import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import io_path, PipelineError
from ocd_kernel.projection.categories.prose import project_prose_document
from ocd_kernel.projection.native_content import project_content, content_policy
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "elisha-w-green-life-1888"
WORK = ROOT / "library/works" / WORK_ID
LOG = ROOT / "reports/_logs/green-current-reconciliation-20261002-v1"
HISTORICAL = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260930-docsouth-green-exact-v4/baseline/package")
SOURCE = ROOT / "raw/docsouth/l763-greenew-exact-1888/greenew.xml"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, raw):
    path = io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise FileExistsError(path)
    if not path.exists():
        path.write_bytes(raw)


def main():
    inputs = [WORK / "work.json", WORK / "state.json", WORK / "SOURCE_CREDIT.md", SOURCE]
    acquired_home = WORK / "forms/green-docsouth-retained/editions/green-docsouth-electronic/acquisitions"
    inputs += [acquired_home / p.name for p in io_path(acquired_home).glob("*.json")]
    homes = [ROOT / "sources/manifest-acquisitions/docsouth-l763-greenew-exact-1888"]
    for home in homes:
        inputs += [p for p in home.iterdir() if p.is_file()]
    receipts = ROOT / "plans/2026-09-23-acquisition-manifest-source-to-TEI/evidence"
    inputs += sorted(receipts.glob("L763_GREEN_*.json"))
    bindings = {p.relative_to(ROOT).as_posix(): digest(io_path(p).read_bytes()) for p in inputs}
    member_bindings = {}
    for path in HISTORICAL.iterdir():
        raw = path.read_bytes()
        save(LOG / "historical-package" / path.name, raw)
        member_bindings[path.name] = {"sha256": digest(raw), "bytes": len(raw)}
    candidate = LOG / "historical-package/content.tei.xml"
    raw = candidate.read_bytes()
    if digest(raw) != "82c3bb7c1e1f29bd071a037f4a6056170de2986fda690d3d381b5485ef11cc7d":
        raise ValueError("Known conserved Green TEI differs")
    if digest(SOURCE.read_bytes()) != "6d8808688dbbb7d50854aab4b11a6242f76b7ce9fe409066304daeda260d9417":
        raise ValueError("Known retained Green XML differs")
    tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    text = tree.find("{http://www.tei-c.org/ns/1.0}text")
    census = dict(Counter(etree.QName(n).localname for n in text.iter()))
    work = json.loads(io_path(WORK / "work.json").read_bytes())
    edition = work["textual_forms"][0]["editions"][0]
    identity = {"work_id": WORK_ID, "textual_form_id": "green-docsouth-retained", "edition_id": "green-docsouth-electronic", "acquisition_id": "green-docsouth-acquired"}
    probe = {}
    policy = content_policy()
    native_mismatches = []
    for node in text.iter():
        tag = etree.QName(node).localname
        rule = policy["elements"].get(tag)
        if rule is None:
            native_mismatches.append({"tag": tag, "attributes": dict(node.attrib), "reason": "unsupported element"})
    for part in text:
        try:
            project_content(ET.fromstring(etree.tostring(part)))
        except PipelineError as exc:
            native_mismatches.append({"section": etree.QName(part).localname, "reason": str(exc)})
    try:
        projected = project_prose_document(candidate, identity=identity, language="en", representation_revision="green-retained-native-technical-v1", edition_title=edition["title"])
        probe = {"status": "pass", "rows": len(projected["rows"])}
    except (ValueError, RuntimeError, PipelineError) as exc:
        probe = {"status": "rejected", "reason": str(exc), "exception": type(exc).__name__}
    result = {"status": "preflight-complete", "work_id": WORK_ID, "root": ROOT.as_posix(), "historical_package_path": HISTORICAL.as_posix(), "historical_package_members": member_bindings, "source_sha256": digest(SOURCE.read_bytes()), "tei_sha256": digest(raw), "native_text_census": census, "literal_heads": text.xpath('.//t:head//text()', namespaces=ns), "input_bindings": bindings, "projection_probe": probe, "native_content_mismatches": native_mismatches,
              "scope": "One complete retained electronic XML volume including front matter and complete body; no back in source. Three source-declared image URIs remain unretained, not omitted text or acquired binaries.",
              "latest_v6": "Saved Oct2 exact replay/mutation proof binds identical TEI to v4, current successor oracle. Temporary package host read ACL-denied/unknown, not absent. Durable v4 six-member package physically retained and exact-hash reused.",
              "ownership": "Root assigned canonical whole-work installation lane; peer acquisition lane L763/L764 is read-only reconciliation, confirmed by Root. No acquisition manifest/worktree changes."}
    if {p.relative_to(ROOT).as_posix(): digest(io_path(p).read_bytes()) for p in inputs} != bindings:
        raise ValueError("Current Green authority changed during read-only reconciliation")
    save(LOG / "preflight-native-probe.json", (json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    print(json.dumps({k: v for k, v in result.items() if k not in {"input_bindings", "historical_package_members", "literal_heads"}}, ensure_ascii=True))


if __name__ == "__main__":
    main()
