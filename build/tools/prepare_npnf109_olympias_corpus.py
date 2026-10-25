"""Build a nonaccepted six-letter TEI corpus for the existing Olympias collection."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.npnf109_chrysostom_oracle import SOURCE_BYTES, SOURCE_HASH
from build.tei.npnf109_olympias_corpus import _convert
from build.tei.npnf109_olympias_corpus_oracle import _oracle
from build.tei.npnf109_work_reconstruction import _convert as convert_work
from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("sources/structured-text/chrysostom-npnf109-16/olympias-corpus")
WORK_ID = "chrysostom-letters-to-olympias"
SOURCE = Path("raw/ccel/npnf1/npnf109.xml")
SOURCE_SHA = SOURCE_HASH
AGGREGATE_MANIFEST = Path("sources/structured-text/chrysostom-npnf109-16/npnf109-chrysostom.source-manifest.json")
AGGREGATE_PROFILE = Path("sources/structured-text/chrysostom-npnf109-16/npnf109-chrysostom.reconstruction-profile.json")
OLD_MANIFEST = Path("sources/structured-text/chrysostom-npnf109-16/work-bindings") / WORK_ID / "source-manifest.json"
OLD_BINDING = OLD_MANIFEST.parent / "work-binding.json"
BINDING = HOME / "collection-binding.json"
POLICY = HOME / "validation-policy.json"
MANIFEST = HOME / "source-manifest.json"
CONVERTER = Path("build/tei/npnf109_olympias_corpus.py")
ORACLE = Path("build/tei/npnf109_olympias_corpus_oracle.py")
SOURCE_RULES = Path("build/tei/npnf109_chrysostom_oracle.py")
WORK_ORACLE = Path("build/tei/npnf109_work_oracle.py")
SCHEMA = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
XSD = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
PERMISSION = Path("docs/sources/ccel-permission.md")


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _bytes(relative: Path) -> bytes:
    return Path(_io_path(ROOT / relative)).read_bytes()


def _put(relative: Path, content: bytes) -> None:
    if not relative.is_relative_to(HOME):
        raise ValueError("Olympias evidence write escaped its home")
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _authority(relative: Path, name: str, role: str) -> dict:
    content = _bytes(relative)
    return {"name": name, "path": relative.as_posix(), "role": role,
            "bytes": len(content), "sha256": _sha(content)}


def prepare(destination: Path) -> dict:
    destination = destination.absolute()
    if (not destination.parent.is_dir() or ROOT in destination.parents
            or (destination.exists() and any(destination.iterdir()))):
        raise ValueError("Olympias candidate destination must be a fresh external child")
    raw = _bytes(SOURCE)
    if len(raw) != SOURCE_BYTES or _sha(raw) != SOURCE_HASH:
        raise ValueError("retained NPNF109 XML changed")
    old_manifest = SourceManifest.load(ROOT / OLD_MANIFEST, repository_root=ROOT)
    old_manifest.verify()
    old = convert_work(old_manifest)["content.tei.xml"]
    old_binding = json.loads(_bytes(OLD_BINDING))
    if old_binding["source_root_id"] != "xvii" or old_binding["work_id"] != WORK_ID:
        raise ValueError("old Olympias work binding changed")
    source = etree.fromstring(raw, etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True,
    ))
    body = source.find("ThML.body")
    if body is None:
        raise ValueError("retained NPNF109 body missing")
    roots = list(body)
    selected = next(node for node in roots if node.get("id") == "xvii")
    children = list(selected)
    if [node.get("id") for node in children] != ["xvii.i", "xvii.ii", "xvii.iii", "xvii.iv", "xvii.v", "xvii.vi", "xvii.vii", "xvii.viii"]:
        raise ValueError("Olympias source children changed")
    introduction = " ".join(" ".join(children[1].itertext()).split())
    added_prefix = " ".join(" ".join(children[-1][0].itertext()).split())
    if ("to whom seventeen of Chrysostom" not in introduction
            or "The following letter is added as a specimen" not in added_prefix
            or "Chrysostom wrote to his intimate" not in added_prefix):
        raise ValueError("Olympias collection or added-letter attribution changed")
    shared = [
        {"source_root_id": identifier, "source_title": node.get("title"),
         "source_c14n_sha256": _sha(etree.tostring(node, method="c14n")),
         "disposition": "retained-volume-matter-outside-child-body"}
        for identifier in ("i", "ii", "iii", "xx", "xxi")
        for node in roots if node.get("id") == identifier
    ]
    if len(shared) != 5:
        raise ValueError("shared volume roots changed")
    notes = (
        *(["The retained collection identifies this as John Chrysostom's letter to Olympias."] * 5),
        "The retained editorial prefix identifies this as Chrysostom's added letter to four Antioch presbyters, outside the five Olympias addressees.",
    )
    authors = ("John Chrysostom",) * 6
    binding = {
        "contract": "ocd-npnf109-olympias-corpus-binding-v1", "work_id": WORK_ID,
        "textual_form_id": old_binding["textual_form_id"],
        "edition_id": old_binding["edition_id"], "acquisition_id": old_binding["acquisition_id"],
        "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_HASH,
        "source_url": old_binding["source_url"], "source_title": selected.get("title"),
        "source_root_c14n_sha256": _sha(etree.tostring(selected, method="c14n")),
        "children": {node.get("id"): _sha(etree.tostring(node, method="c14n")) for node in children},
        "letters": [
            {"source_id": node.get("id"), "title": node.get("title"), "author": author,
             "attribution_note": note}
            for node, author, note in zip(children[2:], authors, notes, strict=True)
        ],
        "shared_volume_roots": shared,
        "old_work_tei_sha256": _sha(old),
        "work_path": old_binding["work_path"], "work_sha256": _sha(_bytes(Path(old_binding["work_path"]))),
        "acquisition_path": old_binding["acquisition_path"],
        "acquisition_sha256": _sha(_bytes(Path(old_binding["acquisition_path"]))),
    }
    _put(BINDING, _json(binding))
    _put(POLICY, _json({
        "contract": "ocd-npnf109-olympias-corpus-policy-v1", "source_sha256": SOURCE_HASH,
        "required_member_names": ["README.source.md", "content.tei.xml", "provenance.json",
                                  "source-accountability.json", "unresolved.jsonl", "manifest.json"],
        "source_selection": "The complete retained div1#xvii, split into five Olympias letters and one added Antioch letter; collection front matter and editorial prefixes occur exactly once.",
        "publication": "not_ready",
    }))
    authorities = [
        _authority(SOURCE, "retained-thml", "primary-source"),
        _authority(BINDING, "olympias-binding", "complete-source-feature-profile"),
        _authority(POLICY, "olympias-policy", "independent-validation-policy"),
        _authority(OLD_MANIFEST, "old-work-manifest", "verified-whole-root-evidence"),
        _authority(SOURCE_RULES, "aggregate-source-oracle", "independent-source-mapping"),
        _authority(WORK_ORACLE, "work-source-oracle", "independent-source-mapping"),
        _authority(PERMISSION, "ccel-permission", "source-rights-evidence"),
        _authority(XSD, "tei-p5-xsd", "tei-validation-schema"),
        _authority(Path("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd"), "tei-p5-xml-xsd", "tei-validation-schema-dependency"),
        _authority(Path("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"), "tei-p5-teix-xsd", "tei-validation-schema-dependency"),
        _authority(SCHEMA, "candidate-package-schema", "candidate-package-schema"),
    ]
    closure = _sha(_json([{"path": path.as_posix(), "sha256": _sha(_bytes(path))}
                         for path in (ORACLE, SOURCE_RULES, WORK_ORACLE, Path("ocd_kernel/reconstruction/contract.py"))]))
    _put(MANIFEST, _json({
        "contract": "ocd-source-manifest-v1", "source_id": "npnf109-olympias-six-letter-corpus-v1",
        "ticket": "LIB-042", "authorities": authorities,
        "converter": {"id": "ocd-npnf109-olympias-six-letter-corpus", "version": "1", "callable": "_convert",
                      "implementation_path": CONVERTER.as_posix(), "implementation_sha256": _sha(_bytes(CONVERTER))},
        "validator": {"id": "ocd-npnf109-olympias-six-letter-source-oracle", "version": "1", "callable": "_oracle",
                      "implementation_path": ORACLE.as_posix(), "implementation_sha256": _sha(_bytes(ORACLE)),
                      "import_closure_sha256": closure},
        "package_schema": {"path": SCHEMA.as_posix(), "sha256": _sha(_bytes(SCHEMA))},
    }))
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    destination.mkdir(exist_ok=True)
    package = reconstruct(manifest, destination / "package", _convert)
    report = validate(manifest, package, _oracle)
    if report.status != "pass" or report.findings:
        raise ValueError(f"Olympias source oracle failed: {report.findings}")
    validation = {"contract": "ocd-validation-report-v1", "status": report.status,
                  "candidate_sha256": report.candidate_sha256,
                  "source_manifest_sha256": report.source_manifest_sha256,
                  "attestation": dict(report.attestation), "findings": list(report.findings),
                  "report_sha256": report.sha256}
    (destination / "validation.json").write_bytes(_json(validation))
    receipt = {
        "contract": "ocd-npnf109-olympias-corpus-candidate-v1", "status": "validated-nonaccepted",
        "work_id": WORK_ID, "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_HASH,
        "source_root_id": "xvii", "source_root_c14n_sha256": binding["source_root_c14n_sha256"],
        "manifest_path": MANIFEST.as_posix(), "manifest_sha256": manifest.sha256,
        "binding_path": BINDING.as_posix(), "binding_sha256": _sha(_bytes(BINDING)),
        "candidate_sha256": package.sha256, "candidate_tei_sha256": _sha(package.member_bytes("content.tei.xml")),
        "validation_sha256": _sha((destination / "validation.json").read_bytes()),
        "validation_report_sha256": report.sha256,
        "letter_count": 6, "publication": "not_ready",
    }
    (destination / "receipt.json").write_bytes(_json(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = prepare(args.destination)
    print(json.dumps({"status": result["status"], "letter_count": result["letter_count"],
                      "receipt": str(args.destination.absolute() / "receipt.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
