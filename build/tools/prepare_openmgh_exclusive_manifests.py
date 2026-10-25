"""Prepare exact, per-work manifests for the openMGH exclusive-div route.

The existing scope preflight is discovery input only. This tool independently
checks the retained XML and installed sidecars before writing a source manifest.
It never creates accepted masters or reads ZIP bytes as text authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lxml import etree
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
PREFLIGHT = (
    ROOT / "plans/2026-09-22-source-preflight/openmgh-scope-preflight-20260925.json"
)
SOURCE_HOME = ROOT / "sources/openmgh-exclusive"
PRODUCER = "build/tei/openmgh_exclusive_reconstruction.py"
ORACLE = "build/tei/openmgh_exclusive_oracle.py"
CONTRACT = "ocd_kernel/reconstruction/contract.py"
LONG_PATH = "ocd_kernel/tei/install_accepted.py"
XSD = "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
PACKAGE_SCHEMA = "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _read(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _authority(name: str, relative: str, role: str) -> dict[str, object]:
    content = _read(ROOT / relative)
    return {
        "name": name,
        "path": relative,
        "role": role,
        "bytes": len(content),
        "sha256": _sha(content),
    }


def _write(path: Path, content: bytes, *, refresh: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != content and not refresh:
        raise ValueError(f"refusing to replace changed file without --refresh: {path}")
    path.write_bytes(content)


def _policy() -> dict[str, object]:
    return {
        "contract": "ocd-openmgh-exclusive-policy-v1",
        "status": "nonaccepted",
        "source_selection": "Two unique XML IDs must share one direct child div type=work; entire div copied without text or markup conversion.",
        "source_envelope": "One volume with only work div children; header availability and printed-volume bibliography copied; sibling works excluded.",
        "closure_inputs": [ORACLE, CONTRACT, LONG_PATH],
        "forbidden_oracle_imports": ["build.tei.openmgh_exclusive_reconstruction"],
        "checks": [
            "retained-xml-and-sidecar-hashes",
            "exclusive-work-boundary",
            "full-tree-text-and-attribute-equality",
            "tei-p5-xsd",
            "package-and-rights-accounting",
            "independent-oracle",
            "mutation-and-determinism",
        ],
    }


def _prepare(work_id: str, row: dict[str, object], *, refresh: bool) -> dict[str, str]:
    if row.get("scope_discovery") != "exclusive-enclosing-work-div":
        raise ValueError(f"{work_id} is not an exclusive-div discovery")
    locators = row.get("locators")
    if not isinstance(locators, list) or len(locators) < 2:
        raise ValueError(f"{work_id} needs two source locators")
    paths = {item["reference"].split("#", 1)[0] for item in locators}
    if len(paths) != 1:
        raise ValueError(f"{work_id} locators refer to different source files")
    source_path = paths.pop()
    if not source_path.endswith(".xml") or source_path.startswith("/"):
        raise ValueError("primary source must be extracted XML")
    source = _read(ROOT / source_path)
    if any(item.get("source_sha256") != _sha(source) for item in locators):
        raise ValueError(f"{work_id} source preflight hash drifted")
    work_rel = f"library/works/{work_id}/work.json"
    work = json.loads(_read(ROOT / work_rel))
    if work.get("work_id") != work_id:
        raise ValueError(f"{work_id} work sidecar identity drifted")
    editions = [
        (form, edition)
        for form in work.get("textual_forms", [])
        for edition in form.get("editions", [])
    ]
    if len(editions) != 1:
        raise ValueError(f"{work_id} requires one unambiguous edition")
    form, edition = editions[0]
    edition_id = edition["edition_id"]
    acquisition_ids = edition.get("acquisition_ids", [])
    if len(acquisition_ids) != 1:
        raise ValueError(f"{work_id} requires one acquisition")
    acquisition_id = acquisition_ids[0]
    acq_rel = f"library/works/{work_id}/forms/{form['textual_form_id']}/editions/{edition_id}/acquisitions/{acquisition_id}.json"
    acquisition = json.loads(_read(ROOT / acq_rel))
    master_path = (
        ROOT
        / f"library/works/{work_id}/forms/{form['textual_form_id']}/editions/{edition_id}/master.tei.xml"
    )
    if Path(_io_path(master_path)).exists():
        raise ValueError(f"{work_id} already has an accepted master")
    if (
        acquisition.get("source_path") != source_path
        or acquisition.get("source_sha256") != _sha(source)
        or acquisition.get("source_bytes") != len(source)
    ):
        raise ValueError(f"{work_id} installed acquisition does not bind XML")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True
    )
    source_root = etree.fromstring(source, parser=parser)
    if source_root.tag != f"{{{TEI}}}TEI" or source_root.getroottree().docinfo.doctype:
        raise ValueError(f"{work_id} source is not entity-free TEI")
    first_id = locators[0]["reference"].split("#", 1)[1]
    last_id = locators[-1]["reference"].split("#", 1)[1]
    resolved = []
    for xml_id in (first_id, last_id):
        matches = source_root.xpath(
            "//*[@xml:id=$id]", namespaces={"xml": XML}, id=xml_id
        )
        if len(matches) != 1:
            raise ValueError(f"{work_id} XML locator not unique: {xml_id}")
        resolved.append(
            next(
                (
                    n
                    for n in matches[0].iterancestors()
                    if n.tag == f"{{{TEI}}}div" and n.get("type") == "work"
                ),
                None,
            )
        )
    if resolved[0] is None or resolved[0] is not resolved[1]:
        raise ValueError(f"{work_id} locators do not share one work div")
    selected = resolved[0]
    volume = selected.getparent()
    if volume is None or volume.get("type") != "volume":
        raise ValueError(f"{work_id} has no enclosing volume")
    text = source_root.find(f"{{{TEI}}}text")
    body = text.find(f"{{{TEI}}}body") if text is not None else None
    works = list(volume)
    if (
        body is None
        or list(text) != [body]
        or list(body) != [volume]
        or any(
            node.tag != f"{{{TEI}}}div" or node.get("type") != "work" for node in works
        )
        or any((n.text or "").strip() for n in (text, body, volume))
    ):
        raise ValueError(
            f"{work_id} shared/front/back matter requires a different route"
        )
    ordinal = works.index(selected) + 1
    if any(
        item.get("enclosing_work_div", {}).get("attributes", {}).get("n")
        != selected.get("n")
        for item in locators
    ):
        raise ValueError(f"{work_id} preflight work label drifted")
    boundary_rel = f"sources/openmgh-exclusive/{work_id}/boundary-review.json"
    boundary_path = ROOT / boundary_rel
    if not boundary_path.is_file():
        raise ValueError(
            f"{work_id} needs an inspected whole-work boundary declaration"
        )
    boundary = json.loads(_read(boundary_path))
    expected_boundary = {
        "contract": "ocd-openmgh-exclusive-boundary-review-v1",
        "work_id": work_id,
        "scope_assertion": "whole-work-div",
        "review_status": "agent-inspected-source-boundary",
        "source_path": source_path,
        "source_sha256": _sha(source),
        "work_div_n": selected.get("n"),
        "start_xml_id": first_id,
        "end_xml_id": last_id,
    }
    if any(boundary.get(k) != v for k, v in expected_boundary.items()):
        raise ValueError(f"{work_id} inspected work boundary does not bind this source")
    readable = " ".join(" ".join(selected.itertext()).split())
    if (
        not isinstance(boundary.get("opening_evidence"), str)
        or not isinstance(boundary.get("closing_evidence"), str)
        or not readable.startswith(boundary["opening_evidence"])
        or not readable.endswith(boundary["closing_evidence"])
    ):
        raise ValueError(f"{work_id} inspected opening or ending drifted")
    profile = {
        "contract": "ocd-openmgh-exclusive-profile-v1",
        "work_id": work_id,
        "work_title": work["title"],
        "edition_id": edition_id,
        "acquisition_id": acquisition_id,
        "acquisition_path": acq_rel,
        "acquisition_sha256": _sha(_read(ROOT / acq_rel)),
        "source_path": source_path,
        "source_sha256": _sha(source),
        "work_div_n": selected.get("n"),
        "work_div_ordinal": ordinal,
        "volume_work_count": len(works),
        "start_xml_id": first_id,
        "end_xml_id": last_id,
        "preceding_work_n": works[ordinal - 2].get("n") if ordinal > 1 else None,
        "following_work_n": works[ordinal].get("n") if ordinal < len(works) else None,
    }
    profile_rel = f"sources/openmgh-exclusive/{work_id}/reconstruction-profile.json"
    _write(ROOT / profile_rel, _canonical(profile), refresh=refresh)
    closure = _sha(
        _canonical(
            [
                {"path": path, "sha256": _sha(_read(ROOT / path))}
                for path in (ORACLE, CONTRACT, LONG_PATH)
            ]
        )
    )
    authorities = [
        _authority("extracted-xml", source_path, "primary-source"),
        _authority("work-sidecar", work_rel, "work-identity-sidecar"),
        _authority("boundary-review", boundary_rel, "inspected-whole-work-boundary"),
        _authority(
            "reconstruction-profile", profile_rel, "complete-source-feature-profile"
        ),
        _authority(
            "validation-policy",
            "sources/openmgh-exclusive/validation-policy.json",
            "independent-validation-policy",
        ),
        _authority("tei-p5-xsd", XSD, "tei-validation-schema"),
        _authority(
            "candidate-package-schema", PACKAGE_SCHEMA, "candidate-package-schema"
        ),
    ]
    manifest = {
        "contract": "ocd-source-manifest-v1",
        "source_id": f"{work_id}-openmgh-exclusive-electronic-v1",
        "authorities": authorities,
        "converter": {
            "id": "ocd-openmgh-exclusive-div-to-tei",
            "version": "1",
            "callable": "_convert",
            "implementation_path": PRODUCER,
            "implementation_sha256": _sha(_read(ROOT / PRODUCER)),
        },
        "validator": {
            "id": "ocd-openmgh-exclusive-source-oracle",
            "version": "1",
            "callable": "_oracle",
            "implementation_path": ORACLE,
            "implementation_sha256": _sha(_read(ROOT / ORACLE)),
            "import_closure_sha256": closure,
        },
        "package_schema": {
            "path": PACKAGE_SCHEMA,
            "sha256": _sha(_read(ROOT / PACKAGE_SCHEMA)),
        },
    }
    manifest_rel = f"sources/openmgh-exclusive/{work_id}/source-manifest.json"
    _write(ROOT / manifest_rel, _canonical(manifest), refresh=refresh)
    return {
        "work_id": work_id,
        "manifest": manifest_rel,
        "source_sha256": _sha(source),
        "work_div_n": str(selected.get("n")),
        "work_div_ordinal": str(ordinal),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-id", action="append", required=True)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Replace this tool's own profile and manifest bytes after a reviewed implementation change",
    )
    args = parser.parse_args()
    rows = json.loads(PREFLIGHT.read_text(encoding="utf-8"))["works"]
    by_id = {item["work_id"]: item for item in rows}
    policy = _canonical(_policy())
    _write(SOURCE_HOME / "validation-policy.json", policy, refresh=args.refresh)
    results = []
    for work_id in args.work_id:
        if work_id not in by_id:
            raise ValueError(f"unknown openMGH work: {work_id}")
        results.append(_prepare(work_id, by_id[work_id], refresh=args.refresh))
    print(
        _canonical(
            {
                "contract": "ocd-openmgh-exclusive-manifest-preparation-v1",
                "works": results,
            }
        ).decode("utf-8"),
        end="",
    )


if __name__ == "__main__":
    main()
