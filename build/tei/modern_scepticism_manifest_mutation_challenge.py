"""Challenge the PG42957 source oracle with schema-valid candidate mutations."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
from lxml import etree


ROOT = Path(__file__).resolve().parents[2]
TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        remove_blank_text=False,
    )


def _mutate(root: etree._Element, name: str) -> dict[str, str]:
    if name == "body_wording":
        paragraphs = root.xpath(
            "//t:text/t:body//t:p[string-length(normalize-space(string(.))) > 0]",
            namespaces=NS,
        )
        if not paragraphs:
            raise ValueError("body_wording mutation has no paragraph carrier")
        paragraph = paragraphs[0]
        paragraph.text = (paragraph.text or "") + " [oracle challenge]"
        return {"locator": "first nonempty body paragraph", "change": "append text"}

    if name == "carrier_omission":
        paragraphs = root.xpath(
            "//t:text/t:body/t:div[@type='lecture'][1]/t:p[normalize-space(string(.))]",
            namespaces=NS,
        )
        if not paragraphs:
            raise ValueError("carrier_omission mutation has no lecture paragraph")
        paragraph = paragraphs[0]
        paragraph.getparent().remove(paragraph)
        return {"locator": "first lecture's first nonempty paragraph", "change": "remove paragraph"}

    if name == "carrier_reorder":
        body = root.find(f"{{{TEI}}}text/{{{TEI}}}body")
        if body is None:
            raise ValueError("carrier_reorder mutation has no TEI body")
        divisions = body.findall(f"{{{TEI}}}div")
        if len(divisions) < 2:
            raise ValueError("carrier_reorder mutation needs two divisions")
        second = divisions[1]
        body.remove(second)
        body.insert(0, second)
        return {"locator": "first two top-level body divisions", "change": "swap order"}

    if name == "page_marker_omission":
        markers = root.xpath(
            "//t:text//*[@type='page_milestone']",
            namespaces=NS,
        )
        if not markers:
            raise ValueError("page_marker_omission mutation has no page marker")
        marker = markers[0]
        marker.getparent().remove(marker)
        return {"locator": "first identified page milestone", "change": "remove marker"}

    if name == "page_marker_alteration":
        markers = root.xpath(
            "//t:text//*[@type='page_milestone']",
            namespaces=NS,
        )
        if not markers:
            raise ValueError("page_marker_alteration mutation has no page marker")
        markers[0].set("n", "oracle-challenge")
        return {"locator": "first identified page milestone", "change": "alter page label"}

    if name == "note_misattachment":
        references = root.xpath(
            "//t:text//*[@type='note_reference']",
            namespaces=NS,
        )
        if len(references) < 2:
            raise ValueError("note_misattachment mutation needs two note references")
        first, second = references[:2]
        first_target, second_target = first.get("target"), second.get("target")
        if not first_target or not second_target or first_target == second_target:
            raise ValueError("note_misattachment mutation has indistinguishable targets")
        first.set("target", second_target)
        second.set("target", first_target)
        return {"locator": "first two note references", "change": "swap note targets"}

    if name == "link_target_change":
        links = root.xpath(
            "//t:text//t:ref[@target='#Page_1']",
            namespaces=NS,
        )
        if not links:
            raise ValueError("link_target_change mutation has no bound source link")
        links[0].set("target", "#Page_33")
        return {"locator": "first source link to #Page_1", "change": "retarget to #Page_33"}

    if name == "table_cell_change":
        cells = root.xpath("//t:text//t:table/t:row/t:cell", namespaces=NS)
        if not cells:
            raise ValueError("table_cell_change mutation has no table cell")
        cells[0].text = (cells[0].text or "") + " [oracle challenge]"
        return {"locator": "first table cell", "change": "append text"}

    if name == "lecture_division_type":
        divisions = root.xpath(
            "//t:text/t:body/t:div[@type='lecture']",
            namespaces=NS,
        )
        if len(divisions) != 11:
            raise ValueError("lecture_division_type mutation found an unexpected lecture count")
        divisions[0].set("type", "oracle-challenge-lecture")
        return {"locator": "first top-level lecture division", "change": "alter division type"}

    if name == "invent_aggregate_author":
        title_statements = root.xpath(
            "/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt",
            namespaces=NS,
        )
        if len(title_statements) != 1:
            raise ValueError("invent_aggregate_author mutation needs one title statement")
        statement = title_statements[0]
        title = statement.find(f"{{{TEI}}}title")
        if title is None:
            raise ValueError("invent_aggregate_author mutation has no title")
        author = etree.Element(f"{{{TEI}}}author")
        author.text = "Christian Evidence Society"
        statement.insert(statement.index(title) + 1, author)
        return {"locator": "TEI titleStmt", "change": "insert aggregate author"}

    raise ValueError(f"unknown PG42957 mutation {name!r}")


MUTATIONS = (
    ("body_wording", ("complete normalized body text differs",)),
    ("carrier_omission", ("ordered HTML carrier mapping differs",)),
    ("carrier_reorder", ("eleven-lecture and explanatory-paper divisions differ",)),
    ("page_marker_omission", ("page milestone identity, label, or order differs",)),
    ("page_marker_alteration", ("page milestone identity, label, or order differs",)),
    ("note_misattachment", ("footnote reference identity, target, or order differs",)),
    ("link_target_change", ("source hyperlinks or their order differ",)),
    ("table_cell_change", ("table row/cell text or order differs",)),
    ("lecture_division_type", ("eleven-lecture and explanatory-paper divisions differ",)),
    ("invent_aggregate_author", ("aggregate author is not source-established",)),
)


def _bound_oracle(source_manifest: Any):
    binding = source_manifest.record["validator"]
    path = source_manifest.authority_path("independent-oracle")
    if _sha(path.read_bytes()) != binding["implementation_sha256"]:
        raise ValueError("bound PG42957 oracle bytes drifted")
    name = f"_ocd_pg42957_mutation_oracle_{binding['implementation_sha256']}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("bound PG42957 oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    oracle = getattr(module, binding["callable"], None)
    if not callable(oracle):
        raise ValueError("bound PG42957 oracle callable is absent")
    return oracle


def _validate_package_shapes(source_manifest: Any, candidate: Any) -> None:
    package_schema = json.loads(
        source_manifest.authority_path("candidate-package-schema").read_text(encoding="utf-8")
    )
    package_record = json.loads((candidate.path / "manifest.json").read_text(encoding="utf-8"))
    Draft202012Validator(package_schema).validate(package_record)

    accountability_schema = json.loads(
        source_manifest.authority_path("accountability-schema").read_text(encoding="utf-8")
    )
    accountability = json.loads(
        (candidate.path / "source-accountability.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(accountability_schema).validate(accountability)

    content = (candidate.path / "content.tei.xml").read_bytes()
    tree = etree.ElementTree(etree.fromstring(content, _parser()))
    xsd = etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path("tei-validation-schema")), _parser())
    )
    if not xsd.validate(tree):
        raise ValueError(f"mutated candidate failed TEI XSD: {xsd.error_log[0]}")
    relaxng = etree.RelaxNG(
        etree.parse(str(source_manifest.authority_path("tei-p5-relaxng")), _parser())
    )
    if not relaxng.validate(tree):
        raise ValueError(f"mutated candidate failed TEI P5 Relax NG: {relaxng.error_log[0]}")


def _build_mutant(source_package: Any, destination: Path, name: str, contract: Any):
    destination.mkdir()
    for member in source_package.member_names:
        shutil.copyfile(source_package.path / member, destination / member)

    content_path = destination / "content.tei.xml"
    tree = etree.parse(str(content_path), _parser())
    details = _mutate(tree.getroot(), name)
    content = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    content_path.write_bytes(content)

    manifest_path = destination / "manifest.json"
    package_record = json.loads(manifest_path.read_text(encoding="utf-8"))
    for member in package_record["members"]:
        if member["name"] == "content.tei.xml":
            member["bytes"] = len(content)
            member["sha256"] = _sha(content)
            break
    else:
        raise ValueError("candidate package manifest does not bind content.tei.xml")
    package_record["members"].sort(key=lambda item: item["name"])
    manifest_path.write_bytes(_canonical(package_record))
    return contract.CandidatePackage.load(destination), details


def run(*, manifest_path: str | Path, candidate_path: str | Path, receipt_path: str | Path) -> dict[str, object]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from ocd_kernel.reconstruction import contract

    source_manifest = contract.SourceManifest.load(manifest_path, repository_root=ROOT)
    candidate = contract.CandidatePackage.load(candidate_path)
    if candidate.path.name != "package":
        raise ValueError("mutation challenge candidate must be a run's package directory")
    candidate_root = candidate.path.parent.parent.resolve(strict=True)
    if candidate_root.parent.name != "candidate-reviews":
        raise ValueError("mutation challenge candidate must live under candidate-reviews")
    try:
        candidate_root.relative_to(ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise ValueError("mutation challenge candidate root must be outside the repository")

    oracle = _bound_oracle(source_manifest)
    baseline = contract.validate(source_manifest, candidate, oracle)
    if baseline.status != "pass":
        raise ValueError("PG42957 valid baseline did not pass the bound oracle")

    requested_receipt = Path(receipt_path).absolute()
    if requested_receipt.is_symlink() or requested_receipt.exists():
        raise ValueError(f"refusing to overwrite mutation receipt: {requested_receipt}")
    receipt_parent = requested_receipt.parent.resolve(strict=True)
    try:
        receipt_parent.relative_to(candidate_root)
    except ValueError as error:
        raise ValueError("mutation receipt and temporary outputs must stay within this candidate root") from error
    if not receipt_parent.is_dir():
        raise ValueError("mutation receipt parent must already exist")
    receipt = receipt_parent / requested_receipt.name
    if receipt.is_symlink() or receipt.exists():
        raise ValueError(f"refusing to overwrite mutation receipt: {receipt}")

    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="pg42957-mutation-", dir=receipt.parent) as scratch:
        scratch_root = Path(scratch)
        for index, (name, expected_findings) in enumerate(MUTATIONS, 1):
            package_path = scratch_root / f"{index:02d}-{name}"
            mutant, details = _build_mutant(candidate, package_path, name, contract)
            _validate_package_shapes(source_manifest, mutant)
            oracle_result = dict(oracle(source_manifest, mutant))
            findings = oracle_result.get("findings")
            if oracle_result.get("status") != "fail" or not isinstance(findings, list):
                raise ValueError(f"mutation {name} did not fail the bound oracle")
            if not any(
                hint in finding
                for hint in expected_findings
                for finding in findings
            ):
                raise ValueError(
                    f"mutation {name} failed for an unexpected reason: {findings}"
                )
            try:
                contract.validate(source_manifest, mutant, oracle)
            except ValueError as error:
                if str(error) != "candidate validation failed":
                    raise
                rejected = True
                rejection = str(error)
            else:
                rejected = False
                rejection = "accepted"
            if not rejected:
                raise ValueError(f"generic reconstruction contract accepted mutation {name}")
            results.append(
                {
                    "candidate_manifest_sha256": mutant.sha256,
                    "expected_finding_fragments": list(expected_findings),
                    "findings": findings,
                    "generic_contract": {"rejected": rejected, "reason": rejection},
                    "name": name,
                    "schema_validation": "pass",
                    "tei_sha256": _sha(mutant.member_bytes("content.tei.xml")),
                    **details,
                }
            )

    record: dict[str, object] = {
        "baseline_candidate_sha256": candidate.sha256,
        "baseline_validation_sha256": baseline.sha256,
        "contract": "ocd-pg42957-mutation-challenge-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mutation_count": len(results),
        "mutations": results,
        "source_manifest_sha256": source_manifest.sha256,
        "status": "pass",
    }
    record["receipt_sha256"] = _sha(_canonical(record))
    with receipt.open("xb") as output:
        output.write(_canonical(record))
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    result = run(
        manifest_path=args.manifest,
        candidate_path=args.candidate,
        receipt_path=args.receipt,
    )
    sys.stdout.buffer.write(_canonical(result))


if __name__ == "__main__":
    main()
