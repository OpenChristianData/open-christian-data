"""Independent source and structure checks for the ordered Revised Version corpus."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import io_path
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    _validation_authority_bindings,
)
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
NS = {"tei": TEI_NS}
WORK_ID = "revised-version-with-apocrypha"
EDITION_ID = "revised-version-with-apocrypha-electronic"
RAW_BASE = "raw/clean-ready-acquisition-to-tei/master-3/21/revised-version-with-apocrypha"
EXPECTED_COUNTS = {
    "books": 80,
    "old_testament_books": 39,
    "apocrypha_file_members": 14,
    "apocrypha_units": 15,
    "new_testament_books": 27,
    "chapters": 1362,
    "verses": 36878,
    "source_lines": 47631,
    "poetry_lines": 6884,
    "word_links": 714769,
    "supplied_text_spans": 5131,
    "footnotes": 1336,
    "cross_references": 19,
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _import_closure_sha256() -> str:
    path = Path(__file__).resolve(strict=True)
    return _sha(_canonical([{"path": path.name, "sha256": _sha(path.read_bytes())}]))


def _logical_path(root: Path, logical: str) -> Path:
    return io_path(resolve_repo_path(root, logical)).resolve(strict=True)


def _json_bytes(content: bytes, label: str) -> dict[str, Any]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {label}")
    return value


def _authority_map(manifest: SourceManifest) -> dict[str, Mapping[str, Any]]:
    return {str(item["name"]): item for item in manifest.record["authorities"]}


def _usfm_book_id(data: bytes, path: str) -> str:
    if b"\r" in data or data.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"unsupported USFM encoding or line boundary: {path}")
    text = data.decode("utf-8", errors="strict")
    for line in text.split("\n"):
        if line.startswith("\\id "):
            return line[4:].split(maxsplit=1)[0]
    raise ValueError(f"USFM book identifier is missing: {path}")


def _canonical_xml(node: etree._Element) -> bytes:
    return etree.tostring(node, method="c14n", exclusive=False, with_comments=True)


def _source_lines_from_component(
    component: etree._Element,
    *,
    expected_filename: str,
    expected_lines: list[str],
) -> None:
    found: dict[int, str] = {}
    prefix = f"source-usfm:eng-rv/{expected_filename}#line="
    for node in component.iter():
        pointer = node.get("corresp")
        if pointer is None or not pointer.startswith("source-usfm:"):
            continue
        if "&token=" in pointer:
            continue
        if "#line=" not in pointer:
            continue
        if not pointer.startswith(prefix):
            raise ValueError(
                f"member component contains a source line from another member: {pointer}"
            )
        suffix = pointer[len(prefix) :]
        line_number_text, marker_suffix, marker_kind = suffix.partition(":")
        if marker_suffix and marker_kind == "label" and line_number_text.isdecimal():
            # The existing converter binds the id-label child to the same raw
            # USFM line; the owning line carrier has the exact unsuffixed ID.
            continue
        if not line_number_text.isdecimal() or marker_suffix:
            raise ValueError(f"malformed USFM source line pointer: {pointer}")
        line_number = int(line_number_text)
        raw_notes = node.xpath(
            "./tei:note[@type='source-usfm-raw']", namespaces=NS
        )
        if len(raw_notes) != 1 or raw_notes[0].text is None:
            raise ValueError(f"source pointer lacks one exact raw line note: {pointer}")
        if line_number in found:
            raise ValueError(f"duplicate source line pointer: {pointer}")
        found[line_number] = raw_notes[0].text
    if sorted(found) != list(range(1, len(expected_lines) + 1)):
        raise ValueError(f"USFM source-line coverage differs for {expected_filename}")
    reopened = "\n".join(found[number] for number in range(1, len(expected_lines) + 1))
    if reopened != "\n".join(expected_lines):
        raise ValueError(f"exact USFM line reopening differs for {expected_filename}")


def _check_retained_envelope(
    manifest: SourceManifest,
    *,
    authorities: Mapping[str, Mapping[str, Any]],
    source_receipt: Mapping[str, Any],
) -> None:
    retained = source_receipt.get("retained_files")
    if not isinstance(retained, list) or len(retained) != 107:
        raise ValueError("the exact 107-file retained envelope is not represented")
    raw_authorities = {
        str(item["path"]): item
        for item in authorities.values()
        if str(item.get("path", "")).startswith(f"{RAW_BASE}/")
    }
    expected_paths: set[str] = set()
    for row in retained:
        relative = row.get("path")
        if not isinstance(relative, str):
            raise ValueError("retained envelope row has no path")
        logical = f"{RAW_BASE}/{relative}"
        expected_paths.add(logical)
        authority = raw_authorities.get(logical)
        if authority is None:
            raise ValueError(f"retained envelope authority is absent: {logical}")
        data = manifest.authority_path(str(authority["name"])).read_bytes()
        if (len(data), _sha(data)) != (row.get("bytes"), row.get("sha256")):
            raise ValueError(f"retained envelope member changed: {logical}")
    if set(raw_authorities) != expected_paths:
        raise ValueError("source manifest raw authorities do not equal the 107-file envelope")


def _check_package(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> None:
    record = source_manifest.record
    authorities = _authority_map(source_manifest)
    profile = _json_bytes(
        source_manifest.authority_path("profile").read_bytes(), "profile"
    )
    policy = _json_bytes(
        source_manifest.authority_path("policy").read_bytes(), "policy"
    )
    source_set = _json_bytes(
        source_manifest.authority_path("source-member-set").read_bytes(),
        "retained source-member-set",
    )
    receipt = _json_bytes(
        source_manifest.authority_path("prior-source-receipt").read_bytes(),
        "retained source receipt",
    )
    prior_manifest = _json_bytes(
        source_manifest.authority_path("prior-candidate-manifest").read_bytes(),
        "prior candidate manifest",
    )
    prior_accountability = _json_bytes(
        source_manifest.authority_path("prior-source-accountability").read_bytes(),
        "prior source accountability",
    )
    current_provenance = _json_bytes(
        candidate.member_bytes("provenance.json"), "current candidate provenance"
    )
    current_accountability = _json_bytes(
        candidate.member_bytes("source-accountability.json"),
        "current source accountability",
    )

    if record.get("work_id") != WORK_ID or record.get("edition_id") != EDITION_ID:
        raise ValueError("current source manifest work or edition identity differs")
    if candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("review candidate must remain nonaccepted")
    if candidate.manifest.get("source_id") != record.get("source_id"):
        raise ValueError("candidate source identity differs")
    if profile.get("contract") != "ocd-revised-version-ordered-corpus-profile-v1":
        raise ValueError("source feature profile contract differs")
    if policy.get("contract") != "ocd-revised-version-ordered-corpus-policy-v1":
        raise ValueError("independent validation policy contract differs")
    if len(profile.get("ordered_members", [])) != 80:
        raise ValueError("profile does not declare all 80 ordered source members")

    member_rows = source_set.get("members")
    manifest_members = list(record.get("source_members", ()))
    primary = [
        item
        for item in record.get("authorities", ())
        if item.get("role") == "primary-source"
    ]
    if not isinstance(member_rows, list) or len(member_rows) != 80:
        raise ValueError("retained source-member-set does not declare exactly 80 members")
    if len(manifest_members) != 80 or len(primary) != 80:
        raise ValueError("current source manifest does not declare exactly 80 primary members")
    _check_retained_envelope(source_manifest, authorities=authorities, source_receipt=receipt)

    profile_rows = profile["ordered_members"]
    if len(profile_rows) != 80:
        raise ValueError("feature profile member count differs")
    originals = etree.fromstring(
        source_manifest.authority_path("prior-candidate-tei").read_bytes(),
        parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    original_groups: dict[str, tuple[etree._Element, etree._Element]] = {}
    for group in originals.xpath("./tei:text/tei:body/tei:div", namespaces=NS):
        for book in group.xpath("./tei:div[@type='book']", namespaces=NS):
            book_id = book.get("n")
            if not book_id or book_id in original_groups:
                raise ValueError("prior TEI has missing or duplicate book identities")
            original_groups[book_id] = (group, book)
    if len(original_groups) != 80:
        raise ValueError("prior TEI does not contain all 80 book subtrees")

    current_content = candidate.member_bytes("content.tei.xml")
    try:
        current_root = etree.fromstring(
            current_content,
            parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"ordered corpus is not well-formed TEI XML: {exc}") from exc
    if etree.QName(current_root).localname != "teiCorpus":
        raise ValueError("multi-member candidate root is not teiCorpus")
    if current_root.get(XML_ID) != "revised-version-with-apocrypha-eng-rv-corpus":
        raise ValueError("ordered corpus identity is missing")
    children = current_root.findall(f"{{{TEI_NS}}}TEI")
    if len(children) != 80:
        raise ValueError("teiCorpus must contain one complete TEI child per source member")
    compiled_schema().assertValid(etree.ElementTree(current_root))

    ordered_paths: list[str] = []
    source_line_count = 0
    poetry_line_count = 0
    source_ids: list[str] = []
    group_sizes: Counter[str] = Counter()
    source_set_by_position = {int(row["position"]): row for row in member_rows}
    primary_by_path = {str(item["path"]): item for item in primary}
    if len(primary_by_path) != 80:
        raise ValueError("primary source paths are not unique")

    visible_members = current_provenance.get("members")
    if not isinstance(visible_members, list) or len(visible_members) != 80:
        raise ValueError("provenance does not retain all ordered component identities")

    for position, (child, profile_row, manifest_member, visible_row) in enumerate(
        zip(children, profile_rows, manifest_members, visible_members), start=1
    ):
        sidecar_member = source_set_by_position.get(position)
        if sidecar_member is None or sidecar_member.get("position") != position:
            raise ValueError(f"source-member-set position {position} is missing")
        source_path = str(sidecar_member["path"])
        authority = primary_by_path.get(source_path)
        if authority is None:
            raise ValueError(f"source manifest primary member is missing: {source_path}")
        data = source_manifest.authority_path(str(authority["name"])).read_bytes()
        if (len(data), _sha(data)) != (
            sidecar_member.get("bytes"),
            sidecar_member.get("sha256"),
        ):
            raise ValueError(f"source sidecar and source manifest differ: {source_path}")
        book_id = _usfm_book_id(data, source_path)
        filename = Path(source_path).name
        expected_testament = (
            "old-testament"
            if position <= 39
            else "apocrypha"
            if position <= 53
            else "new-testament"
        )
        expected_head = {
            "old-testament": "Old Testament",
            "apocrypha": "Apocrypha / Deuterocanon",
            "new-testament": "New Testament",
        }[expected_testament]
        expected_tei_id = f"rv-member-{position:03d}-{book_id}"
        expected_profile = {
            "position": position,
            "path": source_path,
            "filename": filename,
            "bytes": len(data),
            "sha256": _sha(data),
            "book_id": book_id,
            "testament": expected_testament,
            "testament_head": expected_head,
            "tei_id": expected_tei_id,
        }
        if dict(profile_row) != expected_profile:
            raise ValueError(f"source feature profile identity differs at member {position}")
        if (
            manifest_member.get("name") != authority.get("name")
            or manifest_member.get("logical_name") != filename
            or manifest_member.get("position") != position
            or manifest_member.get("book_id") != book_id
            or manifest_member.get("sha256") != _sha(data)
            or manifest_member.get("work_id") != WORK_ID
            or manifest_member.get("edition_id") != EDITION_ID
        ):
            raise ValueError(f"source manifest member identity differs at member {position}")
        if (
            visible_row.get("position") != position
            or visible_row.get("member_path") != source_path
            or visible_row.get("member_sha256") != _sha(data)
            or visible_row.get("book_id") != book_id
            or visible_row.get("testament") != expected_testament
            or visible_row.get("tei_xml_id") != expected_tei_id
        ):
            raise ValueError(f"candidate provenance member identity differs at member {position}")

        child_id = child.get(XML_ID)
        if child_id != expected_tei_id or len(child.findall(f"{{{TEI_NS}}}teiHeader")) != 1:
            raise ValueError(f"TEI child identity or header differs at member {position}")
        groups = child.xpath("./tei:text/tei:body/tei:div", namespaces=NS)
        if len(groups) != 1 or groups[0].get("type") != expected_testament:
            raise ValueError(f"testament grouping differs at member {position}")
        headings = groups[0].xpath("./tei:head/text()", namespaces=NS)
        if headings != [expected_head]:
            raise ValueError(f"testament heading differs at member {position}")
        books = groups[0].xpath("./tei:div[@type='book']", namespaces=NS)
        if len(books) != 1 or books[0].get("n") != book_id:
            raise ValueError(f"member TEI does not contain exactly {book_id}")
        original_group, original_book = original_groups.get(book_id, (None, None))
        if original_group is None or original_book is None:
            raise ValueError(f"prior candidate body lacks {book_id}")
        if original_group.get("type") != expected_testament:
            raise ValueError(f"prior testament group differs for {book_id}")
        original_head = original_group.xpath("./tei:head/text()", namespaces=NS)
        if original_head != [expected_head]:
            raise ValueError(f"prior testament heading differs for {book_id}")
        if _canonical_xml(books[0]) != _canonical_xml(original_book):
            raise ValueError(f"existing book subtree changed during corpus composition: {book_id}")
        if any(
            any(
                witness_id in pointer.partition("#")[0]
                for witness_id in ("TOB_RV", "ESG_RV", "1895", "1913")
            )
            for pointer in books[0].xpath(".//@corresp")
        ):
            raise ValueError(f"non-USFM witness text entered candidate book {book_id}")
        lines = data.decode("utf-8", errors="strict").split("\n")
        poetry_line_count += sum(
            1 for line in lines if re.fullmatch(r"\\q[12](?:[ \t].*)?", line)
        )
        _source_lines_from_component(
            child, expected_filename=filename, expected_lines=lines
        )
        source_line_count += len(lines)
        ordered_paths.append(source_path)
        source_ids.append(book_id)
        group_sizes[expected_testament] += 1

    expected_paths = [str(row["path"]) for row in member_rows]
    if ordered_paths != expected_paths:
        raise ValueError("teiCorpus order differs from retained source-member-set order")
    if source_ids != [str(row["book_id"]) for row in profile_rows]:
        raise ValueError("TEI component order differs from source book identity order")
    if group_sizes != Counter(
        {"old-testament": 39, "apocrypha": 14, "new-testament": 27}
    ):
        raise ValueError("testament source-member accounting differs")

    observed_counts = {
        "books": len(current_root.xpath(".//tei:div[@type='book']", namespaces=NS)),
        "old_testament_books": group_sizes["old-testament"],
        "apocrypha_file_members": group_sizes["apocrypha"],
        "apocrypha_units": group_sizes["apocrypha"] + 1,
        "new_testament_books": group_sizes["new-testament"],
        "chapters": len(current_root.xpath(".//tei:div[@type='chapter']", namespaces=NS)),
        "verses": len(current_root.xpath(".//tei:ab[@type='verse']", namespaces=NS)),
        "source_lines": source_line_count,
        "poetry_lines": poetry_line_count,
        "word_links": len(current_root.xpath(".//tei:w", namespaces=NS)),
        "supplied_text_spans": len(current_root.xpath(".//tei:supplied", namespaces=NS)),
        "footnotes": len(current_root.xpath(".//tei:note[@type='footnote']", namespaces=NS)),
        "cross_references": len(current_root.xpath(".//tei:note[@type='cross-reference']", namespaces=NS)),
    }
    if observed_counts != EXPECTED_COUNTS:
        raise ValueError(f"ordered corpus structural counts differ: {observed_counts}")
    if dict(prior_accountability.get("text_counts", {})) != {
        key: value for key, value in EXPECTED_COUNTS.items() if key != "books"
    }:
        raise ValueError("current source counts differ from the existing accountability record")

    baruch = current_root.xpath(".//tei:div[@type='book' and @n='BAR']", namespaces=NS)
    jeremy = current_root.xpath(
        ".//tei:div[@type='chapter' and @n='6' and @ana='#epistle-of-jeremy']",
        namespaces=NS,
    )
    if len(baruch) != 1 or len(jeremy) != 1 or jeremy[0].getparent() is None:
        raise ValueError("embedded Epistle of Jeremy boundary is not preserved in Baruch 6")

    if current_accountability.get("contract") != "ocd-revised-version-ordered-corpus-accountability-v1":
        raise ValueError("current source-accountability contract differs")
    if current_accountability.get("content_tei_sha256") != _sha(current_content):
        raise ValueError("current source-accountability does not bind candidate TEI bytes")
    if current_accountability.get("current_checks") != "pending independent validation":
        raise ValueError("candidate package overstates independent validation status")
    if current_accountability.get("human_acceptance") != "not recorded":
        raise ValueError("candidate package overstates human acceptance")
    if current_provenance.get("source_edition") != receipt.get("source_edition"):
        raise ValueError("source edition provenance differs from retained receipt")
    if current_provenance.get("source_manifest", {}).get("sha256") != source_manifest.sha256:
        raise ValueError("candidate provenance does not bind current source manifest")
    if current_provenance.get("profile_sha256") != source_manifest.record.get("profile_sha256"):
        raise ValueError("candidate provenance does not bind current source profile")
    if prior_manifest.get("status") != "nonaccepted":
        raise ValueError("prior candidate did not retain nonaccepted status")
    unresolved = candidate.member_bytes("unresolved.jsonl").splitlines()
    prior_unresolved = _json_bytes(
        source_manifest.authority_path("prior-unresolved").read_bytes(),
        "prior unresolved questions",
    )
    unresolved_rows = [_json_bytes(line, "unresolved item") for line in unresolved]
    if [row.get("question") for row in unresolved_rows] != prior_unresolved.get("items"):
        raise ValueError("identity and witness questions were not preserved exactly")
    if any(row.get("status") != "open" for row in unresolved_rows):
        raise ValueError("an unresolved identity or witness question was silently closed")
    readme = candidate.member_bytes("README.source.md").decode("utf-8")
    if "https://ebible.org/find/show.php?id=eng-rv" not in readme or "public domain" not in readme:
        raise ValueError("visible source notice omits the retained provider identity or license")


def _oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> Mapping[str, object]:
    _check_package(source_manifest, candidate)
    bindings = _validation_authority_bindings(source_manifest)
    validator = source_manifest.record["validator"]
    facts = MechanicalFacts(
        validator_implementation_sha256=str(validator["implementation_sha256"]),
        validator_import_closure_sha256=str(validator["import_closure_sha256"]),
        source_sha256=bindings["source_sha256"],
        profile_sha256=bindings["profile_sha256"],
        package_schema_sha256=bindings["package_schema_sha256"],
        xsd_sha256=bindings["xsd_sha256"],
        policy_sha256=bindings["policy_sha256"],
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = "ocd-revised-version-ordered-corpus-independent-oracle"
_oracle.oracle_version = "1"
