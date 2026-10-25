"""Check inspected flat-ab verse witnesses without assigning line units."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage


ROOT = Path(__file__).resolve().parents[2]
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb830-inspected-batch-20260926.json")
BATCH_SHA = "9115c45b7bb855125f81fc4f8122a217f600b6bac2239160e9d6c9c0822f2562"
SOURCE = Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml")
SOURCE_SHA = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
WORKS = (
    "defense-of-priests-sons",
    "exiled-monk-calamities-of-the-church-of-liege",
    "hunald-carmen-de-anulo-et-baculo",
)
REMAINDER_WORKS = (
    "poem-on-the-simoniacal-heresy",
    "satire-against-the-people-of-metz",
)
TEI = "{http://www.tei-c.org/ns/1.0}"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"object expected: {path}")
    return value


def _parse(raw: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_comments=False, huge_tree=True)
    root = etree.fromstring(raw, parser)
    if root.tag != f"{TEI}TEI" or root.getroottree().docinfo.doctype:
        raise PipelineError("entity-free TEI source expected")
    return root


def _c14n(node: etree._Element, *, exclusive: bool) -> bytes:
    return etree.tostring(node, method="c14n", exclusive=exclusive,
                          with_comments=True)


def check(root: Path, *, work_ids: tuple[str, ...] = WORKS) -> dict:
    if _sha((root / BATCH).read_bytes()) != BATCH_SHA:
        raise PipelineError("inspected batch receipt changed")
    source_raw = (root / SOURCE).read_bytes()
    if _sha(source_raw) != SOURCE_SHA:
        raise PipelineError("retained extracted XML changed")
    batch = _json(root / BATCH)
    source_root = _parse(source_raw)
    volume = source_root.find(f"{TEI}text/{TEI}body/{TEI}div[@type='volume']")
    if volume is None:
        raise PipelineError("source volume missing")
    works = [node for node in volume if node.tag == f"{TEI}div"
             and node.get("type") == "work"]
    if len(works) != 29:
        raise PipelineError("source work count changed")
    result = {"contract": "ocd-openmgh-flat-ab-poetry-fixture-v1",
              "status": "candidate-source-conserved-projection-pending",
              "inspection_receipt": BATCH.as_posix(),
              "inspection_receipt_sha256": BATCH_SHA,
              "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
              "works": []}
    if not work_ids or len(set(work_ids)) != len(work_ids):
        raise PipelineError("flat-ab work IDs must be distinct and nonempty")
    for work_id in work_ids:
        entries = [item for item in batch["works"] if item["work_id"] == work_id]
        if len(entries) != 1:
            raise PipelineError(f"nonunique inspection: {work_id}")
        entry = entries[0]
        selected = works[entry["work_div_ordinal"] - 1]
        if selected.get("n") != entry["work_div_n"]:
            raise PipelineError(f"source boundary changed: {work_id}")
        boundary_path = root / entry["boundary_review_path"]
        if _sha(boundary_path.read_bytes()) != entry["boundary_review_sha256"]:
            raise PipelineError(f"inspected boundary changed: {work_id}")
        boundary = _json(boundary_path)
        direct_ab = [node for node in selected if node.tag == f"{TEI}ab"]
        if len(direct_ab) != 1:
            raise PipelineError(f"one direct source ab expected: {work_id}")
        accounting = _json(Path(entry["candidate_root"]) / "package/source-accountability.json")
        if (_sha(_c14n(selected, exclusive=False))
                != accounting["source_div_c14n_sha256"]):
            raise PipelineError(f"source accounting changed: {work_id}")
        package = CandidatePackage.load(Path(entry["candidate_root"]) / "package")
        if package.sha256 != entry["candidate_sha256"]:
            raise PipelineError(f"inspected package changed: {work_id}")
        candidate_root = _parse(package.member_bytes("content.tei.xml"))
        candidate = candidate_root.find(f"{TEI}text/{TEI}body/{TEI}div")
        if candidate is None or len(candidate_root.findall(f"{TEI}text/{TEI}body/{TEI}div")) != 1:
            raise PipelineError(f"candidate work boundary changed: {work_id}")
        if _c14n(candidate, exclusive=True) != _c14n(selected, exclusive=True):
            raise PipelineError(f"candidate changed source div: {work_id}")
        counts = Counter(etree.QName(node).localname for node in selected.iter()
                         if isinstance(node.tag, str))
        if counts["ab"] != 1 or counts["lg"] or counts["l"]:
            raise PipelineError(f"line or stanza units were invented: {work_id}")
        ab = direct_ab[0]
        work_result = {
            "work_id": work_id, "work_div_ordinal": entry["work_div_ordinal"],
            "work_div_n": entry["work_div_n"],
            "source_div_accounting_sha256": accounting["source_div_c14n_sha256"],
            "source_div_exclusive_c14n_sha256": _sha(_c14n(selected, exclusive=True)),
            "source_ab_exclusive_c14n_sha256": _sha(_c14n(ab, exclusive=True)),
            "element_counts": dict(sorted(counts.items())),
            "candidate_package_sha256": package.sha256,
            "candidate_tei_sha256": _sha(package.member_bytes("content.tei.xml")),
            "source_terminal_evidence": boundary["closing_evidence"],
            "assertion": "one exact flat ab, no projected line or stanza units",
        }
        result["works"].append(work_result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    result = check(args.root.resolve(strict=True))
    if args.fixture is not None and result != _json(args.fixture):
        raise PipelineError("flat-ab fixture differs from source and inspected candidates")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
