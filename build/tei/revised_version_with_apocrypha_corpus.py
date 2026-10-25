"""Package the existing Revised Version TEI as an ordered TEI corpus.

This route composes the already reconstructed, retained USFM candidate into
one TEI document per selected source member. It does not acquire or download
source material. The source-member order is taken from the existing library
sidecar and checked against the exact current source bytes.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import io_path
from ocd_kernel.reconstruction.contract import SourceManifest


WORK_ID = "revised-version-with-apocrypha"
FORM_ID = "revised-version-with-apocrypha-retained-en"
EDITION_ID = "revised-version-with-apocrypha-electronic"
ACQUISITION_ID = "revised-version-with-apocrypha-acquired"
SOURCE_ID = "revised-version-with-apocrypha-engrv5-retained-set-v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
NS = {"tei": TEI_NS}

WORK_PATH = f"library/works/{WORK_ID}/work.json"
STATE_PATH = f"library/works/{WORK_ID}/state.json"
MEMBER_SET_PATH = (
    f"library/works/{WORK_ID}/forms/{FORM_ID}/editions/{EDITION_ID}/"
    "source-member-set.json"
)
ACQUISITION_PATH = (
    f"library/works/{WORK_ID}/forms/{FORM_ID}/editions/{EDITION_ID}/"
    f"acquisitions/{ACQUISITION_ID}.json"
)
SOURCE_CONFIG_PATH = f"sources/structured-text/{WORK_ID}/config.json"
SOURCE_DIR = f"sources/structured-text/{WORK_ID}/corpus-v4"
MANIFEST_PATH = f"{SOURCE_DIR}/reconstruction-source-manifest.json"
PROFILE_PATH = f"{SOURCE_DIR}/profile.json"
POLICY_PATH = f"{SOURCE_DIR}/policy.json"
README_PATH = f"{SOURCE_DIR}/README.source.md"
STATE_SNAPSHOT_PATH = f"{SOURCE_DIR}/work-state-at-reconstruction.json"
OLD_CANDIDATE_DIR = (
    "reports/clean-ready-acquisition-to-tei/master-3/21/"
    f"{WORK_ID}/candidate"
)
RAW_BASE = "raw/clean-ready-acquisition-to-tei/master-3/21/revised-version-with-apocrypha"
PACKAGE_SCHEMA_PATH = "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
TEI_SCHEMA_PATH = "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
PACKAGER_PATH = "build/tei/revised_version_with_apocrypha_corpus.py"
ORACLE_PATH = "build/tei/revised_version_with_apocrypha_corpus_oracle.py"
UPSTREAM_PATH = "build/tei/revised_version_with_apocrypha.py"

CONVERTER_ID = "ocd-revised-version-existing-tei-to-ordered-corpus"
CONVERTER_VERSION = "1"
ORACLE_ID = "ocd-revised-version-ordered-corpus-independent-oracle"
ORACLE_VERSION = "1"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _logical_path(root: Path, logical: str) -> Path:
    return io_path(resolve_repo_path(root, logical)).resolve(strict=True)


def _read_bytes(root: Path, logical: str) -> bytes:
    return _logical_path(root, logical).read_bytes()


def _read_json(root: Path, logical: str) -> dict[str, Any]:
    value = json.loads(_read_bytes(root, logical).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object at {logical}")
    return value


def _book_id(source_bytes: bytes, label: str) -> str:
    if source_bytes.startswith(b"\xef\xbb\xbf") or b"\r" in source_bytes:
        raise ValueError(f"unsupported USFM encoding or line endings: {label}")
    text = source_bytes.decode("utf-8", errors="strict")
    for line in text.split("\n"):
        if line.startswith("\\id "):
            value = line[4:].split(maxsplit=1)[0]
            if not re.fullmatch(r"[A-Z0-9]{3}", value):
                raise ValueError(f"invalid USFM book identifier in {label}: {value!r}")
            return value
    raise ValueError(f"USFM book identifier is missing: {label}")


def _member_rows(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    member_set = _read_json(root, MEMBER_SET_PATH)
    if member_set.get("contract") != "ocd-retained-source-member-set-v1":
        raise ValueError("retained source-member-set contract changed")
    members = member_set.get("members")
    if not isinstance(members, list) or len(members) != 80:
        raise ValueError("expected the exact 80-member retained USFM set")
    rows: list[dict[str, Any]] = []
    for expected_position, member in enumerate(members, start=1):
        if not isinstance(member, dict) or member.get("position") != expected_position:
            raise ValueError("source-member-set positions are not complete and ordered")
        path = member.get("path")
        if not isinstance(path, str) or not path.endswith(".usfm"):
            raise ValueError("source-member-set contains a non-USFM textual member")
        data = _read_bytes(root, path)
        if len(data) != member.get("bytes") or _sha(data) != member.get("sha256"):
            raise ValueError(f"retained USFM member changed: {path}")
        book_id = _book_id(data, path)
        testament = (
            "old-testament"
            if expected_position <= 39
            else "apocrypha"
            if expected_position <= 53
            else "new-testament"
        )
        group_head = {
            "old-testament": "Old Testament",
            "apocrypha": "Apocrypha / Deuterocanon",
            "new-testament": "New Testament",
        }[testament]
        rows.append(
            {
                "position": expected_position,
                "path": path,
                "filename": Path(path).name,
                "bytes": len(data),
                "sha256": _sha(data),
                "book_id": book_id,
                "testament": testament,
                "testament_head": group_head,
                "tei_id": f"rv-member-{expected_position:03d}-{book_id}",
            }
        )
    if len({row["book_id"] for row in rows}) != 80:
        raise ValueError("the retained USFM order contains duplicate book identifiers")
    return member_set, rows


def _authority(
    root: Path,
    authorities: list[dict[str, Any]],
    name: str,
    path: str,
    role: str,
    *,
    content: bytes | None = None,
    work_ids: list[str] | None = None,
) -> dict[str, Any]:
    data = content if content is not None else _read_bytes(root, path)
    record: dict[str, Any] = {
        "name": name,
        "path": path,
        "role": role,
        "bytes": len(data),
        "sha256": _sha(data),
    }
    if work_ids is not None:
        record["work_ids"] = work_ids
    authorities.append(record)
    return record


def _profile_and_policy(root: Path) -> tuple[bytes, bytes, bytes, list[dict[str, Any]]]:
    member_set, rows = _member_rows(root)
    config = _read_json(root, SOURCE_CONFIG_PATH)
    old_accountability = _read_json(root, f"{OLD_CANDIDATE_DIR}/source-accountability.json")
    old_manifest = _read_json(root, f"{OLD_CANDIDATE_DIR}/manifest.json")
    old_receipt = _read_json(root, f"{OLD_CANDIDATE_DIR}/source-receipt.json")
    member_set_bytes = _read_bytes(root, MEMBER_SET_PATH)
    old_tei = _read_bytes(root, f"{OLD_CANDIDATE_DIR}/content.tei.xml")

    profile = {
        "contract": "ocd-revised-version-ordered-corpus-profile-v1",
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "source_id": SOURCE_ID,
        "source_edition": config["source_edition"],
        "source_member_set": {
            "contract": member_set["contract"],
            "path": MEMBER_SET_PATH,
            "sha256": _sha(member_set_bytes),
            "member_count": len(rows),
            "order_field": "position",
        },
        "ordered_members": rows,
        "groups": [
            {"testament": "old-testament", "member_positions": [1, 39]},
            {"testament": "apocrypha", "member_positions": [40, 53]},
            {"testament": "new-testament", "member_positions": [54, 80]},
        ],
        "prior_candidate": {
            "path": f"{OLD_CANDIDATE_DIR}/content.tei.xml",
            "sha256": _sha(old_tei),
            "candidate_manifest_sha256": _sha(
                _read_bytes(root, f"{OLD_CANDIDATE_DIR}/manifest.json")
            ),
            "candidate_id": old_manifest.get("candidate_id"),
            "source_accountability_sha256": _sha(
                _read_bytes(root, f"{OLD_CANDIDATE_DIR}/source-accountability.json")
            ),
        },
        "prior_accounting": old_accountability.get("text_counts"),
        "prior_retained_envelope": {
            "file_count": old_receipt.get("retained_file_count"),
            "inventory_sha256": old_receipt.get("retained_file_inventory_sha256"),
        },
        "preservation_contract": {
            "one_child_TEI_per_ordered_USFM_member": True,
            "member_book_subtree_is_copied_from_the_existing_candidate": True,
            "member_book_subtree_order_matches_source_member_set": True,
            "source_usfm_line_notes_must_reopen_byte_exactly": True,
            "print_prelims_projected": False,
            "replacement_scans_projected": False,
            "human_acceptance": "not recorded",
            "rights_clearance": "not established by this technical route",
        },
    }
    profile_bytes = _canonical(profile)
    policy = {
        "contract": "ocd-revised-version-ordered-corpus-policy-v1",
        "scope": "The exact existing eBible ENGRV5/eng-rv retained candidate and its 80-member USFM source set.",
        "required_checks": [
            "all 80 current retained USFM member hashes and positions match the work sidecar",
            "the new teiCorpus has exactly one TEI child for each source member in source order",
            "each child contains exactly its corresponding existing book subtree without body edits",
            "every retained USFM line reopens exactly from its source-usfm-raw carrier",
            "the teiCorpus validates against the bound TEI P5 schema",
            "no print scan or replacement scan content enters the candidate",
            "the electronic identity, human acceptance, and rights questions remain separately recorded",
        ],
        "forbidden_import_prefixes": [
            "build.tei.revised_version_with_apocrypha",
            "build.tei.revised_version_with_apocrypha_corpus",
        ],
        "mutation_controls": [
            "visible body-text mutation must fail against the existing member subtree",
            "raw source-line mutation must fail exact retained-source reopening",
            "source-member reorder must fail ordered-member composition",
        ],
    }
    readme = (
        "# Revised Version with Apocrypha — source description\n\n"
        "The textual authority is the retained eBible structured USFM edition, "
        "resource ENGRV5 / `eng-rv`, identified by its retained official details "
        "page as *Revised Version with Apocrypha (1895)*. The edition page is "
        "https://ebible.org/find/show.php?id=eng-rv and identifies the source as "
        "public domain. The source was updated 2026-08-08.\n\n"
        "This candidate binds the complete ordered set of 80 extracted USFM book "
        "members. The 1895 and 1913 scans, the Tobit and Greek Esther replacement "
        "scans, print-only prelims, and other retained envelope files are evidence "
        "only; their text is not projected into the TEI. This source description "
        "does not claim exact print equivalence, human acceptance, or rights "
        "clearance for a separate publication.\n\n"
        "The manifest includes `work-state-at-reconstruction.json`, a frozen copy "
        "of the work state when this reconstruction contract was created. It is "
        "evidence for that run and does not replace the mutable canonical "
        "`library/works/revised-version-with-apocrypha/state.json`.\n"
    ).encode("utf-8")
    return profile_bytes, _canonical(policy), readme, rows


def build_source_manifest(root: Path) -> tuple[bytes, dict[str, bytes]]:
    root = Path(root).resolve(strict=True)
    profile_bytes, policy_bytes, readme_bytes, rows = _profile_and_policy(root)
    member_set_bytes = _read_bytes(root, MEMBER_SET_PATH)
    member_set_hash = _sha(member_set_bytes)
    old_receipt = _read_json(root, f"{OLD_CANDIDATE_DIR}/source-receipt.json")
    work = _read_json(root, WORK_PATH)
    state_snapshot_bytes = _read_bytes(root, STATE_PATH)
    if work.get("work_id") != WORK_ID:
        raise ValueError("current work identity differs")
    authorities: list[dict[str, Any]] = []

    profile_authority = _authority(
        root, authorities, "profile", PROFILE_PATH,
        "complete-source-feature-profile", content=profile_bytes,
    )
    policy_authority = _authority(
        root, authorities, "policy", POLICY_PATH,
        "independent-validation-policy", content=policy_bytes,
    )
    _authority(root, authorities, "readme", README_PATH, "source-description", content=readme_bytes)
    _authority(root, authorities, "work", WORK_PATH, "work-identity-config", work_ids=[WORK_ID])
    # Keep workflow state as an immutable input snapshot. The canonical state
    # advances during review and acceptance, so pinning its mutable path would
    # make this manifest unverifiable immediately after promotion.
    _authority(
        root,
        authorities,
        "state-snapshot",
        STATE_SNAPSHOT_PATH,
        "work-state-snapshot",
        content=state_snapshot_bytes,
        work_ids=[WORK_ID],
    )
    _authority(root, authorities, "acquisition", ACQUISITION_PATH, "acquisition-selection-authority", work_ids=[WORK_ID])
    _authority(root, authorities, "source-member-set", MEMBER_SET_PATH, "retained-member-set")
    _authority(root, authorities, "source-config", SOURCE_CONFIG_PATH, "source-identity-config")
    _authority(root, authorities, "candidate-package-schema", PACKAGE_SCHEMA_PATH, "candidate-package-schema")
    _authority(root, authorities, "tei-validation-schema", TEI_SCHEMA_PATH, "tei-validation-schema")
    _authority(root, authorities, "candidate-packager", PACKAGER_PATH, "converter-implementation")
    _authority(root, authorities, "upstream-tei-builder", UPSTREAM_PATH, "existing-candidate-producer")
    _authority(root, authorities, "candidate-oracle", ORACLE_PATH, "independent-validator-implementation")
    _authority(root, authorities, "reconstruction-contract", "ocd_kernel/reconstruction/contract.py", "validation-runtime")
    _authority(root, authorities, "mechanical-verifier", "ocd_kernel/reconstruction/verifier.py", "validation-runtime")
    _authority(root, authorities, "tei-validator", "ocd_kernel/tei/validate.py", "validation-runtime")
    _authority(root, authorities, "prior-candidate-manifest", f"{OLD_CANDIDATE_DIR}/manifest.json", "prior-candidate-evidence")
    _authority(root, authorities, "prior-candidate-validation", f"{OLD_CANDIDATE_DIR}/validation.json", "prior-candidate-evidence")
    _authority(root, authorities, "prior-source-accountability", f"{OLD_CANDIDATE_DIR}/source-accountability.json", "prior-candidate-evidence")
    _authority(root, authorities, "prior-source-receipt", f"{OLD_CANDIDATE_DIR}/source-receipt.json", "source-acquisition-evidence")
    _authority(root, authorities, "prior-unresolved", f"{OLD_CANDIDATE_DIR}/unresolved.json", "prior-candidate-evidence")
    _authority(root, authorities, "prior-witness-boundaries", f"{OLD_CANDIDATE_DIR}/witness-boundaries.json", "prior-candidate-evidence")
    _authority(root, authorities, "prior-candidate-tei", f"{OLD_CANDIDATE_DIR}/content.tei.xml", "existing-candidate-input")

    primary_by_path: dict[str, dict[str, Any]] = {}
    source_members: list[dict[str, Any]] = []
    for row in rows:
        path = row["path"]
        record = _authority(
            root, authorities, f"usfm-{row['position']:03d}", path,
            "primary-source", work_ids=[WORK_ID],
        )
        primary_by_path[path] = record
        source_members.append(
            {
                "name": record["name"],
                "logical_name": row["filename"],
                "path": path,
                "role": "primary-source",
                "position": row["position"],
                "book_id": row["book_id"],
                "work_id": WORK_ID,
                "edition_id": EDITION_ID,
                "bytes": record["bytes"],
                "sha256": record["sha256"],
                "identity_resolution_evidence": {
                    "path": MEMBER_SET_PATH,
                    "sha256": member_set_hash,
                    "position": row["position"],
                },
            }
        )

    observed_support = 0
    for index, retained in enumerate(old_receipt["retained_files"], start=1):
        relative = retained["path"]
        logical = f"{RAW_BASE}/{relative}"
        if logical in primary_by_path:
            record = primary_by_path[logical]
            if (record["bytes"], record["sha256"]) != (retained["bytes"], retained["sha256"]):
                raise ValueError(f"retained envelope and selected source differ: {logical}")
            continue
        data = _read_bytes(root, logical)
        if len(data) != retained["bytes"] or _sha(data) != retained["sha256"]:
            raise ValueError(f"retained support evidence changed: {logical}")
        _authority(
            root, authorities, f"retained-envelope-{index:03d}", logical,
            "source-acquisition-evidence", content=data,
        )
        observed_support += 1
    if len(rows) + observed_support != old_receipt.get("retained_file_count"):
        raise ValueError("the current retained source envelope is not fully accounted")

    # Keep repository-local paths unprefixed so their repository-relative
    # authority identities remain portable on Windows.
    xsd_dir = root / "ocd_kernel/tei/vendor/xsd"
    for path in sorted(xsd_dir.glob("*.xsd")):
        logical = path.relative_to(root).as_posix()
        if logical == TEI_SCHEMA_PATH:
            continue
        data = path.read_bytes()
        _authority(
            root, authorities, f"tei-schema-dependency-{path.stem}", logical,
            "tei-validation-schema-dependency", content=data,
        )

    oracle_path = _logical_path(root, ORACLE_PATH)
    oracle_closure = _sha(
        _canonical([{"path": oracle_path.name, "sha256": _sha(oracle_path.read_bytes())}])
    )
    package_schema_record = next(x for x in authorities if x["name"] == "candidate-package-schema")
    validator_record = next(x for x in authorities if x["name"] == "candidate-oracle")
    packager_record = next(x for x in authorities if x["name"] == "candidate-packager")
    package_schema = {"path": PACKAGE_SCHEMA_PATH, "sha256": package_schema_record["sha256"]}
    manifest = {
        "contract": "ocd-source-manifest-v1",
        "source_id": SOURCE_ID,
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "source_url": "https://ebible.org/find/show.php?id=eng-rv",
        "retained_member_set": {
            "path": MEMBER_SET_PATH,
            "sha256": member_set_hash,
            "positions": [row["position"] for row in rows],
        },
        "authorities": authorities,
        "source_members": source_members,
        "converter": {
            "id": CONVERTER_ID,
            "version": CONVERTER_VERSION,
            "callable": "_convert",
            "implementation_path": PACKAGER_PATH,
            "implementation_sha256": packager_record["sha256"],
        },
        "validator": {
            "id": ORACLE_ID,
            "version": ORACLE_VERSION,
            "callable": "_oracle",
            "implementation_path": ORACLE_PATH,
            "implementation_sha256": validator_record["sha256"],
            "import_closure_sha256": oracle_closure,
        },
        "package_schema": package_schema,
        "profile_sha256": profile_authority["sha256"],
        "policy_sha256": policy_authority["sha256"],
        "source_order_contract": "The existing retained source-member-set positions are authoritative.",
    }
    return _canonical(manifest), {
        PROFILE_PATH: profile_bytes,
        POLICY_PATH: policy_bytes,
        README_PATH: readme_bytes,
        STATE_SNAPSHOT_PATH: state_snapshot_bytes,
        MANIFEST_PATH: _canonical(manifest),
    }


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    """Compose the exact existing candidate into one child TEI per source member."""
    root = source_manifest.repository_root
    profile = json.loads(source_manifest.authority_path("profile").read_bytes())
    rows = profile["ordered_members"]
    legacy_path = source_manifest.authority_path("prior-candidate-tei")

    # Reuse the existing producer and require its current bytes to match the
    # retained candidate before making this structural-only composition.
    from build.tei.revised_version_with_apocrypha import _build_candidate

    prior_outputs = _build_candidate(root)
    prior_bytes = prior_outputs["content.tei.xml"]
    if prior_bytes != legacy_path.read_bytes():
        raise ValueError("existing TEI no longer reproduces its retained candidate bytes")

    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    original_root = etree.fromstring(prior_bytes, parser=parser)
    header = original_root.find(f"{{{TEI_NS}}}teiHeader")
    source_body = original_root.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body")
    if header is None or source_body is None:
        raise ValueError("existing TEI header or body is missing")

    book_by_id: dict[str, tuple[etree._Element, etree._Element]] = {}
    for group in source_body.findall(f"{{{TEI_NS}}}div"):
        for book in group.findall(f"{{{TEI_NS}}}div"):
            if book.get("type") != "book" or not book.get("n"):
                raise ValueError("existing TEI contains an unexpected testament child")
            book_id = book.get("n")
            if book_id in book_by_id:
                raise ValueError(f"existing TEI has duplicate book {book_id}")
            book_by_id[book_id] = (group, book)
    if len(book_by_id) != len(rows):
        raise ValueError("existing TEI book count differs from retained member set")

    corpus = etree.Element(f"{{{TEI_NS}}}teiCorpus", nsmap={None: TEI_NS})
    corpus.set(XML_ID, "revised-version-with-apocrypha-eng-rv-corpus")
    corpus.set(XML_LANG, "en")
    corpus.append(deepcopy(header))
    components: list[dict[str, Any]] = []
    for row in rows:
        book_id = row["book_id"]
        if book_id not in book_by_id:
            raise ValueError(f"existing TEI has no source book {book_id}")
        original_group, original_book = book_by_id[book_id]
        if original_group.get("type") != row["testament"]:
            raise ValueError(f"source member order and testament grouping differ: {book_id}")
        heads = original_group.findall(f"{{{TEI_NS}}}head")
        if len(heads) != 1 or "".join(heads[0].itertext()) != row["testament_head"]:
            raise ValueError(f"source group label differs for {book_id}")

        child = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
        child.set(XML_ID, row["tei_id"])
        child.set(XML_LANG, "en")
        child.set("ana", "#nonaccepted-candidate")
        child.append(deepcopy(header))
        text = etree.SubElement(child, f"{{{TEI_NS}}}text")
        body = etree.SubElement(text, f"{{{TEI_NS}}}body")
        group_attributes = {
            key: value for key, value in original_group.attrib.items() if key != XML_ID
        }
        group = etree.Element(
            original_group.tag,
            attrib=group_attributes,
            nsmap=original_group.nsmap,
        )
        group.set(XML_ID, f"rv-member-group-{row['position']:03d}")
        group.text = original_group.text
        for original_child in original_group:
            if original_child.tag == f"{{{TEI_NS}}}head" or original_child is original_book:
                group.append(deepcopy(original_child))
        if len(group.findall(f"{{{TEI_NS}}}div[@type='book']")) != 1:
            raise ValueError(f"member component does not contain exactly one book: {book_id}")
        body.append(group)
        corpus.append(child)
        components.append(
            {
                "position": row["position"],
                "member_path": row["path"],
                "member_sha256": row["sha256"],
                "book_id": book_id,
                "testament": row["testament"],
                "tei_xml_id": row["tei_id"],
            }
        )

    content = etree.tostring(
        corpus, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )
    old_accountability = json.loads(
        source_manifest.authority_path("prior-source-accountability").read_bytes()
    )
    source_set_record = source_manifest.record["retained_member_set"]
    accountability = {
        "contract": "ocd-revised-version-ordered-corpus-accountability-v1",
        "candidate_status": "nonaccepted",
        "current_checks": "pending independent validation",
        "content_tei_sha256": _sha(content),
        "content_tei_bytes": len(content),
        "composition": {
            "contract": "one-TEI-child-per-retained-source-member-v1",
            "child_tei_count": len(components),
            "ordered_source_member_set": dict(source_set_record),
            "members": components,
        },
        "existing_candidate": {
            "path": f"{OLD_CANDIDATE_DIR}/content.tei.xml",
            "sha256": _sha(prior_bytes),
            "source_accountability_sha256": _sha(
                source_manifest.authority_path("prior-source-accountability").read_bytes()
            ),
            "recorded_text_counts": old_accountability.get("text_counts"),
            "recorded_source_lines": old_accountability.get("text_counts", {}).get("source_lines"),
            "recorded_source_files": old_accountability.get("source_files_verified"),
        },
        "source_order": [row["filename"] for row in rows],
        "source_text_changed": False,
        "human_acceptance": "not recorded",
        "rights_clearance": "not established by this technical route",
    }
    old_unresolved = json.loads(
        source_manifest.authority_path("prior-unresolved").read_bytes()
    )
    unresolved_lines = [
        _canonical(
            {
                "contract": "ocd-revised-version-unresolved-item-v1",
                "status": "open",
                "question": question,
            }
        )
        for question in old_unresolved.get("items", [])
    ]
    if len(unresolved_lines) != 4:
        raise ValueError("the current candidate's four identity/witness questions changed")
    provenance = {
        "contract": "ocd-revised-version-ordered-corpus-provenance-v1",
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "source_id": SOURCE_ID,
        "source_manifest": {
            "path": source_manifest.path.relative_to(root).as_posix(),
            "sha256": source_manifest.sha256,
        },
        "profile_sha256": source_manifest.record["profile_sha256"],
        "source_member_set": dict(source_set_record),
        "source_edition": json.loads(
            source_manifest.authority_path("source-config").read_bytes()
        )["source_edition"],
        "existing_candidate": {
            "path": f"{OLD_CANDIDATE_DIR}/content.tei.xml",
            "sha256": _sha(prior_bytes),
            "structural_change": "split existing testament groups into one TEI child per ordered source member and wrap in teiCorpus",
            "body_text_change": False,
        },
        "members": components,
        "print_witness_material_projected": False,
        "replacement_scan_material_projected": False,
        "acceptance": "not recorded",
    }
    return {
        "README.source.md": source_manifest.authority_path("readme").read_bytes(),
        "content.tei.xml": content,
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(unresolved_lines),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def write_source_contract(root: Path) -> dict[str, Any]:
    """Write only the new source-local profile, policy, notice, and manifest."""
    root = Path(root).resolve(strict=True)
    manifest_bytes, files = build_source_manifest(root)
    for logical, content in files.items():
        path = _logical_path(root, logical) if Path(logical).exists() else root / logical
        if path.exists():
            if path.read_bytes() != content:
                raise FileExistsError(f"refusing to replace changed source contract file: {logical}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {
        "manifest_path": MANIFEST_PATH,
        "manifest_sha256": _sha(manifest_bytes),
        "files": sorted(files),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--write-source-contract", action="store_true")
    args = parser.parse_args()
    root = args.repository_root.resolve(strict=True)
    if not args.write_source_contract:
        raise SystemExit("pass --write-source-contract to create the reviewed current source contract")
    print(json.dumps(write_source_contract(root), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
