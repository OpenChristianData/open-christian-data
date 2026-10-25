"""Prepare source-bound, readable LIB-051 Owen candidates outside the library sidecars."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from lxml import etree

from build.tei.john_owen_lib050_reconstruction import _node_records, _parse, _readable_transcription
from build.tei.john_owen_lib050_oracle import _parse_source, _records, _verify_readable_transcription
from build.tei.john_owen_lib051_reconstruction import _tei
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.projection.categories.lib051_owen import _native_view
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
FAMILY = Path("sources/structured-text/lib051-john-owen")
MANIFEST = FAMILY / "john-owen-lib051.source-manifest.json"
PROFILE = FAMILY / "john-owen-lib051.reconstruction-profile.json"
TEI = "http://www.tei-c.org/ns/1.0"
WORK_IDS = (
    "john-owen-glory", "john-owen-grotius", "john-owen-indwelling-sin", "john-owen-justification",
    "john-owen-liturgies", "john-owen-mortification", "john-owen-pastors-people",
    "john-owen-perseverance", "john-owen-pneumatologia", "john-owen-psalm130",
)
FINAL_THREE_WORK_IDS = (
    "john-owen-glory", "john-owen-justification", "john-owen-pneumatologia",
)
DEFAULT_WORK_IDS = tuple(work_id for work_id in WORK_IDS if work_id not in FINAL_THREE_WORK_IDS)


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _read(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _identity(work_id: str, row: dict) -> tuple[dict, Path, dict]:
    work_path = Path("library/works") / work_id
    work = _read(ROOT / work_path / "work.json")
    forms = work.get("textual_forms", [])
    if work.get("work_id") != work_id or len(forms) != 1 or len(forms[0].get("editions", [])) != 1:
        raise PipelineError(f"work/form/edition identity changed: {work_id}")
    form, edition = forms[0], forms[0]["editions"][0]
    acquisitions = edition.get("acquisition_ids", [])
    if len(acquisitions) != 1:
        raise PipelineError(f"one acquisition required: {work_id}")
    acquisition_path = (work_path / "forms" / form["textual_form_id"] / "editions"
                        / edition["edition_id"] / "acquisitions" / f"{acquisitions[0]}.json")
    acquisition = _read(ROOT / acquisition_path)
    retained = acquisition.get("retained_files", [])
    if (len(retained) != 1 or retained[0]["path"] != row["path"]
            or retained[0]["sha256"] != row["sha256"]
            or retained[0]["bytes"] != row["bytes"]):
        raise PipelineError(f"retained acquisition differs: {work_id}")
    return {"work_id": work_id, "textual_form_id": form["textual_form_id"],
            "edition_id": edition["edition_id"], "acquisition_id": acquisitions[0]}, acquisition_path, acquisition


def prepare(destination: Path, selected: tuple[str, ...] = DEFAULT_WORK_IDS) -> dict:
    destination = destination.absolute()
    if (destination.exists() or not destination.parent.is_dir()
            or ROOT == destination or ROOT in destination.parents):
        raise PipelineError("fresh external candidate destination required")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    profile_bytes = (ROOT / PROFILE).read_bytes()
    profile = json.loads(profile_bytes)
    rows = {row["work_id"]: row for row in profile["works"]}
    if (len(rows) != 10 or not selected or len(set(selected)) != len(selected)
            or set(selected) - set(WORK_IDS)):
        raise PipelineError("LIB-051 ten-source inventory changed")
    prepared: list[tuple[str, bytes, dict, bytes]] = []
    for work_id in selected:
        row = rows[work_id]
        content = manifest.authority_path(row["authority_name"]).read_bytes()
        if len(content) != row["bytes"] or _sha(content) != row["sha256"]:
            raise PipelineError(f"retained source drift: {work_id}")
        identity, acquisition_path, acquisition = _identity(work_id, row)
        source = _parse(content)
        body = source.find("ThML.body")
        if source.getroot().tag != "ThML" or body is None:
            raise PipelineError(f"retained ThML body missing: {work_id}")
        divisions = [node for node in body if isinstance(node.tag, str)]
        if not divisions or any(node.tag != "div1" for node in divisions):
            raise PipelineError(f"top-level work division changed: {work_id}")
        records = _node_records(source, row["member_id"])
        member = etree.fromstring(_tei([(row, content, source, records)])).find(f"{{{TEI}}}TEI")
        if member is None or member.get("{http://www.w3.org/XML/1998/namespace}id") != work_id:
            raise PipelineError(f"member extraction differs: {work_id}")
        member_body = member.find(f"{{{TEI}}}text/{{{TEI}}}body")
        if member_body is None or len(member_body) != 1:
            raise PipelineError(f"member body differs: {work_id}")
        member_body.remove(member_body[0])
        member_body.append(_readable_transcription(source, records, work_id))
        independent_source = _parse_source(content)
        _verify_readable_transcription(
            independent_source, _records(independent_source, row["member_id"]), member_body, work_id,
        )
        tei = etree.tostring(member, encoding="UTF-8", xml_declaration=True) + b"\n"
        candidate_path = destination / work_id / "candidate.tei.xml"
        candidate_path.parent.mkdir(parents=True, exist_ok=False)
        candidate_path.write_bytes(tei)
        if errors := validate_file(candidate_path):
            raise PipelineError(f"P5 validation failed for {work_id}: {errors[:3]}")
        context = {
            "identity": {key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")},
            "language": "en", "representation_revision": "lib051-readable-diagnostic-v1",
            "edition_title": row["title"], "category": "prose", "_allow_acceptance_metadata": True,
        }
        with tempfile.TemporaryDirectory(prefix="ocd-lib051-readable-") as folder:
            view_path = Path(folder) / "native-view.tei.xml"
            view_path.write_bytes(_native_view(member, member_body[0], row["title"]) if work_id != "john-owen-mortification" else tei)
            projected = project_document(view_path, **context)
            errors = verify_document(view_path, projected["rows"], projected["receipt"], **context)
        if errors or len(projected["rows"]) != 1 or projected["receipt"]["unsupported"]:
            raise PipelineError(f"native readable projection failed for {work_id}: {errors[:3]}")
        accounting = {
            "contract": "ocd-lib051-readable-work-accounting-v1", "identity": identity,
            "source_path": row["path"], "source_sha256": row["sha256"],
            "source_bytes": len(content), "source_nodes": len(records),
            "top_level_divisions": [{"id": node.get("id"), "title": node.get("title")}
                                    for node in divisions],
            "source_manifest_sha256": manifest.sha256, "profile_sha256": _sha(profile_bytes),
            "acquisition_path": acquisition_path.as_posix(),
            "acquisition_sha256": _sha((ROOT / acquisition_path).read_bytes()),
            "source_url": acquisition["url"],
            "readable_oracle": "build.tei.john_owen_lib050_oracle._verify_readable_transcription",
            "tei_sha256": _sha(tei), "projection_rows": 1,
        }
        (candidate_path.parent / "source-accounting.json").write_bytes(_json(accounting))
        receipt = accounting | {"contract": "ocd-lib051-readable-work-candidate-v1",
                                "status": "validated-nonaccepted", "publication": "not_ready",
                                "source_accounting_sha256": _sha(_json(accounting))}
        (candidate_path.parent / "receipt.json").write_bytes(_json(receipt))
        prepared.append((work_id, tei, receipt, _json(accounting)))
    result = {
        "contract": "ocd-lib051-readable-work-candidates-v1", "status": "validated-nonaccepted",
        "work_ids": list(selected), "source_manifest_sha256": manifest.sha256,
        "profile_sha256": _sha(profile_bytes),
        "receipts": {work_id: _sha((destination / work_id / "receipt.json").read_bytes())
                     for work_id in selected},
        "tei": {work_id: _sha(tei) for work_id, tei, _receipt, _accounting in prepared},
        "not_selected_work_ids": sorted(set(rows) - set(selected)),
        "installation": "not-performed",
    }
    (destination / "receipt.json").write_bytes(_json(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--work-id", choices=WORK_IDS)
    args = parser.parse_args()
    result = prepare(args.destination, (args.work_id,) if args.work_id else DEFAULT_WORK_IDS)
    print(json.dumps({"status": result["status"], "count": len(result["work_ids"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
