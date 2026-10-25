"""Extract the Communion work from its validated four-division CCEL container.

The later Vindication and two mixed indexes remain accounted-for container
material. The complete retained XML stays bound in the private evidence child.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei import john_owen_lib050_oracle as oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/ccel/owen/communion.xml")
MANIFEST = Path("sources/structured-text/lib050-john-owen/john-owen-lib050.source-manifest.json")
PARENT = Path("D:/Library/Open Christian Data/candidate-reviews/lib050-communion-source-refresh-20260930-v2")
WORK_ID = "john-owen-communion"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI = "{http://www.tei-c.org/ns/1.0}"
SOURCE_TITLES = (
    "Of Communion with God the Father, Son and Holy Ghost",
    "A Vindication of Some Passages in a Discourse concerning Communion with God",
    "Indexes",
    "Indexes",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parse(content: bytes) -> etree._Element:
    return etree.fromstring(
        content,
        etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True),
    )


def _scope(source: bytes) -> tuple[etree._Element, list[dict[str, str]]]:
    root = _parse(source)
    body = root.find("ThML.body")
    if root.tag != "ThML" or body is None:
        raise PipelineError("Communion retained XML envelope differs")
    divisions = [child for child in body if isinstance(child.tag, str)]
    if ([node.tag for node in divisions] != ["div1"] * 4
            or [node.get("id") for node in divisions] != ["i", "ii", "iii", "iv"]
            or [node.get("title") for node in divisions] != list(SOURCE_TITLES)
            or [node.get("type") for node in divisions[:2]] != ["Work", "Work"]
            or divisions[0].find("div2[@type='Titlepage']") is None
            or divisions[1].find("div2[@type='Titlepage']") is None):
        raise PipelineError("Communion and sibling source divisions differ")
    first_pages = [node.get("n") for node in divisions[0].iter("pb")]
    sibling_pages = [node.get("n") for node in divisions[1].iter("pb")]
    if not first_pages or first_pages[-1] != "274" or not sibling_pages or sibling_pages[0] != "275":
        raise PipelineError("Communion printed boundary differs")
    for node in divisions[0].iter():
        if any("#ii" in value or value.startswith("ii.") for value in node.attrib.values()):
            raise PipelineError("Communion text has a link into the excluded sibling")
    return root, [
        {"id": node.get("id"), "title": node.get("title"), "disposition": (
            "included-work-text" if position == 0 else
            "excluded-sibling-work" if position == 1 else
            "excluded-mixed-container-index"
        )}
        for position, node in enumerate(divisions)
    ]


def extract(parent_xml: bytes, source_xml: bytes) -> tuple[bytes, list[dict[str, str]]]:
    """Return one scoped TEI and source-derived four-division accounting."""
    _, scope = _scope(source_xml)
    corpus = _parse(parent_xml)
    children = [node for node in corpus if node.tag == TEI + "TEI" and node.get(XML_ID) == WORK_ID]
    if corpus.tag != TEI + "teiCorpus" or len(children) != 1:
        raise PipelineError("one Communion child required in validated family candidate")
    document = deepcopy(children[0])
    readable = [node for node in document.iter(TEI + "div") if node.get("type") == "readable-transcription"]
    if len(readable) != 1 or [node.get(XML_ID) for node in readable[0]] != [
        f"{WORK_ID}--{key}" for key in ("i", "ii", "iii", "iv")
    ]:
        raise PipelineError("family candidate readable divisions differ")
    # A source-specific selection from an independently verified full family
    # candidate: the selected subtree is unchanged, including its descendants.
    first = etree.tostring(readable[0][0], method="c14n", with_comments=True)
    for node in list(readable[0])[1:]:
        readable[0].remove(node)
    if etree.tostring(readable[0][0], method="c14n", with_comments=True) != first:
        raise PipelineError("Communion readable subtree changed during selection")
    for node in document.iter():
        for value in node.attrib.values():
            if value.startswith(f"#{WORK_ID}--ii") or value.startswith(f"#{WORK_ID}--iii") or value.startswith(f"#{WORK_ID}--iv"):
                raise PipelineError("scoped Communion TEI links to excluded material")
    scoped_source = oracle._parse_source(source_xml)
    scoped_body = scoped_source.getroot().find("ThML.body")
    for node in list(scoped_body)[1:]:
        scoped_body.remove(node)
    member = document.find(TEI + "text/" + TEI + "body/" + TEI + "div")
    if member is None:
        raise PipelineError("Communion retained-source member is missing")
    oracle._verify_readable_transcription(
        scoped_source, oracle._records(scoped_source, "communion"), member, WORK_ID
    )
    return etree.tostring(document, encoding="UTF-8", xml_declaration=True) + b"\n", scope


def prepare(destination: Path) -> dict[str, object]:
    destination = destination.resolve(strict=False)
    candidate_home = PARENT.parent.resolve(strict=True)
    if destination.exists() or destination.parent != candidate_home or not destination.name.startswith("lib050-communion-work-local-"):
        raise PipelineError("destination must be a fresh Communion work-local candidate child")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(PARENT / "package")
    validation = json.loads((PARENT / "validation.json").read_bytes())
    if (validation.get("status") != "pass"
            or validation.get("candidate_sha256") != package.sha256
            or validation.get("source_manifest_sha256") != manifest.sha256):
        raise PipelineError("current LIB-050 candidate validation binding differs")
    acquisition_path = (ROOT / "library/works/john-owen-communion/forms/john-owen-communion-english/"
                        "editions/john-owen-communion-ccel-thml-electronic/acquisitions/"
                        "john-owen-communion-ccel-retained-xml.json")
    acquisition = json.loads(acquisition_path.read_bytes())
    source_xml = (ROOT / SOURCE).read_bytes()
    if (acquisition["source_path"] != SOURCE.as_posix()
            or acquisition["source_bytes"] != len(source_xml)
            or acquisition["source_sha256"] != _sha(source_xml)):
        raise PipelineError("Communion acquisition and retained XML differ")
    candidate, scope = extract(package.member_bytes("content.tei.xml"), source_xml)
    destination.mkdir()
    path = destination / "candidate.tei.xml"
    path.write_bytes(candidate)
    if errors := validate_file(path):
        raise PipelineError(f"scoped Communion TEI P5 failed: {errors[:3]}")
    receipt = {
        "contract": "ocd-lib050-communion-work-local-candidate-v1",
        "status": "nonaccepted",
        "work_id": WORK_ID,
        "source_path": SOURCE.as_posix(),
        "source_bytes": len(source_xml),
        "source_sha256": _sha(source_xml),
        "source_divisions": scope,
        "accepted_text_scope": "ThML.body/div1[@id='i'] through printed page 274",
        "excluded_container_scope": ["div1#ii", "div1#iii", "div1#iv"],
        "parent_candidate_sha256": package.sha256,
        "parent_package_manifest_sha256": _sha((PARENT / "package/manifest.json").read_bytes()),
        "source_manifest_sha256": manifest.sha256,
        "recorded_validation_sha256": _sha((PARENT / "validation.json").read_bytes()),
        "tei_sha256": _sha(candidate),
        "tei_bytes": len(candidate),
        "schema_status": "pass",
        "scoped_independent_oracle_status": "pass",
        "acceptance": "not-staged",
        "rights_clearance": "not-assessed",
        "publication": "not-authorized",
    }
    (destination / "receipt.json").write_bytes(
        (json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.destination), sort_keys=True))


if __name__ == "__main__":
    main()
