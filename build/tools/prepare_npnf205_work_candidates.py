"""Package fourteen exact Gregory NPNF2-05 work roots from retained XML."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree

from ocd_kernel.projection.categories.native_documents import verify_document
from ocd_kernel.projection.categories.prose import project_prose_document
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
HOME = Path("sources/structured-text/gregory-nyssa-npnf205-works")
SOURCE = Path("raw/ccel/npnf2/npnf205.xml")
SOURCE_SHA = "43e87ed232457fd2d5862f72dd2d5d84fe1e8b69f4c3eec839bad04579327bf3"
SOURCE_URL = "https://www.ccel.org/ccel/schaff/npnf205.xml"
POLICY = HOME / "validation-policy.json"
PLAN = HOME / "selection-plan.json"
LEGACY_POLICY = Path("sources/structured-text/gregory-nyssa-npnf205/gregory-nyssa-npnf205.validation-policy.json")
CONVERTER = Path("build/tei/npnf205_work_reconstruction.py")
ORACLE = Path("build/tei/npnf205_work_oracle.py")
LEGACY_MAPPER = Path("build/tei/npnf2_lib047_reconstruction.py")
LEGACY_ORACLE = Path("build/tei/npnf2_lib047_oracle.py")
SCHEMA = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
XSD = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
CONTRACT = Path("ocd_kernel/reconstruction/contract.py")
VALIDATE = Path("ocd_kernel/tei/validate.py")
ATTRIBUTION = Path("sources/structured-text/gregory-nyssa-npnf205/README.md")
PERMISSION = Path("docs/sources/ccel-permission.md")
WORKS = (
    ("viii.ii", "gregory-of-nyssa-answer-to-eunomius-second-book", "viii"),
    ("viii.iii", "gregory-of-nyssa-on-the-holy-spirit", "viii"),
    ("viii.iv", "gregory-of-nyssa-on-the-holy-trinity", "viii"),
    ("viii.v", "gregory-of-nyssa-not-three-gods", "viii"),
    ("viii.vi", "gregory-of-nyssa-on-the-faith", "viii"),
    ("ix.ii", "gregory-of-nyssa-on-virginity", "ix"),
    ("ix.iii", "gregory-of-nyssa-on-infants-early-deaths", "ix"),
    ("ix.iv", "gregory-of-nyssa-on-pilgrimages", "ix"),
    ("x.ii", "gregory-of-nyssa-on-the-making-of-man", "x"),
    ("x.iii", "gregory-of-nyssa-on-the-soul-and-resurrection", "x"),
    ("xi.ii", "gregory-of-nyssa-great-catechism", "xi"),
    ("xii.ii", "gregory-of-nyssa-funeral-oration-on-meletius", "xii"),
    ("xii.iii", "gregory-of-nyssa-on-the-baptism-of-christ", "xii"),
    ("xiii", "gregory-of-nyssa-letters", None),
)


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put_owned(path: Path, data: bytes, *, refresh: bool) -> None:
    actual = Path(_io_path(path))
    actual.parent.mkdir(parents=True, exist_ok=True)
    if actual.exists() and actual.read_bytes() != data and not refresh:
        raise ValueError(f"existing source evidence differs: {path}")
    actual.write_bytes(data)


def _authority(path: Path, name: str, role: str) -> dict:
    actual = Path(_io_path(ROOT / path))
    return {"name": name, "path": path.as_posix(), "role": role,
            "bytes": actual.stat().st_size, "sha256": _sha(ROOT / path)}


def _source() -> tuple[bytes, etree._Element, etree._Element]:
    if _sha(ROOT / SOURCE) != SOURCE_SHA:
        raise ValueError("retained NPNF2-05 source hash changed")
    data = Path(_io_path(ROOT / SOURCE)).read_bytes()
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_comments=False, remove_pis=False, huge_tree=True)
    root = etree.fromstring(data, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE is forbidden")
    body = root.find("ThML.body")
    if body is None or len(body) != 16:
        raise ValueError("NPNF2-05 source envelope changed")
    return data, root, body


def _selection_plan(root: etree._Element, body: etree._Element) -> dict:
    entries = []
    selected = set()
    for source_id, work_id, parent_id in WORKS:
        matches = root.xpath("//*[@id=$scope]", scope=source_id)
        if len(matches) != 1:
            raise ValueError(f"source root absent or repeated: {source_id}")
        node = matches[0]
        parent = node.getparent()
        if (parent is None or parent.get("id") != parent_id
                or (parent_id is None and parent is not body)
                or (parent_id is not None and (node.tag != "div2" or parent.getparent() is not body))):
            raise ValueError(f"source parent boundary changed: {source_id}")
        selected.add(source_id)
        entries.append({"work_id": work_id, "source_root_id": source_id,
                        "source_parent_id": parent_id, "source_tag": node.tag,
                        "source_title": node.get("title"),
                        "element_count": len(list(node.iter())),
                        "source_xml_id_count": sum(bool(x.get("id")) for x in node.iter()),
                        "source_root_c14n_sha256": sha256(etree.tostring(node, method="c14n")).hexdigest(),
                        "native_source_ordinal": list(parent).index(node) + 1})
    by_scope = {scope: work for scope, work, _parent in WORKS}
    envelope = []
    non_elements = []
    for node in body:
        if not isinstance(node.tag, str):
            non_elements.append({"source_ordinal": list(body).index(node) + 1,
                                 "node_kind": "comment" if isinstance(node, etree._Comment)
                                 else "processing-instruction",
                                 "serialized_sha256": sha256(etree.tostring(node, encoding="UTF-8")).hexdigest()})
            continue
        children = [{"id": child.get("id"), "tag": child.tag,
                     "title": child.get("title"),
                     "selected_work_id": by_scope.get(child.get("id"))}
                    for child in node if isinstance(child.tag, str)]
        envelope.append({"id": node.get("id"), "title": node.get("title"),
                         "tag": node.tag, "selected_work_id": by_scope.get(node.get("id")),
                         "direct_children": children})
    return {"contract": "ocd-npnf205-fourteen-selection-plan-v1",
            "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
            "work_count": len(entries), "works": entries,
            "volume_direct_divisions": envelope,
            "volume_direct_non_elements": non_elements,
            "fully_unselected_direct_divisions": [node.get("id") for node in body
                                                     if isinstance(node.tag, str)
                                                     if node.get("id") not in selected
                                                     and not any(child.get("id") in selected
                                                                 for child in node)],
            "shared_matter_disposition": (
                "Volume title pages, prefaces, prolegomena, bibliography, dates, group headings, "
                "index, the separately routed Against Eunomius root, and other sibling works remain "
                "in the complete retained ThML. The Letters collection includes its own title page "
                "and addressed-letter children in source order."),
            "excluded_work_route": "Against Eunomius (viii.i) has a separate acquisition route."}


def prepare(destination: Path, *, refresh: bool = False) -> dict:
    destination = destination.absolute()
    if not Path(_io_path(destination.parent)).is_dir():
        raise ValueError("external candidate parent is absent")
    Path(_io_path(destination)).mkdir(exist_ok=True)
    source_bytes, root, body = _source()
    plan = _selection_plan(root, body)
    if len(plan["works"]) != 14 or len({row["work_id"] for row in plan["works"]}) != 14:
        raise ValueError("fourteen distinct work roots required")
    _put_owned(ROOT / PLAN, _json(plan), refresh=refresh)
    policy = {
        "contract": "ocd-npnf205-work-policy-v1", "source_sha256": SOURCE_SHA,
        "selection_plan_sha256": _sha(ROOT / PLAN),
        "source_selection": "One exact complete native work root; letters use complete direct div1 xiii.",
        "neutral_reference_exceptions": [{"source_member": "npnf205", "source_root_id": "xiii",
                                         "source_xml_id": "xiii.xii-p3.1", "passage": "Ep. xviii. 4"}],
        "closure_inputs": [ORACLE.as_posix(), LEGACY_ORACLE.as_posix(),
                           CONTRACT.as_posix(), VALIDATE.as_posix()],
    }
    _put_owned(ROOT / POLICY, _json(policy), refresh=refresh)
    closure = sha256(_json([{"path": path, "sha256": _sha(ROOT / path)}
                            for path in policy["closure_inputs"]])).hexdigest()
    outcomes = []
    for entry in plan["works"]:
        work_id = entry["work_id"]
        work_rel = Path("library/works") / work_id / "work.json"
        work = _read(ROOT / work_rel)
        if work.get("work_id") != work_id or len(work.get("textual_forms", [])) != 1:
            raise ValueError(f"work identity differs: {work_id}")
        form = work["textual_forms"][0]
        if len(form.get("editions", [])) != 1:
            raise ValueError(f"edition identity differs: {work_id}")
        edition = form["editions"][0]
        if (edition.get("containing_source", {}).get("locator")
                != f"{SOURCE.as_posix()}#{entry['source_root_id']}"
                or len(edition.get("acquisition_ids", [])) != 1
                or edition.get("language") != "en"):
            raise ValueError(f"declared locator, acquisition, or language differs: {work_id}")
        acquisition_id = edition["acquisition_ids"][0]
        acquisition_rel = (Path("library/works") / work_id / "forms" / form["textual_form_id"]
                           / "editions" / edition["edition_id"] / "acquisitions"
                           / f"{acquisition_id}.json")
        acquisition = _read(ROOT / acquisition_rel)
        if (acquisition.get("source_path") != SOURCE.as_posix()
                or acquisition.get("source_sha256") != SOURCE_SHA
                or acquisition.get("source_bytes") != len(source_bytes)
                or acquisition.get("url") != SOURCE_URL):
            raise ValueError(f"exact acquisition differs: {work_id}")
        scope_note = (f"Complete native {entry['source_tag']} {entry['source_root_id']} "
                      f"inside NPNF2-05, titled {entry['source_title']}.")
        profile = {
            "contract": "ocd-npnf205-work-profile-v1", **entry,
            "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
            "selection_plan_sha256": _sha(ROOT / PLAN),
            "edition_id": edition["edition_id"], "edition_title": edition["title"],
            "textual_form_id": form["textual_form_id"], "acquisition_id": acquisition_id,
            "acquisition_path": acquisition_rel.as_posix(),
            "acquisition_sha256": _sha(ROOT / acquisition_rel),
            "work_sha256": _sha(ROOT / work_rel),
            "scope_note": scope_note,
            "shared_matter_disposition": plan["shared_matter_disposition"],
        }
        home = HOME / work_id
        profile_rel = home / "reconstruction-profile.json"
        _put_owned(ROOT / profile_rel, _json(profile), refresh=refresh)
        authorities = [
            _authority(SOURCE, "retained-thml", "primary-source"),
            _authority(PLAN, "selection-plan", "complete-work-boundary-plan"),
            _authority(profile_rel, "reconstruction-profile", "complete-source-feature-profile"),
            _authority(POLICY, "validation-policy", "independent-validation-policy"),
            _authority(LEGACY_POLICY, "legacy-projection-policy", "source-projection-policy"),
            _authority(LEGACY_MAPPER, "legacy-mapper", "bound-source-mapper"),
            _authority(LEGACY_ORACLE, "legacy-oracle", "independent-node-checker"),
            _authority(ATTRIBUTION, "source-attribution", "retained-volume-attribution"),
            _authority(PERMISSION, "ccel-permission", "separate-permission-evidence"),
            _authority(XSD, "tei-p5-xsd", "tei-validation-schema"),
            _authority(SCHEMA, "candidate-package-schema", "candidate-package-schema"),
        ]
        manifest_rel = home / "source-manifest.json"
        manifest = {
            "contract": "ocd-source-manifest-v1",
            "source_id": f"{work_id}-npnf205-native-root-v1",
            "authorities": authorities,
            "converter": {"id": "ocd-npnf205-work-root-to-tei", "version": "1",
                          "callable": "_convert", "implementation_path": CONVERTER.as_posix(),
                          "implementation_sha256": _sha(ROOT / CONVERTER)},
            "validator": {"id": "ocd-npnf205-work-root-source-oracle", "version": "1",
                          "callable": "_oracle", "implementation_path": ORACLE.as_posix(),
                          "implementation_sha256": _sha(ROOT / ORACLE),
                          "import_closure_sha256": closure},
            "package_schema": {"path": SCHEMA.as_posix(), "sha256": _sha(ROOT / SCHEMA)},
        }
        _put_owned(ROOT / manifest_rel, _json(manifest), refresh=refresh)
        SourceManifest.load(ROOT / manifest_rel, repository_root=ROOT)
        candidate_root = destination / work_id
        if not Path(_io_path(candidate_root / "validation.json")).exists():
            process = subprocess.run(
                [sys.executable, "-m", "build.tools.reconstruct_candidate", "--manifest",
                 manifest_rel.as_posix(), "--destination", str(candidate_root),
                 "--repository-root", str(ROOT)],
                cwd=ROOT, capture_output=True, text=True, check=True,
            )
            if not process.stdout.strip():
                raise ValueError(f"candidate command had no receipt: {work_id}")
        package = CandidatePackage.load(Path(_io_path(candidate_root / "package")))
        validation = _read(candidate_root / "validation.json")
        if validation.get("status") != "pass" or validation.get("findings"):
            raise ValueError(f"candidate oracle did not pass: {work_id}")
        identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                    "edition_id": edition["edition_id"]}
        projection = project_prose_document(
            Path(_io_path(candidate_root / "package/content.tei.xml")), identity=identity,
            language="en", representation_revision=f"{work_id}-npnf205-v1",
            edition_title=edition["title"],
        )
        errors = verify_document(Path(_io_path(candidate_root / "package/content.tei.xml")),
                                 projection["rows"], projection["receipt"], identity=identity,
                                 language="en", representation_revision=f"{work_id}-npnf205-v1",
                                 edition_title=edition["title"], category="prose")
        if errors or not projection["rows"]:
            raise ValueError(f"native candidate prose projection differs: {work_id}: {errors[:3]}")
        outcomes.append({
            "work_id": work_id, "source_root_id": entry["source_root_id"],
            "manifest_path": manifest_rel.as_posix(), "manifest_sha256": _sha(ROOT / manifest_rel),
            "profile_path": profile_rel.as_posix(), "profile_sha256": _sha(ROOT / profile_rel),
            "acquisition_path": acquisition_rel.as_posix(),
            "acquisition_sha256": _sha(ROOT / acquisition_rel),
            "work_sidecar_sha256": _sha(ROOT / work_rel),
            "candidate_root": candidate_root.as_posix(), "candidate_sha256": package.sha256,
            "candidate_tei_sha256": _sha(candidate_root / "package/content.tei.xml"),
            "validation_sha256": _sha(candidate_root / "validation.json"),
            "native_prose_rows": len(projection["rows"]),
            "native_prose_independent_check": "pass",
            "element_count": entry["element_count"],
            "source_root_c14n_sha256": entry["source_root_c14n_sha256"],
        })
        print(f"{len(outcomes)}/14 {work_id}: {len(projection['rows'])} native rows", flush=True)
    receipt = {"contract": "ocd-npnf205-fourteen-work-candidates-v1",
               "status": "validated-nonaccepted", "source_path": SOURCE.as_posix(),
               "source_sha256": SOURCE_SHA, "selection_plan_path": PLAN.as_posix(),
               "selection_plan_sha256": _sha(ROOT / PLAN), "work_count": 14,
               "works": outcomes, "canonical_install": "not-performed"}
    _put_owned(destination / "receipt.json", _json(receipt), refresh=False)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    result = prepare(args.destination, refresh=args.refresh)
    print(json.dumps({"works": len(result["works"]), "receipt": str(args.destination / "receipt.json")},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
