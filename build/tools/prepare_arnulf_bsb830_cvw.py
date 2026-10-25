"""Pin an Arnulf-only source manifest for the maintained CVW candidate runner."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei.openmgh_exact_work_div import check_candidate, parse_tei
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "arnulf-of-sees-invective-to-geoffrey-of-chartres"
HOME = ROOT / "sources" / "openmgh-exclusive" / WORK_ID
EXACT = "plans/2026-09-22-source-preflight/arnulf-bsb830-exact-manifest-20260929.json"
INVENTORY = "plans/2026-09-22-source-preflight/arnulf-bsb830-source-selection-20260929.json"
PRODUCER = "build/tei/arnulf_bsb830_cvw_reconstruction.py"
ORACLE = "build/tei/arnulf_bsb830_cvw_oracle.py"
PACKAGE_SCHEMA = "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
XSD = "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
CLOSURE = [ORACLE, "build/tei/openmgh_exact_work_div.py", "ocd_kernel/reconstruction/contract.py", "ocd_kernel/tei/install_accepted.py", "ocd_kernel/tei/validate.py"]


def _bytes(relative: str) -> bytes:
    return Path(_io_path(ROOT / relative)).read_bytes()


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"refusing to replace existing Arnulf evidence: {path}")
        return
    path.write_bytes(content)


def _authority(name: str, path: str, role: str) -> dict:
    content = _bytes(path)
    return {"name": name, "path": path, "role": role, "bytes": len(content), "sha256": _sha(content)}


def prepare() -> dict:
    exact = json.loads(_bytes(EXACT))
    inventory = json.loads(_bytes(INVENTORY))
    if (
        exact.get("contract") != "ocd-openmgh-exact-work-div-batch-v1"
        or len(exact.get("works", [])) != 1
        or exact["works"][0].get("work_id") != WORK_ID
        or inventory.get("selected_work_div_index") != 4
        or inventory.get("selected_part_count") != 2
    ):
        raise ValueError("Arnulf exact source selection drifted")
    entry = exact["works"][0]
    work_path = entry["work_path"]
    acquisition_path = entry["acquisition_path"]
    source_path = exact["source"]["path"]
    master_path = str(Path(acquisition_path).parent.parent / "master.tei.xml").replace("\\", "/")
    work = json.loads(_bytes(work_path))
    acquisition = json.loads(_bytes(acquisition_path))
    source = _bytes(source_path)
    master = _bytes(master_path)
    if (
        _sha(source) != exact["source"]["sha256"]
        or _sha(master) != "ea0a68291595046132841824ceb0589a8307b4321117d86d5f143627822636f4"
        or acquisition.get("source_path") != source_path
        or acquisition.get("source_sha256") != _sha(source)
    ):
        raise ValueError("Arnulf retained source or accepted master drifted")
    check_candidate(source, master, exact, entry, work, acquisition)
    root = parse_tei(source)
    accepted = parse_tei(master)
    revision = accepted.find("{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}revisionDesc/{http://www.tei-c.org/ns/1.0}change")
    if (
        revision is None
        or revision.get("{http://www.w3.org/XML/1998/namespace}id") != f"{WORK_ID}-openmgh-exact-work-div-v1"
        or revision.text != "Accept the complete source work div in the extracted openMGH electronic witness."
        or not revision.get("when")
    ):
        raise ValueError("Arnulf accepted revision binding drifted")
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1:
        raise ValueError("Arnulf source volume is ambiguous")
    works = list(volumes[0])
    index = entry["source_work_div_index"]
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    profile = {
        "contract": "ocd-openmgh-exclusive-profile-v1",
        "work_id": WORK_ID,
        "work_title": work["title"],
        "edition_id": edition["edition_id"],
        "acquisition_id": acquisition["acquisition_id"],
        "acquisition_path": acquisition_path,
        "acquisition_sha256": _sha(_bytes(acquisition_path)),
        "source_path": source_path,
        "source_sha256": _sha(source),
        "source_url": acquisition["url"],
        "revision_date": revision.get("when"),
        "work_div_n": works[index].get("n"),
        "work_div_ordinal": index + 1,
        "volume_work_count": len(works),
        "start_xml_id": entry["catalog_locator_ids"][0],
        "end_xml_id": entry["catalog_locator_ids"][-1],
        "preceding_work_n": works[index - 1].get("n"),
        "following_work_n": works[index + 1].get("n"),
        "accepted_master_path": master_path,
        "accepted_master_sha256": _sha(master),
        "exact_manifest_sha256": _sha(_bytes(EXACT)),
    }
    policy = {"contract": "ocd-arnulf-bsb830-cvw-policy-v1", "status": "nonaccepted", "closure_inputs": CLOSURE}
    HOME.mkdir(parents=True, exist_ok=True)
    profile_path = f"sources/openmgh-exclusive/{WORK_ID}/reconstruction-profile.json"
    policy_path = f"sources/openmgh-exclusive/{WORK_ID}/validation-policy.json"
    manifest_path = f"sources/openmgh-exclusive/{WORK_ID}/source-manifest.json"
    _write(ROOT / profile_path, _json(profile))
    _write(ROOT / policy_path, _json(policy))
    closure = _sha(_json([{"path": path, "sha256": _sha(_bytes(path))} for path in CLOSURE]))
    manifest = {
        "contract": "ocd-source-manifest-v1",
        "source_id": f"{WORK_ID}-openmgh-exclusive-electronic-v1",
        "work_id": WORK_ID,
        "authorities": [
            _authority("extracted-xml", source_path, "primary-source"),
            _authority("work-sidecar", work_path, "work-identity-config"),
            _authority("acquisition-sidecar", acquisition_path, "acquisition-selection-authority"),
            _authority("source-inventory", INVENTORY, "inspected-work-boundary"),
            _authority("exact-work-div-manifest", EXACT, "exact-source-selection"),
            _authority("reconstruction-profile", profile_path, "complete-source-feature-profile"),
            _authority("validation-policy", policy_path, "independent-validation-policy"),
            _authority("tei-p5-xsd", XSD, "tei-validation-schema"),
            _authority("candidate-package-schema", PACKAGE_SCHEMA, "candidate-package-schema"),
        ],
        "converter": {"id": "ocd-arnulf-bsb830-exact-div-cvw", "version": "1", "callable": "_convert", "implementation_path": PRODUCER, "implementation_sha256": _sha(_bytes(PRODUCER))},
        "validator": {"id": "ocd-arnulf-bsb830-exact-div-cvw-oracle", "version": "1", "callable": "_oracle", "implementation_path": ORACLE, "implementation_sha256": _sha(_bytes(ORACLE)), "import_closure_sha256": closure},
        "package_schema": {"path": PACKAGE_SCHEMA, "sha256": _sha(_bytes(PACKAGE_SCHEMA))},
    }
    _write(ROOT / manifest_path, _json(manifest))
    return {"manifest": manifest_path, "manifest_sha256": _sha(_bytes(manifest_path)), "master_sha256": _sha(master)}


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
