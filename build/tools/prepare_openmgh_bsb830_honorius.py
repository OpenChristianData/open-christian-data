"""Bind two complete Honorius native parts to exact bsb830 work-local manifests."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml")
SOURCE_SHA = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
HOME = Path("sources/openmgh-bsb830-honorius")
SIDE_HOME = HOME
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb830-honorius-two-candidates-20260927.json")
BATCH_SHA = "22251b145fb30789c554ca9930e094ea0c8c9d16a0d1e4cf46cf98974a49fdbd"
RECEIPT = Path("raw/openmgh/bsb00000830/acquisition-receipt.json")
RECEIPT_SHA = "6937a8c05fc2c094ae1b9ab57f34fe639e77972877976474ba2513de0d8b885c"
PRODUCER = Path("build/tei/openmgh_bsb830_honorius_reconstruction.py")
ORACLE = Path("build/tei/openmgh_bsb830_honorius_oracle.py")
CONTRACT = Path("ocd_kernel/reconstruction/contract.py")
LONG_PATH = Path("ocd_kernel/tei/install_accepted.py")
XSD = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
SCHEMA = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORKS = {
    "honorius-de-apostatis": (2, "II. DE APOSTATIS.",
                               "ut lupi ab ovibus Dei repellantur."),
    "honorius-summa-gloria": (3, "III. SUMMA GLORIA.",
                                "EXPLICIT SUMMA GLORIA HONORII."),
}


def _read(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _sha(path: Path) -> str:
    return sha256(_read(path)).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_once(path: Path, content: bytes) -> None:
    target = Path(_io_path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError(f"existing Honorius evidence differs: {path}")
        return
    target.write_bytes(content)


def _authority(name: str, relative: Path, role: str) -> dict:
    data = _read(ROOT / relative)
    return {"name": name, "path": relative.as_posix(), "role": role,
            "bytes": len(data), "sha256": sha256(data).hexdigest()}


def prepare() -> dict:
    source = _read(ROOT / SOURCE)
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError("extracted bsb830 source changed")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False,
                             huge_tree=True)
    root = etree.fromstring(source, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE is forbidden")
    body = root.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1 or len(body[0]) != 29:
        raise ValueError("bsb830 source envelope changed")
    parent = body[0][3]
    parts = list(parent)
    if (parent.get("n") != "Libelli Hon. August. presb. et schol."
            or len(parts) != 3
            or any(p.tag != f"{TEI}div" or p.get("type") != "part" for p in parts)):
        raise ValueError("Honorius parent/part inventory changed")
    policy = {
        "contract": "ocd-openmgh-bsb830-honorius-policy-v1",
        "status": "nonaccepted",
        "source_selection": "Each selected work is one complete native part under volume work division 4, bounded by unique source XML IDs; the sibling first part remains unassigned.",
        "closure_inputs": [p.as_posix() for p in (ORACLE, CONTRACT, LONG_PATH)],
        "forbidden_oracle_imports": ["build.tei.openmgh_bsb830_honorius_reconstruction"],
        "checks": ["source-and-identity-hashes", "native-part-boundary", "complete-tree-equality",
                   "header-license-bibliography", "tei-p5-xsd", "independent-oracle"],
    }
    _write_once(ROOT / HOME / "validation-policy.json", _json(policy))
    rows = []
    for work_id, (ordinal, opening, closing) in WORKS.items():
        work_rel = Path("library/works") / work_id / "work.json"
        work = json.loads(_read(ROOT / work_rel))
        if work.get("work_id") != work_id:
            raise ValueError("installed work identity changed")
        forms = work["textual_forms"]
        if len(forms) != 1 or len(forms[0]["editions"]) != 1:
            raise ValueError("ambiguous Honorius edition")
        form = forms[0]
        edition = form["editions"][0]
        if len(edition.get("acquisition_ids", [])) != 1:
            raise ValueError("ambiguous Honorius acquisition")
        edition_id = edition["edition_id"]
        acquisition_id = edition["acquisition_ids"][0]
        acquisition_rel = (Path("library/works") / work_id / "forms" / form["textual_form_id"]
                           / "editions" / edition_id / "acquisitions" / f"{acquisition_id}.json")
        acquisition = json.loads(_read(ROOT / acquisition_rel))
        if acquisition.get("source_path") != SOURCE.as_posix() or acquisition.get("source_sha256") != SOURCE_SHA:
            raise ValueError("ZIP package or other source replaced extracted XML")
        locator = edition["containing_source"]["locator"].split("; ")
        if len(locator) != 2 or any(not item.startswith(SOURCE.as_posix() + "#") for item in locator):
            raise ValueError("source locator pair differs")
        first, last = (item.split("#", 1)[1] for item in locator)
        part = parts[ordinal - 1]
        native_ids = [node.get(XML_ID) for node in part.iter()
                      if (node.get(XML_ID) or "").startswith("bsb00000830_")]
        if not native_ids or (native_ids[0], native_ids[-1]) != (first, last):
            raise ValueError("locators do not span the complete native part")
        readable = " ".join(" ".join(part.itertext()).split())
        if not readable.startswith(opening) or not readable.endswith(closing):
            raise ValueError("part opening or ending differs")
        digest = sha256(etree.tostring(part, method="c14n", with_comments=True)).hexdigest()
        shared = "The containing Honorius collection label remains in the retained source; this work's title is represented in its header, while the selected complete part carries its own native heading."
        unassigned = "Part 1, De offendiculo, has a separate native heading but no selected work identity in this batch; it and the other sibling part remain in the retained source."
        boundary = {
            "contract": "ocd-openmgh-bsb830-honorius-boundary-v1", "work_id": work_id,
            "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
            "source_division_ordinal": 4, "source_part_ordinal": ordinal,
            "native_type": "part", "start_xml_id": first, "end_xml_id": last,
            "selection_c14n_sha256": digest, "shared_matter_disposition": shared,
            "unassigned_fragment_disposition": unassigned,
            "opening": opening, "closing": closing,
        }
        home = HOME / work_id
        boundary_rel = home / "boundary-review.json"
        profile_rel = home / "reconstruction-profile.json"
        manifest_rel = home / "source-manifest.json"
        _write_once(ROOT / boundary_rel, _json(boundary))
        profile = {
            "contract": "ocd-openmgh-bsb830-honorius-profile-v1", "work_id": work_id,
            "work_title": work["title"], "edition_id": edition_id,
            "acquisition_id": acquisition_id, "acquisition_path": acquisition_rel.as_posix(),
            "acquisition_sha256": _sha(ROOT / acquisition_rel),
            **{k: boundary[k] for k in ("source_path", "source_sha256", "source_division_ordinal",
                                        "source_part_ordinal", "native_type", "start_xml_id", "end_xml_id",
                                        "selection_c14n_sha256", "shared_matter_disposition",
                                        "unassigned_fragment_disposition")},
        }
        _write_once(ROOT / profile_rel, _json(profile))
        closure = [{"path": p.as_posix(), "sha256": _sha(ROOT / p)}
                   for p in (ORACLE, CONTRACT, LONG_PATH)]
        manifest = {
            "contract": "ocd-source-manifest-v1",
            "source_id": f"{work_id}-openmgh-bsb830-honorius-electronic-v1",
            "authorities": [
                _authority("extracted-xml", SOURCE, "primary-source"),
                _authority("work-sidecar", work_rel, "work-identity-sidecar"),
                _authority("boundary-review", boundary_rel, "inspected-native-part-boundary"),
                _authority("reconstruction-profile", profile_rel, "complete-source-feature-profile"),
                _authority("validation-policy", HOME / "validation-policy.json", "independent-validation-policy"),
                _authority("tei-p5-xsd", XSD, "tei-validation-schema"),
                _authority("candidate-package-schema", SCHEMA, "candidate-package-schema"),
            ],
            "converter": {"id": "ocd-openmgh-bsb830-honorius-part-to-tei", "version": "1",
                          "callable": "_convert", "implementation_path": PRODUCER.as_posix(),
                          "implementation_sha256": _sha(ROOT / PRODUCER)},
            "validator": {"id": "ocd-openmgh-bsb830-honorius-part-source-oracle", "version": "1",
                          "callable": "_oracle", "implementation_path": ORACLE.as_posix(),
                          "implementation_sha256": _sha(ROOT / ORACLE),
                          "import_closure_sha256": sha256(_json(closure)).hexdigest()},
            "package_schema": {"path": SCHEMA.as_posix(), "sha256": _sha(ROOT / SCHEMA)},
        }
        _write_once(ROOT / manifest_rel, _json(manifest))
        rows.append({"work_id": work_id, "part": ordinal, "boundary_sha256": _sha(ROOT / boundary_rel),
                     "manifest_sha256": _sha(ROOT / manifest_rel), "selection_c14n_sha256": digest})
    return {"contract": "ocd-openmgh-bsb830-honorius-preparation-v1", "works": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(prepare(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
