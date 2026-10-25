"""Bind a complete retained New Advent envelope to the LIB-025 reconstruction route."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from lxml import etree
from ocd_kernel.lib.storage_topology import repository_relative_path
from ocd_kernel.reconstruction.contract import SourceManifest

from build.tools.acquire_newadvent_envelope import verified_members
from build.tools.census_newadvent_assets import inventory
from build.tei.newadvent_oracle import _closure, envelope_for_page
from build.tei.newadvent_reconstruction import _producer_closure


ROOT = Path(__file__).resolve().parents[2]


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def logical(path):
    return repository_relative_path(ROOT, path.resolve(strict=True))


def refresh_import_closures(manifest_path: Path):
    """Rebind helper-only changes after verifying every unchanged source authority.

    Top-level producer/oracle byte drift is rejected by SourceManifest.load;
    source records and profile bytes are never regenerated or relabeled here.
    """
    verified = SourceManifest.load(manifest_path, repository_root=ROOT)
    payload = verified.path.read_bytes()
    if sha(payload) != verified.sha256:
        raise ValueError("Source manifest changed during import-closure refresh")
    record = json.loads(payload)
    if record.get("ticket_id") != "LIB-025" or record.get("work_id") != "catholic-encyclopedia-vol01":
        raise ValueError("Import-closure refresh requires the LIB-025 route")
    record["producer_import_closure_sha256"] = _producer_closure(ROOT)
    record["validator"]["import_closure_sha256"] = _closure(ROOT)
    verified.path.write_bytes(canonical(record))
    refreshed = SourceManifest.load(verified.path, repository_root=ROOT)
    return {"manifest": str(verified.path), "previous_manifest_sha256": verified.sha256, "manifest_sha256": refreshed.sha256, "source_authorities_unchanged": True, "producer_import_closure_sha256": record["producer_import_closure_sha256"], "oracle_import_closure_sha256": record["validator"]["import_closure_sha256"]}


def image_media(payload):
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    if payload.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    try:
        root = etree.fromstring(payload, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise ValueError("Retained image does not have an identified image format") from exc
    if root.tag != "{http://www.w3.org/2000/svg}svg" or root.getroottree().docinfo.doctype:
        raise ValueError("Retained image XML is not SVG")
    return "image/svg+xml"


def validate_link_reconciliation_policy(policy):
    """Validate the source-local declaration before binding generated artifacts."""
    if not isinstance(policy, dict) or set(policy) != {"contract", "work_id", "mappings", "unmapped"} or policy["contract"] != "ocd-lib025-newadvent-link-reconciliation-v1" or policy["work_id"] != "catholic-encyclopedia-vol01" or not isinstance(policy["mappings"], list) or not isinstance(policy["unmapped"], list):
        raise ValueError("Invalid link reconciliation policy schema")
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    def address(value):
        return text(value) and re.fullmatch(r"https://www\.newadvent\.org/cathen/[a-z0-9-]+\.htm", value) is not None
    sources = set()
    for mapped, rows in ((True, policy["mappings"]), (False, policy["unmapped"])):
        keys = {"source_url", "rationale"} | ({"target_url", "index_url", "index_title", "source_occurrences"} if mapped else set())
        for row in rows:
            if not isinstance(row, dict) or set(row) != keys or not address(row["source_url"]) or not text(row["rationale"]) or row["source_url"] in sources:
                raise ValueError("Invalid or duplicate link reconciliation entry")
            sources.add(row["source_url"])
            if mapped:
                occurrences = row["source_occurrences"]
                if not address(row["target_url"]) or not address(row["index_url"]) or row["target_url"] == row["source_url"] or not text(row["index_title"]) or not isinstance(occurrences, list) or not occurrences or any(not isinstance(item, dict) or set(item) != {"page_url", "label"} or not address(item["page_url"]) or not text(item["label"]) for item in occurrences):
                    raise ValueError("Invalid link reconciliation mapping or occurrences")


def prepare(graph_path: Path, cohorts: list[Path], image_cohorts: list[Path], output: Path, stylesheet_cohorts: list[Path] | None = None, asset_cohorts: list[Path] | None = None, *, allow_partial_source: bool = False, failure_cohorts: list[Path] | None = None, typography_policy: Path | None = None, link_reconciliation_policy: Path | None = None, progress=None):
    # Check the human-visible attribution deliverable before creating derived
    # configuration, so a missing README cannot leave a plausible partial route.
    (output / "README.source.md").read_bytes()
    if link_reconciliation_policy is not None:
        validate_link_reconciliation_policy(json.loads(link_reconciliation_policy.read_bytes()))
    stylesheet_cohorts = stylesheet_cohorts or []
    asset_cohorts = asset_cohorts or []
    failure_cohorts = failure_cohorts or []
    all_cohorts = [*cohorts, *image_cohorts, *stylesheet_cohorts, *asset_cohorts, *failure_cohorts]
    if len({path.resolve() for path in all_cohorts}) != len(all_cohorts):
        raise ValueError("Duplicate acquisition cohort inputs")
    graph_bytes = graph_path.read_bytes()
    graph = json.loads(graph_bytes)
    if graph.get("contract") != "ocd-newadvent-link-census-v1" or graph["missing_linked_indexes"]:
        raise ValueError("A complete retained index graph is required")
    expected_urls = list(dict.fromkeys([row["url"] for row in graph["members"]] + graph["article_urls_in_first_occurrence_order"]))
    acquired = {}
    for cohort in cohorts:
        incoming = verified_members(cohort)
        if set(acquired) & set(incoming):
            raise ValueError("Duplicate retained HTML witnesses require reconciliation")
        acquired.update(incoming)
    missing = [url for url in expected_urls if url not in acquired]
    if (missing and not allow_partial_source) or set(acquired) - set(expected_urls):
        raise ValueError(f"Retained HTML envelope is incomplete or has extras: missing={len(missing)}, extra={len(set(acquired)-set(expected_urls))}, first_missing={missing[:3]}")
    for row in graph["members"]:
        payload = Path(row["path"]).read_bytes()
        if sha(payload) != row["sha256"] or len(payload) != row["bytes"]:
            raise ValueError("Retained index graph member bytes changed")
    assets = inventory(cohorts)
    if progress:
        progress(f"Verified {len(acquired)} retained HTML members; source asset census complete")
    if assets["unresolved"]:
        raise ValueError(f"Unresolved source image routes: {len(assets['unresolved'])}")
    image_records = {}
    for cohort in image_cohorts:
        incoming = verified_members(cohort, allow_images=True)
        if set(image_records) & set(incoming):
            raise ValueError("Duplicate retained image witnesses require reconciliation")
        image_records.update(incoming)
    stylesheet_records = {}
    for cohort in stylesheet_cohorts:
        incoming = verified_members(cohort, allow_stylesheets=True)
        if set(stylesheet_records) & set(incoming):
            raise ValueError("Duplicate retained stylesheet witnesses require reconciliation")
        stylesheet_records.update(incoming)
    for cohort in asset_cohorts:
        incoming = verified_members(cohort, allow_images=True, allow_stylesheets=True)
        receipt = json.loads((cohort / "acquisition.json").read_bytes())
        declared_assets = set(assets["image_urls"]) | set(assets["stylesheet_urls"])
        requested = [member["url"] for member in receipt["members"]]
        if len(requested) != len(set(requested)):
            raise ValueError("Duplicate mixed asset request URLs")
        for member in receipt["members"]:
            if member["status"] not in {"retained", "failed", "not-attempted"}:
                raise ValueError("Mixed asset cohort contains unknown request status")
            if member["url"] not in declared_assets:
                raise ValueError("Mixed asset cohort contains a non-asset URL or undeclared request URL")
        for url, record in incoming.items():
            path = urlsplit(url).path
            if path.startswith("/images/"):
                records = image_records
            elif path.startswith("/utility/") and path.endswith(".css"):
                records = stylesheet_records
            else:
                raise ValueError("Mixed asset cohort contains a non-asset URL")
            if url in records:
                raise ValueError("Duplicate retained asset witnesses require reconciliation")
            records[url] = record
    missing_images = set(assets["image_urls"]) - set(image_records)
    if (missing_images and not allow_partial_source) or set(image_records) - set(assets["image_urls"]):
        raise ValueError(f"Image envelope differs: required={len(assets['image_urls'])}, retained={len(image_records)}")
    if set(stylesheet_records) != set(assets["stylesheet_urls"]):
        raise ValueError("Required source stylesheet envelope is incomplete or contains extras")
    nonempty_stylesheets = [(Path(row["cohort"]) / row["path"]).read_bytes() for row in stylesheet_records.values() if (Path(row["cohort"]) / row["path"]).read_bytes().strip()]
    if nonempty_stylesheets:
        if typography_policy is None:
            raise ValueError("Nonempty source stylesheet requires a bound typography policy")
        policy_record = json.loads(typography_policy.read_bytes())
        if len(nonempty_stylesheets) != 1 or policy_record.get("css_sha256") != sha(nonempty_stylesheets[0]):
            raise ValueError("Typography policy does not bind the retained stylesheet")
    authorities = []
    def bind(name, path, role):
        payload = path.read_bytes()
        authorities.append({"name": name, "path": logical(path), "bytes": len(payload), "sha256": sha(payload), "role": role})
    unavailable_urls = [*missing, *(url for url in assets["image_urls"] if url in missing_images)]
    failed_evidence = {}
    if unavailable_urls:
        for cohort in all_cohorts:
            retained = verified_members(cohort, allow_images=True, allow_stylesheets=True)
            if cohort in failure_cohorts and retained:
                raise ValueError("Failure evidence cannot supply an alternate textual witness")
            for member in json.loads((cohort / "acquisition.json").read_bytes())["members"]:
                if cohort in failure_cohorts and (member["url"] not in unavailable_urls or member["status"] != "failed"):
                    raise ValueError("Supplemental failure evidence lies outside the unavailable member set")
                if member["url"] not in unavailable_urls or member["status"] != "failed":
                    continue
                if member.get("http_status") not in {404, 410}:
                    raise ValueError("Unavailable source has a nonterminal failure requiring review")
                error = member.get("error_response")
                if error is not None:
                    if error.get("final_url") != member["url"]:
                        raise ValueError("Unavailable source response URL differs")
                    failed_evidence[member["url"]] = (cohort, member)
        if set(failed_evidence) != set(unavailable_urls):
            raise ValueError("Every unavailable source member requires retained exact failure-response evidence")
    failed_acquisitions = []
    receipt_by_cohort = {cohort.resolve(): f"acquisition-{number:04d}" for number, cohort in enumerate(all_cohorts, 1)}
    html_members = []
    envelopes = []
    for number, url in enumerate(expected_urls, 1):
        if url not in acquired:
            continue
        record = acquired[url]
        path = Path(record["cohort"]) / record["path"]
        name = f"html-{number:06d}"
        bind(name, path, "primary-source")
        html_members.append({"authority": name, "url": url, "tei_id": f"newadvent-page-{number:06d}"})
        try:
            envelope = envelope_for_page(path.read_bytes(), url, name)
        except ValueError as exc:
            raise ValueError(f"Retained source envelope failed for {url}: {exc}") from exc
        envelopes.append(envelope)
        if progress and len(envelopes) % 500 == 0:
            progress(f"Accounted {len(envelopes)}/{len(acquired)} retained HTML document envelopes")
    image_members = []
    for number, url in enumerate(assets["image_urls"], 1):
        if url not in image_records:
            continue
        record = image_records[url]
        path = Path(record["cohort"]) / record["path"]
        name = f"image-{number:06d}"
        bind(name, path, "primary-source")
        image_members.append({"authority": name, "url": url, "media_type": image_media(path.read_bytes())})
    receipt_names = []
    stylesheet_members = []
    for number, url in enumerate(assets["stylesheet_urls"], 1):
        record = stylesheet_records[url]
        path = Path(record["cohort"]) / record["path"]
        name = f"stylesheet-{number:06d}"
        bind(name, path, "source-presentation-stylesheet")
        stylesheet_members.append({"authority": name, "url": url})
    for number, url in enumerate(unavailable_urls, 1):
        cohort, evidence = failed_evidence[url]
        authority = f"unavailable-response-{number:04d}"
        bind(authority, cohort / evidence["error_response"]["path"], "failed-acquisition-evidence")
        failed_acquisitions.append({"url": url, "kind": "html" if url in missing else "image", "http_status": evidence["http_status"], "response_authority": authority, "receipt_authority": receipt_by_cohort[cohort.resolve()], "disposition": "unavailable; excluded from included source members; no alternate witness substituted"})
    for number, cohort in enumerate(all_cohorts, 1):
        name = f"acquisition-{number:04d}"
        bind(name, cohort / "acquisition.json", "acquisition-receipt")
        receipt_names.append(name)
    if typography_policy is not None:
        bind("source-typography-policy", typography_policy, "source-presentation-policy")
    if link_reconciliation_policy is not None:
        bind("source-link-reconciliation-policy", link_reconciliation_policy, "source-link-reconciliation-policy")
    profile = {
        "contract": "ocd-lib025-newadvent-profile-v1", "work_id": "catholic-encyclopedia-vol01", "ticket_id": "LIB-025",
        "declared_envelope_retained": not unavailable_urls, "declared_envelope_accounted": True, "graph_sha256": sha(graph_bytes),
        "expression_scope": {"status": "partial" if unavailable_urls else "retained-cohort", "declared": "available retained New Advent web cohort; unavailable requested members are explicit gaps", "whole_work_complete": False, "expected_html_urls": expected_urls, "included_html_urls": [url for url in expected_urls if url in acquired], "expected_image_urls": assets["image_urls"], "included_image_urls": [url for url in assets["image_urls"] if url in image_records], "unavailable_urls": unavailable_urls},
        "failed_acquisitions": failed_acquisitions,
        "typography_policy_authority": "source-typography-policy" if typography_policy is not None else None,
        "link_reconciliation_policy_authority": "source-link-reconciliation-policy" if link_reconciliation_policy is not None else None,
        "html_parser": {"distribution": "html5lib", "version": "1.1", "producer_tree_builder": "etree", "oracle_tree_builder": "dom", "shared_source_adapter": "build/tei/newadvent_source_tree.py", "document_shell_builder": "dom", "source_address_syntax": "percent-encoded HTML name and same-kind sibling ordinal; not XPath", "topology": "browser-standard optional-end-tag recovery; implied attribute-free tbody is transparent only when no literal tbody exists"},
        "identity": {"title": "The Catholic Encyclopedia", "catalog_work_id": "catholic-encyclopedia-vol01", "witness": "newly retained current New Advent web collection", "printed_volume_scope": "article-local citation statements are preserved; the web collection includes separately identified source-history material", "historical_hash_claims": "preserved as historical missing-response claims; not relabeled as hashes of this new witness"},
        "mapping_summary": "Preserves all retained main-region and publisher-footer wording, source heading intervals, mixed inline order, links, lists, tables and images. HTML-standard numeric character references and CR/CRLF normalization follow browser reading. Complete document-shell metadata and explicit navigation, executable, advertising/layout and comment dispositions accompany the readable reconstruction. No generated legacy JSON is source authority.",
        "html_members": html_members, "image_members": image_members, "stylesheet_members": stylesheet_members, "source_envelope": envelopes, "acquisition_receipts": receipt_names,
        "unresolved": [
            {"id": "lib025-current-witness", "kind": "edition-witness", "status": "unresolved", "detail": "This newly retained web witness does not recover the discarded responses behind the 15 historical source-hash claims; article-local historical edition statements and web support/history pages remain distinct.", "owner": "project-maintainer"},
            {"id": "lib025-carrier-rights", "kind": "rights", "status": "unresolved", "detail": "The retained New Advent publisher copyright and transcription/credit statements are preserved; technical reconstruction does not establish carrier rights or authorize publication.", "owner": "project-maintainer"},
            {"id": "lib025-acceptance", "kind": "acceptance", "status": "unresolved", "detail": "The candidate has not received human textual acceptance or accepted-master promotion.", "owner": "project-maintainer"},
        ],
    }
    if failure_cohorts and not unavailable_urls:
        raise ValueError("Supplemental failures cannot be attached to a fully retained source scope")
    if unavailable_urls:
        profile["unresolved"].append({"id": "lib025-unavailable-source-members", "kind": "source-coverage", "status": "unresolved", "detail": "This is a partial retained-cohort reconstruction. The failure-bound HTML and image URLs remain unavailable; no whole-work completeness or alternate-witness substitution is claimed.", "owner": "project-maintainer"})
    profile_bytes = canonical(profile)
    policy = {"contract": "ocd-lib025-validation-policy-v1", "work_id": "catholic-encyclopedia-vol01", "profile_sha256": sha(profile_bytes), "required_checks": ["complete-index-and-article-envelope", "acquisition-url-path-byte-binding", "complete-source-shell-dispositions", "source-native-mixed-tree-and-heading-intervals", "independent-lexical-region-text", "complete-displayed-and-linked-images", "closed-header-and-package-evidence", "bound-TEI-P5-schema"], "shared_assumption": "html5lib 1.1 topology algorithm and source-node adapter are shared; producer uses ElementTree and oracle uses DOM; document-shell interpretation uses DOM in both; decoded main/footer text is independently corroborated using stdlib HTMLParser"}
    if unavailable_urls:
        policy["required_checks"][0] = "complete-retained-cohort-and-explicit-unavailable-HTML-accounting"
        policy["required_checks"][5] = "retained-images-and-explicit-unavailable-image-accounting"
        policy["scope_boundary"] = "Partial retained cohort only; failed acquisitions are evidence, never included source text; whole-work completeness is false."
    output.mkdir(parents=True, exist_ok=True)
    profile_path = output / "reconstruction-profile.json"
    policy_path = output / "validation-policy.json"
    profile_path.write_bytes(profile_bytes)
    policy_path.write_bytes(canonical(policy))
    bind("reconstruction-profile", profile_path, "complete-source-feature-profile")
    bind("validation-policy", policy_path, "independent-validation-policy")
    bind("source-graph", graph_path, "source-member-graph")
    bind("source-attribution-readme", output / "README.source.md", "source-attribution-readme")
    bind("historical-source-blocker", ROOT / "sources/reference/catholic-encyclopedia/LIB-025.blocked-source-evidence.json", "historical-source-blocker")
    for name, path, role in [
        ("tei-p5-xsd", "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-validation-schema"),
        ("tei-p5-xsd-teix", "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd", "tei-validation-schema-dependency"),
        ("tei-p5-xsd-xml", "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd", "tei-validation-schema-dependency"),
        ("candidate-package-schema", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "candidate-package-schema"),
    ]:
        bind(name, ROOT / path, role)
    producer = ROOT / "build/tei/newadvent_reconstruction.py"
    oracle = ROOT / "build/tei/newadvent_oracle.py"
    package_schema = next(row for row in authorities if row["name"] == "candidate-package-schema")
    manifest = {"contract": "ocd-source-manifest-v1", "work_id": "catholic-encyclopedia-vol01", "ticket_id": "LIB-025", "source_id": "newadvent-catholic-encyclopedia-current-web-20260911", "retained_source_path": authorities[0]["path"], "authorities": authorities, "converter": {"id": "ocd-lib025-newadvent-retained-html-to-tei", "version": "1", "callable": "_convert", "implementation_path": producer.relative_to(ROOT).as_posix(), "implementation_sha256": sha(producer.read_bytes())}, "producer_import_closure_sha256": _producer_closure(ROOT), "validator": {"id": "ocd-lib025-newadvent-independent-html-tei-oracle", "version": "1", "callable": "_oracle", "implementation_path": oracle.relative_to(ROOT).as_posix(), "implementation_sha256": sha(oracle.read_bytes()), "import_closure_sha256": _closure(ROOT)}, "package_schema": {"path": package_schema["path"], "sha256": package_schema["sha256"]}}
    manifest["expression_scope"] = profile["expression_scope"]
    manifest["failed_acquisitions"] = failed_acquisitions
    manifest_path = output / "catholic-encyclopedia.source-manifest.json"
    manifest_path.write_bytes(canonical(manifest))
    return {"manifest": str(manifest_path), "manifest_sha256": sha(manifest_path.read_bytes()), "html_members": len(html_members), "image_members": len(image_members)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--cohort", type=Path, action="append", default=[])
    parser.add_argument("--acquisition-run", type=Path)
    parser.add_argument("--image-cohort", type=Path, action="append", default=[])
    parser.add_argument("--stylesheet-cohort", type=Path, action="append", default=[])
    parser.add_argument("--asset-cohort", type=Path, action="append", default=[], help="Mixed retained image and stylesheet cohort")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--refresh-import-closures", type=Path, help="Verify unchanged source/top-level implementation bytes and refresh only imported helper digests")
    parser.add_argument("--allow-partial-source", action="store_true", help="Declare only the retained cohort complete; bind unavailable HTML/image responses as explicit source gaps")
    parser.add_argument("--failure-cohort", type=Path, action="append", default=[], help="Additional exact failed-response evidence, never alternate textual witnesses")
    parser.add_argument("--typography-policy", type=Path, help="Source-bound native typography policy; nonempty supported stylesheets require it")
    parser.add_argument("--link-reconciliation-policy", type=Path, help="Bind exact failed source href repairs to retained index and occurrence evidence")
    args = parser.parse_args()
    if args.refresh_import_closures:
        if args.graph or args.cohort or args.acquisition_run or args.image_cohort or args.stylesheet_cohort or args.asset_cohort or args.output_dir or args.allow_partial_source or args.failure_cohort or args.typography_policy or args.link_reconciliation_policy:
            parser.error("Import-closure refresh cannot be mixed with source preparation arguments")
        print(json.dumps(refresh_import_closures(args.refresh_import_closures), indent=2))
        raise SystemExit(0)
    if not args.graph or not args.output_dir or not (args.cohort or args.acquisition_run):
        parser.error("Source preparation requires --graph, --output-dir, and retained --cohort or --acquisition-run inputs")
    if args.acquisition_run:
        if (args.acquisition_run / "acquisition.lock").exists():
            parser.error("The article acquisition run has not been finalized")
        args.cohort.extend(sorted(args.acquisition_run.glob("batch-[0-9][0-9][0-9][0-9]")))
    print(json.dumps(prepare(args.graph, args.cohort, args.image_cohort, args.output_dir, args.stylesheet_cohort, args.asset_cohort, allow_partial_source=args.allow_partial_source, failure_cohorts=args.failure_cohort, typography_policy=args.typography_policy, link_reconciliation_policy=args.link_reconciliation_policy, progress=lambda message: print(message, file=sys.stderr, flush=True)), indent=2))
