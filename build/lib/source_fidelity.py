"""Compare source-derived claims with actual TEI, without generating expected TEI."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


class CandidateProjectionError(ValueError):
    """The candidate has readable content outside a declared projection."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def parse_tei(data: bytes):
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True,
                            load_dtd=False, remove_blank_text=False, collect_ids=False))
    if root.getroottree().docinfo.doctype:
        raise ValueError("candidate DTDs are unsupported")
    if any(isinstance(n, etree._Entity) for n in root.iter()):
        raise ValueError("candidate entity references are unsupported")
    return root


def tag_name(node):
    if isinstance(node, etree._Comment):
        return "#comment"
    if isinstance(node, etree._ProcessingInstruction):
        return "#pi:" + node.target
    return node.tag


@dataclass
class Carrier:
    key: str
    parent: str | None
    position: int
    tag: str
    attributes: dict[str, str]
    text: str = ""
    tail: str = ""
    location: str = ""


@dataclass
class Expectations:
    scope_id: str | None
    source_sha256: str
    profile: dict
    carriers: list[Carrier] = field(default_factory=list)
    coverage: dict[str, dict] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    claim_scopes: dict[str, str] = field(default_factory=dict)
    unsupported_claims: dict[str, str] = field(default_factory=dict)

    def account(self, location, target=None, *, disposition="checked", reason=""):
        item = self.coverage[location]
        item.update(disposition=disposition, reason=reason)
        if target is not None:
            item.setdefault("targets", []).append(target)


def candidate_carriers(data: bytes, scope_id: str | None, *,
                       identity_mode: str = "xml-id", projection: str | None = None):
    root = parse_tei(data)
    if root.tag != f"{{{TEI}}}TEI":
        raise ValueError("candidate must be a TEI document")
    bodies = root.xpath("/t:TEI/t:text/t:body", namespaces={"t": TEI})
    if len(bodies) != 1:
        raise ValueError("candidate must have exactly one readable body")
    if projection == "tei-ab-lines":
        if scope_id is not None:
            raise ValueError("line projection requires the whole readable body")
        body = bodies[0]
        nodes = body.xpath(".//t:ab", namespaces={"t": TEI})
        rows = []
        for position, node in enumerate(nodes, 1):
            if len(node):
                raise CandidateProjectionError(
                    f"plain-line projection cannot ignore nested content inside tei:ab at "
                    f"{root.getroottree().getpath(node)}")
            rows.append(Carrier(f"line-{position:06d}", "@scope", position, node.tag,
                                dict(node.attrib), node.text or "", "",
                                root.getroottree().getpath(node)))
        for node in body.iter():
            location = root.getroottree().getpath(node)
            if (isinstance(node.tag, str) and node.tag != f"{{{TEI}}}ab"
                    and node.text and node.text.strip()):
                raise CandidateProjectionError(f"readable text outside tei:ab at {location}/text")
            if node is not body and node.tail and node.tail.strip():
                raise CandidateProjectionError(f"readable text outside tei:ab at {location}/tail")
        return rows
    if projection is not None:
        raise ValueError(f"unsupported candidate projection: {projection}")
    if identity_mode not in {"xml-id", "structural-position"}:
        raise ValueError(f"unsupported candidate identity mode: {identity_mode}")
    if scope_id is None:
        selected = bodies
    else:
        selected = root.xpath("//*[@xml:id=$identity]", identity=scope_id)
    if len(selected) != 1:
        raise ValueError(f"candidate scope must resolve once, observed {len(selected)}")
    if selected[0] is not bodies[0] and bodies[0] not in selected[0].iterancestors():
        raise ValueError("candidate selection is outside the readable body")
    rows = []
    def visit(node, parent, position):
        identity = node.get(XML_ID) if identity_mode == "xml-id" and isinstance(node.tag, str) else None
        key = identity or (f"{parent}/child[{position}]" if parent else "@scope")
        attrs = dict(node.attrib) if isinstance(node.tag, str) else {}
        rows.append(Carrier(key, parent, position, tag_name(node), attrs,
                            node.text or "", node.tail or "", root.getroottree().getpath(node)))
        for i, child in enumerate(node, 1):
            visit(child, key, i)
    visit(selected[0], None, 0)
    return rows


def compare(expectations: Expectations, candidate: bytes, corroboration: dict) -> dict:
    """Check cardinality, ordering, ownership, role, attributes and mixed text."""
    findings = []
    def finding(rule, key, source="", candidate_location="", **details):
        findings.append(dict(rule=rule, key=key, source_location=source,
                             candidate_location=candidate_location, **details))
    candidate_ready = True
    try:
        actual = candidate_carriers(
            candidate, expectations.scope_id,
            identity_mode=expectations.profile.get("identity_mode", "xml-id"),
            projection=expectations.profile.get("candidate_projection"))
    except CandidateProjectionError as exc:
        candidate_ready = False
        actual = []
        finding("candidate-projection", "@scope", message=str(exc))
    except (ValueError, etree.XMLSyntaxError) as exc:
        candidate_ready = False
        actual = []
        finding("candidate-parse-or-scope", "@scope", message=str(exc))
    if corroboration.get("source_sha256") != expectations.source_sha256:
        finding("parser-source-binding", "@source", message="corroboration belongs to another source")
    candidate_exclusions = []
    excluded_attributes = expectations.profile.get("candidate_attribute_exclusions", {})
    expected_attrs = {n.key: n.attributes for n in expectations.carriers}
    if candidate_ready:
        for node in actual:
            for attr, reason in excluded_attributes.items():
                if attr in node.attributes:
                    if attr in expected_attrs.get(node.key, {}):
                        raise ValueError(f"candidate exclusion conflicts with source claim: {attr}")
                    candidate_exclusions.append(dict(location=node.location, attribute=attr,
                                                     value=node.attributes.pop(attr), reason=reason))
    expected = expectations.carriers
    ec, ac = Counter(n.key for n in expected), Counter(n.key for n in actual)
    if any(v != 1 for v in ec.values()):
        raise ValueError("source adapter emitted duplicate expected identities")
    if candidate_ready:
        index = {n.key: n for n in actual}
        for key, count in ac.items():
            if count > 1:
                finding("duplication", key, count=count)
        for node in expected:
            other = index.get(node.key)
            if other is None:
                finding("omission", node.key, node.location)
                continue
            for attr, rule in [("parent", "attachment"), ("position", "order"),
                               ("tag", "role"), ("attributes", "attributes"),
                               ("text", "text"), ("tail", "inline-tail")]:
                if getattr(node, attr) != getattr(other, attr):
                    finding(rule, node.key, node.location, other.location,
                            expected=getattr(node, attr), actual=getattr(other, attr))
        for node in actual:
            if node.key not in ec:
                finding("invention", node.key, candidate_location=node.location)
    failed = {f["key"] for f in findings}
    coverage = []
    for location, entry in expectations.coverage.items():
        item = dict(location=location, **entry)
        if item["disposition"] == "checked":
            item["result"] = ("unassessed" if not candidate_ready else
                              "failed" if failed.intersection(item.get("targets", [])) else "passed")
        else:
            item["result"] = item["disposition"]
        coverage.append(item)
    unsupported = [c for c in coverage if c["disposition"] == "unsupported"]
    counts = Counter(c["result"] for c in coverage)
    claims = {}
    for rule in ("omission", "duplication", "invention", "attachment", "order", "role",
                 "attributes", "text", "inline-tail"):
        claim_status = ("unassessed" if not candidate_ready else
                        "failed" if any(f["rule"] == rule for f in findings) else
                        "unsupported" if rule in expectations.unsupported_claims else "passed")
        claims[rule] = dict(status=claim_status,
                            scope=expectations.claim_scopes.get(rule, "selected readable subtree"),
                            expected_carriers=len(expected),
                            actual_carriers=len(actual) if candidate_ready else None)
        if rule in expectations.unsupported_claims:
            claims[rule]["limitation"] = expectations.unsupported_claims[rule]
    status = ("fail" if findings or corroboration["status"] == "fail" else
              "incomplete" if unsupported or expectations.unsupported_claims or
              corroboration["status"] != "pass" else "pass")
    return dict(status=status, claim_scope="explicit source selection and readable TEI subtree only",
                source_sha256=expectations.source_sha256, candidate_sha256=digest(candidate),
                profile_sha256=digest(canonical(expectations.profile)), findings=findings,
                claims=claims, parser_corroboration=corroboration,
                coverage=dict(total=len(coverage), counts=dict(counts), occurrences=coverage),
                candidate_attribute_exclusions=candidate_exclusions,
                limitations=expectations.limitations,
                acceptance="not-assessed", schema_validity="not-assessed")
