"""LIB-084 complete retained-corpus reconstruction and mutation gates."""

from __future__ import annotations

from copy import deepcopy
from functools import cache
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import re
import shutil
import subprocess
import sys
from unittest.mock import patch

from lxml import etree, html
import pytest

from build.tei import spurgeon_mtp_oracle as oracle
from build.tei import spurgeon_mtp_reconstruction as producer
from build.tools import count_dataset_records
from build.tools.count_dataset_records import collect_work_catalog
from build.tools.reconstruct_candidate import run
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import (
    MechanicalFacts,
    verify_mechanical_facts,
)
from ocd_kernel.tei.writer import tei_el


ROOT = Path(__file__).resolve().parents[1]
RETAINED_MANIFEST = ROOT / "sources/spurgeon-mtp/spurgeon-mtp.source-manifest.json"
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/spurgeon-mtp.source-manifest.json"
PROFILE = ROOT / "sources/spurgeon-mtp/spurgeon-mtp.reconstruction-profile.json"
SOURCE_README = ROOT / "sources/spurgeon-mtp/README.md"
WORK_IDENTITY_CONFIG = ROOT / "sources/sermons/spurgeon-mtp/config.json"
CANDIDATE = Path(
    os.environ.get(
        "OCD_LIB084_CANDIDATE",
        str(ROOT / ".tmp_candidates/LIB-084/candidate"),
    )
)
_candidate_gate_failure_reported = False
MISSING = [8, 40, 42, 62, 67, 82, 142, 155, 269, 270, 298, 332, 390]
EXPECTED_ORACLE_FIRST_PARTY_IMPORTS = (
    "build/tei/spurgeon_mtp_oracle.py",
    "ocd_kernel/__init__.py",
    "ocd_kernel/lib/__init__.py",
    "ocd_kernel/lib/path_io.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
)
EXPECTED_ATTRIBUTION_EVIDENCE = {
    "primary_html_count": 3547,
    "retained_wording": [
        {
            "name": "Emmett O'Donnell",
            "wording": "transcribed from manuscripts edited by Emmett O'Donnell",
            "supported_responsibility": "manuscript editor",
        },
        {
            "name": "Benry Yip",
            "wording": "Designed by Benry Yip",
            "supported_responsibility": "designer",
        },
    ],
    "unresolved_responsibilities": [
        "The retained primary wording does not identify the transcriber.",
        "The retained primary wording does not identify the digitizer.",
    ],
}

_ATTESTATION_FIELDS = frozenset(
    {
        "status",
        "oracle_id",
        "oracle_version",
        "implementation_sha256",
        "import_closure_sha256",
        "runtime",
        "source_manifest_sha256",
        "candidate_sha256",
        "profile_sha256",
        "package_schema_sha256",
        "source_sha256",
        "xsd_sha256",
        "policy_sha256",
        "findings",
    }
)


class _AttestationBoundary(Exception):
    """Capture the incumbent reader's facts before its result digest is built."""


EXPECTED_ATTRIBUTION_UNRESOLVED = {
    "id": "spurgeon-mtp-contributor-responsibility",
    "kind": "metadata/source-responsibility",
    "scope": {"primary_html_count": 3547},
    "status": "localized-unresolved",
    "evidence": EXPECTED_ATTRIBUTION_EVIDENCE["retained_wording"],
    "unresolved_responsibilities": EXPECTED_ATTRIBUTION_EVIDENCE[
        "unresolved_responsibilities"
    ],
    "owner": "source-evidence-maintainer",
    "next_action": (
        "Do not assign transcriber or digitizer contributor roles without retained "
        "primary evidence."
    ),
    "reopening_condition": (
        "Retained primary evidence identifies who performed transcription or "
        "digitization."
    ),
}

EXPECTED_WORK_IDENTITY_CONTRIBUTORS = [
    {
        "name": "Emmett O'Donnell",
        "role": "manuscript editor",
        "affiliation": "SpurgeonGems (spurgeongems.org)",
        "url": "http://www.spurgeongems.org/",
    },
    {
        "name": "Benry Yip",
        "role": "designer",
        "affiliation": "The Kingdom Collective",
        "url": "https://thekingdomcollective.com/spurgeon/",
    },
]
EXPECTED_WORK_IDENTITY_SOURCE_EDITION = "Retained Kingdom Collective HTML sermon pages."
EXPECTED_WORK_IDENTITY_NOTES = (
    "Spurgeon died in 1892; the underlying sermons are public domain. Retained "
    'primary wording says the collection was "transcribed from manuscripts edited '
    'by Emmett O\'Donnell" and states "Designed by Benry Yip." It does not identify '
    "the transcriber or digitizer; those responsibilities remain unresolved. Legacy "
    "canonical JSON is an aid outside this campaign, not candidate authority, and "
    "remains untouched under the protected-path rule. Output is split into per-chunk "
    "files (sermons-<start>-<end>.json, 100 sermons per file) to stay under GitHub's "
    "100 MB file-size limit."
)
EXPECTED_LEGACY_JSON_BOUNDARY = (
    "Legacy canonical JSON is an aid outside this campaign, not candidate authority, "
    "and remains untouched under the protected-path rule."
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


@cache
def _source_manifest() -> SourceManifest:
    """Reuse frozen retained authority; candidate mutations affect only temp copies."""

    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@cache
def _source_facts() -> oracle._SourceFacts:
    """Build one immutable, hash-bound retained-source baseline per test process."""

    return oracle._derive_source_facts(_source_manifest())


@pytest.fixture
def lib084_e2e_candidate() -> Path:
    """Require one explicit, accessible candidate for every serialized E2E item."""

    global _candidate_gate_failure_reported
    package = CANDIDATE / "package"
    try:
        resolved = package.resolve(strict=True)
    except OSError:
        resolved = None
    if resolved is not None and resolved.is_dir():
        return CANDIDATE
    message = (
        "LIB-084 E2E candidate is missing or inaccessible. Build it with "
        "`py -3 -m build.tools.reconstruct_candidate --manifest "
        "tests/fixtures/reconstruction-runtime/spurgeon-mtp.source-manifest.json --destination "
        "<external-candidate-root> --repository-root .`, then set "
        "OCD_LIB084_CANDIDATE=<external-candidate-root>."
    )
    if not _candidate_gate_failure_reported:
        _candidate_gate_failure_reported = True
        pytest.fail(message)
    pytest.skip("LIB-084 E2E candidate requirement already reported")


def _candidate_overlay(
    tmp_path: Path, name: str, mutable_members: tuple[str, ...]
) -> Path:
    """Create a fully isolated package copy for one resealed mutation."""

    source = CANDIDATE / "package"
    destination = tmp_path / name / "package"
    assert mutable_members
    shutil.copytree(source, destination)
    return destination


def _shared_oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    facts: oracle._SourceFacts,
) -> dict[str, object]:
    """Run the unchanged reader, then replace only its final result assembly."""

    incumbent_canonical = oracle._canonical

    def capture_attestation(value: object) -> bytes:
        if (
            isinstance(value, dict)
            and frozenset(value) == _ATTESTATION_FIELDS
            and value.get("status") == "pass"
        ):
            raise _AttestationBoundary(dict(value))
        return incumbent_canonical(value)

    try:
        with patch.object(oracle, "_canonical", new=capture_attestation):
            oracle._validate_with_source_facts(source_manifest, candidate, facts)
    except _AttestationBoundary as caught:
        record = caught.args[0]
    else:
        raise AssertionError("Spurgeon attestation boundary was not reached")
    if not isinstance(record, dict):
        raise AssertionError("Spurgeon attestation boundary was invalid")
    facts = MechanicalFacts(
        validator_implementation_sha256=str(record["implementation_sha256"]),
        validator_import_closure_sha256=str(record["import_closure_sha256"]),
        source_sha256=str(record["source_sha256"]),
        profile_sha256=str(record["profile_sha256"]),
        package_schema_sha256=str(record["package_schema_sha256"]),
        xsd_sha256=str(record["xsd_sha256"]),
        policy_sha256=str(record["policy_sha256"]),
        findings=tuple(record["findings"]),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


def _rejection_message(
    reader, source_manifest: SourceManifest, candidate: CandidatePackage
) -> str:
    with pytest.raises(ValueError) as caught:
        reader(source_manifest, candidate)
    return str(caught.value)


def _assert_rejection(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    *,
    match: str,
) -> str:
    message = _rejection_message(
        lambda manifest, package: oracle._validate_with_source_facts(
            manifest, package, _source_facts()
        ),
        source_manifest,
        candidate,
    )
    assert re.search(match, message)
    return message


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _assert_retained_package_conserved(candidate: CandidatePackage) -> None:
    """Reverse only the test runtime identity and recover the frozen package hash."""
    assert _sha(RETAINED_MANIFEST) == "12ccaf17790f0916048a679c3bb985efa5221f9c424ae9c3ec10101eda1c8e7a"
    # Exact pre-main runtime fixture from source commit 08eb7640.
    original_sha = "36bbc661abefd494c1bf478f846133025702f63a623184ff631197c997d3a4c0"
    runtime_sha = _sha(MANIFEST)
    assert candidate.manifest["source_manifest"] == {
        "path": MANIFEST.relative_to(ROOT).as_posix(), "sha256": runtime_sha,
    }
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["source_manifest_sha256"] == runtime_sha
    provenance["source_manifest_sha256"] = original_sha
    original_provenance = _canonical(provenance)
    restored = json.loads(candidate.member_bytes("manifest.json"))
    restored["source_manifest"] = {
        "path": MANIFEST.relative_to(ROOT).as_posix(), "sha256": original_sha,
    }
    binding = next(row for row in restored["members"] if row["name"] == "provenance.json")
    binding.update(bytes=len(original_provenance), sha256=hashlib.sha256(original_provenance).hexdigest())
    assert hashlib.sha256(_canonical(restored)).hexdigest() == (
        "06085a98fb48844070bcf063f594796bc88e381ba68ea14a33cec28bf50069b8"
    )


def test_work_identity_config_uses_only_retained_supported_roles_and_lineage() -> None:
    config = json.loads(WORK_IDENTITY_CONFIG.read_text(encoding="utf-8"))

    assert config["contributors"] == EXPECTED_WORK_IDENTITY_CONTRIBUTORS
    assert config["source_edition"] == EXPECTED_WORK_IDENTITY_SOURCE_EDITION
    assert config["notes"] == EXPECTED_WORK_IDENTITY_NOTES
    serialized = json.dumps(config, ensure_ascii=False)
    assert '"role": "transcriber"' not in serialized
    assert '"role": "digitizer"' not in serialized
    assert "O'Donnell transcription" not in serialized
    assert "HTML parsing by Benry Yip" not in serialized
    expected_binding = {
        "path": "sources/sermons/spurgeon-mtp/config.json",
        "bytes": WORK_IDENTITY_CONFIG.stat().st_size,
        "sha256": _sha(WORK_IDENTITY_CONFIG),
        "candidate_authority": False,
        "legacy_json_boundary": EXPECTED_LEGACY_JSON_BOUNDARY,
    }
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert profile["work_identity_config"] == expected_binding
    authority = next(
        item
        for item in _manifest()["authorities"]
        if item["name"] == "work-identity-config"
    )
    assert authority == {
        "name": "work-identity-config",
        "path": expected_binding["path"],
        "role": "work-identity-config",
        "bytes": expected_binding["bytes"],
        "sha256": expected_binding["sha256"],
    }


@pytest.mark.lib084_candidate_local
def test_source_fact_construction_deeply_isolates_nested_inputs() -> None:
    source = {"policy": {"roles": ["editor", {"name": "designer"}]}}
    frozen = oracle._deep_freeze(source)
    source["policy"]["roles"][1]["name"] = "mutated"
    source["policy"]["roles"].append("invented")

    assert oracle._deep_thaw(frozen) == {
        "policy": {"roles": ["editor", {"name": "designer"}]}
    }
    with pytest.raises(TypeError):
        frozen["policy"] = {}
    with pytest.raises(TypeError):
        frozen["policy"]["roles"][1]["name"] = "mutated"


@pytest.mark.lib084_candidate_local
def test_source_fact_digest_binds_profile_and_accountability_values() -> None:
    def digest(profile_title: str, accountability_role: str) -> str:
        authority = oracle._deep_freeze(
            {"name": "sermon-0001", "path": "raw/1.html", "bytes": 1, "sha256": "a"}
        )
        fact = oracle._SermonFact(
            number=1,
            authority=authority,
            selection="primary-article",
            source_tree_sha256="tree",
            source_event_tags=("p",),
            source_events_sha256="events",
            normalized_text_sha256="text",
            expected_accountability=oracle._deep_freeze(
                {"number": 1, "role": accountability_role}
            ),
        )
        return oracle._source_facts_digest(
            source_manifest_sha256="manifest",
            oracle_implementation_sha256="implementation",
            import_closure_sha256="closure",
            profile_sha256="profile-sha",
            package_schema_sha256="package-schema",
            xsd_sha256="xsd",
            policy_sha256="policy",
            source_set_sha256="source-set",
            authorities=(authority,),
            profile=oracle._deep_freeze({"tei_header_policy": {"title": profile_title}}),
            work_identity_config=oracle._deep_freeze({"contributors": []}),
            supplemental_rights=oracle._deep_freeze({"scope": {}}),
            rights_evidence=oracle._deep_freeze({}),
            source_readme=b"readme",
            request_log=oracle._deep_freeze({"name": "request-log"}),
            sermon_facts=(fact,),
        )

    baseline = digest("Retained title", "textual-witness")
    assert digest("Invented title", "textual-witness") != baseline
    assert digest("Retained title", "invented-role") != baseline


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("transcriber", "contributors"),
        ("digitizer", "contributors"),
        ("unsupported-lineage", "source_edition"),
    ],
)
def test_oracle_semantically_rejects_resealed_work_identity_claims(
    tmp_path: Path, mutation: str, message: str
) -> None:
    config = json.loads(WORK_IDENTITY_CONFIG.read_text(encoding="utf-8"))
    if mutation == "transcriber":
        config["contributors"][0]["role"] = "transcriber"
    elif mutation == "digitizer":
        config["contributors"][1]["role"] = "digitizer"
    else:
        config["source_edition"] = (
            "Emmett O'Donnell transcription with HTML parsing by Benry Yip"
        )
    config_path = tmp_path / "config.json"
    config_path.write_bytes(_canonical(config))

    class _Manifest:
        @staticmethod
        def authority_path(name: str) -> Path:
            assert name == "work-identity-config"
            return config_path

    profile = {
        "work_identity_config": {
            "path": "sources/sermons/spurgeon-mtp/config.json",
            "bytes": config_path.stat().st_size,
            "sha256": _sha(config_path),
            "candidate_authority": False,
            "legacy_json_boundary": EXPECTED_LEGACY_JSON_BOUNDARY,
        }
    }

    with pytest.raises(ValueError, match=message):
        oracle._validate_work_identity_config(_Manifest(), profile)


def _sample(number: int) -> tuple[etree._Element, etree._Element]:
    folder = "html" if number not in {708, 1698, 3032} else "missing"
    path = ROOT / f"raw/spurgeon_sermons/{folder}/{number}.html"
    selected, selection = producer._selected_source(path, number)
    target = tei_el("div", {"type": "sermon", "n": str(number)})
    context = producer._Context(number)
    if selection == "primary-article":
        producer._append_blocks(selected, target, context)
    else:
        producer._append_container_segments(selected, target, context)
    return selected, target


def _resealed_content_mutation(tmp_path: Path, mutation: str) -> CandidatePackage:
    package_path = _candidate_overlay(
        tmp_path, mutation, ("content.tei.xml",)
    )
    content_path = package_path / "content.tei.xml"
    raw_mutations = {
        "blank-line-before-root": (
            b"<?xml version='1.0' encoding='UTF-8'?>\n",
            b"<?xml version='1.0' encoding='UTF-8'?>\n\n",
        ),
        "multiple-spaces-before-root": (
            b"<?xml version='1.0' encoding='UTF-8'?>\n",
            b"<?xml version='1.0' encoding='UTF-8'?>\n   ",
        ),
        "whitespace-line-before-root": (
            b"<?xml version='1.0' encoding='UTF-8'?>\n",
            b"<?xml version='1.0' encoding='UTF-8'?>\n  \n",
        ),
        "trailing-whitespace-after-root": (
            b"</TEI>",
            b"</TEI> \t\n",
        ),
        "unused-root-namespace": (
            b'<TEI xmlns="http://www.tei-c.org/ns/1.0">',
            b'<TEI xmlns="http://www.tei-c.org/ns/1.0" '
            b'xmlns:unused="urn:ocd:lib084:invented-root">',
        ),
        "unused-nested-namespace": (
            b'<ns0:div xmlns:ns0="http://www.tei-c.org/ns/1.0" '
            b'xml:id="spurgeon-mtp-0001"',
            b'<ns0:div xmlns:ns0="http://www.tei-c.org/ns/1.0" '
            b'xmlns:unused="urn:ocd:lib084:invented-nested" '
            b'xml:id="spurgeon-mtp-0001"',
        ),
        "explicit-reserved-xml-namespace": (
            b'<TEI xmlns="http://www.tei-c.org/ns/1.0">',
            b'<TEI xmlns="http://www.tei-c.org/ns/1.0" '
            b'xmlns:xml="http://www.w3.org/XML/1998/namespace">',
        ),
        "document-comment-before-root": (
            b"<?xml version='1.0' encoding='UTF-8'?>",
            b"<?xml version='1.0' encoding='UTF-8'?>"
            b"<!--invented document comment before root-->",
        ),
        "document-processing-instruction-before-root": (
            b"<?xml version='1.0' encoding='UTF-8'?>",
            b"<?xml version='1.0' encoding='UTF-8'?>"
            b"<?invented document-processing-instruction-before-root?>",
        ),
        "document-comment-after-root": (
            b"</TEI>",
            b"</TEI><!--invented document comment after root-->",
        ),
        "document-processing-instruction-after-root": (
            b"</TEI>",
            b"</TEI><?invented document-processing-instruction-after-root?>",
        ),
        "document-doctype": (
            b"<?xml version='1.0' encoding='UTF-8'?>",
            b"<?xml version='1.0' encoding='UTF-8'?><!DOCTYPE TEI>",
        ),
        "xml-declaration-omitted": (
            b"<?xml version='1.0' encoding='UTF-8'?>",
            b"",
        ),
        "xml-declaration-standalone-yes": (
            b"<?xml version='1.0' encoding='UTF-8'?>",
            b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>",
        ),
        "xml-declaration-standalone-no": (
            b"<?xml version='1.0' encoding='UTF-8'?>",
            b"<?xml version='1.0' encoding='UTF-8' standalone='no'?>",
        ),
    }
    if mutation in raw_mutations:
        needle, replacement = raw_mutations[mutation]
        content = content_path.read_bytes()
        assert content.count(needle) == 1
        content_path.write_bytes(content.replace(needle, replacement, 1))
    elif mutation == "unprefixed-sermon-subtrees":
        content = content_path.read_bytes()
        header, separator, sermons = content.partition(b"<text><body>")
        assert separator
        namespace_declaration = b' xmlns:ns0="http://www.tei-c.org/ns/1.0"'
        assert sermons.count(namespace_declaration) == 3550
        assert b"ns0:" in sermons
        sermons = sermons.replace(namespace_declaration, b"").replace(b"ns0:", b"")
        content_path.write_bytes(header + separator + sermons)
    document = etree.parse(
        str(content_path),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    namespace = {"tei": oracle._TEI_NS}
    if mutation in raw_mutations or mutation == "unprefixed-sermon-subtrees":
        pass
    elif mutation == "list-rend":
        node = document.xpath(
            "/tei:TEI/tei:text/tei:body/tei:div[@n='1']//tei:list[@rend][1]",
            namespaces=namespace,
        )[0]
        node.set("rend", "invented-list-style")
    elif mutation == "list-type":
        node = document.xpath("//tei:list[@type='ordered'][1]", namespaces=namespace)[0]
        node.set("type", "invented-list-type")
    elif mutation == "hi-rend":
        node = document.xpath("//tei:hi[@rend][1]", namespaces=namespace)[0]
        node.set("rend", "invented-highlight")
    elif mutation == "source-link-type":
        node = document.xpath(
            "//tei:ref[@type='source-link'][1]", namespaces=namespace
        )[0]
        node.set("type", "invented-link-type")
    elif mutation == "scripture-ref-type":
        node = document.xpath("//tei:ref[@type='scripture'][1]", namespaces=namespace)[
            0
        ]
        node.set("type", "invented-reference-type")
    elif mutation == "code-type":
        node = document.xpath(
            "//tei:seg[@type='source-code'][1]", namespaces=namespace
        )[0]
        node.set("type", "invented-code-type")
    elif mutation == "span-type":
        node = document.xpath(
            "//tei:seg[@type='source-span'][1]", namespaces=namespace
        )[0]
        node.set("type", "invented-span-type")
    elif mutation == "font-type":
        node = document.xpath(
            "//tei:seg[@type='source-font'][1]", namespaces=namespace
        )[0]
        node.set("type", "invented-font-type")
    elif mutation == "font-rend":
        node = document.xpath(
            "//tei:seg[@type='source-font'][1]", namespaces=namespace
        )[0]
        node.set("rend", "invented-font-size")
    elif mutation == "mapped-container-type":
        node = document.xpath("//tei:div[@type='source-div'][1]", namespaces=namespace)[
            0
        ]
        node.set("type", "invented-container-type")
    elif mutation == "generated-container-type":
        node = document.xpath(
            "//tei:div[@type='source-container-segment'][1]", namespaces=namespace
        )[0]
        node.set("type", "invented-container-segment")
    elif mutation == "source-flow-type":
        node = document.xpath("//tei:ab[@type='source-flow'][1]", namespaces=namespace)[
            0
        ]
        node.set("type", "invented-flow-type")
    elif mutation == "milestone-unit":
        node = document.xpath(
            "//tei:milestone[@unit='source-horizontal-rule'][1]", namespaces=namespace
        )[0]
        node.set("unit", "invented-milestone-unit")
    elif mutation == "sermon-subtype":
        node = document.xpath(
            "/tei:TEI/tei:text/tei:body/tei:div[@type='sermon'][1]",
            namespaces=namespace,
        )[0]
        node.set("subtype", "invented-selection")
    elif mutation == "header-title":
        node = document.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title",
            namespaces=namespace,
        )[0]
        node.text = "Invented title"
    elif mutation == "header-author":
        node = document.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author",
            namespaces=namespace,
        )[0]
        node.text = "Invented author"
    elif mutation == "header-contributor":
        node = document.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name",
            namespaces=namespace,
        )[0]
        node.text = "Invented contributor"
    elif mutation == "header-publisher":
        node = document.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:publisher",
            namespaces=namespace,
        )[0]
        node.text = "Invented publisher"
    elif mutation == "header-availability-status":
        node = document.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability",
            namespaces=namespace,
        )[0]
        node.set("status", "free")
    elif mutation == "header-source-target":
        node = document.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:ptr",
            namespaces=namespace,
        )[0]
        node.set("target", "https://example.invalid/invented")
    elif mutation == "header-source-sha":
        node = document.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256']",
            namespaces=namespace,
        )[0]
        node.text = "0" * 64
    elif mutation == "header-print-source":
        node = document.xpath(
            "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note[@type='print-source']",
            namespaces=namespace,
        )[0]
        node.text = "Invented print source"
    elif mutation == "optional-header-metadata-addition":
        header = document.xpath("/tei:TEI/tei:teiHeader", namespaces=namespace)[0]
        encoding_desc = etree.SubElement(header, tei_el("encodingDesc").tag)
        project_desc = etree.SubElement(encoding_desc, tei_el("projectDesc").tag)
        etree.SubElement(
            project_desc, tei_el("p").tag
        ).text = "Invented encoding project"
        profile_desc = etree.SubElement(header, tei_el("profileDesc").tag)
        lang_usage = etree.SubElement(profile_desc, tei_el("langUsage").tag)
        language = etree.SubElement(lang_usage, tei_el("language", {"ident": "en"}).tag)
        language.set("ident", "en")
        language.text = "Invented language metadata"
        revision_desc = etree.SubElement(header, tei_el("revisionDesc").tag)
        etree.SubElement(
            revision_desc, tei_el("change").tag
        ).text = "Invented revision history"
    elif mutation == "foreign-id-empty-page-break":
        sermon = document.xpath(
            "/tei:TEI/tei:text/tei:body/tei:div[@type='sermon'][1]",
            namespaces=namespace,
        )[0]
        etree.SubElement(
            sermon,
            tei_el("pb").tag,
            {"{http://www.w3.org/XML/1998/namespace}id": "invented-page-marker"},
        )
    elif mutation == "empty-generated-source-flow":
        sermon = document.xpath(
            "/tei:TEI/tei:text/tei:body/tei:div[@type='sermon'][1]",
            namespaces=namespace,
        )[0]
        etree.SubElement(sermon, tei_el("ab").tag, {"type": "source-flow"})
    elif mutation == "body-comment":
        body = document.xpath("/tei:TEI/tei:text/tei:body", namespaces=namespace)[0]
        body.insert(0, etree.Comment("invented body comment"))
    elif mutation == "body-processing-instruction":
        body = document.xpath("/tei:TEI/tei:text/tei:body", namespaces=namespace)[0]
        body.insert(0, etree.ProcessingInstruction("invented", "body"))
    elif mutation == "body-level-generated-carrier":
        body = document.xpath("/tei:TEI/tei:text/tei:body", namespaces=namespace)[0]
        etree.SubElement(body, tei_el("div").tag, {"type": "source-container-segment"})
    else:
        raise AssertionError(f"Unknown test mutation {mutation}")
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(document), schema.error_log.last_error
    if mutation not in raw_mutations:
        document.write(str(content_path), encoding="UTF-8", xml_declaration=True)

    manifest_path = package_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_manifest = _source_manifest()
    manifest["source_manifest"]["sha256"] = source_manifest.sha256
    manifest["converter"] = dict(source_manifest.record["converter"])
    member = next(
        item for item in manifest["members"] if item["name"] == "content.tei.xml"
    )
    member["bytes"] = content_path.stat().st_size
    member["sha256"] = _sha(content_path)
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(package_path)


def _resealed_missing_blocker_mutation(tmp_path: Path, field: str) -> CandidatePackage:
    package_path = _candidate_overlay(
        tmp_path, f"missing-blocker-{field}", ("unresolved.jsonl",)
    )
    unresolved_path = package_path / "unresolved.jsonl"
    records = [
        json.loads(line)
        for line in unresolved_path.read_text(encoding="utf-8").splitlines()
    ]
    missing_records = [
        record
        for record in records
        if record["kind"] == "missing-source/source-identity"
    ]
    assert len(missing_records) == 13
    for index, record in enumerate(missing_records):
        number = record["scope"]["sermon_number"]
        mutations = {
            "id": f"invented-missing-{number}",
            "kind": "invented-kind",
            "scope": {"sermon_number": number + 10_000},
            "status": "invented-status",
            "evidence": f"Invented evidence for missing sermon {number}",
            "routes_attempted": [f"invented-route-{index}"],
            "owner": "invented-owner",
            "next_action": "Invented next action",
            "reopening_condition": "Invented reopening condition",
        }
        record[field] = mutations[field]
    unresolved_path.write_text(
        "".join(
            json.dumps(
                record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
            for record in records
        ),
        encoding="utf-8",
        newline="",
    )
    manifest_path = package_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    member = next(
        item for item in manifest["members"] if item["name"] == "unresolved.jsonl"
    )
    member["bytes"] = unresolved_path.stat().st_size
    member["sha256"] = _sha(unresolved_path)
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(package_path)


def _reseal_candidate_members(package_path: Path, names: tuple[str, ...]) -> None:
    manifest_path = package_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_name = {item["name"]: item for item in manifest["members"]}
    for name in names:
        path = package_path / name
        by_name[name]["bytes"] = path.stat().st_size
        by_name[name]["sha256"] = _sha(path)
    manifest_path.write_bytes(_canonical(manifest))


def _resealed_false_contributor_roles(package_path: Path) -> CandidatePackage:
    content_path = package_path / "content.tei.xml"
    content = content_path.read_bytes()
    assert content.count(b">manuscript editor<") == 1
    assert content.count(b">designer<") == 1
    content = content.replace(b">manuscript editor<", b">transcriber<", 1)
    content = content.replace(b">designer<", b">digitizer<", 1)
    content_path.write_bytes(content)

    provenance_path = package_path / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["attribution"][0]["role"] = "transcriber"
    provenance["attribution"][1]["role"] = "digitizer"
    provenance["attribution_evidence"]["retained_wording"][0][
        "supported_responsibility"
    ] = "transcriber"
    provenance["attribution_evidence"]["retained_wording"][1][
        "supported_responsibility"
    ] = "digitizer"
    provenance_path.write_bytes(_canonical(provenance))

    readme_path = package_path / "README.source.md"
    readme = readme_path.read_text(encoding="utf-8")
    readme = readme.replace("only as manuscript editor", "as transcriber", 1)
    readme = readme.replace("only as designer", "as digitizer", 1)
    readme_path.write_text(readme, encoding="utf-8", newline="")

    unresolved_path = package_path / "unresolved.jsonl"
    unresolved = [
        json.loads(line)
        for line in unresolved_path.read_text(encoding="utf-8").splitlines()
    ]
    record = next(
        item
        for item in unresolved
        if item["id"] == "spurgeon-mtp-contributor-responsibility"
    )
    record["evidence"][0]["supported_responsibility"] = "transcriber"
    record["evidence"][1]["supported_responsibility"] = "digitizer"
    unresolved_path.write_bytes(b"".join(_canonical(item) for item in unresolved))

    _reseal_candidate_members(
        package_path,
        (
            "content.tei.xml",
            "provenance.json",
            "README.source.md",
            "unresolved.jsonl",
        ),
    )
    return CandidatePackage.load(package_path)


def _fresh_oracle_first_party_imports(root: Path) -> tuple[str, ...]:
    script = """
import importlib.util
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve(strict=True)
oracle_path = root / "build/tei/spurgeon_mtp_oracle.py"
sys.path.insert(0, str(root))
before = set(sys.modules)
spec = importlib.util.spec_from_file_location("_lib084_oracle_probe", oracle_path)
if spec is None or spec.loader is None:
    raise RuntimeError("oracle probe cannot create a module spec")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
paths = set()
for name in set(sys.modules) - before:
    module_path = getattr(sys.modules[name], "__file__", None)
    if module_path is None:
        continue
    path = Path(module_path).resolve(strict=True)
    try:
        relative = path.relative_to(root)
    except ValueError:
        continue
    paths.add(relative.as_posix())
print(json.dumps(sorted(paths)))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(json.loads(result.stdout))


def _copy_oracle_first_party_imports(root: Path, destination: Path) -> None:
    for relative in EXPECTED_ORACLE_FIRST_PARTY_IMPORTS:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)


@pytest.mark.requires_local_artifacts
def test_manifest_accounts_for_every_retained_member_and_authority() -> None:
    document = _manifest()
    source_members = document["source_members"]
    excluded = document["excluded_members"]
    authorities = document["authorities"]
    assert len(source_members) == 3550
    assert len(excluded) == 1
    assert len(authorities) == 3560
    assert [item["logical_name"] for item in source_members] == [
        f"sermon-{number:04d}" for number in range(1, 3564) if number not in MISSING
    ]
    assert [item["logical_name"] for item in excluded] == ["request-log"]
    assert (
        sum(item["bytes"] for item in source_members) + excluded[0]["bytes"]
        == 143_873_038
    )
    lineage = document["catalog_claim_lineage"]
    assert lineage["contract"] == "ocd-catalog-claim-lineage-v1"
    assert lineage["work_id"] == "spurgeon-mtp"
    assert lineage["retained_source_sha256"] == (
        "5e8d99a95625d77f8c83cfe3a3143f2fab1e2205ffa1222ca4ba40bfc60ed9ea"
    )
    assert lineage["claim_count"] == len(lineage["claims"]) == 36
    assert {item["legacy_source_sha256"] for item in lineage["claims"]} == {
        "46c7e316cd6c3b2934450a5fc552686786e31bba2d7399aff15dbb93beb44a79"
    }
    assert [item["source_path"] for item in lineage["claims"]] == sorted(
        item["source_path"] for item in lineage["claims"]
    )
    SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.mark.requires_local_artifacts
def test_manifest_binds_current_implementation_and_schema_authorities() -> None:
    document = _manifest()
    assert document["converter"]["implementation_sha256"] == _sha(
        ROOT / document["converter"]["implementation_path"]
    )
    assert document["validator"]["implementation_sha256"] == _sha(
        ROOT / document["validator"]["implementation_path"]
    )
    by_name = {item["name"]: item for item in document["authorities"]}
    for name in (
        "retained-member-inventory",
        "source-attribution-readme",
        "work-identity-config",
        "reconstruction-profile",
        "validation-policy",
        "request-log",
        "tei-p5-xsd",
        "candidate-package-schema",
        "reconstruction-contract",
        "tei-writer",
    ):
        item = by_name[name]
        path = ROOT / item["path"]
        assert item["bytes"] == path.stat().st_size
        assert item["sha256"] == _sha(path)


def test_runtime_fixture_preserves_retained_inputs_and_only_updates_changed_dependencies() -> None:
    retained = json.loads(RETAINED_MANIFEST.read_bytes())
    assert _sha(RETAINED_MANIFEST) == "12ccaf17790f0916048a679c3bb985efa5221f9c424ae9c3ec10101eda1c8e7a"
    expected = deepcopy(retained)
    contract = next(item for item in expected["authorities"] if item["name"] == "reconstruction-contract")
    contract["bytes"] = (ROOT / contract["path"]).stat().st_size
    contract["sha256"] = _sha(ROOT / contract["path"])
    expected["validator"]["implementation_sha256"] = _sha(ROOT / expected["validator"]["implementation_path"])
    expected["validator"]["import_closure_sha256"] = oracle._import_closure(ROOT)
    assert _manifest() == expected


@pytest.mark.requires_local_artifacts
def test_durable_source_readme_is_manifest_bound_and_retained_evidence_exact() -> None:
    document = _manifest()
    by_name = {item["name"]: item for item in document["authorities"]}
    authority = by_name["source-attribution-readme"]
    assert authority["path"] == "sources/spurgeon-mtp/README.md"
    assert authority["role"] == "source-attribution-and-rights-notice"
    assert authority["bytes"] == SOURCE_README.stat().st_size
    assert authority["sha256"] == _sha(SOURCE_README)

    readme = SOURCE_README.read_text(encoding="utf-8")
    primary = [
        ROOT / item["path"]
        for item in document["authorities"]
        if item.get("role") == "primary-source"
        and str(item["path"]).startswith("raw/spurgeon_sermons/html/")
    ]
    assert len(primary) == 3547
    for path in primary:
        page_text = " ".join(html.parse(path).getroot().itertext())
        normalized = " ".join(page_text.split())
        assert "transcribed from manuscripts edited by Emmett O'Donnell" in normalized
        assert "Designed by Benry Yip" in normalized

    terms = []
    for number in (708, 3032):
        page = html.parse(ROOT / f"raw/spurgeon_sermons/missing/{number}.html")
        nodes = page.xpath(
            "//div[@id='ipaNodeOutro' and contains(concat(' ', normalize-space(@class), ' '), ' outro ')]"
            "/h2[normalize-space()='Terms of Use']/following-sibling::p[1]"
        )
        assert len(nodes) == 1
        terms.append(" ".join(" ".join(nodes[0].itertext()).split()))
    assert terms[0] == terms[1]

    assert "transcribed from manuscripts edited by Emmett O'Donnell" in readme
    assert "Designed by Benry Yip" in readme
    assert terms[0] in readme
    assert "Emmett O'Donnell, transcriber" not in readme
    assert "Benry Yip, digitizer" not in readme
    assert "nonaccepted" in readme
    assert "publication status remains not-ready" in readme


def test_oracle_first_party_import_closure_is_current() -> None:
    assert oracle._FIRST_PARTY_IMPORT_PATHS == EXPECTED_ORACLE_FIRST_PARTY_IMPORTS
    assert _fresh_oracle_first_party_imports(ROOT) == (
        EXPECTED_ORACLE_FIRST_PARTY_IMPORTS
    )


@pytest.mark.parametrize("relative", EXPECTED_ORACLE_FIRST_PARTY_IMPORTS)
def test_oracle_import_closure_binds_every_executed_first_party_module(
    tmp_path: Path, relative: str
) -> None:
    shadow = tmp_path / "shadow"
    _copy_oracle_first_party_imports(ROOT, shadow)
    baseline = oracle._import_closure(shadow)
    target = shadow / relative
    target.write_bytes(target.read_bytes() + b"\n# closure drift\n")
    assert oracle._import_closure(shadow) != baseline


@pytest.mark.parametrize("relative", EXPECTED_ORACLE_FIRST_PARTY_IMPORTS)
def test_oracle_import_closure_rejects_missing_first_party_module(
    tmp_path: Path, relative: str
) -> None:
    shadow = tmp_path / "shadow"
    _copy_oracle_first_party_imports(ROOT, shadow)
    (shadow / relative).unlink()
    with pytest.raises(ValueError, match="first-party import closure"):
        oracle._import_closure(shadow)


def test_oracle_import_closure_rejects_unexpected_first_party_execution(
    tmp_path: Path,
) -> None:
    shadow = tmp_path / "shadow"
    _copy_oracle_first_party_imports(ROOT, shadow)
    unexpected = shadow / "ocd_kernel/unexpected_lib084_probe.py"
    unexpected.write_text("VALUE = 'unexpected'\n", encoding="utf-8", newline="")
    oracle_path = shadow / "build/tei/spurgeon_mtp_oracle.py"
    oracle_path.write_bytes(
        oracle_path.read_bytes() + b"\nimport ocd_kernel.unexpected_lib084_probe\n"
    )
    with pytest.raises(ValueError, match="first-party import closure"):
        oracle._import_closure(shadow)


def test_profile_localizes_only_the_thirteen_unresolved_slots() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert profile["inventory"] == {
        "path": "tests/fixtures/spurgeon_mtp/retained-member-inventory-v1.tsv",
        "bytes": 378913,
        "sha256": "1e11bebdad45995675c1a03e5aef18792a2c7fcac3e4fc64e4e1fb6edc3a09fe",
        "member_count": 3551,
        "total_bytes": 143873038,
        "primary_html_count": 3547,
        "supplemental_html_count": 3,
        "evidence_only_count": 1,
    }
    slots = profile["slot_accounting"]
    assert slots["resolved_textual_witness_count"] == 3550
    assert slots["supplemental_resolutions"] == [708, 1698, 3032]
    assert slots["unresolved_sermon_numbers"] == MISSING
    assert slots["claims_complete_slot_resolution"] is False
    assert profile["rights"]["publication_status"] == "not-ready"
    assert profile["rights"]["publication_authorized"] is False
    supplemental = profile["rights"]["supplemental_witness_terms"]
    assert supplemental["rights_owners"] == ["Larry Pierce", "Marion Pierce"]
    assert supplemental["scope"] == {
        "sermon_numbers": [708, 3032],
        "retained_paths": [
            "raw/spurgeon_sermons/missing/708.html",
            "raw/spurgeon_sermons/missing/3032.html",
        ],
    }
    assert profile["structure_policy"]["tei_mapping"]["font"] == "seg"
    assert profile["structure_policy"]["attribute_mapping"] == {
        "a.href": "ref.target",
        "font.size": "seg.rend",
        "ol.type": "list.rend",
        "ul.type": "list.rend",
    }
    assert profile["structure_policy"]["tei_attribute_policy"]["ol"] == {
        "type": "ordered",
        "source_attribute_map": {"type": "rend"},
    }
    assert profile["structure_policy"]["generated_tei_attribute_policy"] == {
        "source-container-segment": {
            "element": "div",
            "type": "source-container-segment",
        },
        "source-flow": {"element": "ab", "type": "source-flow"},
    }
    assert profile["tei_header_policy"]["title"].startswith(
        "Metropolitan Tabernacle Pulpit"
    )


@pytest.mark.requires_local_artifacts
def test_profile_uses_only_literal_retained_contributor_responsibilities() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    primary = sorted((ROOT / "raw/spurgeon_sermons/html").glob("*.html"))
    assert len(primary) == 3547
    for path in primary:
        page_text = " ".join(html.parse(path).getroot().itertext())
        normalized = " ".join(page_text.split())
        for evidence in EXPECTED_ATTRIBUTION_EVIDENCE["retained_wording"]:
            assert evidence["wording"] in normalized

    assert profile["attribution_evidence"] == EXPECTED_ATTRIBUTION_EVIDENCE
    assert profile["tei_header_policy"]["contributors"] == [
        {"resp": "manuscript editor", "name": "Emmett O'Donnell"},
        {"resp": "designer", "name": "Benry Yip"},
    ]
    assert profile["attribution"] == [
        {
            "name": "Emmett O'Donnell",
            "role": "manuscript editor",
            "source_wording": "transcribed from manuscripts edited by Emmett O'Donnell",
            "affiliation": "SpurgeonGems (spurgeongems.org)",
            "url": "http://www.spurgeongems.org/",
        },
        {
            "name": "Benry Yip",
            "role": "designer",
            "source_wording": "Designed by Benry Yip",
            "affiliation": "The Kingdom Collective",
            "url": "https://thekingdomcollective.com/spurgeon/",
        },
    ]


def test_installed_candidate_derives_durable_readme_and_supported_roles() -> None:
    try:
        candidate = CandidatePackage.load(CANDIDATE / "package")
    except OSError:
        pytest.skip("caller-selected LIB-084 candidate is not accessible")
    assert candidate.member_bytes("README.source.md") == SOURCE_README.read_bytes()

    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["attribution"] == profile["attribution"]
    assert provenance["attribution_evidence"] == EXPECTED_ATTRIBUTION_EVIDENCE

    document = etree.parse(
        str(CANDIDATE / "package/content.tei.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    contributors = []
    for node in document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt",
        namespaces={"tei": oracle._TEI_NS},
    ):
        contributors.append(
            {
                "resp": " ".join(
                    node.xpath(
                        "string(tei:resp)", namespaces={"tei": oracle._TEI_NS}
                    ).split()
                ),
                "name": " ".join(
                    node.xpath(
                        "string(tei:name)", namespaces={"tei": oracle._TEI_NS}
                    ).split()
                ),
            }
        )
    assert contributors == profile["tei_header_policy"]["contributors"]

    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]
    assert unresolved[-2] == EXPECTED_ATTRIBUTION_UNRESOLVED
    assert unresolved[-1]["id"] == "spurgeon-mtp-rights"

    false_role_tokens = ('"role":"transcriber"', '"role":"digitizer"')
    serialized = [
        _canonical(profile).decode("utf-8"),
        candidate.member_bytes("README.source.md").decode("utf-8"),
        candidate.member_bytes("provenance.json").decode("utf-8"),
        candidate.member_bytes("unresolved.jsonl").decode("utf-8"),
        candidate.member_bytes("content.tei.xml").decode("utf-8"),
    ]
    assert all(token not in text for token in false_role_tokens for text in serialized)


@pytest.mark.parametrize("number", [1, 317, 708, 1698, 3032])
@pytest.mark.requires_local_artifacts
def test_primary_and_supplemental_samples_preserve_structure_and_text(
    number: int,
) -> None:
    source, candidate = _sample(number)
    source_events = oracle._source_events(
        oracle._evidence_region(
            ROOT
            / f"raw/spurgeon_sermons/{'missing' if number in {708, 1698, 3032} else 'html'}/{number}.html",
            number,
        )[0],
        number,
    )
    candidate_events = oracle._candidate_events(candidate, number)
    assert len(candidate_events) == len(source_events)
    candidate_projection = [
        {**record, "source_tag": source_events[index]["source_tag"]}
        for index, record in enumerate(candidate_events)
    ]
    assert candidate_projection == source_events
    assert oracle._text(candidate) == producer._normalized_text(source)


@pytest.mark.requires_local_artifacts
def test_all_thirteen_selected_supplemental_anchor_targets_are_preserved() -> None:
    total = 0
    for number in (708, 1698, 3032):
        source, candidate = _sample(number)
        expected = [str(node.get("href")) for node in source.xpath(".//a[@href]")]
        observed = [
            str(node.get("target"))
            for node in candidate.xpath(
                ".//tei:ref[@type='source-link']", namespaces={"tei": oracle._TEI_NS}
            )
        ]
        assert observed == expected
        total += len(observed)
    assert total == 13


@pytest.mark.parametrize("mutation", ["remove-target", "swap-targets", "change-target"])
@pytest.mark.lib084_candidate_local
@pytest.mark.requires_local_artifacts
def test_supplemental_anchor_target_mutations_are_detected(mutation: str) -> None:
    _, candidate = _sample(708)
    expected = oracle._source_events(
        oracle._evidence_region(ROOT / "raw/spurgeon_sermons/missing/708.html", 708)[0],
        708,
    )
    mutated = deepcopy(candidate)
    refs = mutated.xpath(
        ".//tei:ref[@type='source-link']", namespaces={"tei": oracle._TEI_NS}
    )
    assert len(refs) == 6
    if mutation == "remove-target":
        del refs[0].attrib["target"]
    elif mutation == "swap-targets":
        first = refs[0].get("target")
        refs[0].set("target", str(refs[1].get("target")))
        refs[1].set("target", str(first))
    else:
        refs[0].set("target", "/invented-target/")
    observed = oracle._candidate_events(mutated, 708)
    projection = [
        {**record, "source_tag": expected[index]["source_tag"]}
        for index, record in enumerate(observed)
    ]
    assert projection != expected


@pytest.mark.requires_local_artifacts
def test_supplemental_1698_font_is_inline_and_preserves_source_size() -> None:
    source, candidate = _sample(1698)
    fonts = source.xpath(".//font")
    segments = candidate.xpath(
        ".//tei:seg[@type='source-font']", namespaces={"tei": oracle._TEI_NS}
    )
    assert len(fonts) == len(segments) == 1
    assert fonts[0].get("size") == segments[0].get("rend") == "+1"


@pytest.mark.requires_local_artifacts
@pytest.mark.lib084_oracle_e2e
@pytest.mark.slow
@pytest.mark.xdist_group(name="lib084-oracle-e2e")
def test_spurgeon_incumbent_and_shared_attestations_are_field_for_field_equal(
    lib084_e2e_candidate: Path,
) -> None:
    source_manifest = _source_manifest()
    candidate = CandidatePackage.load(lib084_e2e_candidate / "package")
    incumbent = oracle._oracle(source_manifest, candidate)
    assert _shared_oracle(source_manifest, candidate, _source_facts()) == incumbent


@pytest.mark.requires_local_artifacts
@pytest.mark.lib084_oracle_e2e
@pytest.mark.slow
@pytest.mark.xdist_group(name="lib084-oracle-e2e")
def test_fully_resealed_false_contributor_roles_are_rejected(
    tmp_path: Path, lib084_e2e_candidate: Path
) -> None:
    working = tmp_path / "lib084-false-role-mutant"
    mutable = (
        "content.tei.xml",
        "provenance.json",
        "README.source.md",
        "unresolved.jsonl",
    )
    try:
        package_path = _candidate_overlay(tmp_path, working.name, mutable)
        candidate = _resealed_false_contributor_roles(package_path)
        source_manifest = _source_manifest()
        _assert_rejection(
            source_manifest,
            candidate,
            match="contributor|header|README|provenance",
        )
    finally:
        if working.exists():
            shutil.rmtree(working)


@pytest.mark.parametrize(
    "mutation",
    ["list-rend"],
)
@pytest.mark.requires_local_artifacts
@pytest.mark.lib084_oracle_e2e
@pytest.mark.slow
@pytest.mark.xdist_group(name="lib084-oracle-e2e")
def test_resealed_xsd_valid_tei_attribute_and_header_drift_is_rejected(
    tmp_path: Path, mutation: str, lib084_e2e_candidate: Path
) -> None:
    package = _resealed_content_mutation(tmp_path, mutation)
    source_manifest = _source_manifest()
    _assert_rejection(
        source_manifest,
        package,
        match="structure|attribute|header|metadata|source|subtype",
    )


@pytest.mark.parametrize(
    "mutation",
    ["body-level-generated-carrier"],
)
@pytest.mark.requires_local_artifacts
@pytest.mark.lib084_oracle_e2e
@pytest.mark.slow
@pytest.mark.xdist_group(name="lib084-oracle-e2e")
def test_resealed_xsd_valid_unaccounted_tei_additions_are_rejected(
    tmp_path: Path, mutation: str, lib084_e2e_candidate: Path
) -> None:
    package = _resealed_content_mutation(tmp_path, mutation)
    source_manifest = _source_manifest()
    _assert_rejection(
        source_manifest,
        package,
        match="header|structure|carrier|identity|unaccounted",
    )


@pytest.mark.parametrize(
    "mutation",
    ["unused-root-namespace"],
)
@pytest.mark.requires_local_artifacts
@pytest.mark.lib084_oracle_e2e
@pytest.mark.slow
@pytest.mark.xdist_group(name="lib084-oracle-e2e")
def test_resealed_xsd_valid_document_namespace_and_shell_drift_is_rejected(
    tmp_path: Path, mutation: str, lib084_e2e_candidate: Path
) -> None:
    package = _resealed_content_mutation(tmp_path, mutation)
    source_manifest = _source_manifest()
    _assert_rejection(
        source_manifest, package, match="namespace|document shell|doctype"
    )


@pytest.mark.parametrize(
    "mutation",
    ["blank-line-before-root"],
)
@pytest.mark.requires_local_artifacts
@pytest.mark.lib084_oracle_e2e
@pytest.mark.slow
@pytest.mark.xdist_group(name="lib084-oracle-e2e")
def test_resealed_exterior_whitespace_is_rejected_at_lexical_shell_stage(
    tmp_path: Path, mutation: str, lib084_e2e_candidate: Path
) -> None:
    package = _resealed_content_mutation(tmp_path, mutation)
    source_manifest = _source_manifest()
    assert (
        _assert_rejection(
            source_manifest, package, match=r"^Spurgeon TEI lexical shell drifted$"
        )
        == "Spurgeon TEI lexical shell drifted"
    )


@pytest.mark.parametrize(
    "field",
    ["owner"],
)
@pytest.mark.requires_local_artifacts
@pytest.mark.lib084_oracle_e2e
@pytest.mark.slow
@pytest.mark.xdist_group(name="lib084-oracle-e2e")
def test_resealed_missing_source_blocker_field_drift_is_rejected(
    tmp_path: Path, field: str, lib084_e2e_candidate: Path
) -> None:
    package = _resealed_missing_blocker_mutation(tmp_path, field)
    source_manifest = _source_manifest()
    _assert_rejection(
        source_manifest, package, match="missing-source|unresolved evidence"
    )


@pytest.mark.parametrize("mutation", ["omission", "owner", "term"])
@pytest.mark.lib084_candidate_local
@pytest.mark.requires_local_artifacts
def test_retained_supplemental_rights_node_mutations_are_detected(
    tmp_path: Path, mutation: str
) -> None:
    source = ROOT / "raw/spurgeon_sermons/missing/708.html"
    document = html.document_fromstring(source.read_bytes())
    outro = next(
        node for node in document.iter("div") if node.get("id") == "ipaNodeOutro"
    )
    terms = next(
        node
        for node in outro
        if node.tag == "p" and "Modernized Edition" in oracle._text(node)
    )
    if mutation == "omission":
        outro.remove(terms)
    elif mutation == "owner":
        terms.text = (terms.text or "").replace(
            "Larry and Marion Pierce", "Unknown Owner"
        )
    else:
        terms.text = (terms.text or "").replace(
            "without express written permission", "without any permission"
        )
    mutated = tmp_path / "708.html"
    mutated.write_bytes(etree.tostring(document, method="html", encoding="utf-8"))
    with pytest.raises(ValueError, match="rights|Terms of Use"):
        oracle._retained_rights_evidence(mutated, 708)


@pytest.mark.parametrize(
    "mutation",
    [
        "rights-scope",
        "font-policy",
        "font-attribute",
        "list-attribute-policy",
        "hi-attribute-policy",
        "generated-container-policy",
        "sermon-policy",
        "header-title-policy",
        "header-source-policy",
    ],
)
@pytest.mark.lib084_candidate_local
@pytest.mark.requires_local_artifacts
def test_profile_rights_and_font_policy_mutations_are_detected(mutation: str) -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    evidence = {
        number: oracle._retained_rights_evidence(
            ROOT / f"raw/spurgeon_sermons/missing/{number}.html", number
        )
        for number in (708, 3032)
    }
    if mutation == "rights-scope":
        profile["rights"]["supplemental_witness_terms"]["scope"]["sermon_numbers"] = [
            708
        ]
    elif mutation == "font-policy":
        profile["structure_policy"]["tei_mapping"]["font"] = "div"
    elif mutation == "font-attribute":
        profile["structure_policy"]["attribute_mapping"]["font.size"] = "seg.type"
    elif mutation == "list-attribute-policy":
        del profile["structure_policy"]["attribute_mapping"]["ol.type"]
    elif mutation == "hi-attribute-policy":
        profile["structure_policy"]["tei_attribute_policy"]["em"]["rend"] = "bold"
    elif mutation == "generated-container-policy":
        del profile["structure_policy"]["generated_tei_attribute_policy"]["source-flow"]
    elif mutation == "sermon-policy":
        profile["structure_policy"]["sermon_attribute_policy"]["subtype"] = "guess"
    elif mutation == "header-title-policy":
        profile["tei_header_policy"]["title"] = "Invented title"
    else:
        del profile["tei_header_policy"]["source_url"]
    with pytest.raises(ValueError, match="rights|font|attribute|header|policy"):
        oracle._validate_profile_policy(profile, evidence)


@pytest.mark.parametrize(
    "mutation", ["omission", "duplication", "reorder", "invention"]
)
@pytest.mark.lib084_candidate_local
@pytest.mark.requires_local_artifacts
def test_structural_and_text_mutations_are_detected(mutation: str) -> None:
    source, candidate = _sample(317)
    expected = oracle._source_events(
        oracle._evidence_region(ROOT / "raw/spurgeon_sermons/html/317.html", 317)[0],
        317,
    )
    mutated = deepcopy(candidate)
    mapped = [
        node
        for node in mutated.iterdescendants()
        if node.get("{http://www.w3.org/XML/1998/namespace}id")
    ]
    assert len(mapped) > 5
    if mutation == "omission":
        mapped[2].getparent().remove(mapped[2])
    elif mutation == "duplication":
        mapped[2].addnext(deepcopy(mapped[2]))
    elif mutation == "reorder":
        first, second = list(mutated)[:2]
        mutated.remove(second)
        mutated.insert(0, second)
        assert first is not second
    else:
        mapped[-1].text = (mapped[-1].text or "") + " invented"
    observed = oracle._candidate_events(mutated, 317)
    projection = (
        [
            {**record, "source_tag": expected[index]["source_tag"]}
            for index, record in enumerate(observed)
        ]
        if len(observed) == len(expected)
        else observed
    )
    assert projection != expected or oracle._text(mutated) != producer._normalized_text(
        source
    )


def test_retained_candidate_is_standard_validated_nonaccepted_handoff() -> None:
    if not CANDIDATE.is_dir():
        pytest.skip("caller-selected LIB-084 candidate is not present")
    try:
        package = CandidatePackage.load(CANDIDATE / "package")
    except OSError:
        pytest.skip("caller-selected LIB-084 candidate is not accessible")
    validation = json.loads((CANDIDATE / "validation.json").read_text(encoding="utf-8"))
    accountability = json.loads(package.member_bytes("source-accountability.json"))
    provenance = json.loads(package.member_bytes("provenance.json"))
    _assert_retained_package_conserved(package)
    changed_manifest = json.loads(package.member_bytes("manifest.json"))
    changed_manifest["members"][0]["sha256"] = "0" * 64
    changed = SimpleNamespace(
        manifest=package.manifest,
        member_bytes=lambda name: _canonical(changed_manifest) if name == "manifest.json"
        else package.member_bytes(name),
    )
    with pytest.raises(AssertionError):
        _assert_retained_package_conserved(changed)
    assert validation["status"] == "pass"
    assert validation["candidate_sha256"] == package.sha256
    assert accountability["represented_textual_witness_count"] == 3550
    assert accountability["excluded_evidence_count"] == 1
    assert accountability["omitted_retained_member_count"] == 0
    assert accountability["claims_complete_3563_slot_resolution"] is False
    assert provenance["status"] == "nonaccepted"
    assert provenance["publication_status"] == "not-ready"
    assert provenance["publication_authorized"] is False


@pytest.mark.slow
@pytest.mark.requires_local_artifacts
@pytest.mark.lib084_oracle_e2e
@pytest.mark.xdist_group(name="lib084-oracle-e2e")
def test_retained_candidate_binds_to_ordinary_work_catalog_state(
    lib084_e2e_candidate: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_selection = MANIFEST.relative_to(ROOT).as_posix()

    def selected_manifest_paths(sources_root: Path, selections):
        assert sources_root == ROOT / "sources"
        assert tuple(selections) == (manifest_selection,)
        return sources_root, (MANIFEST,)

    # Select the test authority while retaining the real catalog binding checks.
    monkeypatch.setattr(
        count_dataset_records, "_resolve_source_manifest_allowlist", selected_manifest_paths
    )
    catalog = collect_work_catalog(
        ROOT / "data",
        source_manifest_allowlist=[manifest_selection],
        data_resource_allowlist=[
            (Path("data") / item["source_path"]).as_posix()
            for item in _manifest()["catalog_claim_lineage"]["claims"]
        ],
        reconstruction_evidence={
            ("spurgeon-mtp-complete-retained-html", "spurgeon-mtp"): (
                lib084_e2e_candidate / "package",
                lib084_e2e_candidate / "validation.json",
            )
        },
    )
    work = next(item for item in catalog.works if item["work_id"] == "spurgeon-mtp")
    state = work["reconstruction_state"]
    assert state == {
        "retained_source": "manifest_bound",
        "tei_candidate": "verified",
        "validation": "verified",
        "human_review": "required",
        "accepted_ir": "not_accepted",
        "blocker": None,
        "publication": "not_ready",
        "routes": [
            {
                "association": "catalog_claim_lineage+exact_id",
                "manifest": MANIFEST.relative_to(ROOT).as_posix(),
                "scope": "work",
                "source_id": "spurgeon-mtp-complete-retained-html",
                "verification": "verified",
                "candidate_verification": "verified",
                "validation_verification": "verified",
            }
        ],
    }
    # The bounded catalog excludes the global inventory registry; check this witness directly.
    members = count_dataset_records._inventory_members(
        ROOT / "tests/fixtures/spurgeon_mtp/retained-member-inventory-v1.tsv", ROOT
    )
    parser_hashes = count_dataset_records._work_source_hashes(work)
    assert len(members) == 3551
    assert all(current for _, _, current in members)
    assert sum(digest not in parser_hashes for _, digest, _ in members) == 3551
    assert work["retained_witness_gaps"] == []


@pytest.mark.slow
@pytest.mark.requires_local_artifacts
@pytest.mark.lib084_oracle_e2e
@pytest.mark.xdist_group(name="lib084-oracle-e2e")
def test_complete_authority_bound_route(tmp_path: Path) -> None:
    destination = tmp_path / "lib084-candidate"
    result = run(
        manifest=MANIFEST.relative_to(ROOT).as_posix(),
        destination=str(destination),
        repository_root=str(ROOT),
    )
    assert result["status"] == "pass"
    assert result["acceptance_status"] == "nonaccepted"
    package = CandidatePackage.load(destination / "package")
    assert package.sha256 == result["candidate"]["sha256"]
    _assert_retained_package_conserved(package)
    assert result["validation_report"]["status"] == "pass"


@pytest.mark.requires_local_artifacts
def test_ticket_maps_keep_lib084_exact() -> None:
    work_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    work_lines = [
        value
        for value in work_map.splitlines()
        if value.startswith("| `spurgeon-mtp` |")
    ]
    assert len(work_lines) == 1
    assert "| LIB-084 |" in work_lines[0]
    assert source_map.count("| `spurgeon-mtp` |") == 1
    line = next(
        value for value in source_map.splitlines() if "| `spurgeon-mtp` |" in value
    )
    assert "| LIB-084 |" in line
