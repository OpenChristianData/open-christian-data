"""Build the next four independent NPNF109 candidates from retained XML."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.npnf109_chrysostom_oracle import ASSIGNED, SOURCE_BYTES, SOURCE_HASH
from build.tei.npnf109_chrysostom_reconstruction import _convert as convert_volume
from build.tei.npnf109_work_oracle import _oracle
from build.tei.npnf109_work_reconstruction import _convert
from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("sources/structured-text/chrysostom-npnf109-16/work-bindings")
SOURCE = Path("raw/ccel/npnf1/npnf109.xml")
SOURCE_SHA = SOURCE_HASH
AGGREGATE_TEI_SHA = "38ace0cb485e8d88f8e6e4ab3ba108f21746db1d401416d7b722d0eab32f626a"
AGGREGATE_MANIFEST = Path("sources/structured-text/chrysostom-npnf109-16/npnf109-chrysostom.source-manifest.json")
AGGREGATE_PROFILE = Path("sources/structured-text/chrysostom-npnf109-16/npnf109-chrysostom.reconstruction-profile.json")
CONVERTER = Path("build/tei/npnf109_work_reconstruction.py")
ORACLE = Path("build/tei/npnf109_work_oracle.py")
SOURCE_RULES = Path("build/tei/npnf109_chrysostom_oracle.py")
SCHEMA = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
XSD = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
XSD_XML = Path("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd")
XSD_TEIX = Path("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd")
PERMISSION = Path("docs/sources/ccel-permission.md")
POLICY = HOME / "work-validation-policy.json"
BATCH = ASSIGNED[4:8]


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _bytes(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _read(path: Path) -> dict:
    value = json.loads(_bytes(path))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put_new(path: Path, value: bytes) -> None:
    actual = Path(_io_path(path))
    if actual.exists():
        if actual.read_bytes() != value:
            if not path.is_relative_to(ROOT / HOME):
                raise ValueError(f"existing NPNF109 work evidence differs: {path}")
            actual.write_bytes(value)
        return
    actual.parent.mkdir(parents=True, exist_ok=True)
    actual.write_bytes(value)


def _authority(path: Path, name: str, role: str) -> dict:
    content = _bytes(ROOT / path)
    return {"name": name, "path": path.as_posix(), "role": role,
            "bytes": len(content), "sha256": _sha(content)}


def prepare(destination: Path) -> dict:
    destination = destination.absolute()
    if (not destination.parent.is_dir() or ROOT in destination.parents
            or (destination.exists() and any(destination.iterdir()))):
        raise ValueError("candidate destination must be a fresh external child of an existing directory")
    source_bytes = _bytes(ROOT / SOURCE)
    if len(source_bytes) != SOURCE_BYTES or _sha(source_bytes) != SOURCE_HASH:
        raise ValueError("retained extracted XML changed")
    aggregate_manifest = SourceManifest.load(ROOT / AGGREGATE_MANIFEST, repository_root=ROOT)
    aggregate_manifest.verify()
    aggregate = convert_volume(aggregate_manifest)
    if _sha(aggregate["content.tei.xml"]) != AGGREGATE_TEI_SHA:
        raise ValueError("existing verified aggregate TEI changed")
    profile = _read(ROOT / AGGREGATE_PROFILE)
    if profile["assigned_div1"] != [root_id for root_id, _ in ASSIGNED]:
        raise ValueError("sixteen work roots changed")
    _put_new(ROOT / POLICY, _json({
        "contract": "ocd-npnf109-work-validation-policy-v1",
        "source_sha256": SOURCE_HASH,
        "aggregate_tei_sha256": AGGREGATE_TEI_SHA,
        "required_member_names": ["README.source.md", "content.tei.xml", "provenance.json",
                                  "source-accountability.json", "unresolved.jsonl", "manifest.json"],
        "source_selection": "One complete direct div1 child root with its native descendants.",
        "shared_volume_matter": "Title, preface, prolegomena, and indexes remain source-owned and hash-accounted.",
        "publication": "not_ready",
    }))
    source = etree.fromstring(source_bytes, etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    body = source.find("ThML.body")
    if body is None:
        raise ValueError("retained source body absent")
    roots = [node for node in body if isinstance(node.tag, str)]
    if [node.get("id") for node in roots] != ["i", "ii", "iii", *[row[0] for row in ASSIGNED], "xx", "xxi"]:
        raise ValueError("retained volume root sequence changed")
    outcomes = []
    destination.mkdir(exist_ok=True)
    for root_id, work_id in BATCH:
        selected = [node for node in roots if node.get("id") == root_id]
        if len(selected) != 1 or selected[0].tag != "div1":
            raise ValueError(f"source root changed: {root_id}")
        selected = selected[0]
        work_rel = Path("library/works") / work_id / "work.json"
        work = _read(ROOT / work_rel)
        if work.get("work_id") != work_id or len(work.get("textual_forms", [])) != 1:
            raise ValueError(f"work identity changed: {work_id}")
        form = work["textual_forms"][0]
        if len(form.get("editions", [])) != 1:
            raise ValueError(f"edition count changed: {work_id}")
        edition = form["editions"][0]
        if edition.get("containing_source", {}).get("locator") != f"{SOURCE.as_posix()}#{root_id}":
            raise ValueError(f"source locator changed: {work_id}")
        if len(edition.get("acquisition_ids", [])) != 1:
            raise ValueError(f"acquisition count changed: {work_id}")
        acquisition_id = edition["acquisition_ids"][0]
        acquisition_rel = (Path("library/works") / work_id / "forms" / form["textual_form_id"]
                           / "editions" / edition["edition_id"] / "acquisitions" / f"{acquisition_id}.json")
        acquisition = _read(ROOT / acquisition_rel)
        retained = acquisition.get("retained_files", [])
        if (len(retained) != 1 or retained[0].get("path") != SOURCE.as_posix()
                or retained[0].get("sha256") != SOURCE_HASH
                or retained[0].get("bytes") != SOURCE_BYTES):
            raise ValueError(f"acquisition retained-file route changed: {work_id}")
        binding = {
            "contract": "ocd-npnf109-work-binding-v1", "work_id": work_id,
            "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_HASH,
            "source_root_id": root_id, "source_title": selected.get("title"),
            "source_root_c14n_sha256": _sha(etree.tostring(selected, method="c14n")),
            "shared_root_ids": ["i", "ii", "iii", "xx", "xxi"],
            "textual_form_id": form["textual_form_id"], "edition_id": edition["edition_id"],
            "acquisition_id": acquisition_id, "aggregate_tei_sha256": AGGREGATE_TEI_SHA,
            "source_url": acquisition["url"],
            "work_path": work_rel.as_posix(), "work_sha256": _sha(_bytes(ROOT / work_rel)),
            "acquisition_path": acquisition_rel.as_posix(),
            "acquisition_sha256": _sha(_bytes(ROOT / acquisition_rel)),
        }
        home = HOME / work_id
        binding_rel = home / "work-binding.json"
        _put_new(ROOT / binding_rel, _json(binding))
        authorities = [
            _authority(SOURCE, "retained-thml", "primary-source"),
            _authority(binding_rel, "work-binding", "complete-source-feature-profile"),
            _authority(AGGREGATE_MANIFEST, "aggregate-source-manifest", "verified-aggregate-evidence"),
            _authority(AGGREGATE_PROFILE, "aggregate-profile", "complete-volume-source-accounting"),
            _authority(POLICY, "validation-policy", "independent-validation-policy"),
            _authority(SOURCE_RULES, "aggregate-source-oracle", "independent-source-mapping"),
            _authority(PERMISSION, "ccel-permission", "source-rights-evidence"),
            _authority(XSD, "tei-p5-xsd", "tei-validation-schema"),
            _authority(XSD_XML, "tei-p5-xml-xsd", "tei-validation-schema-dependency"),
            _authority(XSD_TEIX, "tei-p5-teix-xsd", "tei-validation-schema-dependency"),
            _authority(SCHEMA, "candidate-package-schema", "candidate-package-schema"),
        ]
        manifest_rel = home / "source-manifest.json"
        closure = _sha(_json([{"path": path.as_posix(), "sha256": _sha(_bytes(ROOT / path))}
                             for path in (ORACLE, SOURCE_RULES, Path("ocd_kernel/reconstruction/contract.py"))]))
        manifest_record = {
            "contract": "ocd-source-manifest-v1", "source_id": f"{work_id}-npnf109-native-root-v1",
            "ticket": "LIB-042", "authorities": authorities,
            "converter": {"id": "ocd-npnf109-work-root-to-tei", "version": "1", "callable": "_convert",
                          "implementation_path": CONVERTER.as_posix(),
                          "implementation_sha256": _sha(_bytes(ROOT / CONVERTER))},
            "validator": {"id": "ocd-npnf109-work-root-source-oracle", "version": "1", "callable": "_oracle",
                          "implementation_path": ORACLE.as_posix(),
                          "implementation_sha256": _sha(_bytes(ROOT / ORACLE)),
                          "import_closure_sha256": closure},
            "package_schema": {"path": SCHEMA.as_posix(), "sha256": _sha(_bytes(ROOT / SCHEMA))},
        }
        _put_new(ROOT / manifest_rel, _json(manifest_record))
        manifest = SourceManifest.load(ROOT / manifest_rel, repository_root=ROOT)
        candidate_root = destination / work_id
        candidate_root.mkdir()
        package = reconstruct(manifest, candidate_root / "package", _convert)
        report = validate(manifest, package, _oracle)
        if report.status != "pass" or report.findings:
            raise ValueError(f"independent work oracle failed: {work_id}: {report.findings}")
        report_record = {"contract": "ocd-validation-report-v1", "status": report.status,
                         "candidate_sha256": report.candidate_sha256,
                         "source_manifest_sha256": report.source_manifest_sha256,
                         "attestation": dict(report.attestation), "findings": list(report.findings)}
        (candidate_root / "validation.json").write_bytes(_json(report_record))
        outcomes.append({
            "work_id": work_id, "source_root_id": root_id,
            "manifest_path": manifest_rel.as_posix(), "manifest_sha256": manifest.sha256,
            "binding_path": binding_rel.as_posix(), "binding_sha256": _sha(_bytes(ROOT / binding_rel)),
            "candidate_root": str(candidate_root), "candidate_sha256": package.sha256,
            "candidate_tei_sha256": _sha(package.member_bytes("content.tei.xml")),
            "validation_sha256": _sha((candidate_root / "validation.json").read_bytes()),
            "validation_report_sha256": report.sha256,
        })
    receipt = {"contract": "ocd-npnf109-next-four-work-candidates-v1", "status": "validated-nonaccepted",
               "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_HASH,
               "aggregate_manifest_sha256": aggregate_manifest.sha256,
               "aggregate_tei_sha256": AGGREGATE_TEI_SHA,
               "work_count": len(outcomes), "works": outcomes}
    (destination / "receipt.json").write_bytes(_json(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    result = prepare(arguments.destination)
    print(json.dumps({"work_count": result["work_count"], "status": result["status"],
                      "receipt": str(arguments.destination.absolute() / "receipt.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
