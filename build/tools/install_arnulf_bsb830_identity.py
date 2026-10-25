"""Stage or guardedly install the Arnulf bsb830 title and source-scope correction."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

from lxml import etree

from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library.acquisitions import load_acquisition, validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _commit_generation


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "arnulf-of-sees-invective-to-geoffrey-of-chartres"
WORK = Path("library/works") / WORK_ID
SOURCE = Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml")
SOURCE_SHA256 = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
OLD_WORK_SHA256 = "890b987ec5a89dbcc8ab086c52f2fc04c67d49c29a2aee9b6e4060d12a3fb00e"
OLD_STATE_SHA256 = "6e2524b54eaa2aa866ef39db0f8e640b4f6fe6e44c861611e205fdabf6bbc33d"
OLD_TITLE = "Arnulf of Sees, Invective to Geoffrey of Chartres"
TITLE = "Arnulf of Sees, Invective against Girard of Angouleme"
START_ID = "bsb00000830_00093_16"
END_ID = "bsb00000830_00116_9"
TRACT_ID = "bsb00000830_00094_32"


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(Path(_io_path(path)).read_bytes())


def _write(path: Path, value: dict) -> None:
    Path(_io_path(path)).write_bytes(
        (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )


def _source_boundary() -> None:
    data = Path(_io_path(ROOT / SOURCE)).read_bytes()
    if sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("retained bsb830 XML changed")
    tree = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if tree.getroottree().docinfo.doctype:
        raise ValueError("source contains a DOCTYPE")
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    volume = tree.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volume) != 1 or len(volume[0]) != 29:
        raise ValueError("source volume boundary changed")
    work = volume[0][4]
    if work.get("type") != "work" or work.get("n") != "Arn. Sagiensis archid. invect." or len(work) != 2:
        raise ValueError("Arnulf source work boundary changed")
    if any(part.get("type") != "part" for part in work):
        raise ValueError("Arnulf source part boundary changed")
    for identity, part in ((START_ID, work[0]), (TRACT_ID, work[1]), (END_ID, work[1])):
        nodes = tree.xpath("//*[@xml:id=$identity]", identity=identity)
        if len(nodes) != 1 or part not in nodes[0].iterancestors():
            raise ValueError(f"Arnulf source locator changed: {identity}")
    letter = " ".join(" ".join(work[0].itertext()).split())
    tract = " ".join(" ".join(work[1].itertext()).split())
    if ("in Girardum Engolismensem" not in letter
            or "Opus autem ipsum" not in letter
            or not letter.endswith("Valete.")
            or not tract.startswith("ARNULFI SAGIENSIS ARCHIDIACONI IN GIRARDUM ENGOLISMENSEM TRACTATUS.")
            or not tract.endswith("EXPLICIT.")):
        raise ValueError("Arnulf letter/tract relationship changed")


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if stage == ROOT or ROOT in stage.parents or Path(_io_path(stage)).exists():
        raise ValueError("fresh external Arnulf stage required")
    if _sha(ROOT / WORK / "work.json") != OLD_WORK_SHA256:
        raise ValueError("Arnulf work preimage changed")
    if _sha(ROOT / WORK / "state.json") != OLD_STATE_SHA256:
        raise ValueError("Arnulf state preimage changed")
    _source_boundary()
    before = _files(ROOT / WORK)
    shutil.copytree(_io_path(ROOT / WORK), _io_path(stage / WORK))
    old = _read(ROOT / WORK / "work.json")
    if old["title"] != OLD_TITLE:
        raise ValueError("original Arnulf title changed")
    revised = _read(stage / WORK / "work.json")
    revised["title"] = TITLE
    validate_identity_update(old, revised)
    _write(stage / WORK / "work.json", revised)
    load_work(Path(_io_path(stage / WORK / "work.json")))
    form = revised["textual_forms"][0]
    edition = form["editions"][0]
    if len(edition["acquisition_ids"]) != 1:
        raise ValueError("Arnulf acquisition identity changed")
    acquired = (WORK / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"]
                / "acquisitions" / f"{edition['acquisition_ids'][0]}.json")
    record = _read(stage / acquired)
    if record["source_path"] != SOURCE.as_posix() or record["source_sha256"] != SOURCE_SHA256:
        raise ValueError("Arnulf acquisition source changed")
    scope = (
        "Extracted TEI XML is the retained text source for complete volume work division 5/29 "
        "(Arn. Sagiensis archid. invect.): the dedicatory letter to Geoffrey of Chartres "
        f"from #{START_ID} through #bsb00000830_00094_31, followed by the invective "
        f"against Girard of Angouleme from #{TRACT_ID} through #{END_ID}. "
        "The two native part divisions and their order are retained. The ZIP is acquisition "
        "packaging, and the other 28 volume work divisions are outside this edition."
    )
    record["source_scope"] = scope
    matching = [item for item in record["retained_files"] if item["path"] == SOURCE.as_posix()]
    if len(matching) != 1:
        raise ValueError("retained Arnulf text member changed")
    matching[0]["scope"] = scope
    _write(stage / acquired, record)
    load_acquisition(Path(_io_path(stage / acquired)))
    after = _files(stage / WORK)
    changed = {name for name in before | after if before.get(name) != after.get(name)}
    if changed != {"work.json", acquired.relative_to(WORK).as_posix()}:
        raise ValueError(f"unexpected Arnulf metadata change: {sorted(changed)}")
    return {"work_id": WORK_ID, "stage": stage.as_posix(), "before": before,
            "after": after, "source_sha256": SOURCE_SHA256, "title": TITLE}


def install(stage: Path, *, expected_after: dict[str, str]) -> dict:
    stage = stage.resolve(strict=True)
    target = ROOT / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        _source_boundary()
        if _sha(target / "work.json") != OLD_WORK_SHA256 or _sha(target / "state.json") != OLD_STATE_SHA256:
            raise ValueError("Arnulf canonical preimage changed")
        before = _files(target)
        if _files(stage / WORK) != expected_after:
            raise ValueError("Arnulf staged metadata changed")
        old = _read(target / "work.json")
        new = _read(stage / WORK / "work.json")
        validate_identity_update(old, new)
        result = _commit_generation(
            ROOT, target, stage / WORK, work_id=WORK_ID, before=before,
            after=expected_after, existed=True, replacement=False,
            operation_kind="arnulf-bsb830-identity-correction",
            result_status="identity-corrected-and-validated", accepted_editions=0,
            fail_at=None,
        )
    form = new["textual_forms"][0]
    edition = form["editions"][0]
    acquired = (target / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"]
                / "acquisitions" / f"{edition['acquisition_ids'][0]}.json")
    validate_acquisition(acquired, root=ROOT)
    validate_state(target / "state.json", root=ROOT)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-after", type=Path)
    args = parser.parse_args()
    if args.apply:
        if args.expected_after is None:
            parser.error("--expected-after is required with --apply")
        result = install(args.stage, expected_after=_read(args.expected_after)["after"])
    else:
        result = prepare(args.stage)
        if args.receipt is None or Path(_io_path(args.receipt)).exists():
            parser.error("a fresh --receipt is required for staging")
        Path(_io_path(args.receipt)).write_bytes(
            (json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
    print(json.dumps({"status": "applied" if args.apply else "staged-only",
                      "work_id": WORK_ID, "stage": str(args.stage)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
