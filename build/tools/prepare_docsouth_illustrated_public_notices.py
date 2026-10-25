"""Prepare 22 source-bound illustrated DocSouth notices without publishing."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library.identities import discover_library
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.tei.acceptance import _validate_acceptance_for_views
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "plans/2026-09-22-source-preflight/docsouth-tei2-exact-source-shapes-20260927.json"
INVENTORY_SHA = "90f085ef14460c3a3d0351781c077502bf845e93dd2934a6afa344655d48341b"
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-public-notices-20260928-v1")
CONTRACT = "ocd-docsouth-illustrated-public-notice-handoff-v1"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _one(parent: etree._Element, path: str) -> etree._Element:
    result = parent.findall(path)
    if len(result) != 1:
        raise ValueError(f"DocSouth source header field must occur once: {path}")
    return result[0]


def _wording(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _header(source_bytes: bytes, expected_rights_sha: str) -> dict:
    source = etree.fromstring(source_bytes, etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    if source.tag != "TEI.2":
        raise ValueError("DocSouth retained source is not TEI.2")
    file_desc = _one(source, "teiHeader/fileDesc")
    availability = _one(file_desc, "publicationStmt/availability")
    rights_raw = "".join(availability.itertext())
    if _sha(rights_raw.encode("utf-8")) != expected_rights_sha or availability.attrib != {"status": "unknown"}:
        raise ValueError("DocSouth exact source availability/status differs")
    links = availability.findall(".//a")
    if len(links) != 1 or set(links[0].attrib) != {"href"}:
        raise ValueError("DocSouth source rights link differs")
    label, url = _wording(links[0]), links[0].get("href")
    if not label or not url.startswith("http://rightsstatements.org/vocab/"):
        raise ValueError("DocSouth source rights label/URL differs")
    publisher = _wording(_one(file_desc, "publicationStmt/publisher"))
    if publisher != "Academic Affairs Library, UNC-CH":
        raise ValueError("DocSouth electronic publisher differs")
    credits = []
    for statement in file_desc.findall("titleStmt/respStmt"):
        role, name = _wording(_one(statement, "resp")), _wording(_one(statement, "name"))
        if not role or not name:
            raise ValueError("DocSouth named electronic credit is empty")
        credits.append(f"- {role}: {name}")
    if not credits:
        raise ValueError("DocSouth named electronic credits missing")
    funders = file_desc.findall("titleStmt/funder")
    if len(funders) > 1:
        raise ValueError("DocSouth multiple funders require separate review")
    funder = _wording(funders[0]) if funders else None
    if funders and not funder:
        raise ValueError("DocSouth source funder wording empty")
    return dict(availability=_wording(availability), availability_sha256=expected_rights_sha,
                rights_label=label, rights_url=url, rights_status="unknown",
                publisher=publisher, credits=credits, funder=funder)


def _notice(work_id: str, header: dict) -> bytes:
    lines = [f"# Source and rights notice for {work_id}", "",
             "Electronic text source: Documenting the American South, University of North Carolina at Chapel Hill.",
             f"The retained electronic header names {header['publisher']} as publisher.", "",
             "The retained electronic header credits:", *header["credits"]]
    if header["funder"]:
        lines.append(f"- Funding: {header['funder']}")
    lines.extend(["", f"Source rights statement: [{header['rights_label']}]({header['rights_url']}); "
                  f"header status: {header['rights_status']}.",
                  f"Source availability wording: {header['availability']}", "",
                  "This notice records the electronic source's statement. Rights outside that statement remain unresolved.", ""])
    value = "\n".join(lines).encode("utf-8")
    if _scan(value.decode("utf-8"), "public notice") or b"<" in value or b">" in value:
        raise ValueError(f"DocSouth public notice contains disallowed content: {work_id}")
    return value


def _source_note(work_id: str, source_path: str, source_sha: str, notice_path: str,
                 header: dict) -> bytes:
    lines = [f"# Electronic source for {work_id}", "",
             f"The retained DocSouth TEI.2 source is `{source_path}` (SHA-256 `{source_sha}`).",
             f"The electronic header names {header['publisher']} as publisher and gives these credits:",
             *header["credits"]]
    if header["funder"]:
        lines.append(f"- Funding: {header['funder']}")
    lines.extend(["", f"Source rights link: [{header['rights_label']}]({header['rights_url']}); "
                  f"header status: {header['rights_status']}.",
                  f"Exact source availability wording, with whitespace normalized: {header['availability']}", "",
                  "This source note does not grant worldwide rights clearance or public release.",
                  f"For any future public data release, include the corresponding visible notice at `{notice_path}` "
                  "and bind both file hashes through `public_notices`.", ""])
    return "\n".join(lines).encode("utf-8")


def prepare() -> dict:
    if _io_path(HOME).exists() or ROOT.resolve() in HOME.resolve().parents:
        raise ValueError("fresh external DocSouth notice home required")
    inventory_bytes = _io_path(INVENTORY).read_bytes()
    if _sha(inventory_bytes) != INVENTORY_SHA:
        raise ValueError("DocSouth exact source inventory changed")
    illustrated = sorted((item for item in json.loads(inventory_bytes)["works"]
                          if item["element_counts"].get("figure", 0) > 0),
                         key=lambda item: item["work_id"])
    if len(illustrated) != 22 or len({item["work_id"] for item in illustrated}) != 22:
        raise ValueError("DocSouth illustrated cohort differs")
    discovered_works = discover_library(_io_path(ROOT))
    pending: list[tuple[Path, bytes, Path, bytes]] = []
    items = []
    for entry in illustrated:
        work_id = entry["work_id"]
        work_root = ROOT / "library/works" / work_id
        files = _files(work_root)
        masters = [relative for relative in files if relative.endswith("/master.tei.xml")]
        acceptances = [relative for relative in files if relative.endswith("/acceptance.json")]
        if len(masters) != 1 or len(acceptances) != 1 or entry["accepted_master_present"]:
            raise ValueError(f"DocSouth exact illustrated accepted work differs: {work_id}")
        accepted = _validate_acceptance_for_views(_io_path(work_root / acceptances[0]),
                                                   root=_io_path(ROOT), discovered_works=discovered_works)
        master_sha = files[masters[0]]
        if accepted["promotion"]["master"]["sha256"] != master_sha:
            raise ValueError(f"DocSouth promoted master differs: {work_id}")
        source_path = ROOT / entry["source_path"]
        source_bytes = _io_path(source_path).read_bytes()
        if _sha(source_bytes) != entry["source_sha256"] or len(source_bytes) != entry["source_bytes"]:
            raise ValueError(f"DocSouth retained source changed: {work_id}")
        header = _header(source_bytes, entry["rights_text_sha256"])
        source_note_path = Path("sources/docsouth") / work_id / "README.source.md"
        notice_path = Path("data/structured-text") / work_id / "README.md"
        note = _source_note(work_id, entry["source_path"], entry["source_sha256"],
                            notice_path.as_posix(), header)
        notice = _notice(work_id, header)
        target = ROOT / source_note_path
        if _io_path(target).exists() and _io_path(target).read_bytes() != note:
            raise ValueError(f"DocSouth existing source note differs: {target}")
        external = HOME / notice_path
        pending.append((target, note, external, notice))
        items.append(dict(work_id=work_id, source_path=source_note_path.as_posix(),
                          source_sha256=_sha(note), notice_path=notice_path.as_posix(),
                          notice_sha256=_sha(notice), external_notice_path=external.as_posix(),
                          retained_xml_path=entry["source_path"], retained_xml_sha256=entry["source_sha256"],
                          retained_rights_text_sha256=entry["rights_text_sha256"],
                          rights_label=header["rights_label"], rights_status=header["rights_status"],
                          accepted_master_sha256=master_sha,
                          acceptance_sha256=files[acceptances[0]]))
    _io_path(HOME).mkdir(parents=True)
    for target, note, external, notice in pending:
        _io_path(target).parent.mkdir(parents=True, exist_ok=True)
        _io_path(target).write_bytes(note)
        _io_path(external).parent.mkdir(parents=True, exist_ok=True)
        _io_path(external).write_bytes(notice)
    index = dict(contract=CONTRACT, status="future-release-notice-only",
                 inventory_path=INVENTORY.relative_to(ROOT).as_posix(),
                 inventory_sha256=INVENTORY_SHA, selected_work_count=22,
                 source_note_count=22, external_notice_count=22,
                 canonical_data_write="not-performed", public_release="not-performed", items=items)
    index_path = HOME / "notice-index.json"
    _io_path(index_path).write_bytes((json.dumps(index, sort_keys=True, separators=(",", ":"),
                                              ensure_ascii=False) + "\n").encode("utf-8"))
    return dict(index=index_path.as_posix(), index_sha256=_sha(_io_path(index_path).read_bytes()),
                items=len(items))


def main() -> None:
    print(json.dumps(prepare(), sort_keys=True))


if __name__ == "__main__":
    main()
