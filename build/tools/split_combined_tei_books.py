"""Extract source-bound, nonaccepted TEI review selections from batch candidates.

The batch candidate remains the reconstruction authority. This utility preserves each
selected TEI subtree byte-for-byte at XML tree level, checks the retained source
identity, and lists the other extracted selections. Source-wide boundaries and
shared apparatus remain unresolved. Its outputs are review artifacts,
not sealed candidate packages or accepted masters.
"""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from lxml import etree


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"tei": TEI}
SAFE_REVIEW_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")


def _safe_review_id(value: object) -> str:
    if not isinstance(value, str) or not SAFE_REVIEW_ID.fullmatch(value):
        raise ValueError(f"unsafe review/work ID: {value!r}")
    return value


def _output_targets(output: Path, books: list[tuple[str, etree._Element, dict[str, object]]]) -> list[Path]:
    root = output.resolve()
    targets = []
    for raw_id, _, _ in books:
        work_id = _safe_review_id(raw_id)
        target = (output / work_id / "content.tei.xml").resolve()
        if target.parent.parent != root or not target.is_relative_to(root):
            raise ValueError(f"review output escapes selected root: {work_id}")
        targets.append(target)
    return targets
NPNF103 = (
    ("iv.i", "augustine-on-the-trinity"),
    ("iv.ii", "augustine-enchiridion"),
    ("iv.iii", "augustine-catechising-uninstructed"),
    ("iv.iv", "augustine-faith-and-creed"),
    ("iv.v", "augustine-faith-things-not-seen"),
    ("iv.vi", "augustine-profit-of-believing"),
    ("iv.vii", "augustine-on-the-creed"),
    ("v.i", "augustine-on-continence"),
    ("v.ii", "augustine-good-of-marriage"),
    ("v.iii", "augustine-holy-virginity"),
    ("v.iv", "augustine-good-of-widowhood"),
    ("v.v", "augustine-on-lying"),
    ("v.vi", "augustine-against-lying"),
    ("v.vii", "augustine-work-of-monks"),
    ("v.viii", "augustine-on-patience"),
    ("v.ix", "augustine-care-for-dead"),
)
OWEN = (
    "john-owen-apostasy", "john-owen-church-love", "john-owen-communion",
    "john-owen-conscience", "john-owen-death-of-death",
    "john-owen-display-arminianism", "john-owen-divine-justice",
    "john-owen-eshcol", "john-owen-evangelical-churches",
    "john-owen-faith-elect",
)
MANIFESTS = {
    "maclaren-volumes": "sources/sermons/maclaren-expositions/maclaren-expositions.source-manifest.json",
    "lib033": "sources/commentaries/expositors-bible/lib033.source-manifest.json",
    "lib034": "sources/commentaries/expositors-bible/lib034.source-manifest.json",
    "npnf204": "sources/structured-text/athanasius-on-the-incarnation/athanasius-table.source-manifest.json",
    "lib040": "sources/structured-text/augustine-npnf101-106-107-lib040/lib040.source-manifest.json",
    "npnf105": "sources/structured-text/augustine-npnf105/npnf105.source-manifest.json",
    "lib041": "sources/structured-text/chrysostom-npnf113-lib041/npnf113-lib041.source-manifest.json",
    "chrysostom-multi": "sources/structured-text/chrysostom-npnf110-111-112-114/npnf-chrysostom.source-manifest.json",
    "lib047": "sources/structured-text/gregory-nyssa-npnf205/gregory-nyssa-npnf205.source-manifest.json",
    "lib048": "sources/structured-text/npnf2-lib048/npnf2-lib048.source-manifest.json",
    "lib049": "sources/structured-text/npnf211-lib049/npnf211-lib049.source-manifest.json",
    "lib031": "sources/structured-text/bounds-essentials-of-prayer/lib031.source-manifest.json",
    "lib054": "sources/structured-text/lib054-ccel-puritan/lib054.source-manifest.json",
    "npnf103": "sources/structured-text/augustine-npnf103/augustine-npnf103.source-manifest.json",
    "owen-lib050": "sources/structured-text/lib050-john-owen/john-owen-lib050.source-manifest.json",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse(data: bytes) -> etree._Element:
    return etree.fromstring(
        data,
        etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True,
                        remove_comments=False, remove_pis=False, huge_tree=True),
    )


def _one(nodes: list[etree._Element], label: str) -> etree._Element:
    if len(nodes) != 1:
        raise ValueError(f"expected exactly one {label}; found {len(nodes)}")
    return nodes[0]


def _serialize(node: etree._Element) -> bytes:
    return etree.tostring(node, encoding="UTF-8", xml_declaration=True,
                          pretty_print=False)


def _source_path(root: Path, library: Path, authority: dict[str, object]) -> Path:
    relative = Path(str(authority["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe authority path: {relative}")
    base = library if relative.parts[0] == "raw" else root
    target = (base / relative).resolve(strict=True)
    if not target.is_relative_to(base.resolve(strict=True)):
        raise ValueError(f"authority escapes base: {relative}")
    return target


def _authorities(root: Path, library: Path, manifest: dict[str, object]) -> tuple[dict[str, tuple[dict[str, object], bytes]], list[str]]:
    result = {}
    ancillary_drift = []
    for row in manifest["authorities"]:
        path = _source_path(root, library, row)
        data = path.read_bytes()
        if len(data) != row["bytes"] or _sha(data) != row["sha256"]:
            if row["role"] == "primary-source":
                raise ValueError(f"primary source authority drifted: {row['name']}")
            ancillary_drift.append(str(row["name"]))
            continue
        result[str(row["name"])] = (row, data)
    return result, ancillary_drift


def _npnf_books(batch: etree._Element, source: bytes) -> list[tuple[str, etree._Element, dict[str, object]]]:
    if batch.tag != f"{{{TEI}}}TEI":
        raise ValueError("NPNF103 candidate is not one TEI")
    body = _one(batch.xpath("./tei:text/tei:body", namespaces=NS), "candidate body")
    divisions = list(body)
    expected_ids = [f"npnf103-{scope}" for scope, _ in NPNF103]
    if [node.get(XML_ID) for node in divisions] != expected_ids:
        raise ValueError("NPNF103 candidate book order/IDs drifted")
    source_root = _parse(source)
    source_body = _one(source_root.xpath("./ThML.body"), "retained ThML body")
    top = [node for node in source_body if isinstance(node.tag, str) and node.tag == "div1"]
    if [node.get("id") for node in top] != ["i", "ii", "iii", "iv", "v", "vi", "vii"]:
        raise ValueError("retained NPNF103 volume structure drifted")
    direct = [node for wrapper in top for node in wrapper
              if isinstance(node.tag, str) and node.tag == "div2"]
    expected_source = [scope for scope, _ in NPNF103] + ["vi.i", "vi.ii", "vii.i", "vii.ii", "vii.iii"]
    if [node.get("id") for node in direct] != expected_source:
        raise ValueError("retained NPNF103 source book order drifted")
    header = _one(batch.xpath("./tei:teiHeader", namespaces=NS), "candidate header")
    books = []
    for (scope, work_id), division, source_div in zip(NPNF103, divisions, direct, strict=False):
        title = "".join(division.xpath("./tei:head[1]", namespaces=NS)[0].itertext()).strip()
        if not title:
            raise ValueError(f"untitled book: {work_id}")
        root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
        root.set(XML_ID, work_id)
        own_header = deepcopy(header)
        title_node = _one(own_header.xpath("./tei:fileDesc/tei:titleStmt/tei:title[1]", namespaces=NS), "title")
        title_node.text = title
        root.append(own_header)
        text = etree.SubElement(root, f"{{{TEI}}}text")
        own_body = etree.SubElement(text, f"{{{TEI}}}body")
        own_body.append(deepcopy(division))
        books.append((work_id, root, {
            "source_div2_id": scope,
            "source_div2_sha256": _sha(etree.tostring(source_div, encoding="UTF-8")),
            "batch_division_sha256": _sha(etree.tostring(division, encoding="UTF-8")),
            "title": title,
        }))
    return books


def _owen_books(batch: etree._Element, authority: dict[str, tuple[dict[str, object], bytes]],
                profile: dict[str, object]) -> list[tuple[str, etree._Element, dict[str, object]]]:
    if batch.tag != f"{{{TEI}}}teiCorpus":
        raise ValueError("Owen candidate is not a TEI corpus")
    children = batch.xpath("./tei:TEI", namespaces=NS)
    if [node.get(XML_ID) for node in children] != list(OWEN):
        raise ValueError("Owen candidate work order/IDs drifted")
    bindings = profile["works"]
    if [work["work_id"] for work in bindings] != list(OWEN):
        raise ValueError("Owen source profile work order/IDs drifted")
    books = []
    for child, work in zip(children, bindings, strict=True):
        work_id = _safe_review_id(work["work_id"])
        row, source = authority[str(work["authority_name"])]
        if row["sha256"] != work["sha256"] or row["bytes"] != work["bytes"]:
            raise ValueError(f"Owen profile source mismatch: {work_id}")
        encoded = _one(child.xpath(".//tei:ab[@type='exact-retained-source-bytes']", namespaces=NS),
                       f"embedded source: {work_id}")
        if encoded.get("n") != row["sha256"] or base64.b64decode(encoded.text or "", validate=True) != source:
            raise ValueError(f"Owen TEI does not embed exact source: {work_id}")
        books.append((work_id, deepcopy(child), {
            "source_path": row["path"], "source_bytes": row["bytes"],
            "source_sha256": row["sha256"],
            "batch_child_sha256": _sha(etree.tostring(child, encoding="UTF-8")),
            "title": "".join(child.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title[1]", namespaces=NS)[0].itertext()).strip(),
        }))
    return books



PLAIN_PROFILES = {
    "npnf204": (20, "div1_id"), "lib040": (8, "source_root_id"),
    "npnf105": (12, "div1_id"), "lib041": (10, "root_id"),
    "chrysostom-multi": (7, "div1_id"), "lib047": (2, "source_root_id"),
    "lib048": (15, "source_root_id"), "lib049": (3, "source_root_id"),
    "lib031": (10, None),
}



def _bound_manifest(root: Path, manifest_relative: str, expected_sha256: str) -> tuple[bytes, str | None]:
    current = (root / manifest_relative).read_bytes()
    if _sha(current) == expected_sha256:
        return current, None
    revisions = subprocess.run(
        ["git", "log", "--format=%H", "--", manifest_relative],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    for revision in revisions:
        historic = subprocess.run(
            ["git", "show", f"{revision}:{manifest_relative}"],
            cwd=root, capture_output=True, check=True,
        ).stdout
        if _sha(historic) == expected_sha256:
            return historic, revision
    raise ValueError(f"sealed historical source manifest cannot be recovered: {manifest_relative}")

def _sealed_provenance(candidate: Path, manifest_bytes: bytes, content: bytes, *, allow_unrecovered: bool = False) -> dict[str, object]:
    package_dir = candidate.parent
    seal = json.loads((package_dir / "manifest.json").read_bytes())
    if seal.get("contract") != "ocd-candidate-package-v1" or seal.get("status") != "nonaccepted":
        raise ValueError("batch package is not sealed nonaccepted candidate")
    if seal["source_manifest"]["sha256"] != _sha(manifest_bytes) and not allow_unrecovered:
        raise ValueError("batch package source manifest binding drifted")
    members = {row["name"]: row for row in seal["members"]}
    for name, data in (("content.tei.xml", content),
                       ("provenance.json", (package_dir / "provenance.json").read_bytes())):
        if members[name]["bytes"] != len(data) or members[name]["sha256"] != _sha(data):
            raise ValueError(f"batch package member drifted: {name}")
    return json.loads((package_dir / "provenance.json").read_bytes())


def _find_primary(work: dict[str, object], authority: dict[str, tuple[dict[str, object], bytes]]) -> tuple[dict[str, object], bytes]:
    primary = [entry for row, data in authority.values() if row["role"] == "primary-source"
               for entry in [(row, data)]]
    member = str(work.get("source_member", ""))
    digest = work.get("source_sha256")
    matches = [(row, data) for row, data in primary
               if (not member or row["path"] == member or Path(str(row["path"])).stem == member)
               and (not digest or row["sha256"] == digest)]
    if len(matches) != 1:
        raise ValueError(f"work has {len(matches)} primary source matches: {work['work_id']}")
    return matches[0]


def _plain_books(family: str, batch: etree._Element, provenance: dict[str, object],
                 authority: dict[str, tuple[dict[str, object], bytes]]) -> list[tuple[str, etree._Element, dict[str, object]]]:
    count, source_key = PLAIN_PROFILES[family]
    if batch.tag != f"{{{TEI}}}TEI":
        raise ValueError(f"{family} candidate is not one TEI")
    works = provenance.get("works")
    if not isinstance(works, list) or len(works) != count:
        raise ValueError(f"{family} provenance work count drifted")
    body = _one(batch.xpath("./tei:text/tei:body", namespaces=NS), "candidate body")
    divisions = list(body)
    if len(divisions) != count:
        raise ValueError(f"{family} candidate division count drifted")
    header = _one(batch.xpath("./tei:teiHeader", namespaces=NS), "candidate header")
    books = []
    for division, work in zip(divisions, works, strict=True):
        work_id = _safe_review_id(work["work_id"])
        candidate_id = division.get(XML_ID) or ""
        source_id = str(work.get(source_key, "")) if source_key else ""
        if not candidate_id or not (work_id in candidate_id or (source_id and candidate_id.endswith("-" + source_id))):
            raise ValueError(f"candidate division does not match work binding: {work_id}")
        row, source = _find_primary(work, authority)
        source_evidence = {"source_path": row["path"], "source_bytes": row["bytes"],
                           "source_sha256": row["sha256"]}
        if source_id:
            source_root = _parse(source)
            selected = source_root.xpath("//*[@id=$source_id]", source_id=source_id)
            if len(selected) != 1:
                raise ValueError(f"retained source root {source_id} missing or ambiguous: {work_id}")
            source_evidence["source_root_id"] = source_id
            source_evidence["source_root_sha256"] = _sha(etree.tostring(selected[0], encoding="UTF-8"))
        title_nodes = division.xpath("./tei:head[1]", namespaces=NS)
        title = "".join(title_nodes[0].itertext()).strip() if title_nodes else str(work.get("title") or work.get("catalog_title") or work.get("source_title") or "")
        if not title:
            raise ValueError(f"untitled work division: {work_id}")
        tei = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
        root_id = f"{work_id}-tei" if any(node.get(XML_ID) == work_id for node in division.iter()) else work_id
        tei.set(XML_ID, root_id)
        own_header = deepcopy(header)
        _one(own_header.xpath("./tei:fileDesc/tei:titleStmt/tei:title[1]", namespaces=NS), "title").text = title
        tei.append(own_header)
        own_text = etree.SubElement(tei, f"{{{TEI}}}text")
        own_body = etree.SubElement(own_text, f"{{{TEI}}}body")
        own_body.append(deepcopy(division))
        books.append((work_id, tei, {**source_evidence,
            "candidate_division_id": candidate_id,
            "batch_division_sha256": _sha(etree.tostring(division, encoding="UTF-8")),
            "title": title}))
    return books


def _puritan_books(batch: etree._Element, provenance: dict[str, object],
                   authority: dict[str, tuple[dict[str, object], bytes]]) -> list[tuple[str, etree._Element, dict[str, object]]]:
    if batch.tag != f"{{{TEI}}}teiCorpus":
        raise ValueError("LIB054 candidate is not a TEI corpus")
    children = batch.xpath("./tei:TEI", namespaces=NS)
    work_ids = provenance.get("work_ids")
    primary = [(row, data) for row, data in authority.values() if row["role"] == "primary-source"]
    if len(children) != 10 or [child.get(XML_ID) for child in children] != work_ids or len(primary) != 10:
        raise ValueError("LIB054 source member/work order drifted")
    books = []
    for child, work_id, (row, _) in zip(children, work_ids, primary, strict=True):
        title = "".join(_one(child.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title[1]", namespaces=NS), "title").itertext()).strip()
        books.append((work_id, deepcopy(child), {"source_path": row["path"],
            "source_bytes": row["bytes"], "source_sha256": row["sha256"],
            "batch_child_sha256": _sha(etree.tostring(child, encoding="UTF-8")),
            "title": title}))
    return books


def _expositor_books(family: str, batch: etree._Element,
                     authority: dict[str, tuple[dict[str, object], bytes]]) -> list[tuple[str, etree._Element, dict[str, object]]]:
    if batch.tag != f"{{{TEI}}}teiCorpus":
        raise ValueError(f"{family} candidate is not a TEI corpus")
    primary = [(row, data) for row, data in authority.values() if row["role"] == "primary-source"]
    expected = 12 if family == "lib033" else 10
    if len(primary) != expected:
        raise ValueError(f"{family} primary source member count drifted")
    source_by_stem = {Path(str(row["path"])).stem.replace("_", "-"): (row, data)
                      for row, data in primary}
    books = []
    for aggregate in batch.xpath("./tei:TEI", namespaces=NS):
        aggregate_id = aggregate.get(XML_ID)
        header = _one(aggregate.xpath("./tei:teiHeader", namespaces=NS), "author header")
        body = _one(aggregate.xpath("./tei:text/tei:body", namespaces=NS), "author body")
        for division in body:
            source_member_id = division.get(XML_ID)
            if division.get("type") != "retained-source-member" or source_member_id not in source_by_stem:
                raise ValueError(f"{family} unbound source-book division: {source_member_id}")
            row, _ = source_by_stem[source_member_id]
            title_node = _one(division.xpath("./tei:head[1]", namespaces=NS), "member title")
            title = "".join(title_node.itertext()).strip()
            if not title:
                raise ValueError(f"{family} untitled member: {source_member_id}")
            review_id = f"{source_member_id}-book-review"
            tei = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
            tei.set(XML_ID, review_id)
            own_header = deepcopy(header)
            _one(own_header.xpath("./tei:fileDesc/tei:titleStmt/tei:title[1]", namespaces=NS), "title").text = title
            tei.append(own_header)
            own_text = etree.SubElement(tei, f"{{{TEI}}}text")
            own_body = etree.SubElement(own_text, f"{{{TEI}}}body")
            own_body.append(deepcopy(division))
            books.append((review_id, tei, {
                "canonical_work_id": None,
                "identity_status": "source-book review; author aggregate is not a canonical book identity",
                "parent_author_aggregate_id": aggregate_id,
                "source_member_id": source_member_id,
                "source_path": row["path"], "source_bytes": row["bytes"],
                "source_sha256": row["sha256"],
                "batch_division_sha256": _sha(etree.tostring(division, encoding="UTF-8")),
                "title": title,
            }))
    if len(books) != expected or {book[2]["source_member_id"] for book in books} != set(source_by_stem):
        raise ValueError(f"{family} source-book coverage is incomplete")
    return books


def _maclaren_books(batch: etree._Element,
                    authority: dict[str, tuple[dict[str, object], bytes]]) -> list[tuple[str, etree._Element, dict[str, object]]]:
    if batch.tag != f"{{{TEI}}}TEI":
        raise ValueError("Maclaren candidate is not one TEI")
    header = _one(batch.xpath("./tei:teiHeader", namespaces=NS), "series header")
    body = _one(batch.xpath("./tei:text/tei:body", namespaces=NS), "series body")
    primary = [(row, data) for row, data in authority.values() if row["role"] == "primary-source"]
    if len(primary) != 15 or len(body) != 15:
        raise ValueError("Maclaren retained volume count drifted")
    source_by_pg = {Path(str(row["path"])).stem.removeprefix("pg"): (row, data)
                    for row, data in primary}
    books = []
    for division in body:
        pg_id = division.get("n")
        if (division.get("type") != "source-member" or division.get(XML_ID) != f"member-pg{pg_id}"
                or pg_id not in source_by_pg):
            raise ValueError(f"Maclaren unbound volume division: {pg_id}")
        row, _ = source_by_pg[pg_id]
        review_id = f"maclaren-pg{pg_id}-volume-review"
        title = f"Expositions of Holy Scripture — retained Project Gutenberg volume {pg_id}"
        tei = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
        tei.set(XML_ID, review_id)
        own_header = deepcopy(header)
        _one(own_header.xpath("./tei:fileDesc/tei:titleStmt/tei:title[1]", namespaces=NS), "title").text = title
        tei.append(own_header)
        own_text = etree.SubElement(tei, f"{{{TEI}}}text")
        own_body = etree.SubElement(own_text, f"{{{TEI}}}body")
        own_body.append(deepcopy(division))
        books.append((review_id, tei, {
            "canonical_work_id": None, "identity_status": "provisional published-volume review; series work identity remains unresolved",
            "pg_id": pg_id, "source_path": row["path"], "source_bytes": row["bytes"],
            "source_sha256": row["sha256"],
            "batch_division_sha256": _sha(etree.tostring(division, encoding="UTF-8")),
            "title": title,
        }))
    if len(books) != 15 or {book[2]["pg_id"] for book in books} != set(source_by_pg):
        raise ValueError("Maclaren volume coverage incomplete")
    return books


def _write_review_outputs(output: Path, books: list[tuple[str, etree._Element, dict[str, object]]],
                          report: dict[str, object]) -> None:
    # Validate every derived filename before creating any output directory.
    _output_targets(output, books)
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise FileExistsError(f"output must be an absent or empty directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".book-split-", dir=output.parent) as stage_name:
        stage = Path(stage_name)
        inventory = []
        for (work_id, tei, evidence), target in zip(books, _output_targets(stage, books), strict=True):
            content = _serialize(tei)
            target.parent.mkdir(parents=True, exist_ok=False)
            target.write_bytes(content)
            inventory.append({"work_id": work_id, "file": f"{work_id}/content.tei.xml",
                              "bytes": len(content), "sha256": _sha(content), **evidence,
                              "other_extracted_review_ids": [other for other, _, _ in books if other != work_id]})
        report["book_count"] = len(inventory)
        report["books"] = inventory
        (stage / "split-inventory.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
            raise FileExistsError(f"output changed during generation: {output}")
        if output.exists():
            output.rmdir()
        stage.rename(output)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("family", choices=MANIFESTS)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-unrecovered-manifest", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    manifest_path = root / MANIFESTS[args.family]
    seal = json.loads((args.candidate.parent / "manifest.json").read_bytes())
    if seal["source_manifest"]["path"] != MANIFESTS[args.family]:
        raise ValueError("candidate source manifest path differs from family profile")
    unrecovered_manifest_sha = None
    try:
        manifest_bytes, historic_revision = _bound_manifest(
            root, MANIFESTS[args.family], seal["source_manifest"]["sha256"]
        )
    except ValueError:
        if not args.allow_unrecovered_manifest:
            raise
        manifest_bytes = manifest_path.read_bytes()
        historic_revision = None
        unrecovered_manifest_sha = seal["source_manifest"]["sha256"]
    manifest = json.loads(manifest_bytes)
    authority, ancillary_drift = _authorities(root, args.library_root, manifest)
    candidate_bytes = args.candidate.read_bytes()
    candidate_sha = _sha(candidate_bytes)
    if candidate_sha != args.candidate_sha256:
        raise ValueError("batch candidate SHA-256 mismatch")
    batch = _parse(candidate_bytes)
    if manifest["source_id"] != seal["source_id"]:
        raise ValueError("current source family differs from sealed candidate")
    provenance = _sealed_provenance(
        args.candidate, manifest_bytes, candidate_bytes,
        allow_unrecovered=unrecovered_manifest_sha is not None,
    )
    if args.family == "npnf103":
        source_row, source_bytes = authority["retained-thml"]
        books = _npnf_books(batch, source_bytes)
        source_scope = {"path": source_row["path"], "bytes": source_row["bytes"],
                        "sha256": source_row["sha256"]}
    elif args.family == "owen-lib050":
        profile = json.loads(authority["reconstruction-profile"][1])
        books = _owen_books(batch, authority, profile)
        source_scope = {"members": [book[2]["source_path"] for book in books]}
    elif args.family == "maclaren-volumes":
        books = _maclaren_books(batch, authority)
        source_scope = {"members": [book[2]["source_path"] for book in books]}
    elif args.family in ("lib033", "lib034"):
        books = _expositor_books(args.family, batch, authority)
        source_scope = {"members": [book[2]["source_path"] for book in books]}
    elif args.family == "lib054":
        books = _puritan_books(batch, provenance, authority)
        source_scope = {"members": [book[2]["source_path"] for book in books]}
    else:
        books = _plain_books(args.family, batch, provenance, authority)
        source_scope = {"members": list(dict.fromkeys(book[2]["source_path"] for book in books))}
    expected_count = (16 if args.family == "npnf103" else 15 if args.family == "maclaren-volumes"
                      else 12 if args.family == "lib033"
                      else 10 if args.family in ("owen-lib050", "lib054", "lib034")
                      else PLAIN_PROFILES[args.family][0])
    if len(books) != expected_count or len({work_id for work_id, _, _ in books}) != expected_count:
        raise ValueError("incomplete or duplicate book output")
    report = {
        "contract": "ocd-book-split-review-v1", "status": "nonaccepted-unintegrated",
        "family": args.family, "batch_candidate_path": str(args.candidate),
        "batch_candidate_sha256": candidate_sha,
        "source_manifest": MANIFESTS[args.family],
        "source_manifest_sha256": _sha(manifest_bytes),
        "historical_manifest_revision": historic_revision,
        "unrecovered_sealed_manifest_sha256": unrecovered_manifest_sha,
        "current_manifest_sha256": _sha(manifest_path.read_bytes()),
        "ancillary_authority_drift": ancillary_drift,
        "source_scope": source_scope,
        "source_binding_limit": ("historical sealed manifest unavailable; primary members compared with current manifest"
                                 if unrecovered_manifest_sha else "historical sealed manifest recovered and checked"),
        "batch_seal_check_scope": "content.tei.xml and provenance.json only; other package members not checked",
        "source_wide_boundary_and_apparatus_disposition": "unresolved; other_extracted_review_ids covers only selections made by this tool",
        "limits": "Review TEIs extracted from a historical batch. Local links and source-wide apparatus are unresolved. These are not sealed candidate packages, independently revalidated reconstructions, accepted masters, rights clearance, or publication authority.",
    }
    _write_review_outputs(args.output, books, report)


if __name__ == "__main__":
    main()
