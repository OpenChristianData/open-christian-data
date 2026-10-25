"""Challenge the bound Law candidate oracle with source-shaped mutations."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Callable

from lxml import etree


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MEMBERS = (
    "README.source.md",
    "content.tei.xml",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _load_oracle(repository_root: Path):
    path = repository_root / "build/tei/law_serious_call_oracle.py"
    spec = importlib.util.spec_from_file_location("law_serious_call_mutation_oracle", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the exact Law independent oracle")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.validate


def _reseal(package_dir: Path) -> None:
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["members"] = [
        {
            "name": name,
            "bytes": len((package_dir / name).read_bytes()),
            "sha256": _sha((package_dir / name).read_bytes()),
        }
        for name in MEMBERS
    ]
    manifest_path.write_bytes(_canonical(manifest))


def _mutate_tei(package_dir: Path, operation: Callable[[etree._Element], None]) -> None:
    tei_path = package_dir / "content.tei.xml"
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        remove_comments=False,
        huge_tree=False,
    )
    document = etree.parse(str(tei_path), parser)
    operation(document.getroot())
    tei_path.write_bytes(
        etree.tostring(
            document,
            xml_declaration=True,
            encoding="UTF-8",
            pretty_print=False,
        )
        + b"\n"
    )


def _omit_scripture_reference(root: etree._Element) -> None:
    body = root.find(f".//{{{TEI_NS}}}body")
    reference = body.find(f".//{{{TEI_NS}}}ref[@type='scripture']") if body is not None else None
    if reference is None or reference.getparent() is None:
        raise ValueError("source-bound mutation could not locate a body scripture reference")
    reference.getparent().remove(reference)


def _move_note(root: etree._Element) -> None:
    body = root.find(f".//{{{TEI_NS}}}body")
    if body is None:
        raise ValueError("source-bound mutation could not locate the TEI body")
    note = body.find(f".//{{{TEI_NS}}}note")
    if note is None or note.getparent() is None:
        raise ValueError("source-bound mutation could not locate a body note")
    destination = next(
        (
            paragraph
            for paragraph in body.findall(f".//{{{TEI_NS}}}p")
            if paragraph is not note.getparent()
        ),
        None,
    )
    if destination is None:
        raise ValueError("source-bound mutation could not locate a second paragraph for note movement")
    note.getparent().remove(note)
    destination.append(note)


def _reorder_divisions(root: etree._Element) -> None:
    body = root.find(f".//{{{TEI_NS}}}body")
    divisions = body.findall(f"./{{{TEI_NS}}}div") if body is not None else []
    if body is None or len(divisions) < 2:
        raise ValueError("source-bound mutation could not locate two body divisions")
    body.remove(divisions[0])
    body.insert(1, divisions[0])


def _drop_prev_next_edge(root: etree._Element) -> None:
    body = root.find(f".//{{{TEI_NS}}}body")
    if body is None:
        raise ValueError("source-bound mutation could not locate the TEI body")
    carrier = next(
        (
            node
            for node in body.iter()
            if "prev" in node.attrib or "next" in node.attrib
        ),
        None,
    )
    if carrier is None:
        raise ValueError("source-bound mutation could not locate a TEI prev/next edge")
    edge = next(name for name in ("prev", "next") if name in carrier.attrib)
    del carrier.attrib[edge]


def _navigation_exception_note(root: etree._Element) -> etree._Element:
    note = root.find(f".//{{{TEI_NS}}}note[@type='unresolved-source-navigation-edge']")
    if note is None:
        raise ValueError("source-bound mutation could not locate an unresolved source-navigation note")
    return note


def _delete_navigation_exception_note(root: etree._Element) -> None:
    note = _navigation_exception_note(root)
    parent = note.getparent()
    if parent is None:
        raise ValueError("source-bound mutation found a detached source-navigation note")
    parent.remove(note)


def _change_navigation_exception_direction(root: etree._Element) -> None:
    note = _navigation_exception_note(root)
    direction = note.find(f".//{{{TEI_NS}}}seg[@type='source-direction']")
    if direction is None:
        raise ValueError("source-bound mutation could not locate the source-navigation direction")
    direction.text = "next" if direction.text != "next" else "prev"


def _change_navigation_exception_value(root: etree._Element) -> None:
    note = _navigation_exception_note(root)
    raw_target = note.find(f".//{{{TEI_NS}}}seg[@type='source-raw-target']")
    if raw_target is None:
        raise ValueError("source-bound mutation could not locate the source-navigation raw target")
    raw_target.text = "law-serious-call-navigation-title-001"


def _change_navigation_exception_carrier(root: etree._Element) -> None:
    note = _navigation_exception_note(root)
    note.set("corresp", "#xxx" if note.get("corresp") != "#xxx" else "#i")


def _false_resolve_to_generated_navigation_title(root: etree._Element) -> None:
    carrier = root.find(f".//{{{TEI_NS}}}div[@{{{XML_NS}}}id='i']")
    if carrier is None:
        raise ValueError("source-bound mutation could not locate the title-page carrier")
    carrier.set("prev", "#law-serious-call-navigation-title-001")


def _invent_absent_navigation_target(root: etree._Element) -> None:
    body = root.find(f".//{{{TEI_NS}}}body")
    carrier = root.find(f".//{{{TEI_NS}}}div[@{{{XML_NS}}}id='i']")
    if body is None or carrier is None:
        raise ValueError("source-bound mutation could not locate the TEI text body and title page")
    invented = etree.Element(f"{{{TEI_NS}}}anchor")
    invented.set(f"{{{XML_NS}}}id", "toc")
    body.insert(0, invented)
    carrier.set("prev", "#toc")


def _change_accountability(package_dir: Path) -> None:
    path = package_dir / "source-accountability.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    feature = record["features"][0]
    feature["text_sha256"] = "0" * 64
    path.write_bytes(_canonical(record))


def _change_date_disposition(package_dir: Path) -> None:
    path = package_dir / "unresolved.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    record = next(
        (item for item in records if item.get("id") == "original-publication-date-conflict"),
        None,
    )
    if record is None or not record.get("observed_claims"):
        raise ValueError("source-bound mutation could not locate unresolved date evidence")
    first_claim = record["observed_claims"][0]
    first_claim["value"] = "1728" if first_claim.get("value") != "1728" else "1729"
    path.write_bytes(b"".join(_canonical(item) for item in records))


def _navigation_record(package_dir: Path) -> tuple[Path, list[dict[str, object]], dict[str, object]]:
    path = package_dir / "unresolved.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    record = next(
        (item for item in records if item.get("category") == "source-navigation-edge"),
        None,
    )
    if record is None:
        raise ValueError("source-bound mutation could not locate an unresolved source-navigation record")
    return path, records, record


def _drop_navigation_unresolved_record(package_dir: Path) -> None:
    path, records, record = _navigation_record(package_dir)
    records.remove(record)
    path.write_bytes(b"".join(_canonical(item) for item in records))


def _change_navigation_unresolved_direction(package_dir: Path) -> None:
    path, records, record = _navigation_record(package_dir)
    record["direction"] = "next" if record.get("direction") != "next" else "prev"
    path.write_bytes(b"".join(_canonical(item) for item in records))


def _change_navigation_unresolved_value(package_dir: Path) -> None:
    path, records, record = _navigation_record(package_dir)
    record["raw_target"] = "law-serious-call-navigation-title-001"
    path.write_bytes(b"".join(_canonical(item) for item in records))


def _change_navigation_unresolved_carrier(package_dir: Path) -> None:
    path, records, record = _navigation_record(package_dir)
    record["carrier_id"] = "xxx" if record.get("carrier_id") != "xxx" else "i"
    path.write_bytes(b"".join(_canonical(item) for item in records))


def _mark_navigation_unresolved_resolved(package_dir: Path) -> None:
    path, records, record = _navigation_record(package_dir)
    record["disposition"] = "resolved-to-generated-navigation-title"
    path.write_bytes(b"".join(_canonical(item) for item in records))


def _change_navigation_accountability(package_dir: Path) -> None:
    path = package_dir / "source-accountability.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    edge = record["source_navigation"]["unresolved_edges"][0]
    edge["direction"] = "next" if edge["direction"] != "next" else "prev"
    path.write_bytes(_canonical(record))


def run_mutation_challenge(
    *,
    repository_root: Path,
    source_manifest_path: Path,
    candidate_path: Path,
) -> dict[str, object]:
    repository_root = repository_root.resolve(strict=True)
    source_manifest_path = source_manifest_path.resolve(strict=True)
    candidate_path = candidate_path.resolve(strict=True)
    try:
        candidate_path.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise ValueError("mutation challenge requires the durable candidate outside the repository")

    sys.path.insert(0, str(repository_root))
    from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate

    source_manifest = SourceManifest.load(
        source_manifest_path,
        repository_root=repository_root,
    )
    candidate = CandidatePackage.load(candidate_path)
    oracle = _load_oracle(repository_root)
    baseline = validate(source_manifest, candidate, oracle)
    if baseline.status != "pass" or baseline.findings:
        raise AssertionError("the unmutated candidate did not pass the bound oracle")

    mutations: tuple[tuple[str, Callable[[Path], None], str], ...] = (
        (
            "omit-scripture-reference",
            lambda package: _mutate_tei(package, _omit_scripture_reference),
            "independent oracle found a candidate body/text/topology/order/attachment mutation",
        ),
        (
            "move-note-attachment",
            lambda package: _mutate_tei(package, _move_note),
            "independent oracle found a candidate body/text/topology/order/attachment mutation",
        ),
        (
            "reorder-divisions",
            lambda package: _mutate_tei(package, _reorder_divisions),
            "independent oracle found a candidate body/text/topology/order/attachment mutation",
        ),
        (
            "drop-prev-next-edge",
            lambda package: _mutate_tei(package, _drop_prev_next_edge),
            "independent oracle found a candidate body/text/topology/order/attachment mutation",
        ),
        (
            "delete-source-navigation-note",
            lambda package: _mutate_tei(package, _delete_navigation_exception_note),
            "candidate TEI source-navigation exception notes are missing, changed, or attached to the wrong carrier",
        ),
        (
            "change-source-navigation-note-direction",
            lambda package: _mutate_tei(package, _change_navigation_exception_direction),
            "candidate TEI source-navigation exception notes are missing, changed, or attached to the wrong carrier",
        ),
        (
            "change-source-navigation-note-value",
            lambda package: _mutate_tei(package, _change_navigation_exception_value),
            "candidate TEI source-navigation exception notes are missing, changed, or attached to the wrong carrier",
        ),
        (
            "change-source-navigation-note-carrier",
            lambda package: _mutate_tei(package, _change_navigation_exception_carrier),
            "candidate TEI source-navigation exception notes are missing, changed, or attached to the wrong carrier",
        ),
        (
            "false-resolve-to-generated-navigation-title",
            lambda package: _mutate_tei(package, _false_resolve_to_generated_navigation_title),
            "independent oracle found a candidate body/text/topology/order/attachment mutation",
        ),
        (
            "invent-source-navigation-target",
            lambda package: _mutate_tei(package, _invent_absent_navigation_target),
            "candidate TEI invents the absent source navigation target 'toc'",
        ),
        (
            "alter-source-accountability",
            _change_accountability,
            "candidate source-accountability does not reconcile every source carrier",
        ),
        (
            "alter-navigation-accountability",
            _change_navigation_accountability,
            "candidate source-accountability does not reconcile every source carrier",
        ),
        (
            "delete-source-navigation-unresolved-record",
            _drop_navigation_unresolved_record,
            "candidate unresolved register changed or omitted an evidence-undecidable issue",
        ),
        (
            "change-source-navigation-unresolved-direction",
            _change_navigation_unresolved_direction,
            "candidate unresolved register changed or omitted an evidence-undecidable issue",
        ),
        (
            "change-source-navigation-unresolved-value",
            _change_navigation_unresolved_value,
            "candidate unresolved register changed or omitted an evidence-undecidable issue",
        ),
        (
            "change-source-navigation-unresolved-carrier",
            _change_navigation_unresolved_carrier,
            "candidate unresolved register changed or omitted an evidence-undecidable issue",
        ),
        (
            "falsely-resolve-source-navigation-unresolved-record",
            _mark_navigation_unresolved_resolved,
            "candidate unresolved register changed or omitted an evidence-undecidable issue",
        ),
        (
            "select-conflicting-date",
            _change_date_disposition,
            "candidate unresolved register changed or omitted an evidence-undecidable issue",
        ),
    )
    outcomes: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="law-serious-call-mutation-") as temporary_root:
        for name, mutate, expected_reason in mutations:
            package_dir = Path(temporary_root) / name
            package_dir.mkdir()
            for member in (*MEMBERS, "manifest.json"):
                shutil.copyfile(candidate_path / member, package_dir / member)
            mutate(package_dir)
            _reseal(package_dir)
            mutated_candidate = CandidatePackage.load(package_dir)
            try:
                validate(source_manifest, mutated_candidate, oracle)
            except ValueError as exc:
                reason = str(exc)
                if expected_reason not in reason:
                    raise AssertionError(
                        f"{name} failed for an unexpected reason: {reason}"
                    ) from exc
                outcomes.append({"case": name, "result": "rejected", "reason": reason})
            else:
                raise AssertionError(f"oracle accepted the resealed {name} mutation")
    return {
        "contract": "ocd-law-serious-call-mutation-challenge-v1",
        "status": "pass",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "baseline": "pass",
        "mutations": outcomes,
        "rights_clearance": "not-decided",
        "human_acceptance": "not-decided",
        "publication": "not-authorized",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    result = run_mutation_challenge(
        repository_root=args.repository_root,
        source_manifest_path=args.manifest,
        candidate_path=args.candidate,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
