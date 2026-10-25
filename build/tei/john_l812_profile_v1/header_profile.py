"""Diagnostic proposal only: bounded PTA L812 header/PI admission profile.

This is not imported by OCD. It describes the narrow source-bound runtime
route proposed for John of Ephesus L812 and supplies local negative controls.
"""
from __future__ import annotations

import hashlib
from lxml import etree
from pathlib import Path

from ocd_kernel.lib.path_io import io_path

NS = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
IDENTITY = {
    "work_id": "john-of-ephesus-ecclesiastical-history",
    "textual_form_id": "syriac",
    "edition_id": "pta-ef861ab3-john-ecclesiastical-history-part-iii",
}
ACQUISITION_ID = "pta-l812-part-iii"
LANGUAGE = "syc"
PROFILE_ID = "ocd-pta-l812-john-ephesus-syriac-part-iii-header-v1"
SOURCE_MANIFEST_PATH = "sources/manifest-acquisitions/manifest-acquisition-pta-l812-john-of-ephesus-syriac-part-iii-ef861ab3-v3/source-manifest.json"
SOURCE_MANIFEST_SHA256 = "49b3db003120d8aef5aa12ae91370c00326def6238c7de0fb242012aa8cce039"
SOURCE_PROFILE_PATH = "sources/manifest-acquisitions/manifest-acquisition-pta-l812-john-of-ephesus-syriac-part-iii-ef861ab3-v3/complete-source-feature-profile.json"
SOURCE_PROFILE_SHA256 = "b196afe20a94577e5478253864bfeb19ec76fdbf48c781b1470add5c4bd7e5e8"
POLICY_PATH = "sources/manifest-acquisitions/manifest-acquisition-pta-l812-john-of-ephesus-syriac-part-iii-ef861ab3-v3/policy.json"
POLICY_SHA256 = "23e8d24621fa8655175551e353db82ce1b89a56651cdab633da11e23d04842b4"
SOURCE_SELECTION_PATH = "sources/manifest-acquisitions/manifest-acquisition-pta-l812-john-of-ephesus-syriac-part-iii-ef861ab3-v3/source-selection-snapshot.json"
SOURCE_SELECTION_SHA256 = "a0aed5b4981a9a5d85514af8b96874dda3934d82a972ae5b0200f9b6b6fc54cc"
SOURCE_ORACLE_PATH = "build/tei/pta_l812_retained_tei_oracle_v3.py"
SOURCE_ORACLE_SHA256 = "ec9f4bc317d7511641feb581998859b9e396da19bab4ba89a6ad81dc4cb3bedf"
SOURCE_ORACLE_CLOSURE_SHA256 = "d1d4a2a44e9f503bc4ed80fa854e2b55f04838986fac573565ed555b6bb84c8d"
BASELINE_CANDIDATE_MANIFEST_SHA256 = "3742f8276c445b98af49d4befea4a07dd25524c10bfa5a898ae29020c6dab550"
SOURCE_PATH = "raw/pta/ef861ab391ea35c5d85b41dd8d7ba2bf65530b21/pta-l812-john-of-ephesus-ecclesiastical-history-syriac-part-iii-ef861ab3/pta0200.pta001.pta-syc1.xml"
SOURCE_SHA256 = "35e8d68a884aaa10d1e9f4ae0aee4eb447a4cca7ff0c1393bee6674a6b7e437e"
SOURCE_BYTES = 1292998
MASTER_SHA256 = "c0aab5dd6685ee6b29db074426e5395871171664a5b3029714d250f599e3a153"
REVISION_ID = "pta-l812-part-iii-syriac-electronic-v2"
EXPECTED_PROLOG_PIS = (
    (
        "xml-model",
        'href="https://raw.githubusercontent.com/PatristicTextArchive/Schema/master/tei-pta.rng" '
        'schematypens="http://relaxng.org/ns/structure/1.0"',
    ),
    ("xml-stylesheet", 'type="text/css" href="standard.css"'),
)
SOURCE_DESC_CHILDREN = ("listWit", "listBibl")


class ProfileMismatch(ValueError):
    """Fail-closed diagnostic error for a mismatched scoped source profile."""


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_authority_pins(repository_root: Path, source_raw: bytes) -> None:
    """Bind the proposal to its frozen source manifest/profile/policy/snapshot."""
    paths = (
        (SOURCE_MANIFEST_PATH, SOURCE_MANIFEST_SHA256),
        (SOURCE_PROFILE_PATH, SOURCE_PROFILE_SHA256),
        (POLICY_PATH, POLICY_SHA256),
        (SOURCE_SELECTION_PATH, SOURCE_SELECTION_SHA256),
        (SOURCE_ORACLE_PATH, SOURCE_ORACLE_SHA256),
    )
    data = {}
    for relative, expected in paths:
        raw = io_path(repository_root / relative).read_bytes()
        if _sha(raw) != expected:
            raise ProfileMismatch(f"source authority pin differs: {relative}")
        data[relative] = raw
    manifest = __import__("json").loads(data[SOURCE_MANIFEST_PATH])
    profile = __import__("json").loads(data[SOURCE_PROFILE_PATH])
    primary = [item for item in manifest["authorities"] if item.get("role") == "primary-source"]
    if (manifest.get("work_id") != IDENTITY["work_id"]
            or profile.get("work_id") != IDENTITY["work_id"]
            or profile.get("source_sha256") != SOURCE_SHA256
            or len(primary) != 1
            or primary[0].get("path") != SOURCE_PATH
            or primary[0].get("sha256") != SOURCE_SHA256
            or primary[0].get("bytes") != SOURCE_BYTES
            or _sha(source_raw) != SOURCE_SHA256
            or len(source_raw) != SOURCE_BYTES):
        raise ProfileMismatch("current manifest/profile/source identity differs")


def _root(raw: bytes):
    try:
        return etree.fromstring(
            raw,
            etree.XMLParser(
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ProfileMismatch("invalid L812 TEI") from exc


def _prolog_pis(root) -> tuple[tuple[str, str], ...]:
    nodes = list(root.itersiblings(preceding=True))
    nodes.reverse()
    return tuple(
        (node.target, node.text or "")
        for node in nodes
        if isinstance(node, etree._ProcessingInstruction)
    )


def admitted_context(*, identity, raw: bytes, language: str, category: str,
                     collection: bool, projection_profile: str | None,
                     allow_acceptance_metadata: bool) -> bool:
    """Only the reviewed accepted L812 master can enter this exception route."""
    return (
        allow_acceptance_metadata is True
        and identity == IDENTITY
        and language == LANGUAGE
        and category == "prose"
        and collection is False
        and projection_profile == PROFILE_ID
        and _sha(raw) == MASTER_SHA256
    )


def observe_source_derivation(source_raw: bytes, accepted_raw: bytes, *, repository_root: Path, identity,
                              language: str, category: str, collection: bool,
                              projection_profile: str | None,
                              allow_acceptance_metadata: bool) -> dict[str, object]:
    """Verify exact raw-to-bound bytes; remove only this profile's two inserts."""
    if not admitted_context(
        identity=identity,
        raw=accepted_raw,
        language=language,
        category=category,
        collection=collection,
        projection_profile=projection_profile,
        allow_acceptance_metadata=allow_acceptance_metadata,
    ):
        raise ProfileMismatch("identity, scope, profile, or bound-master pin differs")
    if len(source_raw) != SOURCE_BYTES or _sha(source_raw) != SOURCE_SHA256:
        raise ProfileMismatch("retained L812 source bytes differ")
    verify_authority_pins(repository_root, source_raw)
    source_root = _root(source_raw)
    accepted_root = _root(accepted_raw)
    if _prolog_pis(source_root) != EXPECTED_PROLOG_PIS:
        raise ProfileMismatch("retained L812 prolog processing instructions differ")
    if _prolog_pis(accepted_root) != EXPECTED_PROLOG_PIS:
        raise ProfileMismatch("accepted L812 prolog processing instructions differ")

    source_descs = source_root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc",
        namespaces={"tei": NS},
    )
    accepted_descs = accepted_root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc",
        namespaces={"tei": NS},
    )
    if len(source_descs) != 1 or len(accepted_descs) != 1:
        raise ProfileMismatch("sourceDesc cardinality differs")
    if tuple(etree.QName(child).localname for child in source_descs[0]) != SOURCE_DESC_CHILDREN:
        raise ProfileMismatch("retained sourceDesc carrier set/order differs")

    bindings = accepted_root.xpath(
        ".//tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno"
        "[@type='representation_revision' and text()=$value]",
        namespaces={"tei": NS},
        value=REVISION_ID,
    )
    if len(bindings) != 1:
        raise ProfileMismatch("scoped acceptance insertion is missing or duplicated")
    bibl = bindings[0].getparent()
    if bibl.getparent() is not accepted_descs[0]:
        raise ProfileMismatch("acceptance binding is outside sourceDesc")
    changes = accepted_root.xpath(
        "./tei:teiHeader/tei:revisionDesc/tei:change[@xml:id=$value]",
        namespaces={"tei": NS},
        value=REVISION_ID,
    )
    if len(changes) != 1:
        raise ProfileMismatch("scoped acceptance revision is missing or duplicated")

    # The standard binder emits compact element bytes. Use the unique revision
    # fact and revision id to find exactly those two insertions in the byte stream.
    binding_marker = (
        b'<idno type="representation_revision">'
        + REVISION_ID.encode("ascii")
        + b"</idno>"
    )
    if accepted_raw.count(binding_marker) != 1:
        raise ProfileMismatch("acceptance binding byte marker is ambiguous")
    bibl_start = accepted_raw.rfind(b"<bibl", 0, accepted_raw.index(binding_marker))
    bibl_stop = accepted_raw.index(b"</bibl>", accepted_raw.index(binding_marker)) + len(b"</bibl>")
    change_marker = (
        b'<change xmlns="http://www.tei-c.org/ns/1.0" xml:id="'
        + REVISION_ID.encode("ascii")
        + b'" when="2026-10-04">'
    )
    if accepted_raw.count(change_marker) != 1:
        raise ProfileMismatch("acceptance revision byte marker is ambiguous")
    change_start = accepted_raw.index(change_marker)
    change_stop = accepted_raw.index(b"</change>", change_start) + len(b"</change>")
    binding_bytes = accepted_raw[bibl_start:bibl_stop]
    revision_bytes = accepted_raw[change_start:change_stop]
    restored = accepted_raw.replace(binding_bytes, b"", 1).replace(revision_bytes, b"", 1)
    if restored != source_raw:
        raise ProfileMismatch("accepted TEI differs beyond exact acceptance header inserts")
    return {
        "status": "pass",
        "source_sha256": _sha(source_raw),
        "accepted_sha256": _sha(accepted_raw),
        "removed_binding_sha256": _sha(binding_bytes),
        "removed_revision_sha256": _sha(revision_bytes),
        "restored_sha256": _sha(restored),
        "source_prolog_pis": [list(item) for item in _prolog_pis(source_root)],
        "source_desc_children": list(SOURCE_DESC_CHILDREN),
        "source_header_descendants": sum(1 for _ in source_descs[0].iter()),
    }


def source_header_nodes(root) -> set:
    """Nodes of the exact sourceDesc scholarly envelope, excluding binding bibl."""
    descs = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc",
        namespaces={"tei": NS},
    )
    if len(descs) != 1:
        raise ProfileMismatch("sourceDesc cardinality differs")
    binding_nodes = set()
    for binding in descs[0].xpath(
        "./tei:bibl/tei:idno[@type='representation_revision' and text()=$value]/..",
        namespaces={"tei": NS},
        value=REVISION_ID,
    ):
        binding_nodes.update(binding.iter())
    result = set()
    for node in descs[0].iter():
        if node is descs[0] or node in binding_nodes:
            continue
        result.add(node)
    return result


def prolog_processing_instruction_records(root) -> tuple[dict[str, object], ...]:
    """Return ordered, nonpublic prolog evidence for the two retained PIs."""
    found = _prolog_pis(root)
    if found != EXPECTED_PROLOG_PIS:
        raise ProfileMismatch("retained L812 prolog processing instructions differ")
    return tuple(
        {
            "parent_path": "#document",
            "position": ordinal,
            "target": target,
            "data": data,
            "disposition": "source-prolog-processing-directive",
        }
        for ordinal, (target, data) in enumerate(found, 1)
    )
