"""Freeze and check the Didache full-witness identity proposal.

This stage is held before acceptance because the retained Wikisource JSON has
no exact revision or proofreading history. It never writes canonical work data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/didache-prayers/work.json")
SOURCE = Path("raw/wikisource/didache.json")
MANIFEST = Path("sources/didache-prayers/didache-prayers.source-manifest.json")
PROFILE = Path("sources/didache-prayers/didache-prayers.reconstruction-profile.json")
STAGE_PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
SOURCE_SHA256 = "9ba0420fc2f1ef3d960335c100e31f8edbe7343b7fc5eab66dcce075744db764"
OLD_TITLE = "Didache -- Prayers (Lake Translation)"
NEW_TITLE = "Didache"
WITNESS_TITLE = "Didache (Lake translation)"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _json(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"expected JSON object: {path}")
    return value


def _stage_path(path: Path) -> Path:
    path = path.resolve(strict=True)
    parent = STAGE_PARENT.resolve(strict=True)
    if path.parent != parent or not path.name.startswith("didache-lake-full-witness-s"):
        raise PipelineError("unexpected Didache stage path")
    return path


def _inputs(stage: Path) -> dict:
    source_manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    source_manifest.verify()
    source = ROOT / SOURCE
    source_raw = source.read_bytes()
    if len(source_raw) != 23668 or _sha(source_raw) != SOURCE_SHA256:
        raise PipelineError("Didache retained source differs")
    profile = _json(ROOT / PROFILE)
    if (profile.get("identity", {}).get("title") != WITNESS_TITLE
            or profile.get("scope", "").find("chapters I-XVI") < 0):
        raise PipelineError("Didache profile does not identify the full witness")
    package = CandidatePackage.load(stage / "package")
    validation_raw = (stage / "validation.json").read_bytes()
    validation = json.loads(validation_raw)
    if (validation.get("status") != "pass" or validation.get("findings") != []
            or validation.get("candidate_sha256") != package.sha256
            or validation.get("source_manifest_sha256") != source_manifest.sha256):
        raise PipelineError("Didache candidate validation differs")
    provenance = json.loads(package.member_bytes("provenance.json"))
    accountability = json.loads(package.member_bytes("source-accountability.json"))
    tei_raw = package.member_bytes("content.tei.xml")
    tei = etree.fromstring(tei_raw)
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    titles = tei.xpath("./t:teiHeader/t:fileDesc/t:titleStmt/t:title/text()", namespaces=ns)
    chapters = tei.xpath("./t:text/t:body/t:div[@type='chapter']", namespaces=ns)
    verses = tei.xpath("./t:text/t:body//t:ab[@type='verse']", namespaces=ns)
    if (provenance.get("identity", {}).get("title") != WITNESS_TITLE
            or provenance.get("work_id") != "didache-prayers"
            or accountability.get("chapter_count") != 16
            or accountability.get("verse_count") != 100
            or titles != [WITNESS_TITLE]
            or len(chapters) != 16 or len(verses) != 100
            or [chapter.get("n") for chapter in chapters] != [str(n) for n in range(1, 17)]):
        raise PipelineError("Didache stage would misrepresent the complete witness")
    work_raw = (ROOT / WORK).read_bytes()
    work = json.loads(work_raw)
    if (work.get("work_id") != "didache-prayers" or work.get("title") != OLD_TITLE
            or len(work.get("textual_forms", [])) != 1):
        raise PipelineError("Didache canonical work preimage differs")
    proposed = dict(work)
    proposed["title"] = NEW_TITLE
    return {
        "canonical_work_sha256": _sha(work_raw),
        "proposed_work_bytes": _canonical(proposed),
        "source_manifest_sha256": source_manifest.sha256,
        "source_sha256": SOURCE_SHA256,
        "profile_sha256": _sha((ROOT / PROFILE).read_bytes()),
        "candidate_sha256": package.sha256,
        "tei_sha256": _sha(tei_raw),
        "validation_sha256": _sha(validation_raw),
    }


def prepare(stage: Path) -> dict:
    stage = _stage_path(stage)
    proposal_path = stage / WORK
    receipt_path = stage / "didache-stage-receipt.json"
    if proposal_path.exists() or receipt_path.exists():
        raise PipelineError("Didache proposal stage already exists")
    facts = _inputs(stage)
    proposal_path.parent.mkdir(parents=True)
    proposal_path.write_bytes(facts.pop("proposed_work_bytes"))
    load_work(proposal_path)
    receipt = {
        "contract": "ocd-didache-full-witness-identity-stage-v1",
        "status": "held-before-acceptance",
        "work_id": "didache-prayers",
        "work_title": NEW_TITLE,
        "witness_title": WITNESS_TITLE,
        "proposed_work_sha256": _sha(proposal_path.read_bytes()),
        "hold": "Exact Wikisource revision and proofreading history are absent; exhaustive clean-text admission is unproven.",
        **facts,
    }
    receipt_path.write_bytes(_canonical(receipt))
    return {"stage": stage.as_posix(), "receipt_sha256": _sha(receipt_path.read_bytes()), **receipt}


def preflight(stage: Path, expected_receipt_sha256: str) -> dict:
    stage = _stage_path(stage)
    receipt_path = stage / "didache-stage-receipt.json"
    if _sha(receipt_path.read_bytes()) != expected_receipt_sha256:
        raise PipelineError("Didache stage receipt differs from caller pin")
    receipt = _json(receipt_path)
    facts = _inputs(stage)
    proposed_bytes = facts.pop("proposed_work_bytes")
    proposal_path = stage / WORK
    if proposal_path.read_bytes() != proposed_bytes:
        raise PipelineError("Didache staged work differs from the exact title-only proposal")
    load_work(proposal_path)
    for key, value in facts.items():
        if receipt.get(key) != value:
            raise PipelineError(f"Didache stage binding differs: {key}")
    if (receipt.get("contract") != "ocd-didache-full-witness-identity-stage-v1"
            or receipt.get("status") != "held-before-acceptance"
            or receipt.get("work_id") != "didache-prayers"
            or receipt.get("work_title") != NEW_TITLE
            or receipt.get("witness_title") != WITNESS_TITLE
            or receipt.get("proposed_work_sha256") != _sha(proposed_bytes)
            or "revision and proofreading history are absent" not in receipt.get("hold", "")):
        raise PipelineError("Didache stage claim differs")
    return {"status": "held-before-acceptance", "stage": stage.as_posix(),
            "receipt_sha256": expected_receipt_sha256, "candidate_sha256": facts["candidate_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--expected-receipt-sha256")
    args = parser.parse_args()
    if args.prepare:
        if args.expected_receipt_sha256:
            parser.error("--expected-receipt-sha256 is only for preflight")
        result = prepare(args.stage)
    else:
        if not args.expected_receipt_sha256:
            parser.error("read-only preflight requires --expected-receipt-sha256")
        result = preflight(args.stage, args.expected_receipt_sha256)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
