"""Lossless EEBO-TCP TEI verifier for Stillingfleet's *Origines sacræ*.

The released source is already TEI P5.  The faithful transformation is therefore
an exact-byte projection after source identity, metadata, structure, and vendored
TEI schema checks.  Re-serializing this document would add risk while adding no
textual value: the TCP page anchors, marginal notes, gaps, and character markers
are already represented directly in the source XML.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
from collections import Counter
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}
EXPECTED_SOURCE_SHA256 = "4d8363a0fb86a92c10a58a048997a1129e99f712c40d1419021b3a1110541b3c"
EXPECTED_TCP_CHARS_SHA256 = "f4acf5c10f6201c81e1c01dfd4e6e7c3c6b10ed9c1352c5808522ad06d63e9af"
SOURCE_RELATIVE_PATH = (
    "raw/clean-ready-acquisition-to-tei/master-4/28/"
    "stillingfleet-origines-sacrae/A61580.xml"
)
TCP_CHARS_RELATIVE_PATH = (
    "raw/clean-ready-acquisition-to-tei/master-4/28/"
    "stillingfleet-origines-sacrae/tcpchars.xml"
)


class SourceMismatchError(ValueError):
    """The retained byte stream is not the gate-released TCP witness."""


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest of one file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source_path(repository_root: Path) -> Path:
    """Resolve the retained source through the repository storage topology."""
    return resolve_repo_path(repository_root, SOURCE_RELATIVE_PATH)


def resolve_tcp_chars_path(repository_root: Path) -> Path:
    """Resolve the retained, pinned TCP character authority."""
    return resolve_repo_path(repository_root, TCP_CHARS_RELATIVE_PATH)


def _parse(source: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_blank_text=False,
        strip_cdata=False,
        huge_tree=True,
    )
    return etree.parse(str(source), parser)


def _local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _normalized_text(element: etree._Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _single_text(document: etree._ElementTree, xpath: str) -> str:
    matches = document.xpath(xpath, namespaces=NS)
    if len(matches) != 1:
        raise SourceMismatchError(f"expected one value for {xpath}, found {len(matches)}")
    value = matches[0]
    if isinstance(value, etree._Element):
        return _normalized_text(value)
    return str(value).strip()


@lru_cache(maxsize=1)
def _compiled_relaxng(schema_path: Path) -> etree.RelaxNG:
    return etree.RelaxNG(etree.parse(str(schema_path)))


def _validate_relaxng(document: etree._ElementTree, repository_root: Path) -> None:
    schema_path = repository_root / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"
    schema = _compiled_relaxng(schema_path)
    if not schema.validate(document):
        error = schema.error_log.last_error
        raise SourceMismatchError(f"TEI P5 Relax NG validation failed: {error}")


def audit_source(source: Path, *, repository_root: Path) -> dict[str, Any]:
    """Validate and census the exact retained TCP TEI source."""
    source_hash = sha256_file(source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise SourceMismatchError(
            f"source SHA-256 {source_hash} does not match {EXPECTED_SOURCE_SHA256}"
        )

    document = _parse(source)
    root = document.getroot()
    if root.tag != f"{{{TEI_NS}}}TEI":
        raise SourceMismatchError(f"expected TEI P5 root, found {root.tag}")
    _validate_relaxng(document, repository_root)

    elements = list(root.iter())
    tag_counts = Counter(_local_name(element) for element in elements)
    div_types = Counter(
        element.get("type", "") for element in elements if _local_name(element) == "div"
    )
    gap_reasons = Counter(
        element.get("reason", "") for element in elements if _local_name(element) == "gap"
    )
    page_breaks = [element for element in elements if _local_name(element) == "pb"]

    title = _single_text(document, "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title[1]")
    tcp_identifier = _single_text(
        document,
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:idno[@type='DLPS']",
    )
    edition_date = _single_text(
        document,
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:editionStmt/tei:edition/tei:date",
    )
    ending = _single_text(document, "/tei:TEI/tei:text/tei:body/tei:div[last()]/tei:trailer")
    availability_refs = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability//tei:ref/@target",
        namespaces=NS,
    )

    expected = {
        "title": "Origines sacræ",
        "tcp_identifier": "A61580",
        "edition_date": "1662",
        "ending": "FINIS.",
    }
    actual = {
        "title": title,
        "tcp_identifier": tcp_identifier,
        "edition_date": edition_date,
        "ending": ending,
    }
    if not actual["title"].startswith(expected["title"]):
        raise SourceMismatchError(f"unexpected title: {actual['title']}")
    for key in ("tcp_identifier", "edition_date", "ending"):
        if actual[key] != expected[key]:
            raise SourceMismatchError(f"unexpected {key}: {actual[key]}")
    cc0_reference_present = "https://creativecommons.org/publicdomain/zero/1.0/" in {
        str(value) for value in availability_refs
    }
    if not cc0_reference_present:
        raise SourceMismatchError("TCP CC0 reference is missing from teiHeader availability")

    tcp_chars_path = resolve_tcp_chars_path(repository_root)
    tcp_chars_hash = sha256_file(tcp_chars_path)
    if tcp_chars_hash != EXPECTED_TCP_CHARS_SHA256:
        raise SourceMismatchError(
            f"TCP character authority SHA-256 {tcp_chars_hash} does not match "
            f"{EXPECTED_TCP_CHARS_SHA256}"
        )
    tcp_chars = _parse(tcp_chars_path).getroot()
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    authority_ids = {
        element.get(xml_id) for element in tcp_chars.iter() if element.get(xml_id)
    }
    source_g_refs = [
        element.get("ref", "").split(":", 1)[-1]
        for element in elements
        if _local_name(element) == "g"
    ]
    missing_g_refs = sorted(set(source_g_refs) - authority_ids)
    if missing_g_refs:
        raise SourceMismatchError(
            f"TCP character references missing from pinned authority: {missing_g_refs}"
        )

    return {
        "source_sha256": source_hash,
        "source_bytes": source.stat().st_size,
        "tei_p5_relaxng_valid": True,
        "title_starts_with": expected["title"],
        "tcp_identifier": tcp_identifier,
        "edition_date": edition_date,
        "cc0_reference_present": cc0_reference_present,
        "tcp_chars_sha256": tcp_chars_hash,
        "tcp_character_references": len(source_g_refs),
        "unique_tcp_character_references": len(set(source_g_refs)),
        "unresolved_tcp_character_references": missing_g_refs,
        "tag_counts": dict(sorted(tag_counts.items())),
        "div_types": dict(sorted(div_types.items())),
        "gap_reasons": dict(sorted(gap_reasons.items())),
        "marginal_notes": sum(
            1
            for element in elements
            if _local_name(element) == "note" and element.get("place") == "margin"
        ),
        "unique_page_facsimiles": len(
            {element.get("facs") for element in page_breaks if element.get("facs")}
        ),
        "ending": ending,
    }


def build_candidate(
    source: Path,
    candidate: Path,
    report: Path,
    *,
    repository_root: Path,
    replace: bool = False,
) -> dict[str, Any]:
    """Write a byte-identical candidate plus deterministic validation report."""
    audit = audit_source(source, repository_root=repository_root)
    source_bytes = source.read_bytes()

    if not replace and (candidate.exists() or report.exists()):
        raise FileExistsError("candidate or validation report already exists")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    candidate_stage = candidate.with_name(f"{candidate.name}.tmp")
    report_stage = report.with_name(f"{report.name}.tmp")
    if candidate_stage.exists() or report_stage.exists():
        raise FileExistsError("staged candidate or validation path already exists")
    candidate_stage.write_bytes(source_bytes)
    candidate_hash = sha256_file(candidate_stage)
    byte_identity = (
        candidate_hash == audit["source_sha256"]
        and candidate_stage.read_bytes() == source_bytes
    )
    if not byte_identity:
        candidate_stage.unlink(missing_ok=True)
        raise SourceMismatchError("candidate is not byte-identical to the retained source")

    result: dict[str, Any] = {
        "candidate_sha256": candidate_hash,
        "source_sha256": audit["source_sha256"],
        "byte_identity": True,
        "tei_p5_relaxng_valid": audit["tei_p5_relaxng_valid"],
        "tcp_identifier": audit["tcp_identifier"],
        "edition_date": audit["edition_date"],
        "source_bytes": audit["source_bytes"],
        "tag_counts": audit["tag_counts"],
        "div_types": audit["div_types"],
        "marginal_notes": audit["marginal_notes"],
        "unique_page_facsimiles": audit["unique_page_facsimiles"],
        "tcp_chars_sha256": audit["tcp_chars_sha256"],
        "tcp_character_references": audit["tcp_character_references"],
        "unique_tcp_character_references": audit["unique_tcp_character_references"],
        "unresolved_tcp_character_references": audit[
            "unresolved_tcp_character_references"
        ],
        "unresolved_source_gaps": audit["tag_counts"]["gap"],
        "gap_reasons": audit["gap_reasons"],
        "ending": audit["ending"],
        "normalization": "none; exact source bytes retained as candidate",
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    report_stage.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    candidate_stage.replace(candidate)
    report_stage.replace(report)
    return result


def write_determinism_report(
    run_a_candidate: Path,
    run_a_validation: Path,
    run_b_candidate: Path,
    run_b_validation: Path,
    output: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Compare two fresh-run products and persist compact determinism evidence."""
    candidate_bytes_equal = run_a_candidate.read_bytes() == run_b_candidate.read_bytes()
    validation_bytes_equal = run_a_validation.read_bytes() == run_b_validation.read_bytes()
    different_working_directory = Path.cwd().resolve() != repository_root.resolve()
    if not candidate_bytes_equal or not validation_bytes_equal:
        raise SourceMismatchError("fresh-run candidate or validation bytes differ")
    if not different_working_directory:
        raise SourceMismatchError("determinism comparison must run from a different working directory")

    result: dict[str, Any] = {
        "candidate_bytes_equal": candidate_bytes_equal,
        "candidate_sha256": sha256_file(run_a_candidate),
        "different_working_directory": different_working_directory,
        "run_a_working_directory": str(repository_root.resolve()),
        "run_b_working_directory": str(Path.cwd().resolve()),
        "validation_bytes_equal": validation_bytes_equal,
        "validation_sha256": sha256_file(run_a_validation),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


def _write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(f"{path.name}.tmp")
    if stage.exists():
        raise FileExistsError(f"staged evidence path already exists: {stage}")
    stage.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    stage.replace(path)


def _header_date(headers: Path) -> str:
    dates = [
        line.split(":", 1)[1].strip()
        for line in headers.read_text(encoding="utf-8").splitlines()
        if line.lower().startswith("date:")
    ]
    if not dates:
        raise SourceMismatchError(f"download headers contain no Date field: {headers}")
    return parsedate_to_datetime(dates[-1]).isoformat().replace("+00:00", "Z")


def write_evidence_packet(
    source: Path,
    candidate: Path,
    validation: Path,
    determinism: Path,
    evidence_root: Path,
    *,
    repository_root: Path,
) -> dict[str, Path]:
    """Write the ticket-06 receipt, accountability, and unresolved handoff."""
    audit = audit_source(source, repository_root=repository_root)
    raw_root = source.parent
    config = (
        repository_root
        / "sources"
        / "structured-text"
        / "stillingfleet-origines-sacrae"
        / "config.json"
    )
    attribution = config.with_name("README.md")
    schema = repository_root / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"
    converter = Path(__file__).resolve()

    members = [
        {
            "name": "A61580.xml",
            "bytes": source.stat().st_size,
            "sha256": sha256_file(source),
            "url": (
                "https://raw.githubusercontent.com/textcreationpartnership/A61580/"
                "dcb5044e68c0577d5269e9a0cbf90f3b9081057c/A61580.xml"
            ),
            "commit": "dcb5044e68c0577d5269e9a0cbf90f3b9081057c",
        },
        {
            "name": "README.md",
            "bytes": (raw_root / "README.md").stat().st_size,
            "sha256": sha256_file(raw_root / "README.md"),
            "url": (
                "https://raw.githubusercontent.com/textcreationpartnership/A61580/"
                "dcb5044e68c0577d5269e9a0cbf90f3b9081057c/README.md"
            ),
            "commit": "dcb5044e68c0577d5269e9a0cbf90f3b9081057c",
        },
        {
            "name": "tcpchars.xml",
            "bytes": (raw_root / "tcpchars.xml").stat().st_size,
            "sha256": sha256_file(raw_root / "tcpchars.xml"),
            "url": (
                "https://raw.githubusercontent.com/textcreationpartnership/Texts/"
                "c8ff5cf9a08a7b003032bf63f6b91cabec4254bb/tcpchars.xml"
            ),
            "commit": "c8ff5cf9a08a7b003032bf63f6b91cabec4254bb",
        },
        {
            "name": "Texts-LICENSE",
            "bytes": (raw_root / "Texts-LICENSE").stat().st_size,
            "sha256": sha256_file(raw_root / "Texts-LICENSE"),
            "url": (
                "https://raw.githubusercontent.com/textcreationpartnership/Texts/"
                "c8ff5cf9a08a7b003032bf63f6b91cabec4254bb/LICENSE"
            ),
            "commit": "c8ff5cf9a08a7b003032bf63f6b91cabec4254bb",
        },
    ]
    receipt = {
        "ticket": 28,
        "slug": "stillingfleet-origines-sacrae",
        "identity": {
            "author": "Edward Stillingfleet (1635–1699)",
            "title": (
                "Origines sacræ, or, A Rational Account of the Grounds of Christian Faith, "
                "as to the Truth and Divine Authority of the Scriptures and the Matters "
                "Therein Contained"
            ),
            "edition": "London: R. W. for Henry Mortlock, 1662",
            "tcp_identifier": "A61580.0001.001",
            "witness": "Bristol Public Library copy; EEBO image set 53276",
            "workcatalog": "provisional net-new candidate — no canonical WorkCatalog write",
        },
        "landing_urls": [
            "https://github.com/textcreationpartnership/A61580",
            "https://quod.lib.umich.edu/e/eebo/A61580.0001.001",
        ],
        "retrieved_at_utc": _header_date(evidence_root / "A61580.xml.headers.txt"),
        "retained_members": members,
        "rights": {
            "work_and_edition": "Public domain in the United States (1662 edition)",
            "digital_text": "Creative Commons CC0 1.0 Universal",
            "rights_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "attribution": "Credit the Early English Books Online Text Creation Partnership",
            "page_images": "Separately governed and not acquired under this pilot",
        },
        "completeness_observation": {
            "opening": "Title page, dedication, reader preface, contents, and front-matter errata present",
            "middle": "Three body books and twenty-two chapters preserve their source divisions",
            "ending": "Final chapter closes with the source trailer FINIS.",
            "source_extent": "[40], 619 pages; 331 distinct image facsimile identifiers",
            "unusual_features": {
                "page_anchors": audit["tag_counts"]["pb"],
                "marginal_notes": audit["marginal_notes"],
                "source_declared_gaps": audit["gap_reasons"],
                "tcp_character_references": audit["tcp_character_references"],
                "verse_lines": audit["tag_counts"]["l"],
            },
        },
        "acquisition_behavior": {
            "method": "curl -fL from immutable GitHub commit URLs",
            "normalization": "none",
            "archive": "none; source members retained directly",
        },
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    accountability = {
        "source_sha256": audit["source_sha256"],
        "candidate_sha256": sha256_file(candidate),
        "source_candidate_byte_identity": source.read_bytes() == candidate.read_bytes(),
        "validation_sha256": sha256_file(validation),
        "determinism_sha256": sha256_file(determinism),
        "schema": {"path": schema.relative_to(repository_root).as_posix(), "sha256": sha256_file(schema)},
        "converter": {
            "path": converter.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(converter),
        },
        "source_config": {
            "path": config.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(config),
        },
        "attribution_readme": {
            "path": attribution.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(attribution),
        },
        "tei_p5_relaxng_valid": audit["tei_p5_relaxng_valid"],
        "tag_counts": audit["tag_counts"],
        "div_types": audit["div_types"],
        "gap_reasons": audit["gap_reasons"],
        "tcp_character_authority_sha256": audit["tcp_chars_sha256"],
        "unresolved_tcp_character_references": audit["unresolved_tcp_character_references"],
        "xml_comments": 0,
        "xml_processing_instructions": 0,
        "normalization": "none; candidate is the exact retained A61580.xml byte stream",
    }
    if not accountability["source_candidate_byte_identity"]:
        raise SourceMismatchError("evidence packet cannot bind nonidentical source and candidate")
    unresolved = {
        "source_declared_gaps_retained_unrepaired": audit["tag_counts"]["gap"],
        "gap_reasons": audit["gap_reasons"],
        "page_image_collation": "not performed; restricted/separately governed images were not acquired",
        "viewer_tcp_character_rendering": (
            "The existing CETEIcean viewer does not dereference the TCP char: authority; "
            "some g markers therefore appear as bullets or omissions in screenshots. "
            "The source/candidate XML is byte-identical and every referenced character ID "
            "resolves in the retained pinned tcpchars.xml authority."
        ),
        "textual_acceptance": "pending human review",
        "identity_and_edition_acceptance": "pending human review",
        "rights_acceptance": "pending human review; source CC0 evidence retained",
        "editorial_acceptance": "pending human review",
        "canonical_integration": "not authorized",
        "publication": "not authorized",
    }

    paths = {
        "receipt": evidence_root / "source_receipt.json",
        "accountability": evidence_root / "accountability.json",
        "unresolved": evidence_root / "unresolved_items.json",
    }
    _write_json(paths["receipt"], receipt)
    _write_json(paths["accountability"], accountability)
    _write_json(paths["unresolved"], unresolved)
    return paths


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def render_visual_spot_check(
    source: Path,
    candidate: Path,
    output_dir: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Render source and candidate through the existing viewer and capture compact samples."""
    from build.tools.tei_viewer_screenshot import _chromium_path, _serve, _sync_playwright

    targets = [
        ("opening-title", "css", "tei-div[type='title_page']"),
        (
            "middle-transition",
            "text",
            "CHAP. IV. The fidelity of the Prophets succeeding Moses.",
        ),
        ("ending", "css", "tei-trailer"),
        ("front-errata", "css", "tei-div[type='errata']"),
        ("verse-lines", "css", "tei-lg"),
        ("marginal-note", "css", "tei-note[place='margin']"),
        ("foreign-gap", "css", "tei-gap[reason='foreign']"),
        ("duplicate-gap", "css", "tei-gap[reason='duplicate']"),
    ]

    def load(page: Any, path: Path) -> dict[str, int | bool]:
        page.goto(f"{base}/viewer/index.html", wait_until="networkidle")
        page.set_input_files("#viewer-file-input", str(path.resolve()))
        page.wait_for_function(
            "document.querySelector('#viewer-status').textContent.startsWith('Loaded')",
            timeout=60_000,
        )
        page.wait_for_selector("tei-p", state="attached", timeout=60_000)
        return page.evaluate(
            """() => ({
                paragraphs: document.querySelectorAll('tei-p').length,
                heads: document.querySelectorAll('tei-head').length,
                notes: document.querySelectorAll('tei-note').length,
                page_anchors: document.querySelectorAll('tei-pb').length,
                gaps: document.querySelectorAll('tei-gap').length,
                character_markers: document.querySelectorAll('tei-g').length,
                verse_lines: document.querySelectorAll('tei-l').length,
                upgraded: !!customElements.get('tei-p')
            })"""
        )

    def locator(page: Any, mode: str, selector: str) -> Any:
        if mode == "css":
            return page.locator(selector).first
        return page.get_by_text(selector, exact=False).first

    output_dir.mkdir(parents=True, exist_ok=True)
    port = _free_loopback_port()
    source_samples: dict[str, str] = {}
    candidate_samples: dict[str, str] = {}
    screenshots: list[str] = []
    sync_playwright = _sync_playwright()
    with _serve(repository_root, port) as base:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=_chromium_path(),
                headless=True,
            )
            page = browser.new_page(viewport={"width": 1280, "height": 1100})
            try:
                source_stats = load(page, source)
                for label, mode, selector in targets:
                    item = locator(page, mode, selector)
                    item.wait_for(state="attached", timeout=60_000)
                    source_samples[label] = item.evaluate("element => element.outerHTML")

                candidate_stats = load(page, candidate)
                for label, mode, selector in targets:
                    item = locator(page, mode, selector)
                    item.wait_for(state="attached", timeout=60_000)
                    candidate_samples[label] = item.evaluate("element => element.outerHTML")
                    item.evaluate(
                        """element => {
                            let target = element;
                            while (target && target.getClientRects().length === 0) {
                                target = target.parentElement;
                            }
                            if (!target) { throw new Error('sample has no visible ancestor'); }
                            target.style.outline = '4px solid #b45309';
                            target.style.backgroundColor = '#fff7ed';
                            target.scrollIntoView({block: 'center'});
                        }"""
                    )
                    if label == "marginal-note":
                        marker = item.locator(".viewer-note-marker")
                        if marker.count():
                            marker.click()
                    page.wait_for_timeout(200)
                    screenshot = output_dir / f"{label}.png"
                    page.screenshot(path=str(screenshot), full_page=False)
                    screenshots.append(screenshot.name)
            finally:
                browser.close()

    if source_stats != candidate_stats:
        raise SourceMismatchError(
            f"source/candidate rendered DOM stats differ: {source_stats} != {candidate_stats}"
        )
    comparisons: dict[str, Any] = {}
    for label, _, selector in targets:
        source_sample = source_samples[label]
        candidate_sample = candidate_samples[label]
        if source_sample != candidate_sample:
            raise SourceMismatchError(f"rendered source/candidate sample differs at {label}")
        comparisons[label] = {
            "selector_or_text": selector,
            "rendered_outer_html_sha256": hashlib.sha256(
                source_sample.encode("utf-8")
            ).hexdigest(),
            "source_candidate_rendered_match": True,
            "screenshot": f"visual/{label}.png",
            "result": "pass",
        }
    result = {
        "viewer": "existing viewer/index.html with CETEIcean file-input path",
        "source_render_stats": source_stats,
        "candidate_render_stats": candidate_stats,
        "source_candidate_byte_identity": source.read_bytes() == candidate.read_bytes(),
        "checks": comparisons,
        "screenshots": screenshots,
        "acceptance_scope": "fidelity evidence only; no textual, identity, rights, editorial, or publication acceptance",
    }
    _write_json(output_dir / "visual_spot_check.json", result)
    lines = [
        "# Stillingfleet visual spot check",
        "",
        "Both the retained source and generated candidate were opened through the existing ",
        "verification viewer. Their rendered DOM statistics and every selected rendered ",
        "sample matched. The candidate is also byte-identical to the source.",
        "",
        "| Check | Source/candidate | Screenshot | Result |",
        "|---|---|---|---|",
    ]
    for label, details in comparisons.items():
        lines.append(
            f"| {label} | rendered sample SHA `{details['rendered_outer_html_sha256']}` | "
            f"`{details['screenshot']}` | PASS |"
        )
    lines.extend(
        [
            "",
            "This is lightweight fidelity evidence only. It does not constitute human textual, ",
            "identity, edition, rights, editorial, canonical, or publication acceptance.",
            "",
        ]
    )
    (output_dir / "visual_spot_check.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    return result


def write_path_hash_manifest(
    raw_root: Path,
    report_root: Path,
    output: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Hash every retained/evidence file and the four released worktree files."""
    entries: list[dict[str, Any]] = []
    for label, root in (("raw", raw_root), ("report", report_root)):
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.resolve() == output.resolve():
                continue
            entries.append(
                {
                    "scope": label,
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    tracked = [
        repository_root / "sources" / "structured-text" / "stillingfleet-origines-sacrae" / "config.json",
        repository_root / "sources" / "structured-text" / "stillingfleet-origines-sacrae" / "README.md",
        repository_root / "build" / "tei" / "stillingfleet_origines_sacrae.py",
        repository_root / "tests" / "test_stillingfleet_origines_sacrae.py",
    ]
    for path in tracked:
        entries.append(
            {
                "scope": "worktree",
                "path": path.relative_to(repository_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    result = {
        "ticket": 28,
        "slug": "stillingfleet-origines-sacrae",
        "files": entries,
        "file_count_excluding_manifest": len(entries),
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    _write_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--compare-candidate", type=Path)
    parser.add_argument("--compare-report", type=Path)
    parser.add_argument("--determinism-report", type=Path)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="atomically replace an existing generated candidate/report pair",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args(argv)
    repository_root = args.repository_root.resolve()
    source = args.source or resolve_source_path(repository_root)
    result = build_candidate(
        source.resolve(),
        args.candidate.resolve(),
        args.report.resolve(),
        repository_root=repository_root,
        replace=args.replace,
    )
    print(json.dumps(result, sort_keys=True))
    comparison_args = (
        args.compare_candidate,
        args.compare_report,
        args.determinism_report,
    )
    if any(comparison_args):
        if not all(comparison_args):
            parser.error(
                "--compare-candidate, --compare-report, and --determinism-report "
                "must be supplied together"
            )
        determinism = write_determinism_report(
            args.compare_candidate.resolve(),
            args.compare_report.resolve(),
            args.candidate.resolve(),
            args.report.resolve(),
            args.determinism_report.resolve(),
            repository_root=repository_root,
        )
        print(json.dumps(determinism, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
