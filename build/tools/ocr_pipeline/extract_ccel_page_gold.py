"""Extract page-keyed CCEL reference text as gold *proposals* (not gold records).

The Schaff-Herzog diagnostics scorer needs gold keyed to scanned pages. CCEL's
ThML source carries ``<pb n="N">`` page-break milestones, so the human-proofread
encyclopedia prose can be segmented per printed page and lined up with the IA
page scans. This tool produces that page-keyed reference text plus the scan it
maps to.

Why this is a *proposal*, not a ``gold-record-v1``:
  * ``gold-record-v1`` forbids a middle state -- ``verification:"verified"``
    requires non-empty ``ground_truth_text`` (i.e. authored gold), and
    ``verification:"unverifiable"`` requires ``ground_truth_text:null``. There is
    no "machine-proposed, awaiting human confirmation" slot.
  * The tuning embargo forbids authoring gold ``ground_truth_text`` by machine --
    gold is human-verified truth ("blank over unverifiable guess").
  * ``first_diagnostics`` joins gold to WCT positions by ``observation_token_id``
    at the TOKEN level. CCEL gives page-level text; turning that into token gold
    needs a separate CCEL-word-to-WCT-position alignment step that depends on the
    WCT existing. THAT aligner is the remaining tool; this one feeds it.

So the output here is reference material a reviewer (or a downstream aligner)
confirms against the scans -- it never asserts gold itself.

Provenance flag: CCEL's ThML header for vol 1 names the 1951 Baker Book House
reprint, not the 1908-1914 Funk & Wagnalls printing the pipeline scans. The
reprints are photo-offset of the original plates (text + pagination verified
word-for-word at pages 1 and 100 against the scans), but the edition difference
is recorded in the artifact so a reviewer treats it as untrusted until confirmed.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[3]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.nsh_leaf_model import body_pages  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.edition_page_key import body_edition_key  # noqa: E402

# CCEL ThML source per volume (gitignored cache). vols 1/2/9 are keyed ThML.
DEFAULT_XML = REPO_ROOT / "raw" / "ccel" / "schaff" / "encyc{volume:02d}.xml"
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "raw"
    / "internet-archive"
    / "schaff-herzog-pages"
    / "vol_{volume:02d}.manifest.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "reports" / "gold" / "vol_{volume:02d}" / "ccel_page_gold_proposal.json"

ARTIFACT_KIND = "ccel-page-gold-proposal"
# Loud, deliberately not a schema_version: this is NOT a gold-record-v1.
PROPOSAL_STATUS = "PROPOSAL_NOT_GOLD"


def _strip_tag(tag: str) -> str:
    """Drop any XML namespace prefix (``{ns}pb`` -> ``pb``)."""
    return tag.rsplit("}", 1)[-1]


def _walk_text_and_breaks(elem: ET.Element) -> Iterator[tuple[str, str]]:
    """Yield ('pb', n) and ('text', s) events in document order.

    ``<pb>`` is an empty milestone embedded in flowing text; page content is the
    text that follows a ``<pb n="N">`` up to the next ``<pb>``. Tail text (text
    after a child element, within the parent) is emitted in the parent's loop so
    a ``<pb>``'s tail correctly lands on the new page.
    """
    tag = _strip_tag(elem.tag)
    if tag == "pb":
        yield ("pb", elem.get("n") or "")
    if elem.text:
        yield ("text", elem.text)
    for child in elem:
        yield from _walk_text_and_breaks(child)
        if child.tail:
            yield ("text", child.tail)


def _normalize_ws(text: str) -> str:
    """Collapse runs of whitespace to single spaces and trim."""
    return " ".join(text.split())


def extract_page_texts(xml_path: Path) -> dict[int, str]:
    """Map arabic printed page number -> that page's CCEL text.

    Only digit ``n`` values are kept (roman front-matter pages i, ii, ... are
    skipped -- they are not body pages the scorer targets). Page N's text is what
    appears between ``<pb n="N">`` and the next ``<pb>``.
    """
    root = ET.parse(xml_path).getroot()
    pages: dict[int, list[str]] = {}
    current: int | None = None
    for kind, value in _walk_text_and_breaks(root):
        if kind == "pb":
            current = int(value) if value.isdigit() else None
            if current is not None:
                pages.setdefault(current, [])
        elif current is not None and value.strip():
            pages[current].append(value)
    return {n: _normalize_ws("".join(parts)) for n, parts in pages.items() if "".join(parts).strip()}


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _vol_from_manifest(manifest_path: Path) -> str:
    # vol_NN.manifest.json -> NN
    return manifest_path.name.split(".")[0].replace("vol_", "")


def scan_map(manifest_path: Path) -> dict[int, dict[str, Any]]:
    """Map printed page_num -> {page_native_id, scan_path} for scans that exist on disk.

    The manifest's ``local_path`` is canonical (front matter is ``leaf_NNNN.jpg``,
    body is ``page_NNNN.jpg``). ``page_native_id`` is the scan file stem, matching
    how the S1 runner names its sidecars -- so a later step can join CCEL text to
    the OCR sidecar / WCT for the same page. ``local_path`` is tried repo-relative
    first (real manifests) then manifest-relative (hermetic test manifests).
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out: dict[int, dict[str, str]] = {}
    for entry in body_pages(manifest):
        if "page_num" not in entry:
            continue
        page_num = int(entry["page_num"])
        leaf_num = entry.get("leaf_num")
        candidates: list[Path] = []
        local = entry.get("local_path")
        if local:
            candidates.append(REPO_ROOT / local)
            candidates.append(manifest_path.parent / local)
        leaf = entry.get("ia_leaf_id")
        if leaf:
            candidates.append(
                manifest_path.parent / f"vol_{_vol_from_manifest(manifest_path)}" / f"leaf_{leaf}.jpg"
            )
        chosen = next((c for c in candidates if c.exists()), None)
        if chosen is None:
            continue
        out[page_num] = {
            "page_native_id": chosen.stem,
            "scan_path": _relative(chosen),
            # R4b: the engine-agnostic leaf coordinate -- the cross-stage page join
            # key the WCT<->CCEL aligner uses (filename stem stays display only).
            "canonical_leaf_id": int(leaf_num) if isinstance(leaf_num, int) else None,
        }
    return out


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_proposal(
    *,
    volume: int,
    xml_path: Path,
    manifest_path: Path,
    pages: list[int] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the page-gold proposal artifact for one volume (optionally a page subset)."""
    page_texts = extract_page_texts(xml_path)
    scans = scan_map(manifest_path)

    wanted = sorted(set(pages)) if pages is not None else sorted(page_texts)
    records: list[dict[str, Any]] = []
    missing_text: list[int] = []
    missing_scan: list[int] = []
    for n in wanted:
        text = page_texts.get(n)
        scan = scans.get(n)
        if text is None:
            missing_text.append(n)
            continue
        if scan is None:
            missing_scan.append(n)
            continue
        records.append(
            {
                "page_sequence": n,
                "page_native_id": scan["page_native_id"],
                "canonical_leaf_id": scan.get("canonical_leaf_id"),
                "edition_page_key": body_edition_key(n),
                "scan_path": scan["scan_path"],
                "ccel_pb_n": str(n),
                "ccel_page_text": text,
                "char_count": len(text),
                "word_count": len(text.split()),
            }
        )

    return {
        "artifact_kind": ARTIFACT_KIND,
        "status": PROPOSAL_STATUS,
        "volume": volume,
        "source": {
            "source_basis": f"ccel:thml:schaff/encyc{volume:02d}.xml#pb",
            "ccel_print_edition": "Grand Rapids, MI: Baker Book House, 1951 (per ThML <printSourceInfo>)",
            "pipeline_scan_edition": "1908-1914 (Funk & Wagnalls); edition mismatch -- confirm against scan",
            "generated_at": generated_at or _utc_now(),
        },
        "caveats": [
            "NOT a gold-record-v1: machine-proposed reference text, not human-verified gold.",
            "CCEL omits running headers and printed page numbers that appear on the scans.",
            "first_diagnostics needs TOKEN-level gold (observation_token_id); a CCEL-word-to-WCT "
            "alignment step is still required to mint token gold from this page text.",
        ],
        "coverage": {
            "pages_proposed": len(records),
            "pages_requested": len(wanted),
            "missing_ccel_text": missing_text,
            "missing_scan": missing_scan,
        },
        "pages": records,
    }


def _parse_pages(values: list[str]) -> list[int] | None:
    if not values:
        return None
    out: set[int] = set()
    for token in values:
        if "-" in token:
            lo, hi = token.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(token))
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--volume", type=int, default=1)
    parser.add_argument("--xml", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--pages", nargs="+", default=[], metavar="N_OR_RANGE")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--write", action="store_true", help="Write the artifact. Default is dry-run summary.")
    args = parser.parse_args(list(argv or []))

    xml_path = args.xml or Path(str(DEFAULT_XML).format(volume=args.volume))
    manifest_path = args.manifest or Path(str(DEFAULT_MANIFEST).format(volume=args.volume))
    if not xml_path.exists():
        print(f"ERROR: CCEL XML not found: {xml_path}", file=sys.stderr)
        return 2
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    proposal = build_proposal(
        volume=args.volume,
        xml_path=xml_path,
        manifest_path=manifest_path,
        pages=_parse_pages(args.pages),
    )
    cov = proposal["coverage"]
    # Single-line summary (PY-05: ASCII only on the console path).
    print(
        f"{ARTIFACT_KIND} vol={args.volume} proposed={cov['pages_proposed']}/{cov['pages_requested']} "
        f"missing_text={len(cov['missing_ccel_text'])} missing_scan={len(cov['missing_scan'])}"
    )
    if not args.write:
        return 0

    output = args.output or Path(str(DEFAULT_OUTPUT).format(volume=args.volume))
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(output)
    print(f"wrote {_relative(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
