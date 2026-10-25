"""Independent source/TEI checks; does not import the producer."""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from xml.parsers import expat

from lxml import etree
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

NS = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
WORK = "robertson-word-pictures-vol1"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def closure(root):
    paths = (
        "build/tei/robertson_word_pictures_vol1_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
    )
    return digest(canonical({p: digest((root / p).read_bytes()) for p in paths}))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(manifest, members):
    manifest.verify()
    require(
        manifest.record["work_id"] == WORK
        and manifest.record["scope"]["member_order"] == ("matthew", "mark"),
        "work/member boundary",
    )
    require(
        set(members)
        == {
            "content.tei.xml",
            "source-accountability.json",
            "provenance.json",
            "unresolved.jsonl",
            "README.source.md",
        },
        "package member set",
    )
    parser = etree.XMLParser(
        load_dtd=False, no_network=True, resolve_entities=False, recover=False
    )
    tei = etree.fromstring(members["content.tei.xml"], parser)
    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-schema"))))
    q = {"t": NS}
    require(tei.tag == "{" + NS + "}TEI" and len(tei) == 2, "TEI root envelope")
    header = tei.find("t:teiHeader", q)
    expected_header = etree.fromstring(
        (
            '<teiHeader xmlns="'
            + NS
            + '"><fileDesc><titleStmt><title>Word Pictures in the New Testament: assigned Matthew/Mark cohort</title></titleStmt><publicationStmt><p>Nonaccepted reconstruction; no rights or publication decision.</p></publicationStmt><sourceDesc><p n="matthew">Word Pictures in the New Testament - Matthew</p><p n="mark">Word Pictures in the New Testament - Mark</p></sourceDesc></fileDesc></teiHeader>'
        ).encode()
    )
    require(
        header is not None
        and len(list(header.iter())) == len(list(expected_header.iter())),
        "header drift",
    )
    for actual, expected in zip(header.iter(), expected_header.iter(), strict=True):
        require(
            (actual.tag, dict(actual.attrib), actual.text, actual.tail, len(actual))
            == (
                expected.tag,
                dict(expected.attrib),
                expected.text,
                expected.tail,
                len(expected),
            ),
            "header drift",
        )
    body = tei.find("t:text/t:body", q)
    require(
        body is not None
        and len(body) == 2
        and [n.get("n") for n in body] == ["matthew", "mark"],
        "member omission/order",
    )
    text = tei.find("t:text", q)
    require(
        len(text) == 1
        and all(
            not n.attrib and n.text is None and n.tail is None
            for n in (tei, text, body)
        ),
        "TEI wrapper drift",
    )
    ledger = json.loads(members["source-accountability.json"])
    require(
        set(ledger) == {"work_id", "members"}
        and ledger["work_id"] == WORK
        and len(ledger["members"]) == 2,
        "accounting work/member envelope",
    )
    for ordinal, name in enumerate(("matthew", "mark")):
        raw = manifest.authority_path(name).read_bytes()
        source = etree.parse(BytesIO(raw), parser)
        record = ledger["members"][ordinal]
        require(
            record["member"] == name
            and record["bytes"] == len(raw)
            and record["sha256"] == digest(raw),
            "member identity drift",
        )
        require(
            base64.b64decode(record["raw_base64"], validate=True) == raw,
            "complete raw envelope drift",
        )
        # Expat independently corroborates element/attribute/text order without DTD fetch.
        events = []
        xp = expat.ParserCreate()
        xp.StartElementHandler = lambda tag, attrs: events.append((tag, attrs))
        xp.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        xp.Parse(raw, True)
        all_source = source.xpath("//*")
        require(
            events == [(n.tag, dict(n.attrib)) for n in all_source],
            "XML parser inventory disagreement",
        )
        require(
            len(all_source) == record["element_count"] == len(record["nodes"]),
            "node inventory omission",
        )
        source_body = source.find("ThML.body")
        for original, item in zip(all_source, record["nodes"], strict=True):
            expected = {
                "path": source.getpath(original),
                "parent": source.getpath(original.getparent())
                if original.getparent() is not None
                else None,
                "tag": original.tag,
                "attributes": dict(original.attrib),
                "text": original.text,
                "tail": original.tail,
                "disposition": "readable-body"
                if original is source_body or source_body in original.iterancestors()
                else "retained-envelope-and-header-observations",
            }
            require(item == expected, "source carrier ledger drift")
        require(
            record["body_divisions"]
            == [dict(n.attrib) for n in source.findall("ThML.body/div1")],
            "division boundary drift",
        )
        require(
            record["chapters"]
            == [dict(n.attrib) for n in source.findall(".//scripCom")],
            "chapter anchor drift",
        )
        require(
            record["shell"]
            == {
                "doctype": source.docinfo.doctype,
                "comments": [n.text for n in source.xpath("/comment()")],
                "xml_version": source.docinfo.xml_version,
                "encoding": source.docinfo.encoding,
            },
            "document shell drift",
        )
        target_member = body[ordinal]
        require(
            dict(target_member.attrib) == {"type": "retained-member", "n": name}
            and target_member.text == source_body.text
            and target_member.tail is None,
            "member wrapper drift",
        )
        pairs = [(source_body, target_member)]
        correspondence = {}
        source_links = []
        while pairs:
            original_parent, target_parent = pairs.pop()
            flattened = []
            actual_groups = []
            group = 0
            for child in target_parent:
                if child.get("type") == "source-heading-section":
                    require(
                        dict(child.attrib) == {"type": "source-heading-section"}
                        and child.text is None
                        and child.tail is None
                        and len(child) > 0,
                        "heading wrapper drift",
                    )
                    require(
                        child[0].tag == "{" + NS + "}head", "heading ownership drift"
                    )
                    flattened.extend(child)
                    group += 1
                    actual_groups.extend([group] * len(child))
                else:
                    flattened.append(child)
                    actual_groups.append(0)
            require(
                len(original_parent) == len(flattened),
                "source child omission/duplication",
            )
            expected_groups = []
            group = 0
            prose_seen = False
            for source_child in original_parent:
                if source_child.tag in ("h1", "h2", "h3") and prose_seen:
                    group += 1
                expected_groups.append(group)
                if source_child.tag not in ("h1", "h2", "h3", "scripCom"):
                    prose_seen = True
            require(actual_groups == expected_groups, "heading ownership drift")
            for original, target in zip(original_parent, flattened, strict=True):
                correspondence[original] = target
                tag = original.tag
                expected_tag = {
                    "div1": "div",
                    "div2": "div",
                    "div": "div",
                    "h1": "head",
                    "h2": "head",
                    "h3": "head",
                    "p": "p",
                    "a": "ref",
                    "scripRef": "ref",
                    "i": "hi",
                    "b": "hi",
                    "span": "hi",
                    "scripCom": "anchor",
                    "insertIndex": "anchor",
                    "ul": "list",
                    "li": "item",
                }.get(tag)
                require(
                    expected_tag is not None
                    and target.tag == "{" + NS + "}" + expected_tag,
                    "readable structural mapping",
                )
                require(
                    target.text == original.text and target.tail == original.tail,
                    "mixed text order/content drift",
                )
                attrs = {}
                if "id" in original.attrib:
                    attrs["{" + XML + "}id"] = name + "-" + original.get("id")
                if original.get("lang"):
                    attrs["{" + XML + "}lang"] = original.get("lang")
                if tag.startswith("div"):
                    attrs["type"] = "source-" + tag
                    if original.get("title"):
                        attrs["n"] = original.get("title")
                    for pointer in ("prev", "next"):
                        if original.get(pointer):
                            attrs[pointer] = "#" + name + "-" + original.get(pointer)
                if tag in ("h1", "h2", "h3", "scripCom", "insertIndex"):
                    attrs["type"] = "source-" + tag
                if tag in ("i", "b", "span"):
                    attrs["rend"] = (
                        "italic"
                        if tag == "i"
                        else "bold"
                        if tag == "b"
                        else original.get("style", "")
                    )
                    if not attrs["rend"]:
                        del attrs["rend"]
                if tag in ("a", "scripRef"):
                    attrs["type"] = "source-link" if tag == "a" else "scripture"
                    if original.get("version"):
                        attrs["subtype"] = original.get("version")
                    key = "href" if tag == "a" else "osisRef"
                    if key in original.attrib:
                        if tag == "a":
                            # Validate the relationship after all destination nodes
                            # have been matched; do not predict a transformed href.
                            source_links.append((original, target))
                        else:
                            attrs["target"] = original.get(key)
                if tag in ("a", "scripRef", "scripCom", "insertIndex") and original.get(
                    "passage"
                ):
                    attrs["n"] = original.get("passage")
                if tag in ("scripCom", "insertIndex"):
                    if original.get("osisRef"):
                        attrs["corresp"] = original.get("osisRef")
                    if original.get("type"):
                        attrs["subtype"] = original.get("type")
                if original.get("class") or (original.get("style") and tag != "span"):
                    attrs["rend"] = " ; ".join(
                        original.get(a) for a in ("class", "style") if original.get(a)
                    )
                actual_attrs = dict(target.attrib)
                if tag == "a" and "href" in original.attrib:
                    require("target" in actual_attrs, "source-link destination absent")
                    del actual_attrs["target"]
                require(actual_attrs == attrs, "readable attribute/attachment drift")
                pairs.append((original, target))
        # Resolve source relationships before consulting the candidate's fragments.
        # The independently checked tree pairing identifies each destination's TEI
        # node. No converter helper or member-prefix formula is used here.
        source_ids = {}
        for node in source_body.xpath(".//*[@id]"):
            require(
                node.get("id") not in source_ids, "ambiguous source-link destination"
            )
            source_ids[node.get("id")] = node
        candidate_ids = {}
        for node in target_member.iter():
            identifier = node.get("{" + XML + "}id")
            if identifier is not None:
                require(
                    identifier not in candidate_ids, "ambiguous source-link destination"
                )
                candidate_ids[identifier] = node
        source_uri = urljoin(
            "https://www.ccel.org/", source.findtext(".//DC.Identifier")
        )
        document = urlsplit(source_uri)
        for original, target in source_links:
            href = original.get("href")
            destination = urlsplit(urljoin(source_uri, href))
            if (destination.scheme, destination.netloc, destination.path) == (
                document.scheme,
                document.netloc,
                document.path,
            ) and destination.fragment:
                source_endpoint = source_ids.get(unquote(destination.fragment))
                require(
                    source_endpoint is not None,
                    "source-link destination absent in source",
                )
                mapped_endpoint = correspondence.get(source_endpoint)
                actual = target.get("target")
                require(
                    actual.partition("#")[0] == href.partition("#")[0],
                    "source-link context drift",
                )
                actual_endpoint = candidate_ids.get(unquote(urlsplit(actual).fragment))
                require(
                    mapped_endpoint is not None and actual_endpoint is mapped_endpoint,
                    "source-link destination drift",
                )
            else:
                require(target.get("target") == href, "source-link context drift")
    require(
        json.loads(members["provenance.json"])
        == {
            "work_id": WORK,
            "source_manifest_sha256": manifest.sha256,
            "member_order": ["matthew", "mark"],
        },
        "provenance drift",
    )
    require(
        members["README.source.md"] == manifest.authority_path("readme").read_bytes(),
        "source notice drift",
    )
    require(
        members["unresolved.jsonl"]
        == manifest.authority_path("unresolved").read_bytes(),
        "unresolved decisions drift",
    )
    require(schema.validate(tei), str(schema.error_log))


def validate(manifest, candidate):
    check(
        manifest,
        {
            n: candidate.member_bytes(n)
            for n in candidate.member_names
            if n != "manifest.json"
        },
    )
    records = sorted(
        (
            {k: a[k] for k in ("name", "path", "bytes", "sha256")}
            for a in manifest.record["authorities"]
            if a["role"] == "primary-source"
        ),
        key=lambda a: (a["path"], a["name"]),
    )
    facts = MechanicalFacts(
        digest(Path(__file__).read_bytes()),
        closure(manifest.repository_root),
        digest(canonical({"contract": "ocd-source-member-set-v1", "members": records})),
        digest(manifest.authority_path("profile").read_bytes()),
        digest(manifest.authority_path("package-schema").read_bytes()),
        digest(manifest.authority_path("tei-schema").read_bytes()),
        digest(manifest.authority_path("policy").read_bytes()),
        (),
    )
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


validate.oracle_id = "robertson-vol1-independent-oracle"
validate.oracle_version = "1"
