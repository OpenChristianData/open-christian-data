"""Independent source-tree expectations for Standard Ebooks candidates.

This reader uses stdlib ElementTree and does not import the SE converter or its
inventory. Unknown source shapes fail closed instead of receiving text-only
credit. The expectation model is intentionally stricter than the legacy route.
"""
from __future__ import annotations

import base64
import ast
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlsplit

from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

T = "{http://www.tei-c.org/ns/1.0}"
X = "{http://www.w3.org/1999/xhtml}"
E = "{http://www.idpf.org/2007/ops}type"
XML = "{http://www.w3.org/XML/1998/namespace}"
ORACLE_ID = "ocd-standard-ebooks-independent-tree-oracle"
ORACLE_VERSION = "1"


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _local(node):
    return node.tag.rsplit("}", 1)[-1]


def _text(value):
    return re.sub(r"\s+", " ", value or "")


def _attrs(node):
    uncovered = set(node.attrib) - {"id", XML + "lang", "lang", E, "class", "href", "src", "alt", "datetime", "data-parent"}
    if uncovered:
        raise ValueError(f"SE oracle: uncovered source attributes {sorted(uncovered)}")
    result = {}
    if node.get("id"):
        result[XML + "id"] = node.get("id")
    if node.get(XML + "lang") or node.get("lang"):
        result[XML + "lang"] = node.get(XML + "lang") or node.get("lang")
    if node.get(E):
        result["ana"] = " ".join(sorted(node.get(E).split()))
    if node.get("class"):
        result["rend"] = " ".join(node.get("class").split())
    if node.get("data-parent"):
        result["corresp"] = "#" + node.get("data-parent")
    return result


def _element(name, attrs=None):
    return ET.Element(T + name, attrs or {})


def _append(parent, value):
    value = _text(value)
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _source_node(node, member, *, in_header=False):
    tag = _local(node)
    attrs = _attrs(node)
    roles = set(node.get(E, "").split())
    if tag == "section":
        if len(roles) != 1:
            raise ValueError("SE oracle: section must carry one role")
        role = next(iter(roles))
        attrs.pop("ana", None)
        attrs["type"] = {"division": "book", "part": "part", "z3998:subchapter": "subchapter", "z3998:poem": "poem"}.get(role, role)
        result = _element("div", attrs)
        for child in node:
            if _local(child) == "header":
                for item in child:
                    result.append(_source_node(item, member, in_header=True))
            else:
                result.append(_source_node(child, member))
        return result
    if tag == "hgroup":
        result = _element("head", attrs)
        _append(result, node.text)
        for index, child in enumerate(node):
            if index:
                result.append(_element("lb"))
            child_attrs = _attrs(child)
            tokens = set(child.get(E, "").split())
            child_attrs["type"] = "subtitle" if "subtitle" in tokens else "title" if "title" in tokens else "heading-part"
            part = _element("seg", child_attrs)
            _source_children(child, part, member)
            result.append(part)
            _append(result, child.tail)
        return result
    if tag == "img":
        source = node.get("src", "")
        if not source or ":" in source or source.startswith("/") or "\\" in source:
            raise ValueError("SE oracle: image is not a relative retained source")
        path = (member.parent / source).resolve(strict=True)
        if not path.is_relative_to(member.parent.parent.resolve()):
            raise ValueError("SE oracle: image leaves EPUB envelope")
        media = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}.get(path.suffix.lower())
        if not media:
            raise ValueError("SE oracle: unsupported image media type")
        result = _element("figure", attrs)
        result.append(_element("graphic", {"url": f"data:{media};base64," + base64.b64encode(path.read_bytes()).decode("ascii")}))
        if node.get("alt"):
            description = _element("figDesc")
            description.text = node.get("alt")
            result.append(description)
        return result
    if tag == "footer":
        result = _element("trailer", attrs)
        _append(result, node.text)
        for index, child in enumerate(node):
            if _local(child) != "p":
                raise ValueError("SE oracle: unsupported footer child")
            if index:
                result.append(_element("lb"))
            paragraph = _element("seg", {**_attrs(child), "type": "paragraph"})
            _source_children(child, paragraph, member)
            result.append(paragraph)
            _append(result, child.tail)
        return result
    if tag == "blockquote" and roles & {"z3998:verse", "z3998:poem", "z3998:song"}:
        result = _element("quote", attrs)
        group = _element("lg")
        result.append(group)
        for child in node:
            if _local(child) == "cite":
                citation = _element("bibl", _attrs(child))
                _source_children(child, citation, member)
                result.append(citation)
            elif _local(child) == "p":
                if child.attrib:
                    raise ValueError("SE oracle: verse paragraph attributes need a preservation ruling")
                line = _element("l")
                group.append(line)
                _append(line, child.text)
                for part in child:
                    if _local(part) == "br":
                        if part.attrib:
                            raise ValueError("SE oracle: verse break attributes need a preservation ruling")
                        line = _element("l")
                        group.append(line)
                    else:
                        line.append(_source_node(part, member))
                    _append(line, part.tail)
            else:
                raise ValueError("SE oracle: unknown verse child")
        return result
    mapping = {"p": "head" if in_header else "p", "h1": "head", "h2": "head", "h3": "head", "h4": "head",
               "blockquote": "quote", "ol": "list", "ul": "list", "li": "item", "a": "ref", "abbr": "abbr",
               "b": "hi", "strong": "hi", "i": "hi", "small": "hi", "sub": "hi", "sup": "hi", "em": "emph",
               "span": "seg", "q": "q", "time": "date", "br": "lb", "cite": "title"}
    if tag not in mapping:
        raise ValueError(f"SE oracle: uncovered source carrier {tag!r} in {member.name}")
    if tag in {"ol", "ul"}:
        attrs["type"] = "ordered" if tag == "ol" else "bulleted"
    if tag in {"b", "strong", "i", "small", "sub", "sup"}:
        attrs["rend"] = {"b": "bold", "strong": "bold", "i": "italic", "small": "small", "sub": "subscript", "sup": "superscript"}[tag]
    if tag == "a" and node.get("href"):
        attrs["target"] = node.get("href")
        if roles & {"noteref", "backlink"}:
            attrs.pop("ana", None)
            attrs["type"] = "note" if "noteref" in roles else "backlink"
            attrs["target"] = "#" + node.get("href").rsplit("#", 1)[-1]
        else:
            link = urlsplit(node.get("href"))
            if not link.scheme and not link.netloc:
                if link.query:
                    raise ValueError("SE oracle: local link query requires a ruling")
                path = (member.parent / unquote(link.path)).resolve() if link.path else member.resolve()
                if not path.is_relative_to(member.parent.parent.resolve()):
                    raise ValueError("SE oracle: local link escapes source EPUB")
                target = ET.parse(path).getroot()
                identifier = unquote(link.fragment)
                if not identifier:
                    sections = target.findall(X + "body/" + X + "section")
                    if len(sections) != 1:
                        raise ValueError("SE oracle: ambiguous local document target")
                    identifier = sections[0].get("id")
                if not identifier or sum(item.get("id") == identifier for item in target.iter()) != 1:
                    raise ValueError("SE oracle: local link target has no unique retained ID")
                attrs["target"] = "#" + identifier
    if tag == "time" and node.get("datetime"):
        attrs["when"] = node.get("datetime")
    if tag == "p" and roles & {"bridgehead", "se:bridgehead"}:
        attrs.pop("ana", None)
        paragraph = _element("p", attrs)
        _source_children(node, paragraph, member)
        result = _element("argument")
        result.append(paragraph)
        return result
    result = _element(mapping[tag], attrs)
    _source_children(node, result, member)
    return result


def _source_children(source, target, member):
    _append(target, source.text)
    for child in source:
        converted = _source_node(child, member)
        if _local(child) == "cite" and _local(source) in {"blockquote", "section"}:
            converted.tag = T + "bibl"
        target.append(converted)
        _append(target, child.tail)


def _projection(node):
    attrs = dict(node.attrib)
    # @n is a generated convenience number, never a substitute for source IDs.
    if _local(node) == "div":
        attrs.pop("n", None)
    structural = _local(node) in {"TEI", "text", "front", "body", "back", "div", "figure", "lg", "list", "teiHeader", "fileDesc", "titleStmt", "publicationStmt", "sourceDesc", "availability"}
    if _local(node) == "quote" and any(_local(child) == "lg" for child in node):
        structural = True
    text = _text(node.text)
    children = []
    for child in node:
        tail = _text(child.tail)
        children.append((_projection(child), "" if structural and not tail.strip() else tail))
    return (_local(node), sorted(attrs.items()), "" if structural and not text.strip() else text, children)


def check_readable_tree(source_root: Path, content: bytes):
    """Compare ordered source structure, inline carriers, roles and image bytes."""
    opf = ET.parse(source_root / "src/epub/content.opf").getroot()
    package_ns = "{http://www.idpf.org/2007/opf}"
    manifest = {item.get("id"): item.get("href") for item in opf.find(package_ns + "manifest")}
    expected = _element("text")
    buckets = {name: _element(name) for name in ("front", "body", "back")}
    for reference in opf.find(package_ns + "spine"):
        href = manifest.get(reference.get("idref"))
        if not href:
            raise ValueError("SE oracle: unresolved spine member")
        member = source_root / "src/epub" / href
        if member.name == "toc.xhtml":
            continue
        document = ET.parse(member).getroot()
        body = document.find(X + "body")
        if body is None:
            raise ValueError("SE oracle: missing body")
        roles = set(body.get(E, "").split())
        if set(body.attrib) - {E}:
            raise ValueError("SE oracle: uncovered source body attributes")
        bucket = buckets["front" if "frontmatter" in roles else "back" if "backmatter" in roles else "body"]
        for section in body:
            if _local(section) != "section":
                raise ValueError("SE oracle: uncovered body child")
            converted = _source_node(section, member)
            inherited_roles = roles - {"frontmatter", "bodymatter", "backmatter"}
            if inherited_roles:
                converted.set("ana", " ".join(sorted(inherited_roles)))
            if XML + "lang" not in converted.attrib and document.get(XML + "lang"):
                converted.set(XML + "lang", document.get(XML + "lang"))
            bucket.append(converted)
    for name, bucket in buckets.items():
        if len(bucket) or name == "body":
            expected.append(bucket)
    actual = ET.fromstring(content).find(T + "text")
    if actual is None:
        raise ValueError("SE oracle: missing readable TEI text")
    expected_rows = [(bucket.tag, node) for bucket in expected for node in bucket]
    actual_rows = [(bucket.tag, node) for bucket in actual for node in bucket]
    if len(actual_rows) != len(expected_rows):
        raise ValueError("SE oracle: source section omission or invention")
    for (expected_bucket, wanted), (actual_bucket, found) in zip(expected_rows, actual_rows, strict=True):
        if expected_bucket != actual_bucket or _projection(wanted) != _projection(found):
            wanted_value, found_value = _projection(wanted), _projection(found)
            def difference(left, right, path="root"):
                if type(left) is type(right) and isinstance(left, (list, tuple)):
                    if len(left) != len(right):
                        return f"{path}: lengths {len(left)} != {len(right)}"
                    for index, (a, b) in enumerate(zip(left, right)):
                        if a != b:
                            return difference(a, b, path + f"/{index}")
                return f"{path}: expected {str(left)[:150]!r}, observed {str(right)[:150]!r}"
            raise ValueError(f"SE oracle: section {wanted.get(XML + 'id')} differs: {difference(wanted_value, found_value)}")
    # Section rows alone cannot detect invented text between sections, changed
    # container attributes, or additional empty containers.
    if _projection(expected) != _projection(actual):
        raise ValueError("SE oracle: readable text container structure or content differs")


def _closure(root: Path, start: Path | None = None):
    pending = [start or Path(__file__)]
    seen = set()
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        for statement in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(statement, ast.Import):
                names = [item.name for item in statement.names]
            elif isinstance(statement, ast.ImportFrom):
                if statement.level:
                    package = list(path.relative_to(root).parts[:-1])
                    package = package[:len(package) - statement.level + 1]
                    names = [".".join(package + (statement.module or "").split("."))]
                elif statement.module:
                    names = [statement.module]
            for name in names:
                pieces = name.split(".")
                for size in range(1, len(pieces) + 1):
                    package_path = root.joinpath(*pieces[:size], "__init__.py")
                    if package_path.is_file():
                        pending.append(package_path)
                module = root.joinpath(*pieces).with_suffix(".py")
                if module.is_file():
                    pending.append(module)
    records = [{"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": _sha(path.read_bytes())} for path in sorted(seen)]
    return _sha(_canonical({"contract": "ocd-python-import-closure-v1", "members": records})), records


def _independent_inventory(root, profile):
    observed = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts)
    if observed != [row["path"] for row in profile["members"]]:
        raise ValueError("SE oracle: retained envelope mismatch")
    rows = []
    for member in profile["members"]:
        path = root / member["path"]
        content = path.read_bytes()
        if len(content) != member["bytes"] or _sha(content) != member["sha256"]:
            raise ValueError("SE oracle: retained member drift")
        row = dict(member)
        if path.suffix.lower() in {".xhtml", ".opf", ".xml", ".svg"}:
            carriers = []
            def visit(node, pointer):
                carriers.append({"path": pointer, "tag": node.tag, "attributes": dict(node.attrib), "text": node.text, "tail": node.tail})
                for ordinal, child in enumerate(node, 1):
                    visit(child, pointer + "/" + str(ordinal))
            visit(ET.fromstring(content), "/1")
            row["xml_carriers"] = carriers
        rows.append(row)
    return {"contract": "ocd-standard-ebooks-source-accountability-v1", "members": rows}


def _check_header(document, config, revision):
    header = _element("teiHeader")
    desc = ET.SubElement(header, T + "fileDesc")
    title = ET.SubElement(desc, T + "titleStmt")
    ET.SubElement(title, T + "title").text = config.get("title", "")
    ET.SubElement(title, T + "author").text = config.get("author", "")
    for contributor in config.get("contributors", []):
        responsibility = ET.SubElement(title, T + "respStmt")
        ET.SubElement(responsibility, T + "resp").text = contributor.get("role", "contributor").replace("_", " ") if isinstance(contributor, dict) else "Contributor"
        ET.SubElement(responsibility, T + "name").text = contributor.get("name", "") if isinstance(contributor, dict) else contributor
    publication = ET.SubElement(desc, T + "publicationStmt")
    ET.SubElement(publication, T + "publisher").text = "Open Christian Data"
    availability = ET.SubElement(publication, T + "availability", {"status": "unknown"})
    ET.SubElement(availability, T + "p").text = "Rights status unresolved; consult the bound source authority before use."
    source = ET.SubElement(desc, T + "sourceDesc")
    bibl = ET.SubElement(source, T + "bibl")
    ET.SubElement(bibl, T + "ptr", {"target": config.get("source_url", "")})
    if config.get("source_hash"):
        ET.SubElement(bibl, T + "idno", {"type": "sha256"}).text = config["source_hash"].removeprefix("sha256:")
    ET.SubElement(bibl, T + "idno", {"type": "git-commit-sha1"}).text = revision
    ET.SubElement(bibl, T + "note", {"type": "print-source"}).text = config.get("source_edition", "")
    actual = document.find(T + "teiHeader")
    if actual is not None:
        for node in actual.iter():
            if not (node.text or "").strip():
                node.text = None
            if not (node.tail or "").strip():
                node.tail = None
    if actual is None or _projection(actual) != _projection(header):
        raise ValueError("SE oracle: header metadata differs from bound config/revision")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage):
    source_manifest.verify()
    candidate.verify_integrity()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    if policy.get("contract") != "ocd-standard-ebooks-validation-policy-v1" or policy.get("work_id") != source_manifest.record["work_id"] or policy.get("image_policy") != "exact-bytes-data-uri":
        raise ValueError("SE oracle: policy identity or image contract mismatch")
    if profile.get("contract") != "ocd-standard-ebooks-reconstruction-profile-v1" or profile.get("work_id") != source_manifest.record["work_id"] or profile.get("image_policy") != "exact-bytes-data-uri":
        raise ValueError("SE oracle: profile identity mismatch")
    if dict(candidate.manifest["source_manifest"]) != {"path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(), "sha256": source_manifest.sha256} or dict(candidate.manifest["converter"]) != dict(source_manifest.record["converter"]) or candidate.manifest["source_id"] != source_manifest.record["source_id"] or candidate.manifest["status"] != "nonaccepted":
        raise ValueError("SE oracle: candidate binding mismatch")
    root = source_manifest.repository_root
    source_root = root / profile["source_root"]
    if json.loads(candidate.member_bytes("source-accountability.json")) != _independent_inventory(source_root, profile):
        raise ValueError("SE oracle: complete source carrier accounting mismatch")
    content = candidate.member_bytes("content.tei.xml")
    check_readable_tree(source_root, content)
    document = ET.fromstring(content)
    if document.tag != T + "TEI" or [node.tag for node in document] != [T + "teiHeader", T + "text"] or document.attrib:
        raise ValueError("SE oracle: unexpected TEI root content")
    config = json.loads(source_manifest.authority_path("work-config").read_bytes())
    _check_header(document, config, profile["source_revision"])
    etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))).assertValid(etree.fromstring(content))
    expected_provenance = {"contract": "ocd-standard-ebooks-candidate-provenance-v1", "work_id": profile["work_id"],
                          "source_manifest_sha256": source_manifest.sha256, "source_revision": profile["source_revision"],
                          "profile_sha256": _sha(source_manifest.authority_path("reconstruction-profile").read_bytes()),
                          "image_policy": "exact-bytes-data-uri", "status": "nonaccepted", "publication_authorized": False}
    if candidate.member_bytes("provenance.json") != _canonical(expected_provenance):
        raise ValueError("SE oracle: provenance mismatch")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("SE oracle: source attribution mismatch")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_canonical(row) for row in profile["unresolved"]):
        raise ValueError("SE oracle: unresolved questions mismatch")
    closure_sha, closure_rows = _closure(root)
    if any(row["path"] in {"build/tei/se_to_tei.py", "build/tei/se_candidate_reconstruction.py"} for row in closure_rows):
        raise ValueError("SE oracle imports producer")
    primary = sorted(({"name": row["name"], "path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]} for row in source_manifest.record["authorities"] if row["role"] == "primary-source"), key=lambda row: (row["path"], row["name"]))
    source_sha = primary[0]["sha256"] if len(primary) == 1 else _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": primary}))
    return verify_mechanical_facts(source_manifest, candidate, MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()), validator_import_closure_sha256=closure_sha,
        source_sha256=source_sha, profile_sha256=_sha(source_manifest.authority_path("reconstruction-profile").read_bytes()),
        package_schema_sha256=source_manifest.record["package_schema"]["sha256"],
        xsd_sha256=_sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(source_manifest.authority_path("validation-policy").read_bytes()), findings=(),
    )).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
