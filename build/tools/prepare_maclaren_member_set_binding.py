"""Bind Maclaren's ordered fifteen-file electronic edition as one source set."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ocd_kernel.library._common import write_json
from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "maclaren-expositions"
FORM_ID = "maclaren-expositions-pg-retained-en"
EDITION_ID = "maclaren-expositions-pg-fifteen-volume-cohort"
ACQUISITION_ID = "maclaren-expositions-pg-retained-member-set"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
MEMBER_SET = EDITION / "source-member-set.json"
MAP = Path("sources/sermons/maclaren-expositions/full-cohort-v3/source-structure-map.json")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    mapping = json.loads((root / MAP).read_bytes())
    members = [
        {
            "position": position,
            "pg_id": str(member["pg_id"]),
            "path": str(member["path"]),
            "bytes": int(member["bytes"]),
            "sha256": str(member["sha256"]),
        }
        for position, member in enumerate(mapping["members"], 1)
    ]
    if len(members) != 15 or sum(int(item["bytes"]) for item in members) != 20141441:
        raise ValueError("Maclaren retained-member-set scope changed")
    scope = (
        "Exact ordered set of 15 complete retained Project Gutenberg TXT members "
        "for the electronic Expositions of Holy Scripture cohort: 20,141,441 bytes, "
        "339,526 physical lines, and 26 source-attested parts. This binds the electronic "
        "edition envelope; exact print-edition lineage remains uncertain."
    )
    retained = [
        {
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
            "media_type": "text/plain",
            "scope": f"Position {item['position']} of the exact ordered fifteen-member electronic edition envelope.",
        }
        for item in members
    ]
    acquisition: dict[str, object] = {
        "schema_version": "2.0",
        "acquisition_id": ACQUISITION_ID,
        "edition_id": EDITION_ID,
        "provider": "Project Gutenberg",
        "url": "https://www.gutenberg.org/",
        "route": "born-digital",
        "source_path": MEMBER_SET.as_posix(),
        "source_kind": "retained-member-set",
        "source_scope": scope,
        "retained_files": retained,
        "warnings": [
            "Retain each Project Gutenberg license and attribution carried in the complete source files; rights vary by jurisdiction.",
            "Electronic member order and complete source coverage are established; certain print-edition lineage, human acceptance, rights clearance, release selection, and publication remain separate.",
        ],
    }
    descriptor_bytes = source_member_set_bytes(acquisition)
    acquisition["source_bytes"] = len(descriptor_bytes)
    acquisition["source_sha256"] = _sha(descriptor_bytes)
    descriptor_path = root / MEMBER_SET
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor_path.write_bytes(descriptor_bytes)
    write_json(root / ACQUISITION, acquisition)

    work_path = root / WORK / "work.json"
    work = json.loads(work_path.read_bytes())
    editions = [edition for form in work["textual_forms"] if form["textual_form_id"] == FORM_ID
                for edition in form["editions"] if edition["edition_id"] == EDITION_ID]
    if len(editions) != 1:
        raise ValueError("Maclaren edition identity changed")
    acquisition_ids = editions[0]["acquisition_ids"]
    if ACQUISITION_ID not in acquisition_ids:
        acquisition_ids.append(ACQUISITION_ID)
    for evidence in (MEMBER_SET.as_posix(), ACQUISITION.as_posix()):
        if evidence not in work["evidence"]:
            work["evidence"].append(evidence)
    write_json(work_path, work)

    state_path = root / WORK / "state.json"
    state = json.loads(state_path.read_bytes())
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    evidence = [MAP.as_posix(), MEMBER_SET.as_posix(), ACQUISITION.as_posix()]
    targets = {item["target_id"]: item for item in state["targets"]}
    if ACQUISITION_ID not in targets:
        state["targets"].append({
            "target_id": ACQUISITION_ID,
            "target_type": "acquisition",
            "stage": "acquired",
            "updated_at": now,
            "evidence": evidence,
        })
    edition_target = targets[EDITION_ID]
    for reference in evidence:
        if reference not in edition_target["evidence"]:
            edition_target["evidence"].append(reference)
    edition_target["updated_at"] = now
    write_json(state_path, state)

    load_work(work_path)
    validate_acquisition(root / ACQUISITION, root=root)
    validate_state(state_path, root=root)
    return {
        "status": "prepared",
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "source_member_set_sha256": acquisition["source_sha256"],
        "source_member_set_bytes": acquisition["source_bytes"],
        "members": 15,
    }


def main() -> None:
    print(json.dumps(prepare(ROOT), sort_keys=True))


if __name__ == "__main__":
    main()
