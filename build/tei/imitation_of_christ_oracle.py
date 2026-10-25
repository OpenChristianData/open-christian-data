"""Producer-independent retained-source oracle for the Kempis TEI candidate."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-imitation-of-christ-source-to-tei-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XHTML = "http://www.w3.org/1999/xhtml"
EPUB = "http://www.idpf.org/2007/ops"
OPF = "http://www.idpf.org/2007/opf"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EPUB_TYPE = f"{{{EPUB}}}type"
SOURCE_SLUG = "thomas-a-kempis_the-imitation-of-christ_william-benham"
UNRESOLVED_IDS = (
    "kempis-popular-attribution-disputed",
    "kempis-work-date-uncertain",
    "kempis-benham-edition-date-conflict",
    "kempis-project-gutenberg-basis-conflict",
    "kempis-contributor-scope-conflict",
    "kempis-rights-jurisdiction",
    "kempis-human-acceptance",
)
_POLICY_COUNT_NAMES = {
    "source_members",
    "source_bytes",
    "xml_members",
    "non_xml_members",
    "xml_observations",
    "elements",
    "attributes",
    "texts",
    "spine_members",
    "toc_links",
    "sections",
    "headings",
    "hgroups",
    "bridgeheads",
    "paragraphs",
    "note_pairs",
    "lists",
    "list_items",
    "verse_groups",
    "verse_lines",
    "inline_carriers",
    "language_carriers",
    "image_members",
    "packaged_images",
}
_AVAILABILITY_TEXT = (
    "The underlying source text and artwork are believed to be in the United States public domain; "
    "other jurisdictions require review. Standard Ebooks contributor work is dedicated under CC0 1.0. "
    "This nonaccepted candidate is not publication authorization."
)
_METADATA_CONFLICTS = (
    "The retained package and title surfaces popularly attribute the originally anonymous work to Thomas à Kempis, while the retained preface disputes that attribution and argues for John Gersen; attribution remains unresolved.",
    "The local config gives 1427, the retained package says early 15th century, and the retained preface advances earlier manuscript evidence; the work date remains uncertain.",
    "The retained dedication is dated 1874 while the retained colophon says William Benham translated the work in 1877; neither date is silently normalized.",
    "The local config says the edition supersedes Project Gutenberg #26222, while the retained OPF and colophon identify Project Gutenberg #1653 as the transcription basis.",
    "The local config names only William Benham, while the retained package names William Benham, H. C. Beeching, El Greco, Project Gutenberg, Weijia Cheng, Alex Cabal, and The League of Moveable Type in distinct roles.",
    "The underlying text/artwork public-domain belief, other-jurisdiction warning, and CC0 dedication of Standard Ebooks contributions are separate rights claims.",
)
_SOURCE_LINKS = (
    "https://github.com/standardebooks/thomas-a-kempis_the-imitation-of-christ_william-benham",
    "https://standardebooks.org/ebooks/thomas-a-kempis/the-imitation-of-christ/william-benham",
    "https://www.gutenberg.org/ebooks/1653",
    "https://archive.org/details/imitationchrist07thomgoog",
    "https://archive.org/details/dli.bengal.10689.16231",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"{label} duplicate key {key!r}")
            value[key] = item
        return value

    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be a JSON object")
    return result


def _source_binding(member: str, xpath: str) -> str:
    return f"urn:ocd-source-observation:{_sha(f'{member}|{xpath}'.encode('utf-8'))}"


def _text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _expected_readme() -> bytes:
    return (
        "# Source and rights\n\n"
        "This is an explicitly nonaccepted reconstruction candidate from the exact retained Standard Ebooks checkout. "
        "It preserves the retained attribution dispute, date uncertainty, the 1874 dedication versus 1877 colophon conflict, "
        "the local Project Gutenberg #26222 claim versus the retained #1653 basis, and the complete contributor set.\n\n"
        "Source links: https://github.com/standardebooks/thomas-a-kempis_the-imitation-of-christ_william-benham ; "
        "https://standardebooks.org/ebooks/thomas-a-kempis/the-imitation-of-christ/william-benham ; "
        "https://www.gutenberg.org/ebooks/1653 .\n\n"
        "The retained license says the underlying text and artwork are believed public domain in the United States, warns that "
        "other jurisdictions may differ, and separately dedicates Standard Ebooks contributions under CC0 1.0. These categories "
        "are not conflated. Machine validation is not human textual acceptance or publication authorization.\n"
    ).encode("utf-8")


def _types(node: etree._Element) -> list[str]:
    return node.get(EPUB_TYPE, "").split()


def _members(manifest: SourceManifest) -> list[tuple[str, Path, bytes]]:
    marker = f"{SOURCE_SLUG}/"
    result = []
    for authority in manifest.record["authorities"]:
        if authority.get("role") == "primary-source":
            path = manifest.authority_path(str(authority["name"]))
            result.append(
                (
                    str(authority["path"]).split(marker, 1)[1],
                    path,
                    path.read_bytes(),
                )
            )
    return sorted(result)


def _git_value(source_root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={source_root.as_posix()}",
            "-C",
            str(source_root),
            *arguments,
        ],
        check=True,
        capture_output=True,
    ).stdout


def _source_root(members: list[tuple[str, Path, bytes]]) -> Path:
    root = members[0][1]
    while root.name != SOURCE_SLUG:
        root = root.parent
    return root


def _verify_git_authority(
    source_root: Path,
    source_scope: Mapping[str, object],
    logical_members: list[str],
) -> None:
    observed_head = _git_value(source_root, "rev-parse", "--verify", "HEAD").decode().strip()
    observed_tree = _git_value(
        source_root, "rev-parse", "--verify", "HEAD^{tree}"
    ).decode().strip()
    if observed_head != source_scope["commit"] or observed_tree != source_scope["tree"]:
        raise ValueError("oracle observed wrong retained commit or tree")
    if _git_value(source_root, "status", "--porcelain=v1", "--untracked-files=all", "-z"):
        raise ValueError("oracle observed a dirty retained checkout")
    raw = _git_value(source_root, "ls-files", "-z").decode("utf-8")
    tracked = raw.rstrip("\0").split("\0") if raw else []
    if tracked != logical_members:
        raise ValueError("oracle observed tracked-member omission or invention")


def _assert_loaded_paths(root: Path) -> dict[str, str]:
    expected_oracle = (root / "build/tei/imitation_of_christ_oracle.py").resolve(strict=True)
    expected_contract = (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True)
    actual_oracle = Path(__file__).resolve(strict=True)
    contract_file = inspect.getsourcefile(SourceManifest)
    candidate_file = inspect.getsourcefile(CandidatePackage)
    if contract_file is None or candidate_file is None:
        raise ValueError("reconstruction contract classes are not source-backed")
    actual_contract = Path(contract_file).resolve(strict=True)
    actual_candidate_contract = Path(candidate_file).resolve(strict=True)
    if not actual_oracle.samefile(expected_oracle):
        raise ValueError("runtime editable or site-package oracle shadow detected")
    if not actual_contract.samefile(expected_contract) or not actual_candidate_contract.samefile(expected_contract):
        raise ValueError("runtime editable or site-package contract shadow detected")
    return {
        "oracle": actual_oracle.relative_to(root).as_posix(),
        "contract": actual_contract.relative_to(root).as_posix(),
    }


def _local_module(root: Path, module: str) -> Path | None:
    if not module or any(part in {"", ".", ".."} for part in module.split(".")):
        return None
    stem = root.joinpath(*module.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("import closure escaped repository root") from exc
        if resolved.is_file():
            return resolved
    return None


def _import_names(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        base = node.module or ""
    else:
        relative = path.relative_to(root)
        package = list(relative.parts[:-1])
        ascent = node.level - 1
        if ascent > len(package):
            raise ValueError("relative import closure escaped repository root")
        prefix = package[: len(package) - ascent]
        suffix = node.module.split(".") if node.module else []
        base = ".".join([*prefix, *suffix])
    values = [base] if base else []
    for alias in node.names:
        if alias.name != "*":
            values.append(f"{base}.{alias.name}" if base else alias.name)
    return tuple(values)


def _initializers(root: Path, path: Path) -> tuple[Path, ...]:
    relative = path.relative_to(root)
    values = []
    for depth in range(1, len(relative.parts)):
        candidate = root.joinpath(*relative.parts[:depth], "__init__.py")
        if candidate.is_file():
            values.append(candidate.resolve(strict=True))
    return tuple(values)


def _repository_import_closure(
    root: Path,
    entry: Path,
    forbidden: tuple[str, ...],
) -> tuple[dict[str, object], ...]:
    root = root.resolve(strict=True)
    entry = entry.resolve(strict=True)
    entry.relative_to(root)
    pending = [entry, *_initializers(root, entry)]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
                "__import__", "eval", "exec",
            }:
                raise ValueError("oracle closure contains dynamic import or execution")
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = _import_names(path, root, node)
            else:
                names = ()
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"oracle closure contains forbidden import {name}")
                dependency = _local_module(root, name)
                if dependency is not None and dependency not in visited:
                    pending.extend((dependency, *_initializers(root, dependency)))
    records = []
    for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix()):
        content = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": len(content),
                "sha256": _sha(content),
            }
        )
    return tuple(records)


def _closure(
    root: Path,
    entry: Path | None = None,
    forbidden: tuple[str, ...] = (),
) -> tuple[str, list[dict[str, object]]]:
    records = list(
        _repository_import_closure(root, entry or Path(__file__), forbidden)
    )
    digest = _sha(
        _canonical({"contract": "ocd-python-import-closure-v1", "members": records})
    )
    return digest, records


def _walk_observations(
    logical: str,
    tree: etree._ElementTree,
) -> tuple[list[dict[str, object]], dict[etree._Element, str]]:
    records: list[dict[str, object]] = []
    bindings: dict[etree._Element, str] = {}

    def visit(element: etree._Element) -> None:
        qname = etree.QName(element)
        xpath = tree.getpath(element)
        binding = _source_binding(logical, xpath)
        bindings[element] = binding
        common: dict[str, object] = {
            "member": logical,
            "path": xpath,
            "source_binding": binding,
            "disposition": "evidence-only",
        }
        records.append(
            {
                **common,
                "kind": "element",
                "name": qname.text,
                "value_sha256": _sha(qname.text.encode("utf-8")),
            }
        )
        for name in sorted(element.attrib):
            value = element.attrib[name]
            records.append(
                {
                    **common,
                    "kind": "attribute",
                    "name": etree.QName(name).text,
                    "value_sha256": _sha(value.encode("utf-8")),
                }
            )
        if element.text and element.text.strip():
            records.append(
                {
                    **common,
                    "kind": "text",
                    "path": f"{xpath}/text()",
                    "name": "text",
                    "value_sha256": _sha(element.text.encode("utf-8")),
                }
            )
        if element.tail and element.tail.strip():
            records.append(
                {
                    **common,
                    "kind": "text",
                    "path": f"{xpath}/following-sibling-text()",
                    "name": "tail",
                    "value_sha256": _sha(element.tail.encode("utf-8")),
                }
            )
        for child in element:
            visit(child)

    visit(tree.getroot())
    for number, record in enumerate(records, 1):
        record["observation_id"] = f"{logical}#{number:05d}"
    return records, bindings


def _section_id(node: etree._Element) -> str | None:
    if etree.QName(node).localname == "section":
        return node.get("id")
    for ancestor in node.iterancestors():
        if etree.QName(ancestor).namespace == XHTML and etree.QName(ancestor).localname == "section":
            return ancestor.get("id")
    return None


def _source_semantics(
    roots: Mapping[str, etree._ElementTree],
    spine: list[str],
    binding_maps: Mapping[str, Mapping[etree._Element, str]],
) -> dict[str, object]:
    ns = {
        "x": XHTML,
        "epub": EPUB,
        "xml": "http://www.w3.org/XML/1998/namespace",
    }
    result: dict[str, object] = {
        "matter_counts": {"front": 0, "body": 0, "back": 0},
        "sections": [],
        "headings": [],
        "hgroups": [],
        "bridgeheads": [],
        "paragraphs": [],
        "notes": [],
        "lists": [],
        "verse": [],
        "inline": [],
        "languages": [],
        "images": [],
        "toc": [],
        "landmarks": [],
    }
    matter_counts = result["matter_counts"]
    assert isinstance(matter_counts, dict)
    notes = result["notes"]
    assert isinstance(notes, list)
    for href in spine:
        logical = f"src/epub/{href}"
        tree = roots[logical]
        binding = binding_maps[logical]
        body = tree.find(f".//{{{XHTML}}}body")
        if body is None:
            raise ValueError("source spine body disappeared")
        matter = next(
            (
                token.removesuffix("matter")
                for token in _types(body)
                if token in {"frontmatter", "bodymatter", "backmatter"}
            ),
            None,
        )
        if matter not in matter_counts:
            raise ValueError("source matter class disappeared")
        matter_counts[matter] += 1

        sections = result["sections"]
        assert isinstance(sections, list)
        for node in body.xpath(".//x:section", namespaces=ns):
            parent = next(
                (a for a in node.iterancestors() if etree.QName(a).localname == "section"),
                None,
            )
            sections.append(
                {
                    "member": logical,
                    "binding": binding[node],
                    "id": node.get("id"),
                    "parent_id": parent.get("id") if parent is not None else None,
                    "matter": matter,
                    "types": _types(node),
                    "text_sha256": _sha(_text(node).encode("utf-8")),
                }
            )

        headings = result["headings"]
        assert isinstance(headings, list)
        for node in body.xpath(".//x:h1|.//x:h2|.//x:h3|.//x:h4|.//x:h5|.//x:h6", namespaces=ns):
            headings.append(
                {
                    "member": logical,
                    "binding": binding[node],
                    "tag": etree.QName(node).localname,
                    "section_id": _section_id(node),
                    "in_hgroup": any(etree.QName(a).localname == "hgroup" for a in node.iterancestors()),
                    "text_sha256": _sha(_text(node).encode("utf-8")),
                }
            )

        hgroups = result["hgroups"]
        assert isinstance(hgroups, list)
        for node in body.xpath(".//x:hgroup", namespaces=ns):
            hgroups.append(
                {
                    "member": logical,
                    "binding": binding[node],
                    "section_id": _section_id(node),
                    "child_tags": [etree.QName(child).localname for child in node],
                    "text_sha256": _sha(_text(node).encode("utf-8")),
                }
            )

        paragraphs = result["paragraphs"]
        bridgeheads = result["bridgeheads"]
        assert isinstance(paragraphs, list) and isinstance(bridgeheads, list)
        for node in body.xpath(".//x:p", namespaces=ns):
            record = {
                "member": logical,
                "binding": binding[node],
                "section_id": _section_id(node),
                "class": node.get("class"),
                "types": _types(node),
                "text_sha256": _sha(_text(node).encode("utf-8")),
            }
            paragraphs.append(record)
            if "bridgehead" in _types(node):
                bridgeheads.append(record)

        for anchor in body.xpath(".//x:a[@epub:type]", namespaces=ns):
            if "noteref" not in _types(anchor):
                continue
            paragraph = next(
                (a for a in anchor.iterancestors() if etree.QName(a).localname == "p"),
                None,
            )
            notes.append(
                {
                    "member": logical,
                    "binding": binding[anchor],
                    "id": anchor.get("id"),
                    "target": anchor.get("href"),
                    "label": _text(anchor),
                    "paragraph_binding": binding.get(paragraph),
                }
            )

        lists = result["lists"]
        assert isinstance(lists, list)
        for node in body.xpath(".//x:ol|.//x:ul", namespaces=ns):
            items = node.xpath("./x:li", namespaces=ns)
            lists.append(
                {
                    "member": logical,
                    "binding": binding[node],
                    "tag": etree.QName(node).localname,
                    "section_id": _section_id(node),
                    "item_bindings": [binding[item] for item in items],
                    "item_text_sha256": [_sha(_text(item).encode("utf-8")) for item in items],
                }
            )

        verse = result["verse"]
        assert isinstance(verse, list)
        for group in body.xpath(".//x:blockquote[@epub:type]", namespaces=ns):
            if "z3998:verse" not in _types(group):
                continue
            line_text: list[str] = []
            for paragraph in group.xpath("./x:p", namespaces=ns):
                current = paragraph.text or ""
                for child in paragraph:
                    if etree.QName(child).localname == "br":
                        line_text.append(" ".join(current.split()))
                        current = child.tail or ""
                    else:
                        current += "".join(child.itertext()) + (child.tail or "")
                line_text.append(" ".join(current.split()))
            verse.append(
                {
                    "member": logical,
                    "binding": binding[group],
                    "section_id": _section_id(group),
                    "line_text_sha256": [_sha(value.encode("utf-8")) for value in line_text],
                }
            )

        inline = result["inline"]
        images = result["images"]
        assert isinstance(inline, list) and isinstance(images, list)
        for tag in ("a", "abbr", "b", "strong", "i", "em", "span", "time", "br", "img"):
            for node in body.xpath(f".//x:{tag}", namespaces=ns):
                inline.append(
                    {
                        "member": logical,
                        "binding": binding[node],
                        "tag": tag,
                        "section_id": _section_id(node),
                        "attributes": sorted(
                            (etree.QName(name).text, value)
                            for name, value in node.attrib.items()
                        ),
                        "text_sha256": _sha(_text(node).encode("utf-8")),
                    }
                )
                if tag == "img":
                    images.append(
                        {
                            "member": logical,
                            "binding": binding[node],
                            "src": node.get("src"),
                            "alt": node.get("alt"),
                        }
                    )

        languages = result["languages"]
        assert isinstance(languages, list)
        for node in body.xpath(".//*[@xml:lang] | self::*[@xml:lang]", namespaces=ns):
            languages.append(
                {
                    "member": logical,
                    "binding": binding[node],
                    "tag": etree.QName(node).localname,
                    "language": node.get(XML_LANG),
                    "section_id": _section_id(node),
                }
            )
        html = tree.getroot()
        if html.get(XML_LANG):
            languages.append(
                {
                    "member": logical,
                    "binding": binding[html],
                    "tag": "html",
                    "language": html.get(XML_LANG),
                    "section_id": None,
                }
            )

    endnotes_tree = roots["src/epub/text/endnotes.xhtml"]
    endnote_binding = binding_maps["src/epub/text/endnotes.xhtml"]
    note_bodies = endnotes_tree.xpath("//x:li[@epub:type='endnote']", namespaces=ns)
    if len(note_bodies) != len(notes):
        raise ValueError("source note-reference/body cardinality differs")
    for record, note in zip(notes, note_bodies, strict=True):
        backlinks = note.xpath(".//x:a[@epub:type='backlink']", namespaces=ns)
        if len(backlinks) != 1:
            raise ValueError("source note backlink cardinality differs")
        backlink = backlinks[0]
        record.update(
            {
                "note_binding": endnote_binding[note],
                "note_id": note.get("id"),
                "note_text_sha256": _sha(_text(note).encode("utf-8")),
                "backlink_binding": endnote_binding[backlink],
                "backlink_target": backlink.get("href"),
                "backlink_label": _text(backlink),
            }
        )

    toc_tree = roots["src/epub/toc.xhtml"]
    toc_binding = binding_maps["src/epub/toc.xhtml"]
    toc = result["toc"]
    assert isinstance(toc, list)
    for anchor in toc_tree.xpath("//x:nav[@epub:type='toc']//x:a", namespaces=ns):
        ancestor_items = anchor.xpath("ancestor::x:li", namespaces=ns)
        parent_anchor = None
        if len(ancestor_items) > 1:
            candidates = ancestor_items[-2].xpath("./x:a", namespaces=ns)
            parent_anchor = candidates[0] if candidates else None
        toc.append(
            {
                "binding": toc_binding[anchor],
                "href": anchor.get("href"),
                "label": _text(anchor),
                "parent_href": parent_anchor.get("href") if parent_anchor is not None else None,
            }
        )
    landmarks = result["landmarks"]
    assert isinstance(landmarks, list)
    for anchor in toc_tree.xpath("//x:nav[@epub:type='landmarks']//x:a", namespaces=ns):
        landmarks.append(
            {
                "binding": toc_binding[anchor],
                "href": anchor.get("href"),
                "label": _text(anchor),
                "types": _types(anchor),
            }
        )
    return result


def _svg_evidence(roots: Mapping[str, etree._ElementTree]) -> list[dict[str, object]]:
    records = []
    for member in sorted(item for item in roots if item.endswith(".svg")):
        tree = roots[member]
        for node in tree.iter():
            kind = etree.QName(node).localname
            value = node.text.strip() if node.text else ""
            if kind in {"title", "desc", "text"} and value:
                records.append(
                    {
                        "member": member,
                        "path": tree.getpath(node),
                        "kind": kind,
                        "text": value,
                        "text_sha256": _sha(value.encode("utf-8")),
                    }
                )
    return records


def _verify_direct_metadata(
    roots: Mapping[str, etree._ElementTree],
    config: Mapping[str, object],
    profile: Mapping[str, object],
    license_bytes: bytes,
) -> None:
    ns = {"opf": OPF, "x": XHTML, "epub": EPUB}
    opf = roots["src/epub/content.opf"]
    one = lambda query: " ".join("".join(opf.xpath(query, namespaces=ns)).split())
    title = one("string(/opf:package/opf:metadata/*[local-name()='title'][1])")
    creator = one("string(/opf:package/opf:metadata/*[local-name()='creator'][1])")
    description = one("string(/opf:package/opf:metadata/*[@id='long-description'][1])")
    sources = [
        " ".join("".join(node.itertext()).split())
        for node in opf.xpath("/opf:package/opf:metadata/*[local-name()='source']", namespaces=ns)
    ]
    contributors = [
        " ".join("".join(node.itertext()).split())
        for node in opf.xpath("/opf:package/opf:metadata/*[local-name()='contributor']", namespaces=ns)
    ]
    roles = {
        contributor_id: [
            " ".join("".join(node.itertext()).split())
            for node in opf.xpath(
                f"/opf:package/opf:metadata/opf:meta[@property='role'][@refines='#{contributor_id}']",
                namespaces=ns,
            )
        ]
        for contributor_id in ("translator", "annotator", "artist")
    }
    metadata = profile["metadata"]
    if not isinstance(metadata, dict):
        raise ValueError("profile metadata is not an object")
    if title != "The Imitation of Christ" or creator != "Thomas à Kempis":
        raise ValueError("direct OPF title or popular attribution drifted")
    if "popularly attributed" not in description or "early 15th century" not in description:
        raise ValueError("direct OPF attribution/date uncertainty disappeared")
    if sources != [
        "https://www.gutenberg.org/ebooks/1653",
        "https://archive.org/details/imitationchrist07thomgoog",
        "https://archive.org/details/dli.bengal.10689.16231",
    ]:
        raise ValueError("direct OPF source-link set drifted")
    if contributors != [
        "The League of Moveable Type", "William Benham", "H. C. Beeching", "El Greco",
        "Project Gutenberg", "Weijia Cheng", "Alex Cabal",
    ]:
        raise ValueError("direct OPF contributor set drifted")
    titlepage = roots["src/epub/text/titlepage.xhtml"]
    titlepage_credit = _text(
        titlepage.xpath(
            "//x:p[x:b[contains(@epub:type,'z3998:translator')]]",
            namespaces=ns,
        )[0]
    )
    expected_responsibilities = [
        ["annotator, translator, writer of preface", "William Benham"],
        ["annotator", "H. C. Beeching"],
        ["artist", "El Greco"],
    ]
    if (
        roles != {"translator": ["ann", "trl", "wpr"], "annotator": ["ann"], "artist": ["art"]}
        or titlepage_credit != "Translated by William Benham."
        or metadata.get("principal_responsibilities") != expected_responsibilities
    ):
        raise ValueError("retained contributor role evidence drifted or was invented")
    dedication = roots["src/epub/text/dedication.xhtml"]
    colophon = roots["src/epub/text/colophon.xhtml"]
    dedication_dates = [_text(node) for node in dedication.xpath("//x:time", namespaces=ns)]
    colophon_dates = [_text(node) for node in colophon.xpath("//x:time", namespaces=ns)]
    if dedication_dates != ["Second Sunday in Lent, 1874."] or "1877" not in colophon_dates:
        raise ValueError("direct 1874 dedication or 1877 colophon evidence drifted")
    if config.get("original_publication_year") != 1427 or "#26222" not in str(config.get("source_edition")):
        raise ValueError("local config date or Project Gutenberg conflict evidence drifted")
    if metadata.get("title") != title or metadata.get("popular_attribution") != creator:
        raise ValueError("profile coordinated a metadata invention")
    if metadata.get("contributors") != contributors or metadata.get("opf_sources") != sources:
        raise ValueError("profile coordinated contributor or source-link invention")
    rights_text = license_bytes.decode("utf-8")
    for phrase in (
        "believed to be in the United States public domain",
        "may still be copyrighted in other countries",
        "CC0 1.0 Universal Public Domain Dedication",
    ):
        if phrase not in rights_text:
            raise ValueError("retained rights categories drifted or were conflated")


def _header_projection(node: etree._Element) -> dict[str, object]:
    text = node.text or ""
    return {
        "name": etree.QName(node).localname,
        "attributes": {
            ("xml:id" if key == XML_ID else etree.QName(key).localname): value
            for key, value in sorted(node.attrib.items())
        },
        "text": "" if not text.strip() else text,
        "children": [_header_projection(child) for child in node],
    }


def _expected_header(source_member_set_sha256: str) -> dict[str, object]:
    def element(
        name: str,
        *,
        text: str = "",
        attributes: Mapping[str, str] | None = None,
        children: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return {
            "name": name,
            "attributes": dict(attributes or {}),
            "text": text,
            "children": children or [],
        }

    title_responsibilities = [
        ("annotator, translator, writer of preface", "William Benham"),
        ("annotator", "H. C. Beeching"),
        ("artist", "El Greco"),
    ]
    source_responsibilities = [
        ("translator, annotator, and writer of preface", "William Benham"),
        ("annotator", "H. C. Beeching"),
    ]
    return element(
        "teiHeader",
        children=[
            element(
                "fileDesc",
                children=[
                    element(
                        "titleStmt",
                        children=[
                            element("title", text="The Imitation of Christ"),
                            element("author", text="Thomas à Kempis"),
                            *[
                                element(
                                    "respStmt",
                                    children=[element("resp", text=role), element("name", text=person)],
                                )
                                for role, person in title_responsibilities
                            ],
                        ],
                    ),
                    element(
                        "publicationStmt",
                        children=[
                            element("publisher", text="Open Christian Data"),
                            element(
                                "availability",
                                attributes={"status": "unknown"},
                                children=[element("p", text=_AVAILABILITY_TEXT)],
                            ),
                        ],
                    ),
                    element(
                        "notesStmt",
                        children=[
                            element("note", text=conflict, attributes={"type": "unresolved"})
                            for conflict in _METADATA_CONFLICTS
                        ],
                    ),
                    element(
                        "sourceDesc",
                        children=[
                            element(
                                "bibl",
                                children=[
                                    element("title", text="The Imitation of Christ"),
                                    element("author", text="Thomas à Kempis"),
                                    *[
                                        element(
                                            "respStmt",
                                            children=[element("resp", text=role), element("name", text=person)],
                                        )
                                        for role, person in source_responsibilities
                                    ],
                                    element("publisher", text="Standard Ebooks"),
                                    *[element("ptr", attributes={"target": link}) for link in _SOURCE_LINKS],
                                    element("idno", text=source_member_set_sha256, attributes={"type": "sha256"}),
                                ],
                            )
                        ],
                    ),
                ],
            )
        ],
    )


def _verify_complete_package_surfaces(
    tei: etree._Element,
    source_member_set_sha256: str,
    readme: bytes,
) -> None:
    ns = {"t": TEI}
    headers = tei.xpath("/t:TEI/t:teiHeader", namespaces=ns)
    if len(headers) != 1 or _header_projection(headers[0]) != _expected_header(source_member_set_sha256):
        raise ValueError("candidate complete allowed TEI header, metadata, or availability drifted")
    if readme != _expected_readme():
        raise ValueError("candidate complete package-only README drifted")


def _verify_css_semantics(
    members: list[tuple[str, Path, bytes]],
    semantics: Mapping[str, object],
    profile: Mapping[str, object],
) -> None:
    content = {logical: value.decode("utf-8") for logical, _, value in members if logical.endswith(".css")}
    core = content["src/epub/css/core.css"]
    if "p.continued," not in core or "text-indent: 0;" not in core:
        raise ValueError("retained continued paragraph CSS semantics drifted")
    if "abbr{" not in core or "white-space: nowrap;" not in core:
        raise ValueError("retained abbreviation/eoc CSS semantics drifted")
    paragraphs = semantics["paragraphs"]
    inline = semantics["inline"]
    assert isinstance(paragraphs, list) and isinstance(inline, list)
    expected = {
        "continued": {
            "source": "src/epub/css/core.css",
            "selector": "p.continued",
            "effect": "text-indent: 0",
            "occurrence_bindings": [
                item["binding"] for item in paragraphs if item["class"] == "continued"
            ],
        },
        "eoc": {
            "source": "src/epub/css/core.css",
            "selector": "abbr",
            "effect": "white-space: nowrap",
            "class": "eoc",
            "occurrence_bindings": [
                item["binding"]
                for item in inline
                if item["tag"] == "abbr" and dict(item["attributes"]).get("class") == "eoc"
            ],
        },
    }
    if profile.get("css_semantics") != expected:
        raise ValueError("profile coordinated continued/eoc semantic drift")


def _candidate_by_binding(tei: etree._Element) -> dict[str, etree._Element]:
    result: dict[str, etree._Element] = {}
    for node in tei.iter():
        for binding in node.get("corresp", "").split():
            if not binding.startswith("urn:ocd-source-observation:"):
                continue
            if binding in result:
                raise ValueError("candidate duplicates a source occurrence binding")
            result[binding] = node
    return result


def _oracle_projection_targets(
    tei: etree._Element,
    provenance: Mapping[str, object],
) -> list[dict[str, object]]:
    targets: dict[str, list[dict[str, str]]] = {}
    tree = tei.getroottree()
    for node in tei.xpath("//*[@corresp]"):
        for position, token in enumerate(str(node.get("corresp")).split(), 1):
            if token.startswith("urn:ocd-source-observation:"):
                targets.setdefault(token, []).append(
                    {
                        "kind": "tei-corresp",
                        "path": f"{tree.getpath(node)}/@corresp[{position}]",
                    }
                )
    pending: list[tuple[str, object]] = [("$", provenance)]
    while pending:
        pointer, value = pending.pop()
        if isinstance(value, dict):
            for key in sorted(value, reverse=True):
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                pending.append((f"{pointer}/{escaped}", value[key]))
        elif isinstance(value, list):
            for index in range(len(value) - 1, -1, -1):
                pending.append((f"{pointer}/{index}", value[index]))
        elif isinstance(value, str):
            for position, token in enumerate(value.split(), 1):
                if token.startswith("urn:ocd-source-observation:"):
                    targets.setdefault(token, []).append(
                        {
                            "kind": "provenance-value",
                            "path": f"{pointer}#token={position}",
                        }
                    )
    return [
        {
            "binding": binding,
            "targets": sorted(values, key=lambda item: (item["kind"], item["path"])),
        }
        for binding, values in sorted(targets.items())
    ]


def _oracle_apply_dispositions(
    observations: list[dict[str, object]],
    projection_targets: list[dict[str, object]],
) -> tuple[int, int, str, set[str], set[str]]:
    source_bindings = {str(item["source_binding"]) for item in observations}
    candidate_bindings = {str(item["binding"]) for item in projection_targets}
    if not candidate_bindings <= source_bindings:
        raise ValueError("candidate contains bindings outside the retained source inventory")
    for observation in observations:
        binding = str(observation["source_binding"])
        represented = binding in candidate_bindings
        observation["disposition"] = "represented" if represented else "evidence-only"
        if represented:
            observation["candidate_binding"] = binding
        else:
            observation.pop("candidate_binding", None)
    labels = [str(item["disposition"]) for item in observations]
    return (
        labels.count("represented"),
        labels.count("evidence-only"),
        _sha(_canonical(labels)),
        source_bindings,
        candidate_bindings,
    )


def _candidate_text_without_alternatives(node: etree._Element) -> str:
    copy = etree.fromstring(etree.tostring(node))
    ns = {"t": TEI}
    for description in copy.xpath(".//t:figDesc", namespaces=ns):
        description.getparent().remove(description)
    return " ".join("".join(copy.itertext()).split())


def _nearest_candidate_div_binding(node: etree._Element) -> str | None:
    for ancestor in node.iterancestors():
        if etree.QName(ancestor).namespace == TEI and etree.QName(ancestor).localname == "div":
            for binding in ancestor.get("corresp", "").split():
                if binding.startswith("urn:ocd-source-observation:"):
                    return binding
    return None


def _verify_candidate_semantics(
    tei: etree._Element,
    roots: Mapping[str, etree._ElementTree],
    spine: list[str],
    semantics: Mapping[str, object],
    binding_maps: Mapping[str, Mapping[etree._Element, str]],
) -> None:
    ns = {"t": TEI, "xml": "http://www.w3.org/XML/1998/namespace"}
    by_binding = _candidate_by_binding(tei)
    top_divs = tei.xpath("/t:TEI/t:text/t:body/t:div", namespaces=ns)
    if len(top_divs) != 126:
        raise ValueError("candidate top-level spine cardinality drifted")
    top_bindings = [node.get("corresp", "").split()[0] for node in top_divs]
    source_top = []
    for href in spine:
        logical = f"src/epub/{href}"
        section = roots[logical].find(f".//{{{XHTML}}}body/{{{XHTML}}}section")
        if section is None:
            raise ValueError("source top-level section disappeared")
        source_top.append(binding_maps[logical][section])
    if top_bindings != source_top:
        raise ValueError("candidate spine reorder or same-count section swap")

    sections = semantics["sections"]
    assert isinstance(sections, list)
    by_section_id = {record["id"]: record["binding"] for record in sections}
    for record in sections:
        node = by_binding.get(str(record["binding"]))
        if node is None or etree.QName(node).localname != "div":
            raise ValueError("candidate section occurrence binding missing")
        if node.get(XML_ID) != record["id"]:
            raise ValueError("candidate section identity drifted")
        if _sha(_candidate_text_without_alternatives(node).encode("utf-8")) != record["text_sha256"]:
            raise ValueError("candidate section text omission, invention, reorder, or misattachment")
        parent_id = record["parent_id"]
        if parent_id is not None and _nearest_candidate_div_binding(node) != by_section_id[parent_id]:
            raise ValueError("candidate nested-section hierarchy drifted")

    headings = semantics["headings"]
    hgroups = semantics["hgroups"]
    bridgeheads = semantics["bridgeheads"]
    paragraphs = semantics["paragraphs"]
    assert all(isinstance(value, list) for value in (headings, hgroups, bridgeheads, paragraphs))
    hgroup_paragraph_bindings = {
        binding_maps[f"src/epub/{href}"][paragraph]
        for href in spine
        for paragraph in roots[f"src/epub/{href}"].xpath(
            "//*[local-name()='hgroup']/*[local-name()='p']"
        )
    }
    for record in headings:
        node = by_binding.get(str(record["binding"]))
        expected_tag = "seg" if record["in_hgroup"] else "head"
        if node is None or etree.QName(node).localname != expected_tag or node.get("type") != f"source-{record['tag']}":
            raise ValueError("candidate heading/hgroup attachment drifted")
        if record["section_id"] is not None and _nearest_candidate_div_binding(node) != by_section_id[record["section_id"]]:
            raise ValueError("candidate heading moved to the wrong section")
        if _sha(_text(node).encode("utf-8")) != record["text_sha256"]:
            raise ValueError("candidate heading text drifted")
    for record in hgroups:
        node = by_binding.get(str(record["binding"]))
        if node is None or etree.QName(node).localname != "head" or node.get("type") != "hgroup":
            raise ValueError("candidate hgroup carrier drifted")
        if record["section_id"] is not None and _nearest_candidate_div_binding(node) != by_section_id[record["section_id"]]:
            raise ValueError("candidate hgroup moved to the wrong section")
        child_tags = [
            child.get("type", "").removeprefix("source-")
            for child in node
            if etree.QName(child).localname == "seg"
        ]
        if child_tags != record["child_tags"] or _sha(_text(node).encode("utf-8")) != record["text_sha256"]:
            raise ValueError("candidate hgroup child or text attachment drifted")
    for record in bridgeheads:
        node = by_binding.get(str(record["binding"]))
        expected_tag = "seg" if record["binding"] in hgroup_paragraph_bindings else "p"
        if node is None or etree.QName(node).localname != expected_tag or "source-bridgehead" not in node.get("rend", "").split():
            raise ValueError("candidate bridgehead carrier drifted")
        if record["section_id"] is not None and _nearest_candidate_div_binding(node) != by_section_id[record["section_id"]]:
            raise ValueError("candidate bridgehead moved to the wrong section")
    verse_paragraph_bindings = {
        binding_maps[f"src/epub/{href}"][paragraph]
        for href in spine
        for paragraph in roots[f"src/epub/{href}"].xpath(
            "//*[local-name()='blockquote' and contains(@epub:type,'z3998:verse')]/*[local-name()='p']",
            namespaces={"epub": EPUB},
        )
    }
    for record in paragraphs:
        if record["binding"] in verse_paragraph_bindings:
            continue
        node = by_binding.get(str(record["binding"]))
        expected_tag = "seg" if record["binding"] in hgroup_paragraph_bindings else "p"
        if node is None or etree.QName(node).localname != expected_tag:
            raise ValueError("candidate paragraph occurrence disappeared")
        if record["section_id"] is not None and _nearest_candidate_div_binding(node) != by_section_id[record["section_id"]]:
            raise ValueError("candidate repeated paragraph moved to the wrong section")
        if _sha(_text(node).encode("utf-8")) != record["text_sha256"]:
            raise ValueError("candidate repeated paragraph text misattachment")

    notes = semantics["notes"]
    assert isinstance(notes, list)
    expected_numbers = [str(number) for number in range(1, 184)]
    if [record["label"] for record in notes] != expected_numbers:
        raise ValueError("source visible note labels drifted")
    for number, record in enumerate(notes, 1):
        reference = by_binding.get(str(record["binding"]))
        note = by_binding.get(str(record["note_binding"]))
        backlink = by_binding.get(str(record["backlink_binding"]))
        if (
            reference is None
            or note is None
            or backlink is None
            or etree.QName(reference).localname != "ref"
            or reference.get("type") != "note"
            or reference.get("target") != f"#note-{number}"
            or reference.get(XML_ID) != f"noteref-{number}"
            or _text(reference) != str(number)
            or etree.QName(note).localname != "item"
            or note.get(XML_ID) != f"note-{number}"
            or etree.QName(backlink).localname != "ref"
            or backlink.get("type") != "backlink"
            or backlink.get("target") != f"#noteref-{number}"
            or _text(backlink) != "↩"
        ):
            raise ValueError("candidate crossed note/body/backlink/label attachment")
        carriers = [
            ancestor
            for ancestor in reference.iterancestors()
            if etree.QName(ancestor).localname in {"p", "l", "lg"}
        ]
        if not any(
            record["paragraph_binding"] in carrier.get("corresp", "").split()
            for carrier in carriers
        ):
            raise ValueError("candidate note reference attached to the wrong paragraph occurrence")

    lists = semantics["lists"]
    assert isinstance(lists, list)
    for record in lists:
        node = by_binding.get(str(record["binding"]))
        if node is None or etree.QName(node).localname != "list":
            raise ValueError("candidate list carrier disappeared")
        if record["section_id"] is not None and _nearest_candidate_div_binding(node) != by_section_id[record["section_id"]]:
            raise ValueError("candidate list moved to the wrong section")
        item_bindings = [
            child.get("corresp")
            for child in node
            if etree.QName(child).localname == "item"
        ]
        if item_bindings != record["item_bindings"]:
            raise ValueError("candidate list-item swap, loss, or invention")
        if [_sha(_text(child).encode("utf-8")) for child in node if etree.QName(child).localname == "item"] != record["item_text_sha256"]:
            raise ValueError("candidate list-item text drifted")

    verse = semantics["verse"]
    assert isinstance(verse, list)
    for record in verse:
        group = by_binding.get(str(record["binding"]))
        if group is None or etree.QName(group).localname != "lg" or group.get("type") != "verse":
            raise ValueError("candidate verse group placement drifted")
        if record["section_id"] is not None and _nearest_candidate_div_binding(group) != by_section_id[record["section_id"]]:
            raise ValueError("candidate verse group moved to the wrong section")
        line_hashes = [
            _sha(_text(line).encode("utf-8"))
            for line in group
            if etree.QName(line).localname == "l"
        ]
        if line_hashes != record["line_text_sha256"]:
            raise ValueError("candidate verse line move, loss, or invention")

    inline = semantics["inline"]
    assert isinstance(inline, list)
    expected_tags = {
        "a": ("ref", "source-a"),
        "abbr": ("abbr", "source-abbr"),
        "b": ("hi", "source-b"),
        "strong": ("hi", "source-strong"),
        "i": ("hi", "source-i"),
        "em": ("hi", "source-em"),
        "span": ("seg", "source-span"),
        "time": ("date", "source-time"),
        "br": ("lb", "source-br"),
        "img": ("figure", "source-img"),
    }
    for record in inline:
        node = by_binding.get(str(record["binding"]))
        tag, source_type = expected_tags[str(record["tag"])]
        if node is None or etree.QName(node).localname != tag:
            raise ValueError("candidate same-count inline occurrence swap")
        if record["section_id"] is not None and _nearest_candidate_div_binding(node) != by_section_id[record["section_id"]]:
            raise ValueError("candidate inline occurrence moved to the wrong section")
        if record["tag"] == "a":
            if node.get("subtype") != source_type:
                raise ValueError("candidate anchor carrier identity drifted")
        elif record["tag"] in {"b", "strong", "i", "em"}:
            if source_type not in node.get("rend", "").split():
                raise ValueError("candidate inline carrier identity drifted")
        elif node.get("type") != source_type:
            raise ValueError("candidate inline carrier identity drifted")
        attributes = dict(record["attributes"])
        if record["tag"] == "a":
            href = str(attributes.get("href", ""))
            expected_target = f"#{href.rsplit('#', 1)[-1]}" if set(str(attributes.get(EPUB_TYPE, "")).split()) & {"noteref", "backlink"} else href
            if node.get("target") != expected_target:
                raise ValueError("candidate anchor target drifted")
        if record["tag"] == "time" and attributes.get("datetime") and node.get("when") != attributes["datetime"]:
            raise ValueError("candidate time value drifted")
        if record["tag"] == "img":
            graphics = node.xpath("./t:graphic", namespaces=ns)
            alternatives = node.xpath("./t:figDesc", namespaces=ns)
            if len(graphics) != 1 or len(alternatives) != 1 or graphics[0].get("url") != attributes.get("src") or _text(alternatives[0]) != attributes.get("alt", ""):
                raise ValueError("candidate image source/alternative attachment drifted")
        elif _sha(_text(node).encode("utf-8")) != record["text_sha256"]:
            raise ValueError("candidate inline value or attachment drifted")

    languages = semantics["languages"]
    assert isinstance(languages, list)
    for record in languages:
        node = by_binding.get(str(record["binding"]))
        if node is None or node.get(XML_LANG) != record["language"]:
            raise ValueError("candidate same-count language carrier swap")
        if record["section_id"] is not None and _nearest_candidate_div_binding(node) != by_section_id[record["section_id"]]:
            raise ValueError("candidate language carrier moved to the wrong section")

    continued = [
        node for node in tei.xpath("//t:p", namespaces=ns) if "continued" in node.get("rend", "").split()
    ]
    eoc = [
        node for node in tei.xpath("//t:abbr", namespaces=ns) if "eoc" in node.get("rend", "").split()
    ]
    expected_continued = {
        str(record["binding"]) for record in paragraphs if record["class"] == "continued"
    }
    expected_eoc = {
        str(record["binding"])
        for record in inline
        if record["tag"] == "abbr" and dict(record["attributes"]).get("class") == "eoc"
    }
    actual_continued = {
        binding
        for node in continued
        for binding in node.get("corresp", "").split()
        if binding.startswith("urn:ocd-source-observation:")
    }
    actual_eoc = {
        binding
        for node in eoc
        for binding in node.get("corresp", "").split()
        if binding.startswith("urn:ocd-source-observation:")
    }
    if actual_continued != expected_continued or actual_eoc != expected_eoc:
        raise ValueError("candidate CSS-backed continued/eoc semantics drifted")


def _oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    loaded_paths = _assert_loaded_paths(root)
    expected_source_manifest = source_manifest.path.relative_to(root).as_posix()
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_manifest")
        != {"path": expected_source_manifest, "sha256": source_manifest.sha256}
        or candidate.manifest.get("converter") != source_manifest.record["converter"]
        or candidate.manifest.get("package_schema") != source_manifest.record["package_schema"]
    ):
        raise ValueError("candidate authority binding or nonaccepted status drifted")

    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "Kempis reconstruction profile")
    policy = _strict_json(policy_bytes, "Kempis validation policy")
    if profile.get("contract") != "ocd-imitation-of-christ-reconstruction-profile-v1":
        raise ValueError("Kempis profile identity drifted")
    if profile.get("disposition_contract") != {
        "id": "ocd-candidate-projection-disposition-v1",
        "represented": "An XML observation is represented exactly when its source element binding occurs in content.tei.xml @corresp or in a provenance.json string value; every such candidate binding must name a retained source element.",
        "evidence_only": "An XML observation is evidence-only exactly when its source element binding is absent from both candidate projection surfaces.",
        "ordered_dispositions_sha256": "SHA-256 of UTF-8 canonical JSON plus LF for the 10,009 disposition labels in source-member and source-walk observation order.",
    }:
        raise ValueError("Kempis projection disposition contract drifted")
    if policy.get("contract") != "ocd-imitation-of-christ-validation-policy-v1":
        raise ValueError("Kempis policy identity drifted")
    policy_counts = policy.get("required_counts")
    if not isinstance(policy_counts, dict) or set(policy_counts) != _POLICY_COUNT_NAMES:
        raise ValueError("Kempis validation policy count shape drifted")
    if tuple(policy.get("required_unresolved_ids", [])) != UNRESOLVED_IDS:
        raise ValueError("policy coordinated unresolved-evidence deletion")

    members = _members(source_manifest)
    observed_set = [
        {"path": logical, "bytes": len(content), "sha256": _sha(content)}
        for logical, _, content in members
    ]
    member_set_sha = _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": observed_set})
    )
    source_scope = profile["source_scope"]
    assert isinstance(source_scope, dict)
    if (
        len(members) != 142
        or sum(item["bytes"] for item in observed_set) != 5_110_829
        or member_set_sha != "1e5a5f4eb690c01d8424bc8bdaeb9dfc7add41690339e7b67e767e5046f98021"
        or member_set_sha != source_scope.get("member_set_sha256")
    ):
        raise ValueError("oracle retained member set drifted")
    _verify_git_authority(
        _source_root(members), source_scope, [item["path"] for item in observed_set]
    )
    config_bytes = source_manifest.authority_path("local-source-config").read_bytes()
    if len(config_bytes) != 1_197 or _sha(config_bytes) != "702c05e37ca46fed4c9337fe2f664f4b79ac7e813f4602e19ec748d0494a4134":
        raise ValueError("oracle local config authority drifted")
    config = _strict_json(config_bytes, "Kempis local config")

    roots: dict[str, etree._ElementTree] = {}
    binding_maps: dict[str, dict[etree._Element, str]] = {}
    observations: list[dict[str, object]] = []
    non_xml: list[dict[str, object]] = []
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    for logical, path, content in members:
        try:
            tree = etree.parse(str(path), parser)
        except etree.XMLSyntaxError:
            non_xml.append(
                {
                    "member": logical,
                    "bytes": len(content),
                    "sha256": _sha(content),
                    "disposition": profile["non_xml_dispositions"][logical],
                }
            )
            continue
        roots[logical] = tree
        records, bindings = _walk_observations(logical, tree)
        observations.extend(records)
        binding_maps[logical] = bindings
    counts = Counter(str(item["kind"]) for item in observations)
    if (
        len(roots), len(non_xml), len(observations), counts,
    ) != (135, 7, 10_009, Counter({"attribute": 4_283, "element": 3_582, "text": 2_144})):
        raise ValueError("oracle complete XML observation accounting drifted")

    opf = roots["src/epub/content.opf"]
    opf_ns = {"opf": OPF}
    href_by_id = {
        node.get("id"): node.get("href")
        for node in opf.xpath("//opf:manifest/opf:item", namespaces=opf_ns)
    }
    spine = [
        href_by_id[node.get("idref")]
        for node in opf.xpath("//opf:spine/opf:itemref", namespaces=opf_ns)
    ]
    semantics = json.loads(_canonical(_source_semantics(roots, spine, binding_maps)))
    semantic_digests = {
        key: _sha(_canonical(value))
        for key, value in semantics.items()
        if isinstance(value, list)
    }
    if semantic_digests != profile["semantic_digests"]:
        raise ValueError("oracle source semantic occurrence inventory drifted")
    _verify_direct_metadata(
        roots,
        config,
        profile,
        next(content for logical, _, content in members if logical == "LICENSE.md"),
    )
    _verify_css_semantics(members, semantics, profile)

    accountability = _strict_json(
        candidate.member_bytes("source-accountability.json"),
        "Kempis source accountability",
    )
    schema = _strict_json(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "Kempis source accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"source-accountability schema failure: {errors[0].message}")
    tei_bytes = candidate.member_bytes("content.tei.xml")
    tei = etree.fromstring(tei_bytes)
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    xsd = etree.XMLSchema(etree.parse(str(xsd_path)))
    if not xsd.validate(tei):
        raise ValueError(f"TEI P5 XSD failure: {xsd.error_log.last_error}")
    _verify_candidate_semantics(tei, roots, spine, semantics, binding_maps)

    forbidden = tuple(str(value) for value in policy["forbidden_import_prefixes"])
    oracle_closure_sha, oracle_closure = _closure(root, forbidden=forbidden)
    producer_path = (root / "build/tei/imitation_of_christ_reconstruction.py").resolve(strict=True)
    producer_closure_sha, producer_closure = _closure(root, producer_path, forbidden)
    if producer_closure_sha != profile["producer_import_closure_sha256"]:
        raise ValueError("producer recursive import closure drifted")
    validator = source_manifest.record["validator"]
    if oracle_closure_sha != validator["import_closure_sha256"]:
        raise ValueError("oracle recursive import closure drifted")
    if any(
        str(item["path"]).startswith(
            (
                "build/tei/se_to_tei.py", "build/tei/census.py", "build/parsers/standard_ebooks.py",
                "build/reconstruction/", "ocd_kernel/reconstruction/case_declaration.py",
                "ocd_kernel/reconstruction/persistence.py", "ocd_kernel/reconstruction/wave.py",
            )
        )
        for item in oracle_closure
    ):
        raise ValueError("oracle closure reached incumbent or campaign answers")

    image_members = [
        item
        for item in observed_set
        if item["path"] in {
            "images/cover.jpg", "images/cover.source.jpg", "images/cover.svg", "images/titlepage.svg",
            "src/epub/images/cover.svg", "src/epub/images/logo.svg", "src/epub/images/titlepage.svg",
        }
    ]
    provenance = _strict_json(candidate.member_bytes("provenance.json"), "Kempis provenance")
    expected_provenance = {
        "contract": "ocd-imitation-of-christ-provenance-v1",
        "status": "nonaccepted",
        "retained_commit": source_scope["commit"],
        "retained_tree": source_scope["tree"],
        "source_member_set_sha256": member_set_sha,
        "config_sha256": source_scope["config_sha256"],
        "spine": spine,
        "toc": semantics["toc"],
        "landmarks": semantics["landmarks"],
        "image_members": image_members,
        "packaged_images": semantics["images"],
        "svg_strings": _svg_evidence(roots),
        "css_semantics": profile["css_semantics"],
        "metadata": profile["metadata"],
        "metadata_conflicts": profile["metadata_conflicts"],
        "rights": profile["rights"],
        "loaded_module_paths": {
            "converter": "build/tei/imitation_of_christ_reconstruction.py",
            "contract": loaded_paths["contract"],
        },
        "producer_import_closure_sha256": producer_closure_sha,
        "producer_import_closure": producer_closure,
    }
    if provenance != expected_provenance:
        raise ValueError("candidate provenance, source links, conflicts, or rights drifted")
    projection_targets = _oracle_projection_targets(tei, provenance)
    expected_projection_bindings: set[str] = {
        str(record["binding"])
        for group in (semantics["toc"], semantics["landmarks"])
        for record in group
    }
    for href in spine:
        logical = f"src/epub/{href}"
        tree = roots[logical]
        expected_projection_bindings.add(binding_maps[logical][tree.getroot()])
        nodes = tree.xpath(
            "/*[local-name()='html']/*[local-name()='body']/*[local-name()='section']/descendant-or-self::*"
        )
        expected_projection_bindings.update(binding_maps[logical][node] for node in nodes)
    observed_projection_bindings = {str(item["binding"]) for item in projection_targets}
    if observed_projection_bindings != expected_projection_bindings:
        missing = len(expected_projection_bindings - observed_projection_bindings)
        invented = len(observed_projection_bindings - expected_projection_bindings)
        raise ValueError(f"candidate projection carrier bijection drifted: missing={missing}, invented={invented}")
    represented, evidence_only, ordered_disposition_sha, source_bindings, candidate_bindings = (
        _oracle_apply_dispositions(observations, projection_targets)
    )
    projected_bindings = [str(item["binding"]) for item in projection_targets]
    if candidate_bindings != set(projected_bindings) or len(projected_bindings) != len(candidate_bindings):
        raise ValueError("candidate projection target inventory is not a binding bijection")
    expected_accountability = {
        "contract": "ocd-imitation-of-christ-source-accountability-v1",
        "schema": "imitation-of-christ.source-accountability.schema.json",
        "source_members": observed_set,
        "source_member_set_sha256": member_set_sha,
        "xml_member_count": 135,
        "non_xml_member_count": 7,
        "xml_observation_count": 10_009,
        "element_count": 3_582,
        "attribute_count": 4_283,
        "text_count": 2_144,
        "source_binding_count": len(source_bindings),
        "represented_binding_count": len(candidate_bindings),
        "evidence_only_binding_count": len(source_bindings - candidate_bindings),
        "candidate_binding_count": len(projected_bindings),
        "candidate_binding_set_sha256": _sha(_canonical(projected_bindings)),
        "represented_count": represented,
        "evidence_only_count": evidence_only,
        "ordered_dispositions_sha256": ordered_disposition_sha,
        "omitted_count": 0,
        "duplicate_count": 0,
        "observations": observations,
        "projection_targets": projection_targets,
        "non_xml_dispositions": non_xml,
        "semantic_bindings": semantics,
        "semantic_digests": semantic_digests,
    }
    if accountability != expected_accountability:
        raise ValueError("candidate accountability or projection bijection differs from independent source accounting")
    unresolved = [
        _strict_json(line + b"\n", "Kempis unresolved claim")
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
        if line.strip()
    ]
    if tuple(item.get("id") for item in unresolved) != UNRESOLVED_IDS:
        raise ValueError("candidate unresolved evidence was lost or reordered")
    readme = candidate.member_bytes("README.source.md")
    _verify_complete_package_surfaces(tei, member_set_sha, readme)

    source_records = sorted(
        (
            {
                "name": item["name"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in source_manifest.record["authorities"]
            if item["role"] == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    source_sha = _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": source_records})
    )
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": oracle_closure_sha,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": source_sha,
        "xsd_sha256": _sha(xsd_path.read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
