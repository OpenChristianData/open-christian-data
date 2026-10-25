"""Inspect and reconstruct only source-defensible bsb00000829 work divisions.

The extracted XML is the text authority. This command writes work-local source
evidence and nonaccepted candidates; it never installs a master or updates views.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree

from build.tools.prepare_openmgh_exclusive_manifests import _prepare
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000829/tei/bsb00000829.xml")
SOURCE_SHA = "cb35385e4e4ba87f80a002452a527527866322af7ccea7f23f366735e46df989"
PREFLIGHT = Path("plans/2026-09-22-source-preflight/openmgh-scope-preflight-20260925.json")
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb829-inspected-batch-20260926.json")
SELECTED = {
    "altercatio-between-urban-and-clement": (2, "poetry"),
    "de-unitate-ecclesiae-conservanda": (3, "prose"),
    "deusdedit-against-invaders-and-simoniacs": (5, "prose"),
    "garcia-of-toledo-de-albino-et-rufino": (7, "prose"),
    "apologia-against-insults-to-married-priests": (8, "prose"),
    "clergy-of-liege-letter-against-paschal": (9, "prose"),
    "hugh-of-fleury-treatise-to-henry-of-england": (10, "prose"),
    "tractatus-de-investitura-episcoporum": (11, "prose"),
    "rangerius-liber-de-anulo-et-baculo": (12, "poetry"),
    "gregory-of-catino-orthodoxa-defensio-imperialis": (13, "prose"),
    "bruno-of-segni-sermon-on-simoniacs": (14, "prose"),
    "placidus-of-nonantola-liber-de-honore-ecclesiae": (16, "prose"),
    "rhythmus-de-captivitate-paschalis-papae": (20, "poetry"),
}
SPECIAL_HOLDS = {
    "disputatio-vel-defensio-paschalis-papae":
        "Division 18 ends within an unfinished word: 'se ipse po . . . .'; decide the fragment scope.",
    "lamentatio-pro-captione-paschalis-papae":
        "Division 19 also contains a separately titled Excusatio; select part-level boundaries.",
}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI = "{http://www.tei-c.org/ns/1.0}"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _put(path: Path, value: object) -> None:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    target = _io_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:
        raise ValueError(f"refusing to overwrite changed evidence: {path}")
    target.write_bytes(data)


def prepare(candidate_home: Path) -> dict:
    if _sha(ROOT / SOURCE) != SOURCE_SHA:
        raise ValueError("extracted bsb829 XML changed")
    if not _io_path(candidate_home.parent).is_dir():
        raise ValueError("candidate parent is absent")
    if _io_path(ROOT / BATCH).exists():
        raise ValueError("batch receipt already exists")
    preflight = json.loads(_io_path(ROOT / PREFLIGHT).read_bytes())
    rows = [row for row in preflight["works"] if any(
        SOURCE.as_posix() in locator["reference"] for locator in row.get("locators", [])
    )]
    by_id = {row["work_id"]: row for row in rows}
    if len(rows) != 63 or len(by_id) != 63 or not set(SELECTED).isdisjoint(SPECIAL_HOLDS):
        raise ValueError("declared bsb829 identity inventory changed")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    tree = etree.parse(str(_io_path(ROOT / SOURCE)), parser)
    if tree.docinfo.doctype:
        raise ValueError("source has a DOCTYPE")
    volume = tree.getroot().find(f"{TEI}text/{TEI}body/{TEI}div")
    if volume is None or volume.get("type") != "volume":
        raise ValueError("expected one source volume")
    divisions = list(volume)
    if len(divisions) != 21 or any(d.tag != f"{TEI}div" or d.get("type") != "work" for d in divisions):
        raise ValueError("source division envelope changed")
    index = {element.get(XML_ID): ordinal for ordinal, division in enumerate(divisions, 1)
             for element in division.iter() if element.get(XML_ID)}
    groups: dict[int, list[str]] = {ordinal: [] for ordinal in range(1, 22)}
    holds = dict(SPECIAL_HOLDS)
    for work_id, row in by_id.items():
        ordinals = {index.get(loc["reference"].split("#", 1)[-1]) for loc in row["locators"]}
        if len(ordinals) != 1 or None in ordinals:
            raise ValueError(f"unresolved declared locator: {work_id}")
        ordinal = ordinals.pop()
        groups[ordinal].append(work_id)
        if work_id not in SELECTED and work_id not in holds:
            holds[work_id] = f"Shared source division {ordinal}; select a work-local part or locator range."
    if len(holds) != 50 or set(holds) | set(SELECTED) != set(by_id):
        raise ValueError("selection does not account for every declared identity")
    if any(groups[n] != [work_id] for work_id, (n, _) in SELECTED.items()):
        raise ValueError("selected division is not exclusive")
    candidate_home.mkdir(exist_ok=True)
    works = []
    for work_id, (ordinal, category) in sorted(SELECTED.items(), key=lambda item: item[1][0]):
        row = by_id[work_id]
        division = divisions[ordinal - 1]
        first = row["locators"][0]["reference"].split("#", 1)[1]
        last = row["locators"][-1]["reference"].split("#", 1)[1]
        text = " ".join(" ".join(division.itertext()).split())
        local_ids = {node.get(XML_ID) for node in division.iter() if node.get(XML_ID)}
        targets = [node.get("target") for node in division.iter() if node.get("target")]
        external = [target for target in targets if not target.startswith("#") or target[1:] not in local_ids]
        if first not in local_ids or last not in local_ids or not text or external:
            raise ValueError(f"incomplete boundary or external target: {work_id}")
        boundary = {
            "contract": "ocd-openmgh-exclusive-boundary-review-v1",
            "work_id": work_id, "scope_assertion": "whole-work-div",
            "review_status": "agent-inspected-source-boundary",
            "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
            "work_div_n": division.get("n"), "work_div_ordinal": ordinal,
            "volume_work_count": len(divisions), "start_xml_id": first, "end_xml_id": last,
            "preceding_work_n": divisions[ordinal - 2].get("n") if ordinal > 1 else None,
            "following_work_n": divisions[ordinal].get("n") if ordinal < len(divisions) else None,
            "opening_evidence": text[:100], "closing_evidence": text[-100:],
            "source_top_level_children": [
                {"name": child.tag.split("}")[-1], "type": child.get("type"),
                 "opening": " ".join(" ".join(child.itertext()).split())[:80]}
                for child in division
            ],
            "local_fragment_reference_count": len(targets),
            "external_fragment_reference_count": len(external),
            "note": "The complete separately titled division is exclusive to this declared work; surrounding volume divisions remain outside its selected electronic witness.",
        }
        home = ROOT / "sources/openmgh-exclusive" / work_id
        _put(home / "boundary-review.json", boundary)
        _prepare(work_id, row, refresh=False)
        candidate = candidate_home / work_id
        if not _io_path(candidate).exists():
            subprocess.run(
                [sys.executable, "-m", "build.tools.reconstruct_candidate", "--manifest",
                 f"sources/openmgh-exclusive/{work_id}/source-manifest.json",
                 "--destination", str(candidate), "--repository-root", str(ROOT)],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
        package = CandidatePackage.load(candidate / "package")
        validation = json.loads(_io_path(candidate / "validation.json").read_bytes())
        if (validation.get("status") != "pass" or validation.get("findings") != []
                or validation.get("source_manifest_sha256") != _sha(home / "source-manifest.json")):
            raise ValueError(f"independent source oracle or XSD failed: {work_id}")
        accounting = json.loads(_io_path(candidate / "package/source-accountability.json").read_bytes())
        declaration = {
            "contract": "ocd-openmgh-inspected-acceptance-declaration-v1",
            "work_id": work_id, "category": category,
            "category_basis": ("The source division is a verse work, preserved as source-native TEI without inferred lines or stanzas."
                               if category == "poetry" else
                               "The selected source division is predominantly prose; source-native parts, quotations, and any incidental verse remain intact."),
            "boundary_review_sha256": _sha(home / "boundary-review.json"),
            "source_div_c14n_sha256": accounting["source_div_c14n_sha256"],
            "scope": f"The complete separately titled {work_id} division, ordinal {ordinal} of 21, in extracted openMGH bsb00000829 XML, including every source part, element, text node, page break, line break, and internal link. The other divisions and volume shell remain outside this electronic witness. No print collation or close visual review is claimed.",
        }
        _put(home / "acceptance-declaration.json", declaration)
        manifest = home / "source-manifest.json"
        profile = home / "reconstruction-profile.json"
        acquisition = Path(json.loads(_io_path(profile).read_bytes())["acquisition_path"])
        files = {p.relative_to(_io_path(candidate)).as_posix(): _sha(p)
                 for p in _io_path(candidate).rglob("*") if p.is_file()}
        if len(files) != 7:
            raise ValueError(f"unexpected candidate file count: {work_id}")
        works.append({
            "work_id": work_id, "work_title": json.loads(_io_path(ROOT / "library/works" / work_id / "work.json").read_bytes())["title"],
            "work_div_n": division.get("n"), "work_div_ordinal": ordinal,
            "volume_work_count": len(divisions), "start_xml_id": first, "end_xml_id": last,
            "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
            "work_sidecar_path": f"library/works/{work_id}/work.json",
            "work_sidecar_sha256": _sha(ROOT / "library/works" / work_id / "work.json"),
            "acquisition_path": acquisition.as_posix(), "acquisition_sha256": _sha(ROOT / acquisition),
            "boundary_review_path": (home / "boundary-review.json").relative_to(ROOT).as_posix(),
            "boundary_review_sha256": _sha(home / "boundary-review.json"),
            "manifest_path": manifest.relative_to(ROOT).as_posix(), "manifest_sha256": _sha(manifest),
            "profile_path": profile.relative_to(ROOT).as_posix(), "profile_sha256": _sha(profile),
            "candidate_root": candidate.as_posix(), "candidate_sha256": package.sha256,
            "candidate_tei_sha256": files["package/content.tei.xml"],
            "validation_status": "pass", "validation_sha256": files["validation.json"],
            "acceptance_status": "nonaccepted", "category": category,
            "output_file_sha256": files,
        })
    batch = {
        "contract": "ocd-openmgh-bsb829-inspected-batch-v1",
        "status": "13-validated-nonaccepted-50-work-holds",
        "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
        "source_bytes": _io_path(ROOT / SOURCE).stat().st_size,
        "source_volume_work_div_count": len(divisions),
        "inspected_identity_count": len(rows), "validated_candidate_count": len(works),
        "identity_hold_count": len(holds), "holds": dict(sorted(holds.items())),
        "works": works,
        "verification": {"each_candidate": "Independent complete-div oracle and TEI P5 XSD pass for exact extracted XML",
                         "candidate_file_count": 7 * len(works), "canonical_install": "none"},
    }
    _put(ROOT / BATCH, batch)
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-home", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.candidate_home)
    print(json.dumps({"candidates": len(result["works"]), "holds": len(result["holds"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
