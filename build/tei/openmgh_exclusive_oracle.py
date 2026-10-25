"""Independent source-based check for exclusive openMGH child-work TEI.

This module does not import the producer. It locates the source work from the
two retained XML IDs, then compares the complete element/text/attribute tree.
"""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
ORACLE_ID = "ocd-openmgh-exclusive-source-oracle"
ORACLE_VERSION = "1"


def _tag(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _read_json(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object")
    return value


def _equivalent(a: etree._Element, b: etree._Element, *, top: bool = False) -> bool:
    """Compare source-visible tree data, excluding only the outer work tail."""
    if a.tag != b.tag or dict(a.attrib) != dict(b.attrib) or a.text != b.text:
        return False
    if not top and a.tail != b.tail:
        return False
    if len(a) != len(b):
        return False
    return all(_equivalent(x, y) for x, y in zip(a, b, strict=True))


def _ancestor_work(node: etree._Element) -> etree._Element:
    for ancestor in node.iterancestors():
        if ancestor.tag == _tag("div") and ancestor.get("type") == "work":
            return ancestor
    raise ValueError("source locator has no enclosing work div")


def _source_selection(
    source_manifest: SourceManifest, profile: Mapping[str, object]
) -> tuple[etree._Element, etree._Element, list[etree._Element]]:
    source = source_manifest.authority_path("extracted-xml").read_bytes()
    if _sha(source) != profile.get("source_sha256"):
        raise ValueError("source XML hash drifted")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True
    )
    root = etree.fromstring(source, parser=parser)
    if root.tag != _tag("TEI") or root.getroottree().docinfo.doctype:
        raise ValueError("source must be entity-free TEI")
    located = []
    for key in ("start_xml_id", "end_xml_id"):
        xml_id = profile.get(key)
        matches = root.xpath("//*[@xml:id=$id]", namespaces={"xml": XML}, id=xml_id)
        if len(matches) != 1:
            raise ValueError(f"source {key} is not unique")
        located.append(matches[0])
    work = _ancestor_work(located[0])
    if _ancestor_work(located[1]) is not work:
        raise ValueError("source locators straddle two works")
    volume = work.getparent()
    if volume is None or volume.tag != _tag("div") or volume.get("type") != "volume":
        raise ValueError("selected work is not a direct child of one volume")
    text = root.find(_tag("text"))
    body = text.find(_tag("body")) if text is not None else None
    if (
        text is None
        or body is None
        or list(text) != [body]
        or list(body) != [volume]
        or any((node.text or "").strip() for node in (text, body, volume))
    ):
        raise ValueError("volume contains unaccounted shared text or front/back")
    works = list(volume)
    if any(node.tag != _tag("div") or node.get("type") != "work" for node in works):
        raise ValueError("volume has material outside the work divisions")
    ordinal = works.index(work) + 1
    if (
        ordinal != profile.get("work_div_ordinal")
        or len(works) != profile.get("volume_work_count")
        or work.get("n") != profile.get("work_div_n")
    ):
        raise ValueError("source work identity, order, or volume envelope drifted")
    before = works[ordinal - 2].get("n") if ordinal > 1 else None
    after = works[ordinal].get("n") if ordinal < len(works) else None
    if before != profile.get("preceding_work_n") or after != profile.get(
        "following_work_n"
    ):
        raise ValueError("adjacent work boundaries drifted")
    return root, work, works


def _closure(manifest: SourceManifest, policy: Mapping[str, object]) -> str:
    paths = policy.get("closure_inputs")
    if (
        not isinstance(paths, list)
        or not paths
        or any(not isinstance(x, str) for x in paths)
    ):
        raise ValueError("oracle import closure inputs are invalid")
    entries = []
    for relative in paths:
        path = manifest.repository_root / relative
        data = path.read_bytes()
        entries.append({"path": relative, "sha256": _sha(data)})
    return _sha(_json(entries))


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    profile_path = source_manifest.authority_path("reconstruction-profile")
    policy_path = source_manifest.authority_path("validation-policy")
    profile = _read_json(profile_path.read_bytes(), "profile")
    policy = _read_json(policy_path.read_bytes(), "policy")
    if (
        profile.get("contract") != "ocd-openmgh-exclusive-profile-v1"
        or policy.get("contract") != "ocd-openmgh-exclusive-policy-v1"
    ):
        raise ValueError("openMGH profile or policy contract is invalid")
    source_path = profile.get("source_path")
    source_authorities = [
        a
        for a in source_manifest.record["authorities"]
        if a["role"] == "primary-source"
    ]
    if (
        len(source_authorities) != 1
        or source_authorities[0]["path"] != source_path
        or str(source_path).lower().endswith(".zip")
    ):
        raise ValueError("source authority must be exactly one extracted XML file")
    work_sidecar = _read_json(
        source_manifest.authority_path("work-sidecar").read_bytes(), "work"
    )
    acquisition_path = source_manifest.repository_root / str(
        profile.get("acquisition_path")
    )
    acquisition_bytes = Path(_io_path(acquisition_path)).read_bytes()
    if _sha(acquisition_bytes) != profile.get("acquisition_sha256"):
        raise ValueError("installed acquisition sidecar hash drifted")
    acquisition = _read_json(acquisition_bytes, "acquisition")
    work_id = profile.get("work_id")
    edition_id = profile.get("edition_id")
    acquisition_id = profile.get("acquisition_id")
    editions = [
        e
        for form in work_sidecar.get("textual_forms", [])
        for e in form.get("editions", [])
    ]
    if (
        work_sidecar.get("work_id") != work_id
        or len(
            [
                e
                for e in editions
                if e.get("edition_id") == edition_id
                and acquisition_id in e.get("acquisition_ids", [])
            ]
        )
        != 1
        or acquisition.get("acquisition_id") != acquisition_id
        or acquisition.get("edition_id") != edition_id
        or acquisition.get("source_path") != source_path
        or acquisition.get("source_sha256") != profile.get("source_sha256")
    ):
        raise ValueError("work, edition, and extracted acquisition do not bind")
    retained = acquisition.get("retained_files")
    if (
        not isinstance(retained, list)
        or len(
            [
                r
                for r in retained
                if r.get("path") == source_path
                and r.get("sha256") == profile["source_sha256"]
            ]
        )
        != 1
        or any(
            r.get("path", "").lower().endswith(".zip")
            and "archive" not in r.get("scope", "").lower()
            for r in retained
        )
    ):
        raise ValueError("retained extracted source or ZIP package role is invalid")
    source_root, source_work, works = _source_selection(source_manifest, profile)
    boundary = _read_json(
        source_manifest.authority_path("boundary-review").read_bytes(),
        "boundary review",
    )
    expected_boundary = {
        "contract": "ocd-openmgh-exclusive-boundary-review-v1",
        "work_id": work_id,
        "scope_assertion": "whole-work-div",
        "review_status": "agent-inspected-source-boundary",
        "source_path": source_path,
        "source_sha256": profile["source_sha256"],
        "work_div_n": source_work.get("n"),
        "start_xml_id": profile["start_xml_id"],
        "end_xml_id": profile["end_xml_id"],
    }
    if any(boundary.get(k) != v for k, v in expected_boundary.items()):
        raise ValueError("inspected whole-work boundary does not bind this source")
    readable = " ".join(" ".join(source_work.itertext()).split())
    if (
        not isinstance(boundary.get("opening_evidence"), str)
        or not isinstance(boundary.get("closing_evidence"), str)
        or not readable.startswith(boundary["opening_evidence"])
        or not readable.endswith(boundary["closing_evidence"])
    ):
        raise ValueError("inspected work opening or ending drifted")
    internal_ids = {n.get(XML_ID) for n in source_work.iter() if n.get(XML_ID)}
    for node in source_work.iter():
        for key, value in node.attrib.items():
            if etree.QName(key).localname in ("target", "corresp", "sameAs", "ana"):
                for target in value.split():
                    if target.startswith("#") and target[1:] not in internal_ids:
                        raise ValueError(
                            "work has an unresolved cross-boundary XML reference"
                        )
    actual = etree.fromstring(
        candidate.member_bytes("content.tei.xml"),
        parser=etree.XMLParser(
            resolve_entities=False, no_network=True, remove_comments=False
        ),
    )
    if (
        actual.tag != _tag("TEI")
        or actual.get(XML_ID) != f"ocd-{work_id}-electronic-v1"
        or actual.getroottree().docinfo.doctype
    ):
        raise ValueError("candidate TEI identity or XML document is invalid")
    title = actual.find(
        f"{_tag('teiHeader')}/{_tag('fileDesc')}/{_tag('titleStmt')}/{_tag('title')}"
    )
    if title is None or title.text != profile.get("work_title"):
        raise ValueError("child work title drifted")
    source_header = source_root.find(_tag("teiHeader"))
    if source_header is None:
        raise ValueError("source TEI header is missing")
    for xpath in (
        f"{_tag('fileDesc')}/{_tag('publicationStmt')}",
        f"{_tag('fileDesc')}/{_tag('sourceDesc')}/{_tag('biblFull')}",
    ):
        expected = source_header.find(xpath)
        observed = actual.find(f"{_tag('teiHeader')}/{xpath}")
        if (
            expected is None
            or observed is None
            or not _equivalent(expected, observed, top=True)
        ):
            raise ValueError("source license or printed-volume bibliography drifted")
    actual_body = actual.find(f"{_tag('text')}/{_tag('body')}")
    if (
        actual_body is None
        or len(actual_body) != 1
        or not _equivalent(source_work, actual_body[0], top=True)
    ):
        raise ValueError(
            "candidate work body differs from the full retained source div"
        )
    etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
    ).assertValid(actual)
    accounting = _read_json(
        candidate.member_bytes("source-accountability.json"), "accounting"
    )
    expected_counts = dict(
        sorted(
            Counter(
                etree.QName(n).localname
                for n in source_work.iter()
                if isinstance(n.tag, str)
            ).items()
        )
    )
    expected_fields = {
        "contract": "ocd-openmgh-exclusive-accounting-v1",
        "work_id": work_id,
        "edition_id": edition_id,
        "acquisition_id": acquisition_id,
        "source_path": source_path,
        "source_sha256": profile["source_sha256"],
        "work_div_n": source_work.get("n"),
        "work_div_ordinal": works.index(source_work) + 1,
        "volume_work_count": len(works),
        "start_xml_id": profile["start_xml_id"],
        "end_xml_id": profile["end_xml_id"],
        "preceding_work_n": profile["preceding_work_n"],
        "following_work_n": profile["following_work_n"],
        "element_counts": expected_counts,
        "source_div_c14n_sha256": _sha(
            etree.tostring(source_work, method="c14n", with_comments=True)
        ),
    }
    for field, expected in expected_fields.items():
        if accounting.get(field) != expected:
            raise ValueError(f"source accounting {field} drifted")
    for field in (
        "source_header_disposition",
        "outside_work_disposition",
        "zip_disposition",
    ):
        if not isinstance(accounting.get(field), str) or not accounting[field]:
            raise ValueError(f"source accounting {field} is missing")
    provenance = _read_json(candidate.member_bytes("provenance.json"), "provenance")
    if (
        provenance.get("status") != "nonaccepted"
        or provenance.get("work_id") != work_id
        or provenance.get("edition_id") != edition_id
        or provenance.get("acquisition_id") != acquisition_id
        or provenance.get("canonical_ir_written") is not False
    ):
        raise ValueError("candidate provenance drifted")
    if not candidate.member_bytes(
        "unresolved.jsonl"
    ).strip() or b"Monumenta" not in candidate.member_bytes("README.source.md"):
        raise ValueError("unresolved or attribution handoff is missing")
    oracle_source = Path(__file__).resolve()
    imports = ast.parse(oracle_source.read_text(encoding="utf-8"))
    forbidden = policy.get("forbidden_oracle_imports", [])
    if any(
        isinstance(n, ast.ImportFrom)
        and any(n.module == module for module in forbidden)
        for n in ast.walk(imports)
    ):
        raise ValueError("oracle imports its producer")
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(oracle_source.read_bytes()),
        "import_closure_sha256": _closure(source_manifest, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_path.read_bytes()),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": profile["source_sha256"],
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_path.read_bytes()),
        "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION


__all__ = ("_oracle",)
