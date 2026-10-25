"""Prepare eight source-bounded, nonaccepted bsb00000828 review candidates.

This command never changes library works, accepted masters, or corpus views.
Existing work-local evidence is immutable: a differing file is an error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000828/tei/bsb00000828.xml")
SOURCE_SHA = "698ce3c035506c19292c4af5121f133cd5bf033c11eda238d2ed2338f3c872bd"
HOME = Path("sources/openmgh-bsb828-held")
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb828-held-candidates-20260926.json")
PRODUCER = "build/tei/openmgh_bsb828_held_reconstruction.py"
ORACLE = "build/tei/openmgh_bsb828_held_oracle.py"
CONTRACT = "ocd_kernel/reconstruction/contract.py"
XSD = "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
PACKAGE_SCHEMA = "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
# The independently reviewed source decisions, in source division order.
# Child ranges are one-based and inclusive. A flat range counts direct ab children.
DECISIONS = {
    "de-ordinando-pontifice-gallic-author": (2, "whole-div", 1, 1, "prose",
        "The complete surviving electronic division is a fragment: its last sentence ends at 'ministerium suum' before the next work. It is not a claim that the historical work is complete."),
    "peter-damian-liber-gratissimus": (3, "ab-child-range", 17, 3634, "prose",
        "The tract begins at source line bsb00000828_00025_33. The separately titled 'Versus de symoniacis' at preceding lines 18–32 remains in the source volume and outside this work candidate."),
    "peter-damian-disceptatio-synodalis": (4, "whole-div", 1, 1, "prose",
        "The disputation includes its own closing invitation 'celeuma cantemus' and the immediately following 'Versus' coda; both remain inside this source work division."),
    "manegold-against-wolfelm-of-cologne": (9, "part-range", 1, 2, "prose",
        "Source part 1 is the separately titled letter against Wolfelm; part 2 is its 'Capitulacio sequencium' and continuation on philosophers. Parts 3 and 4 are separate works."),
    "manegold-to-gebhard": (9, "part-range", 3, 3, "prose",
        "Only the separately titled source part 'Manegoldus ad Gebehardum' is selected; the Wolfelm tract and Hugo verses remain outside."),
    "hugo-verses-against-manegold": (9, "part-range", 4, 4, "poetry",
        "Only the separately titled source part 'Versus Hugonis contra Manegoldum' is selected; the three preceding Manegold parts remain outside."),
    "dicta-cuiusdam-on-discord-between-pope-and-king": (11, "whole-div", 1, 1, "prose",
        "This is a composite electronic witness with source-labelled Paris, Vienna, and Brussels manuscript sections. They remain distinguishable in sequence; no single manuscript reading is asserted."),
    "osnabruck-t-letter-presenting-wido-excerpts": (12, "ab-child-range", 1, 39, "prose",
        "The presenting letter ends with 'Valete!' at bsb00000828_00472_24. The subsequent Wido excerpts begin at line 25 and remain outside this letter candidate."),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _put(path: Path, value: object) -> None:
    content = _canonical(value)
    target = _io_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != content:
        raise ValueError(f"refusing to replace changed evidence: {path}")
    target.write_bytes(content)


def _authority(name: str, relative: str, role: str) -> dict:
    path = ROOT / relative
    return {"name": name, "path": relative, "role": role,
            "bytes": _io_path(path).stat().st_size, "sha256": _sha(path)}


def prepare(candidate_home: Path) -> dict:
    if _sha(ROOT / SOURCE) != SOURCE_SHA:
        raise ValueError("extracted XML source changed")
    if _io_path(ROOT / BATCH).exists():
        raise ValueError("held-work batch already exists")
    candidate_home = candidate_home.resolve()
    retained_home = Path("D:/Library/Open Christian Data/candidate-reviews").resolve()
    if not candidate_home.is_relative_to(retained_home):
        raise ValueError("candidate home must be within durable candidate-reviews storage")
    candidate_home.mkdir(parents=True, exist_ok=True)
    source = etree.parse(str(_io_path(ROOT / SOURCE)), parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if source.docinfo.doctype:
        raise ValueError("source has a DOCTYPE")
    volume = source.getroot().find(f"{TEI}text/{TEI}body/{TEI}div")
    if volume is None or volume.get("type") != "volume" or len(volume) != 17:
        raise ValueError("17-work source envelope changed")
    policy_rel = (HOME / "validation-policy.json").as_posix()
    policy = {
        "contract": "ocd-openmgh-bsb828-held-policy-v1", "status": "nonaccepted",
        "source_selection": "Eight exact source-bound divisions, parts, or flat-ab child ranges; the extracted XML alone supplies text.",
        "closure_inputs": [ORACLE, CONTRACT],
        "forbidden_oracle_imports": ["build.tei.openmgh_bsb828_held_reconstruction"],
        "checks": ["retained-source-and-sidecar-hashes", "independent-work-boundary",
                   "source-tree-equality", "tei-p5-xsd", "candidate-package-integrity",
                   "mutation-and-determinism"],
    }
    _put(ROOT / policy_rel, policy)
    preflight = json.loads((ROOT / "plans/2026-09-22-source-preflight/openmgh-scope-preflight-20260925.json").read_bytes())
    by_id = {row["work_id"]: row for row in preflight["works"]}
    works = []
    for work_id, (ordinal, mode, start, stop, category, note) in DECISIONS.items():
        row = by_id[work_id]
        if not all(SOURCE.as_posix() in loc["reference"] and loc["source_sha256"] == SOURCE_SHA
                   for loc in row["locators"]):
            raise ValueError(f"discovery locator changed: {work_id}")
        work = volume[ordinal - 1]
        if mode == "ab-child-range":
            if len(work) != 1 or work[0].tag != f"{TEI}ab":
                raise ValueError(f"flat source envelope changed: {work_id}")
            children = list(work[0])
        else:
            children = list(work)
        if stop > len(children) or start < 1:
            raise ValueError(f"source child range changed: {work_id}")
        selected = children[start - 1:stop]
        first_id = next((n.get(XML_ID) for child in selected for n in child.iter() if n.get(XML_ID)), None)
        last_id = next((n.get(XML_ID) for child in reversed(selected)
                        for n in reversed(list(child.iter())) if n.get(XML_ID)), None)
        if first_id is None or last_id is None:
            raise ValueError(f"source range lacks XML IDs: {work_id}")
        work_rel = f"library/works/{work_id}/work.json"
        work_record = json.loads(_io_path(ROOT / work_rel).read_bytes())
        editions = [(form, edition) for form in work_record["textual_forms"] for edition in form["editions"]]
        if work_record["work_id"] != work_id or len(editions) != 1:
            raise ValueError(f"work sidecar identity changed: {work_id}")
        form, edition = editions[0]
        if len(edition.get("acquisition_ids", [])) != 1:
            raise ValueError(f"acquisition identity ambiguous: {work_id}")
        acquisition_id = edition["acquisition_ids"][0]
        acq_rel = (Path("library/works") / work_id / "forms" / form["textual_form_id"]
                   / "editions" / edition["edition_id"] / "acquisitions" / f"{acquisition_id}.json").as_posix()
        acquisition = json.loads(_io_path(ROOT / acq_rel).read_bytes())
        if acquisition.get("source_path") != SOURCE.as_posix() or acquisition.get("source_sha256") != SOURCE_SHA:
            raise ValueError(f"extracted acquisition identity changed: {work_id}")
        local = HOME / work_id
        boundary_rel = (local / "boundary-review.json").as_posix()
        readable = " ".join(" ".join(work.itertext()).split())
        boundary = {
            "contract": "ocd-openmgh-bsb828-held-boundary-v1", "work_id": work_id,
            "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
            "work_div_ordinal": ordinal, "work_div_n": work.get("n"),
            "selection_mode": mode, "child_start": start, "child_stop": stop,
            "first_selected_xml_id": first_id, "last_selected_xml_id": last_id,
            "preceding_work_n": volume[ordinal - 2].get("n") if ordinal > 1 else None,
            "following_work_n": volume[ordinal].get("n") if ordinal < 17 else None,
            "scope_note": note, "source_div_opening": readable[:120], "source_div_ending": readable[-120:],
            "candidate_status": "nonaccepted", "human_verification": "not-performed",
        }
        _put(ROOT / boundary_rel, boundary)
        profile_rel = (local / "reconstruction-profile.json").as_posix()
        profile = {
            "contract": "ocd-openmgh-bsb828-held-profile-v1", "work_id": work_id,
            "work_title": work_record["title"], "edition_id": edition["edition_id"],
            "acquisition_id": acquisition_id, "acquisition_path": acq_rel,
            "acquisition_sha256": _sha(ROOT / acq_rel), "source_path": SOURCE.as_posix(),
            "source_sha256": SOURCE_SHA, "work_div_ordinal": ordinal,
            "work_div_n": work.get("n"), "selection_mode": mode,
            "child_start": start, "child_stop": stop, "scope_note": note,
            "category": category, "language": "la",
        }
        _put(ROOT / profile_rel, profile)
        manifest_rel = (local / "source-manifest.json").as_posix()
        authorities = [
            _authority("extracted-xml", SOURCE.as_posix(), "primary-source"),
            _authority("work-sidecar", work_rel, "work-identity-sidecar"),
            _authority("boundary-review", boundary_rel, "inspected-work-boundary"),
            _authority("reconstruction-profile", profile_rel, "complete-source-feature-profile"),
            _authority("validation-policy", policy_rel, "independent-validation-policy"),
            _authority("tei-p5-xsd", XSD, "tei-validation-schema"),
            _authority("candidate-package-schema", PACKAGE_SCHEMA, "candidate-package-schema"),
        ]
        closure = hashlib.sha256(_canonical([{"path": rel, "sha256": _sha(ROOT / rel)}
                                            for rel in policy["closure_inputs"]])).hexdigest()
        manifest = {
            "contract": "ocd-source-manifest-v1", "source_id": f"{work_id}-openmgh-bsb828-held-v1",
            "authorities": authorities,
            "converter": {"id": "ocd-openmgh-bsb828-held-to-tei", "version": "1",
                          "callable": "_convert", "implementation_path": PRODUCER,
                          "implementation_sha256": _sha(ROOT / PRODUCER)},
            "validator": {"id": "ocd-openmgh-bsb828-held-source-oracle", "version": "1",
                          "callable": "_oracle", "implementation_path": ORACLE,
                          "implementation_sha256": _sha(ROOT / ORACLE),
                          "import_closure_sha256": closure},
            "package_schema": {"path": PACKAGE_SCHEMA, "sha256": _sha(ROOT / PACKAGE_SCHEMA)},
        }
        _put(ROOT / manifest_rel, manifest)
        candidate = candidate_home / work_id
        if not _io_path(candidate).exists():
            try:
                subprocess.run([sys.executable, "-m", "build.tools.reconstruct_candidate",
                                "--manifest", manifest_rel, "--destination", str(candidate),
                                "--repository-root", str(ROOT)], cwd=ROOT, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as exc:
                raise ValueError(f"candidate reconstruction failed for {work_id}: {exc.stderr}") from exc
        package = CandidatePackage.load(candidate / "package")
        validation = json.loads(_io_path(candidate / "validation.json").read_bytes())
        if validation.get("status") != "pass" or validation.get("findings") != []:
            raise ValueError(f"independent oracle or TEI XSD failed: {work_id}")
        files = {p.relative_to(_io_path(candidate)).as_posix(): _sha(p)
                 for p in _io_path(candidate).rglob("*") if p.is_file()}
        if len(files) != 7:
            raise ValueError(f"unexpected candidate file count: {work_id}")
        works.append({"work_id": work_id, "category": category, "source_path": SOURCE.as_posix(),
                      "source_sha256": SOURCE_SHA, "work_div_ordinal": ordinal,
                      "selection_mode": mode, "child_start": start, "child_stop": stop,
                      "boundary_review_path": boundary_rel, "boundary_review_sha256": _sha(ROOT / boundary_rel),
                      "manifest_path": manifest_rel, "manifest_sha256": _sha(ROOT / manifest_rel),
                      "profile_path": profile_rel, "profile_sha256": _sha(ROOT / profile_rel),
                      "acquisition_path": acq_rel, "acquisition_sha256": _sha(ROOT / acq_rel),
                      "candidate_root": candidate.as_posix(), "candidate_sha256": package.sha256,
                      "candidate_tei_sha256": files["package/content.tei.xml"],
                      "validation_sha256": files["validation.json"],
                      "validation_status": "pass", "acceptance_status": "nonaccepted",
                      "output_file_sha256": files})
    batch = {"contract": "ocd-openmgh-bsb828-held-candidate-batch-v1",
             "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
             "source_volume_work_div_count": 17, "identity_count": len(DECISIONS),
             "validated_candidate_count": len(works), "canonical_install": "none",
             "works": works}
    _put(ROOT / BATCH, batch)
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-home", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.candidate_home)
    print(json.dumps({"status": "validated-nonaccepted", "works": len(result["works"]),
                      "receipt": BATCH.as_posix(), "receipt_sha256": _sha(ROOT / BATCH)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
