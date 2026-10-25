from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit

from lxml import etree
import pytest

from build.tei.expositors_bible_lib033_oracle import (
    _assert_json_type_exact,
    _closure_digest,
    _oracle,
    _repository_import_closure,
)
from build.tei.expositors_bible_lib033_reconstruction import _convert
from build.tools.count_dataset_records import collect_work_catalog
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate
from ocd_kernel.tei.validate import compiled_schema


pytestmark = [pytest.mark.slow, pytest.mark.requires_local_artifacts]
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/expositors-bible-lib033.source-manifest.json"
PROFILE = ROOT / "sources/commentaries/expositors-bible/lib033.reconstruction-profile.json"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MEMBERS = {
    "README.source.md",
    "content.tei.xml",
    "manifest.json",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
}
WORK_IDS = (
    "expositors-bible--alexander-maclaren",
    "expositors-bible--alfred-plummer",
    "expositors-bible--andrew-harper",
    "expositors-bible--frederic-w-farrar",
    "expositors-bible--g-g-findlay",
)
EXTRA_MACLAREN_HASHES = {
    "5f76553f07cf45368a772e0a2f654df2852ee9be5c3f0f4d35549391a4791b58",
    "e7bf253c78cc91a77c3a3a5173122f89d03b29390ade4f3e14f5d2db2ef98ebb",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


@pytest.fixture(scope="module")
def lib033_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="module")
def lib033_candidate(
    tmp_path_factory: pytest.TempPathFactory, lib033_manifest: SourceManifest
) -> CandidatePackage:
    destination = tmp_path_factory.mktemp("lib033-candidate-parent") / "candidate"
    return reconstruct(lib033_manifest, destination, _convert)


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def test_manifest_binds_exact_twelve_members_and_five_identity_files(
    lib033_manifest: SourceManifest,
) -> None:
    authorities = list(lib033_manifest.record["authorities"])
    primary = [item for item in authorities if item["role"] == "primary-source"]
    identity = [item for item in authorities if item["role"] == "work-identity-binding"]
    assert len(primary) == 12
    assert sum(int(item["bytes"]) for item in primary) == 12439067
    assert len({item["path"] for item in primary}) == 12
    assert len(identity) == 5
    assert {
        json.loads(lib033_manifest.authority_path(str(item["name"])).read_bytes())["work_id"]
        for item in identity
    } == set(WORK_IDS)


def test_complete_candidate_validates_and_preserves_exact_source_bytes(
    lib033_manifest: SourceManifest, lib033_candidate: CandidatePackage
) -> None:
    report = validate(lib033_manifest, lib033_candidate, _oracle)
    accountability = json.loads(
        lib033_candidate.member_bytes("source-accountability.json")
    )
    provenance = json.loads(lib033_candidate.member_bytes("provenance.json"))
    root = etree.fromstring(
        lib033_candidate.member_bytes("content.tei.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    assert set(lib033_candidate.member_names) == MEMBERS
    assert report.status == "pass"
    assert accountability["source_member_count"] == 12
    assert accountability["work_count"] == 5
    assert accountability["source_bytes"] == 12439067
    assert accountability["feature_count"] == len(accountability["crosswalk"]) == 67869
    assert accountability["omitted_feature_count"] == 0
    assert accountability["unresolved_feature_count"] == 0
    assert accountability["member_census"]["counts"] == {
        "included": 12,
        "excluded": 35,
        "retained_family_total": 47,
    }
    assert len(accountability["member_census"]["excluded"]) == 35
    contradiction = accountability["member_census"]["inventory_contradiction"]
    assert "47 XML files" in contradiction
    assert "48 of 49 volumes" in contradiction
    assert "not a retained-file census" in contradiction
    assert provenance["status"] == "nonaccepted"
    assert provenance["rights"]["publication_authorized"] is False
    assert provenance["identity"]["canonical_identity_decided"] is False
    assert [item.get(XML_ID) for item in root.xpath("./tei:TEI", namespaces=NS)] == list(WORK_IDS)
    raw_by_id = {
        item["member_id"]: (
            ROOT / item["path"]
        ).read_bytes()
        for item in accountability["member_census"]["included"]
    }
    retained = accountability["retained_source_bytes"]
    assert set(retained) == set(raw_by_id)
    for member_id, entry in retained.items():
        decoded = base64.b64decode(entry["base64"].encode("ascii"), validate=True)
        assert len(decoded) == entry["bytes"] == len(raw_by_id[member_id])
        assert _sha(decoded) == entry["sha256"] == _sha(raw_by_id[member_id])
    notes = root.xpath("//tei:note[@type='exact-retained-source-bytes']", namespaces=NS)
    assert len(notes) == 10
    for note in notes:
        member_id = note.getparent().get(XML_ID)
        assert member_id not in {"findlay-expositoreph", "findlay-expositorgal"}
        assert base64.b64decode((note.text or "").encode("ascii"), validate=True) == raw_by_id[member_id]


def test_findlay_members_use_nested_source_projection_and_bound_local_refs(
    lib033_candidate: CandidatePackage,
) -> None:
    root = etree.fromstring(
        lib033_candidate.member_bytes("content.tei.xml"),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    accountability = json.loads(
        lib033_candidate.member_bytes("source-accountability.json")
    )
    expected_stanzas = {
        "findlay-expositoreph": (48, 175),
        "findlay-expositorgal": (8, 22),
    }
    for member_id, (stanza_groups, stanza_lines) in expected_stanzas.items():
        member = root.xpath(
            f"//tei:div[@xml:id='{member_id}']", namespaces=NS
        )[0]
        rows = [
            item for item in accountability["crosswalk"] if item["member_id"] == member_id
        ]
        projected_rows = [
            item for item in rows if item["disposition"] == "represented"
        ]
        evidence_rows = [
            item for item in rows if item["disposition"] == "evidence-only"
        ]
        assert len(evidence_rows) == {
            "findlay-expositoreph": 100,
            "findlay-expositorgal": 69,
        }[member_id]
        assert all(item["tei_selector"] is None for item in evidence_rows)
        assert all(
            not str(item["source_selector"]).startswith("/ThML[1]/ThML.body[1]")
            for item in evidence_rows
        )
        assert all(
            item["tei_selector"] == f"#{item['tei_xml_id']}"
            for item in projected_rows
        )
        feature_ids = {str(item["tei_xml_id"]) for item in projected_rows}
        observed_ids = {
            str(item.get(XML_ID))
            for item in member.xpath(".//*[@xml:id]", namespaces=NS)
        }
        assert feature_ids <= observed_ids
        assert not member.xpath(
            ".//tei:note[@type='exact-retained-source-bytes']", namespaces=NS
        )
        assert not member.xpath(
            ".//tei:div[@type='parsed-xml-feature-transcription']", namespaces=NS
        )
        assert member.xpath(
            ".//tei:div[@type='source-xml-element']//tei:div[@type='source-xml-element']",
            namespaces=NS,
        )
        assert len(
            member.xpath(".//tei:lg[@type='stanza']", namespaces=NS)
        ) == stanza_groups
        assert len(member.xpath(".//tei:l", namespaces=NS)) == stanza_lines
        assert member.xpath(
            ".//tei:div[@type='source-heading-section']", namespaces=NS
        )
        th_rows = [item for item in projected_rows if item["source_tag"] == "th"]
        label_cells = member.xpath(".//tei:cell[@role='label']", namespaces=NS)
        assert {item.get(XML_ID) for item in label_cells} == {
            item["tei_xml_id"] for item in th_rows
        }
        assert all(
            "urn:ocd:source-tag:th" in (item.get("ana") or "")
            for item in label_cells
        )
        source_ids = {
            str(item["source_attributes"]["id"]): str(item["tei_xml_id"])
            for item in projected_rows
            if "id" in item["source_attributes"]
        }
        target_ids = observed_ids
        for item in projected_rows:
            attrs = item["source_attributes"]
            if item["source_tag"] not in {"a", "scripRef", "scripCom"}:
                continue
            link = attrs.get("href") or attrs.get("osisRef")
            if not link:
                continue
            parsed = urlsplit(link)
            if not parsed.fragment or parsed.scheme or parsed.netloc or parsed.path:
                continue
            source_target = source_ids.get(unquote(parsed.fragment))
            nodes = member.xpath(
                ".//*[@xml:id=$feature_id]", namespaces=NS, feature_id=item["tei_xml_id"]
            )
            assert len(nodes) == 1
            observed_target = nodes[0].get("target")
            assert observed_target is not None
            if parsed.query:
                assert observed_target == link
                continue
            assert source_target is not None
            assert unquote(urlsplit(observed_target).fragment) == source_target
            assert source_target in target_ids


def test_exact_catalog_claim_lineage_and_global_work_catalog_invariant(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = json.loads(PROFILE.read_bytes())
    legacy = profile["legacy_current_claims"]
    assert {work: len(legacy[work]) for work in WORK_IDS} == {
        "expositors-bible--alexander-maclaren": 2,
        "expositors-bible--alfred-plummer": 2,
        "expositors-bible--andrew-harper": 1,
        "expositors-bible--frederic-w-farrar": 3,
        "expositors-bible--g-g-findlay": 2,
    }
    retained = {item["sha256"] for item in profile["included_members"]}
    claims = {digest for values in legacy.values() for digest in values}
    assert len(claims) == 10
    assert retained == claims | EXTRA_MACLAREN_HASHES
    from build.tools import count_dataset_records

    manifest_selection = MANIFEST.relative_to(ROOT).as_posix()

    def selected_manifest_paths(sources_root: Path, selections):
        assert sources_root == ROOT / "sources"
        assert tuple(selections) == (manifest_selection,)
        return sources_root, None

    original_rglob = Path.rglob

    def selected_manifest_discovery(path: Path, pattern: str):
        if path == ROOT / "sources" and pattern in {"*.source-manifest.json", "source-manifest.json"}:
            return iter((MANIFEST,))
        return original_rglob(path, pattern)

    # Preserve declaration-only route checks while selecting exact retained authority.
    monkeypatch.setattr(Path, "rglob", selected_manifest_discovery)
    monkeypatch.setattr(
        count_dataset_records, "_resolve_source_manifest_allowlist", selected_manifest_paths
    )
    resources = []
    for path in sorted((ROOT / "data/commentaries/expositors-bible").glob("*.json")):
        record = json.loads(path.read_bytes())
        digest = record["meta"]["provenance"]["source_hash"].removeprefix("sha256:")
        if digest in claims:
            resources.append(path.relative_to(ROOT).as_posix())
    catalog = collect_work_catalog(
        ROOT / "data",
        source_manifest_allowlist=[manifest_selection],
        data_resource_allowlist=resources,
    )
    assert catalog.summary["work_units"] == len(WORK_IDS)
    works = {item["work_id"]: item for item in catalog.works if item["work_id"] in WORK_IDS}
    assert set(works) == set(WORK_IDS)
    for work_id, work in works.items():
        state = work["reconstruction_state"]
        observed_claims = set()
        for source_path in work["source_paths"]:
            resource = json.loads((ROOT / "data" / source_path).read_bytes())
            observed_claims.add(
                resource["meta"]["provenance"]["source_hash"].removeprefix("sha256:")
            )
        assert observed_claims == set(legacy[work_id])
        assert state["retained_source"] == "manifest_bound"
        assert state["tei_candidate"] == "route_available"
        assert state["validation"] == "validator_available"
        assert state["human_review"] == "required"
        assert state["accepted_ir"] == "not_accepted"
        assert state["publication"] == "not_ready"
        route = next(
            item
            for item in state["routes"]
            if item["manifest"]
            == manifest_selection
        )
        assert route["association"] == "source_hash+exact_id"
        assert route["scope"] == "work"
        assert route["verification"] == "verified"


def test_frozen_ticket_maps_remain_exact() -> None:
    work_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    expected_counts = dict(zip(WORK_IDS, (2, 2, 1, 3, 2), strict=True))
    for work_id, count in expected_counts.items():
        lines = [line for line in work_map.splitlines() if line.startswith(f"| `{work_id}` |")]
        assert len(lines) == 1
        assert f"| LIB-033 | {count} | none |" in lines[0]
    profile = json.loads(PROFILE.read_bytes())
    for work_id, digests in profile["legacy_current_claims"].items():
        lines = [line for line in source_map.splitlines() if line.startswith(f"| `{work_id}` |")]
        assert len(lines) == len(digests)
        assert {line.split("`sha256:", 1)[1].split("`", 1)[0] for line in lines} == set(digests)
        assert all("| LIB-033 | current-claim |" in line for line in lines)


def test_required_ccel_attribution_is_durable_and_source_local(
    lib033_candidate: CandidatePackage,
) -> None:
    data_readme = (ROOT / "data/commentaries/expositors-bible/README.md").read_bytes()
    candidate_readme = lib033_candidate.member_bytes("README.source.md")
    permission = (ROOT / "sources/commentaries/expositors-bible/ccel-permission.md").read_bytes()
    assert b"sourced via CCEL.org" in data_readme
    assert b"sourced via CCEL.org" in candidate_readme
    assert b"do not sell CCEL files or derivatives of their formatting" in permission


def test_namespace_qualified_source_attributes_remain_distinct(
    lib033_candidate: CandidatePackage,
) -> None:
    accountability = json.loads(
        lib033_candidate.member_bytes("source-accountability.json")
    )
    collisions = [
        item
        for item in accountability["crosswalk"]
        if item["member_id"] == "harper-expositordeut"
        and item["source_tag"] == "span"
        and "lang" in item["source_attributes"]
        and "{http://www.w3.org/XML/1998/namespace}lang"
        in item["source_attributes"]
    ]
    assert len(collisions) == 10
    assert all(
        item["source_attributes"]["lang"]
        == item["source_attributes"]["{http://www.w3.org/XML/1998/namespace}lang"]
        == "la"
        for item in collisions
    )


def test_json_type_guard_rejects_bool_int_and_float_equivalence() -> None:
    for observed, expected in ((790728.0, 790728), (0, False), (False, 0)):
        with pytest.raises(ValueError, match="JSON type mutation"):
            _assert_json_type_exact(observed, expected, "LIB-033 regression")


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reorder",
        "member-census",
        "exact-source-bytes",
        "feature-misattachment",
        "metadata-rights",
        "unresolved",
        "candidate-source-id",
        "provenance-extra-key",
        "provenance-missing-identity",
        "provenance-false-canonical",
        "provenance-false-print-collation",
        "unresolved-body",
        "unresolved-order",
        "readme-false-claim",
        "p5-valid-tag-substitution",
        "namespace-attribute-collapse",
        "tei-ab-text-invention",
        "tei-direct-seg-tail-invention",
        "tei-harper-author-mutation",
        "provenance-authority-bytes-float",
        "provenance-canonical-bool-int",
        "candidate-manifest-member-bytes-float",
        "accountability-feature-count-float",
    ],
)
def test_independent_oracle_rejects_resealed_adversarial_mutations(
    tmp_path: Path,
    lib033_manifest: SourceManifest,
    lib033_candidate: CandidatePackage,
    mutation: str,
) -> None:
    destination = tmp_path / mutation
    shutil.copytree(lib033_candidate.path, destination)
    try:
        if mutation in {"candidate-source-id", "candidate-manifest-member-bytes-float"}:
            manifest = json.loads((destination / "manifest.json").read_bytes())
            if mutation == "candidate-source-id":
                manifest["source_id"] = "invented-source-id"
            else:
                readme = next(
                    item
                    for item in manifest["members"]
                    if item["name"] == "README.source.md"
                )
                readme["bytes"] = float(readme["bytes"])
            (destination / "manifest.json").write_bytes(_canonical(manifest))
            mutated = CandidatePackage.load(destination)
            with pytest.raises(ValueError):
                validate(lib033_manifest, mutated, _oracle)
            return
        if mutation in {
            "omission",
            "duplication",
            "reorder",
            "member-census",
            "namespace-attribute-collapse",
            "accountability-feature-count-float",
        }:
            name = "source-accountability.json"
            value = json.loads((destination / name).read_bytes())
            if mutation == "omission":
                value["crosswalk"].pop()
            elif mutation == "duplication":
                value["crosswalk"][-1] = value["crosswalk"][-2]
            elif mutation == "reorder":
                value["crosswalk"][100], value["crosswalk"][101] = (
                    value["crosswalk"][101],
                    value["crosswalk"][100],
                )
            elif mutation == "member-census":
                value["member_census"]["excluded"].pop()
            elif mutation == "accountability-feature-count-float":
                value["feature_count"] = float(value["feature_count"])
            else:
                row = next(
                    item
                    for item in value["crosswalk"]
                    if item["member_id"] == "harper-expositordeut"
                    and item["source_tag"] == "span"
                    and "lang" in item["source_attributes"]
                    and "{http://www.w3.org/XML/1998/namespace}lang"
                    in item["source_attributes"]
                )
                del row["source_attributes"][
                    "{http://www.w3.org/XML/1998/namespace}lang"
                ]
            content = _canonical(value)
        elif mutation in {
            "exact-source-bytes",
            "feature-misattachment",
            "p5-valid-tag-substitution",
            "tei-ab-text-invention",
            "tei-direct-seg-tail-invention",
            "tei-harper-author-mutation",
        }:
            name = "content.tei.xml"
            content = (destination / name).read_bytes()
            if mutation == "exact-source-bytes":
                marker = b"exact-retained-source-bytes"
                start = content.index(b">", content.index(marker)) + 1
                replacement = b"B" if content[start : start + 1] != b"B" else b"C"
                content = content[:start] + replacement + content[start + 1 :]
            elif mutation == "feature-misattachment":
                first = b'maclaren-expositorpsalms1-feature-00100'
                second = b'maclaren-expositorpsalms1-feature-00101'
                sentinel = b'lib033-feature-swap-sentinel-0000000000'
                assert len(first) == len(second) == len(sentinel)
                content = content.replace(first, sentinel, 1).replace(second, first, 1).replace(sentinel, second, 1)
            elif mutation == "p5-valid-tag-substitution":
                document = etree.fromstring(
                    content,
                    etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
                )
                segment = document.xpath(
                    "//tei:ab[@type='source-xml-element']/tei:seg[@type='direct-text'][string-length(.) > 0]",
                    namespaces=NS,
                )[0]
                segment.tag = "{http://www.tei-c.org/ns/1.0}q"
                content = etree.tostring(
                    document, encoding="UTF-8", xml_declaration=True, pretty_print=False
                )
                assert compiled_schema().validate(etree.ElementTree(document))
            else:
                document = etree.fromstring(
                    content,
                    etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
                )
                if mutation == "tei-ab-text-invention":
                    block = document.xpath(
                        "//tei:ab[@type='source-xml-element']", namespaces=NS
                    )[0]
                    block.text = "INVENTED"
                elif mutation == "tei-direct-seg-tail-invention":
                    segment = document.xpath(
                        "//tei:seg[@type='direct-text']", namespaces=NS
                    )[0]
                    segment.tail = "INVENTED"
                else:
                    author = document.xpath(
                        "./tei:TEI[@xml:id='expositors-bible--andrew-harper']"
                        "/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author",
                        namespaces={
                            **NS,
                            "xml": "http://www.w3.org/XML/1998/namespace",
                        },
                    )[0]
                    author.text = "Invented Harper"
                content = etree.tostring(
                    document, encoding="UTF-8", xml_declaration=True, pretty_print=False
                )
                assert compiled_schema().validate(etree.ElementTree(document))
        elif mutation in {
            "metadata-rights",
            "provenance-extra-key",
            "provenance-missing-identity",
            "provenance-false-canonical",
            "provenance-false-print-collation",
            "provenance-authority-bytes-float",
            "provenance-canonical-bool-int",
        }:
            name = "provenance.json"
            value = json.loads((destination / name).read_bytes())
            value["status"] = "accepted"
            value["rights"]["publication_authorized"] = True
            if mutation != "metadata-rights":
                value["status"] = "nonaccepted"
                value["rights"]["publication_authorized"] = False
            if mutation == "provenance-extra-key":
                value["invented"] = "accepted"
            elif mutation == "provenance-missing-identity":
                del value["identity"]
            elif mutation == "provenance-false-canonical":
                value["identity"]["canonical_identity_decided"] = True
            elif mutation == "provenance-false-print-collation":
                value["identity"]["print_collation"] = "performed"
            elif mutation == "provenance-authority-bytes-float":
                authority = value["authorities"]["retained-maclaren-psalms-1"]
                authority["bytes"] = float(authority["bytes"])
            elif mutation == "provenance-canonical-bool-int":
                value["identity"]["canonical_identity_decided"] = 0
            content = _canonical(value)
        elif mutation in {"unresolved", "unresolved-body", "unresolved-order"}:
            name = "unresolved.jsonl"
            lines = (destination / name).read_bytes().splitlines(keepends=True)
            if mutation == "unresolved":
                content = b"".join(lines[:-1])
            elif mutation == "unresolved-order":
                lines[0], lines[1] = lines[1], lines[0]
                content = b"".join(lines)
            else:
                value = json.loads(lines[0])
                value["reason"] = "Resolved by an unbound assertion."
                lines[0] = _canonical(value)
                content = b"".join(lines)
        else:
            name = "README.source.md"
            content = (destination / name).read_bytes() + (
                b"\nThis candidate is accepted, rights-cleared, and publication-ready.\n"
            )
        mutated = _reseal(destination, name, content)
        with pytest.raises(ValueError):
            validate(lib033_manifest, mutated, _oracle)
    finally:
        shutil.rmtree(destination, ignore_errors=False)


def test_oracle_import_closure_is_transitive_and_producer_independent(
    lib033_manifest: SourceManifest,
) -> None:
    policy = json.loads(
        lib033_manifest.authority_path("validation-policy").read_bytes()
    )
    closure = _repository_import_closure(
        ROOT,
        ROOT / "build/tei/expositors_bible_lib033_oracle.py",
        tuple(policy["forbidden_import_prefixes"]),
    )
    paths = {item["path"] for item in closure}
    assert {
        "build/tei/expositors_bible_lib033_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/tei/validate.py",
    } <= paths
    assert _closure_digest(ROOT, policy) == lib033_manifest.record["validator"][
        "import_closure_sha256"
    ]
    source = (ROOT / "build/tei/expositors_bible_lib033_oracle.py").read_text(
        encoding="utf-8"
    )
    assert "expositors_bible_lib033_reconstruction" not in source
    assert "ccel_expositors_bible" not in source
    assert "build.lib.ccel_thml" not in source
    assert "normalizer" not in source


def test_fresh_process_different_cwd_and_hash_seed_packages_are_byte_identical(
    tmp_path: Path,
) -> None:
    code = (
        "from pathlib import Path; import hashlib,sys; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.expositors_bible_lib033_reconstruction import _convert; "
        "r=Path(sys.argv[1]); "
        "s=SourceManifest.load(Path(sys.argv[3]),repository_root=r); "
        "c=reconstruct(s,Path(sys.argv[2]),_convert); "
        "print('|'.join(n+':'+hashlib.sha256(c.member_bytes(n)).hexdigest() for n in c.member_names))"
    )
    results = []
    destinations = []
    try:
        for ordinal, seed in ((1, "17"), (2, "991")):
            cwd = tmp_path / f"cwd-{ordinal}"
            destination_parent = tmp_path / f"destination-parent-{ordinal}"
            cwd.mkdir()
            destination_parent.mkdir()
            destination = destination_parent / "candidate"
            destinations.append(destination)
            environment = os.environ.copy()
            environment["PYTHONHASHSEED"] = seed
            environment["PYTHONPATH"] = str(ROOT)
            completed = subprocess.run(
                [sys.executable, "-c", code, str(ROOT), str(destination), str(MANIFEST)],
                cwd=cwd,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            results.append(completed.stdout.strip())
        assert results[0] == results[1]
        assert {
            path.name: path.read_bytes() for path in sorted(destinations[0].iterdir())
        } == {
            path.name: path.read_bytes() for path in sorted(destinations[1].iterdir())
        }
    finally:
        for destination in destinations:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=False)
