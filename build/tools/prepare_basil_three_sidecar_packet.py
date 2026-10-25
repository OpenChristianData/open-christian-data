"""Write the reviewed three-work Basil NPNF2-08 child evidence and sidecar packet."""
from __future__ import annotations

import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError, sha256_file, write_json

from build.tools.library_basil_three_binding import EVIDENCE, MANIFEST


ROOT = Path(__file__).resolve().parents[2]
PACKET = "plans/2026-09-22-source-preflight/basil-npnf208-three-sidecar-packet-20260926.json"
PROFILE = "sources/structured-text/npnf2-lib046/npnf2-lib046.reconstruction-profile.json"
SOURCE = "raw/ccel/npnf2/npnf208.xml"


def _ref(path: str) -> dict[str, str]:
    return {"path": path, "sha256": sha256_file(ROOT / path)}


def main() -> None:
    manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    profile = json.loads((ROOT / PROFILE).read_text(encoding="utf-8"))
    primary = next(item for item in manifest["authorities"] if item.get("role") == "primary-source")
    if (primary["path"] != SOURCE or not all(
            profile["source_member"][key] == primary[key] for key in ("path", "bytes", "sha256"))):
        raise PipelineError("Basil source/profile binding changed")
    children = [{"div1_id": key, "work_id": wid, "child_title": profile["source_envelope"]["assigned_root_titles"][key]}
                for _, key, wid in profile["assigned_roots"]]
    evidence = {"contract": "ocd-basil-three-child-scope-v1", "source_manifest": _ref(MANIFEST),
                "profile": _ref(PROFILE), "source": {key: primary[key] for key in ("path", "bytes", "sha256")},
                "volume_title": "NPNF2-08. Basil: Letters and Select Works",
                "printed_source_notice": "Edinburgh: T&T Clark, 1895", "children": children}
    write_json(ROOT / EVIDENCE, evidence)
    rows = []
    for child in children:
        wid, child_id = child["work_id"], child["div1_id"]
        config_path = f"sources/structured-text/{wid}/config.json"
        config = json.loads((ROOT / config_path).read_text(encoding="utf-8"))
        metadata_path = f"metadata/source-evidence/catalog/{wid}.json"
        locator = SOURCE + "#" + child_id
        rows.append({"work_id": wid, "work": _ref(f"library/works/{wid}/work.json"),
                     "state": _ref(f"library/works/{wid}/state.json"),
                     "source_manifest": _ref(MANIFEST), "basil_child_evidence": _ref(EVIDENCE),
                     "config": _ref(config_path), "metadata_evidence": _ref(metadata_path),
                     "primary_source": primary, "textual_form_id": f"{wid}-ccel-npnf208-retained-en",
                     "edition_id": f"{wid}-ccel-npnf208-electronic",
                     "acquisition_id": f"{wid}-ccel-npnf208-acquired",
                     "edition_title": "CCEL electronic witness of NPNF2-08. Basil: Letters and Select Works",
                     "provider": "Christian Classics Ethereal Library", "url": config["source_url"],
                     "language": "en", "media_type": "application/xml",
                     "containing_source": {"title": evidence["volume_title"], "locator": locator,
                                           "evidence": [EVIDENCE, metadata_path, locator]},
                     "source_scope": (f"Complete acquired XML volume {SOURCE}; work-specific div1 locator {locator} "
                                      "is recorded in edition.containing_source and does not establish accepted child text."),
                     "warnings": [
                         "The retained XML labels its text Public Domain; CCEL permits parsing but retains file and formatting rights. Publication rights require separate review.",
                         "The retained printed-source notice reads Edinburgh: T&T Clark, 1895; it does not independently establish a verified print witness for this child.",
                         "Volume-level translator and series-editor contributor credits do not settle separate child-work allocation.",
                         "The three assigned subtrees are source-accounted; no complete TEI is accepted for these child works, and publication remains separate work.",
                     ]})
    write_json(ROOT / PACKET, {"contract": "ocd-library-sidecar-batch-v1", "entries": rows})
    print(json.dumps({"evidence": EVIDENCE, "evidence_sha256": sha256_file(ROOT / EVIDENCE),
                      "packet": PACKET, "packet_sha256": sha256_file(ROOT / PACKET),
                      "work_ids": [item["work_id"] for item in rows]}, sort_keys=True))


if __name__ == "__main__":
    main()
