"""Independent Form page oracle including exact retained HTML comments."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "ocd-lib089-form-church-independent-comment-oracle"
ORACLE_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SUPPORTED_TAGS = frozenset(
    {
        "a",
        "b",
        "br",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "header",
        "i",
        "li",
        "ol",
        "p",
        "strong",
        "table",
        "tbody",
        "td",
        "tr",
    }
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _normalized_text(node: etree._Element) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _source_attributes(node: etree._Element) -> dict[str, str]:
    return {str(key): str(value) for key, value in sorted(node.attrib.items())}


def _expected_target(source: etree._Element) -> tuple[str, dict[str, str]]:
    tag = str(source.tag).lower()
    if tag not in _SUPPORTED_TAGS:
        raise ValueError(f"unsupported LIB-089 source element {tag!r}")
    if tag in {"div", "header", "table", "tbody", "tr", "td"}:
        return "div", {"type": f"html-{tag}"}
    if tag in {"h1", "h2", "h3"}:
        return "head", {"type": f"html-{tag}"}
    if tag == "p":
        return "p", {}
    if tag in {"em", "strong", "b"}:
        return "hi", {
            "rend": "italic" if tag == "em" else "bold",
            "ana": f"html-{tag}",
        }
    if tag == "i":
        if source.get("class") != "icon-plus-sign" or len(source) or (source.text or "").strip():
            raise ValueError("unsupported LIB-089 source icon")
        return "seg", {"type": "html-icon", "n": "icon-plus-sign"}
    if tag == "a":
        href = source.get("href")
        if href is not None:
            return "ref", {"target": href, "type": "html-a"}
        attributes = {"type": "html-a"}
        if source.get("name"):
            attributes["n"] = str(source.get("name"))
        return "seg", attributes
    if tag == "br":
        return "lb", {}
    if tag in {"ol", "ul"}:
        return "list", {"type": "ordered" if tag == "ol" else "unordered"}
    if tag == "li":
        return "item", {}
    raise AssertionError(tag)


def _target_attributes(node: etree._Element) -> dict[str, str]:
    return {
        etree.QName(key).localname: str(value)
        for key, value in sorted(node.attrib.items())
        if key != _XML_ID
    }


class _Verifier:
    def __init__(self, slug: str, document: etree._ElementTree, fragments=None) -> None:
        self.slug = slug
        self.document = document
        self.serial = 0
        self.comment_serial = 0
        self.events: list[dict[str, object]] = []
        self.fragments = fragments

    def compare(
        self,
        source: etree._Element,
        target: etree._Element,
        *,
        root_attributes: dict[str, str] | None = None,
    ) -> None:
        source_tag = str(source.tag).lower()
        if source_tag in {"p", "ol", "ul"} and source.getparent() is not None and str(source.getparent().tag).lower() in {"div", "header", "table", "tbody", "tr", "td"}:
            if (
                target.tag != f"{{{_TEI}}}div"
                or dict(target.attrib) != {"type": "source-block-content"}
                or target.text is not None
                or len(target) != 1
                or target[0].tail is not None
            ):
                raise ValueError("LIB-089 content wrapper drifted")
            target = target[0]
        if str(source.tag).lower() in {"h1", "h2", "h3"}:
            if (
                target.tag != f"{{{_TEI}}}div"
                or dict(target.attrib) != {"type": "source-heading"}
                or target.text is not None
                or len(target) != 1
                or target[0].tail is not None
            ):
                raise ValueError("LIB-089 heading wrapper drifted")
            target = target[0]
        self.serial += 1
        expected_id = f"{self.slug}-source-{self.serial:06d}"
        expected_tag, expected_attributes = (
            ("div", root_attributes)
            if root_attributes is not None
            else _expected_target(source)
        )
        href = source.get("href", "")
        if self.fragments is not None and source_tag == "a" and href.startswith("#") and len(href) > 1:
            if href[1:] not in self.fragments:
                raise ValueError("LIB-089 source fragment target missing")
            expected_attributes["target"] = "#" + self.fragments[href[1:]]
        if etree.QName(target).namespace != _TEI or etree.QName(target).localname != expected_tag:
            raise ValueError("LIB-089 TEI element mapping drifted")
        if target.get(_XML_ID) != expected_id or _target_attributes(target) != expected_attributes:
            raise ValueError("LIB-089 TEI element identity or attributes drifted")
        content_target = target
        if source_tag == "td":
            if (target.text is not None or len(target) != 1
                    or target[0].tag != f"{{{_TEI}}}p"
                    or dict(target[0].attrib) != {"rend": "source-inline-content"}
                    or target[0].tail is not None):
                raise ValueError("Form table-cell inline carrier drifted")
            content_target = target[0]
        if content_target.text != source.text or len(content_target) != len(source):
            raise ValueError("LIB-089 TEI direct text or child cardinality drifted")
        self.events.append(
            {
                "ordinal": len(self.events) + 1,
                "source_xpath": self.document.getpath(source),
                "source_tag": str(source.tag).lower(),
                "source_attributes": _source_attributes(source),
                "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
                "tail_sha256": _sha((source.tail or "").encode("utf-8")),
                "tei_xml_id": expected_id,
                "tei_tag": expected_tag,
                "tei_attributes": expected_attributes,
                "disposition": "represented",
            }
        )
        for source_child, target_child in zip(source, content_target):
            if isinstance(source_child, etree._Comment):
                self.comment_serial += 1
                comment_id = f"{self.slug}-comment-{self.comment_serial:03d}"
                if (target_child.tag != f"{{{_TEI}}}note"
                        or target_child.attrib != {_XML_ID: comment_id,
                                                   "type": "source-html-comment"}
                        or target_child.text != source_child.text or len(target_child)):
                    raise ValueError("Form TEI comment note text, type, or position drifted")
                self.events.append({
                    "ordinal": len(self.events) + 1,
                    "source_xpath": self.document.getpath(source_child),
                    "source_tag": "#comment",
                    "source_attributes": {},
                    "direct_text_sha256": _sha((source_child.text or "").encode("utf-8")),
                    "tail_sha256": _sha((source_child.tail or "").encode("utf-8")),
                    "tei_parent_xml_id": expected_id,
                    "tei_xml_id": comment_id,
                    "tei_tag": "note",
                    "tei_attributes": {"type": "source-html-comment"},
                    "tei_text_sha256": _sha((target_child.text or "").encode("utf-8")),
                    "disposition": "preserve-as-tei-note",
                })
            elif isinstance(source_child.tag, str):
                self.compare(source_child, target_child)
            else:
                raise ValueError("Form retained source processing instruction drifted")
            if target_child.tail != source_child.tail:
                raise ValueError("LIB-089 TEI source tail drifted")


def _check_comment_inventory(profile: dict[str, object], document: etree._ElementTree,
                             blocks: list[etree._Element]) -> None:
    policy = profile.get("comment_policy")
    if not isinstance(policy, dict) or policy.get("contract") != "ocd-lib089-html-comment-disposition-v1":
        raise ValueError("Form comment policy absent")
    selected = [node for block in blocks for node in block.iter() if isinstance(node, etree._Comment)]
    records = []
    for node in selected:
        parent = node.getparent()
        records.append(dict(
            source_xpath=document.getpath(node), source_text=node.text,
            source_text_sha256=_sha((node.text or "").encode("utf-8")),
            parent_xpath=document.getpath(parent), parent_tag=str(parent.tag).lower(),
            parent_direct_text=parent.text,
            parent_element_child_count=len([child for child in parent if isinstance(child.tag, str)]),
            comment_tail=node.tail,
            comment_tail_sha256=_sha((node.tail or "").encode("utf-8")),
            disposition="preserve-as-tei-note",
        ))
    if (len([node for node in document.iter() if isinstance(node, etree._Comment)]) != 24
            or policy.get("selected_comment_count") != 2
            or policy.get("outside_selected_comment_count") != 22
            or records != policy.get("selected_comments")):
        raise ValueError("Form source comment inventory drifted")


def _profile_and_blocks(
    source_manifest: SourceManifest,
) -> tuple[
    bytes,
    dict[str, object],
    bytes,
    etree._ElementTree,
    list[etree._Element],
    list[dict[str, object]],
]:
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = _strict_json(profile_bytes, "LIB-089 profile")
    if (
        profile.get("contract") != "ocd-lib089-westminster-html-profile-v1"
        or profile.get("ticket_id") != "LIB-089"
        or profile.get("work_id") != source_manifest.record.get("work_id")
        or profile.get("oracle_id") != ORACLE_ID
    ):
        raise ValueError("LIB-089 profile or oracle identity drifted")
    source = source_manifest.authority_path("retained-html").read_bytes()
    document = html.document_fromstring(source).getroottree()
    # Select page text columns by independent DOM traversal, lifting accordion
    # contents to their enclosing toggle so its source heading is included.
    selected: dict[str, etree._Element] = {}
    for node in document.iter("div"):
        if "wpb_text_column" not in node.get("class", "").split():
            continue
        carrier = node
        for ancestor in node.iterancestors("div"):
            if "toggle" in ancestor.get("class", "").split():
                carrier = ancestor
                break
        selected[document.getpath(carrier)] = carrier
    blocks = list(selected.values())
    census = profile.get("html_block_census")
    if not isinstance(census, list) or len(census) != len(blocks):
        raise ValueError("LIB-089 complete HTML block census drifted")
    observed: list[dict[str, object]] = []
    for index, (block, expected) in enumerate(zip(blocks, census), 1):
        if not isinstance(block, etree._Element) or not isinstance(expected, dict):
            raise ValueError("LIB-089 block census member is invalid")
        normalized = _normalized_text(block)
        row = {
            "index": index,
            "disposition": expected.get("disposition"),
            "subtree_sha256": _sha(
                etree.tostring(block, encoding="utf-8", with_tail=False)
            ),
            "normalized_text_sha256": _sha(normalized.encode("utf-8")),
            "word_count": len(normalized.split()),
            "element_count": sum(
                1 for node in block.iter() if isinstance(node.tag, str)
            ),
        }
        if row != expected:
            raise ValueError(f"LIB-089 source block {index} drifted")
        observed.append(row)
    return profile_bytes, profile, source, document, list(blocks), observed


def _verify_family_census(source_manifest: SourceManifest) -> bytes:
    content = source_manifest.authority_path("family-member-census").read_bytes()
    census = _strict_json(content, "LIB-089 family member census")
    members = census.get("members")
    if census.get("scope") == "current-retained-witnesses-20260911":
        expected_ids = {"directory-for-family-worship", "form-of-church-government", "solemn-league-and-covenant", "sum-of-saving-knowledge", "directory-for-publick-worship"}
        if (
            source_manifest.record["work_id"] != "directory-for-publick-worship"
            or census.get("contract") != "ocd-lib089-family-member-census-v1"
            or census.get("ticket_id") != "LIB-089"
            or census.get("member_count") != 5
            or census.get("candidate_member_count") != 5
            or census.get("blocked_member_count") != 0
            or not isinstance(members, list) or len(members) != 5
            or any(not isinstance(item, dict) for item in members)
            or {item.get("work_id") for item in members} != expected_ids
            or any(item.get("state") != "candidate" for item in members)
        ):
            raise ValueError("LIB-089 recovered family census scope drifted")
        authorities = {item["name"]: item for item in source_manifest.record["authorities"]}
        for member in members:
            name = "retained-html" if member["work_id"] == "directory-for-publick-worship" else "family-source-" + member["work_id"]
            authority = authorities.get(name)
            if authority is None or any(member.get(field) != authority.get(target) for field, target in (("source_path", "path"), ("sha256", "sha256"), ("bytes", "bytes"))):
                raise ValueError("LIB-089 recovered family member authority drifted")
            payload = source_manifest.authority_path(name).read_bytes()
            if len(payload) != member["bytes"] or _sha(payload) != member["sha256"]:
                raise ValueError("LIB-089 recovered family source bytes drifted")
        return content
    if (
        census.get("contract") != "ocd-lib089-family-member-census-v1"
        or census.get("ticket_id") != "LIB-089"
        or census.get("member_count") != 5
        or census.get("candidate_member_count") != 4
        or census.get("blocked_member_count") != 1
        or not isinstance(members, list)
        or len(members) != 5
        or len({item.get("work_id") for item in members if isinstance(item, dict)}) != 5
    ):
        raise ValueError("LIB-089 family member census is incomplete")
    blocked = [item for item in members if isinstance(item, dict) and item.get("state") == "blocked"]
    if len(blocked) != 1 or blocked[0].get("work_id") != "directory-for-publick-worship":
        raise ValueError("LIB-089 family blocked member drifted")
    return content


def _verify_blocker(source_manifest: SourceManifest) -> bytes:
    content = source_manifest.authority_path("publick-worship-blocker").read_bytes()
    blocker = _strict_json(content, "LIB-089 publick-worship blocker")
    if (
        blocker.get("contract") != "ocd-lib089-source-blocker-v1"
        or blocker.get("work_id") != "directory-for-publick-worship"
        or blocker.get("source_manifest") is not None
        or blocker.get("candidate") is not None
        or blocker.get("validation") is not None
        or blocker.get("acceptance_status") != "nonaccepted"
        or blocker.get("publication") is not False
        or blocker.get("network_acquisition_performed_for_lib089") is not False
    ):
        raise ValueError("LIB-089 publick-worship blocker drifted")
    if source_manifest.record["work_id"] == "directory-for-publick-worship":
        authorities = {item["name"]: item for item in source_manifest.record["authorities"]}
        if authorities["publick-worship-blocker"]["role"] != "historical-source-blocker":
            raise ValueError("LIB-089 recovered witness mislabels its historical blocker")
        receipt = _strict_json(source_manifest.authority_path("source-recovery-receipt").read_bytes(), "LIB-089 source recovery receipt")
        source_authority = authorities["retained-html"]
        if (
            receipt.get("status") != 200
            or receipt.get("requested_url") != "https://thewestminsterstandard.org/directory-for-the-publick-worship-of-god/"
            or receipt.get("final_url") != receipt.get("requested_url")
            or receipt.get("sha256") != source_authority["sha256"]
            or receipt.get("logical_path") != source_authority["path"]
            or receipt.get("bytes") != source_authority["bytes"]
            or receipt.get("sha256") == blocker["frozen_source_claim"]["sha256"]
        ):
            raise ValueError("LIB-089 recovered witness receipt binding drifted")
    return content


def _expected_unresolved(slug: str) -> tuple[dict[str, object], ...]:
    questions = (
        (
            "identity",
            "The retained provider page does not by itself settle the work, expression, or responsible-body identity.",
        ),
        (
            "edition-witness",
            "The relationship between this web transcription, its page-local wrapper material, and a named historical edition remains undecided.",
        ),
        (
            "rights",
            "Underlying historical public-domain status does not settle rights or requested attribution for this retained web transcription.",
        ),
        (
            "editorial",
            "Replacement characters, source spellings, page-local wrapper material, and excluded navigation controls require human editorial review; no wording was modernized.",
        ),
        (
            "acceptance",
            "The candidate has not received human textual acceptance.",
        ),
    )
    return tuple(
        {
            "id": f"{slug}-{kind}",
            "kind": kind,
            "status": "unresolved",
            "detail": detail,
            "owner": "project-maintainer",
        }
        for kind, detail in questions
    )


def _verify_header(root: etree._Element, profile: Mapping[str, object], source_sha: str) -> None:
    ns = {"t": _TEI}
    slug = str(profile["work_id"])
    if root.get(_XML_ID) != f"{slug}-lib089-candidate":
        raise ValueError("LIB-089 TEI root identity drifted")
    titles = root.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != profile["identity"]["title"]:  # type: ignore[index]
        raise ValueError("LIB-089 TEI title drifted")
    availability = root.xpath(
        "/t:TEI/t:teiHeader/t:fileDesc/t:publicationStmt/t:availability", namespaces=ns
    )
    if (
        len(availability) != 1
        or availability[0].get("status") != "restricted"
        or "publication is false" not in "".join(availability[0].itertext())
    ):
        raise ValueError("LIB-089 TEI publication boundary drifted")
    ids = root.xpath(
        "/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:idno[@type='sha256']",
        namespaces=ns,
    )
    if len(ids) != 1 or ids[0].text != source_sha:
        raise ValueError("LIB-089 TEI source digest drifted")
    summaries = root.xpath("/t:TEI/t:teiHeader/t:encodingDesc/t:p", namespaces=ns)
    if len(summaries) != 1 or summaries[0].text != profile["projection_policy"]["summary"]:  # type: ignore[index]
        raise ValueError("LIB-089 TEI projection declaration drifted")

    # Independently specify the complete header, including fields that do not
    # appear in the body accounting. Reject invented metadata as well as drift.
    def node(name, text=None, attrs=None, children=()):
        return (f"{{{_TEI}}}{name}", tuple(sorted((attrs or {}).items())), text, None, tuple(children))

    def observed(element):
        return (element.tag, tuple(sorted(element.attrib.items())), element.text,
                element.tail, tuple(observed(child) for child in element))

    identity = profile["identity"]
    expected = node("teiHeader", children=(
        node("fileDesc", children=(
            node("titleStmt", children=(node("title", identity["title"]),)),
            node("publicationStmt", children=(
                node("publisher", "Open Christian Data"),
                node("availability", attrs={"status": "restricted"}, children=(
                    node("p", "Nonaccepted candidate; publication is false and not authorized."),)),
            )),
            node("sourceDesc", children=(node("bibl", children=(
                node("title", identity["source_page_title"]),
                node("ptr", attrs={"target": identity["source_url"]}),
                node("idno", source_sha, {"type": "sha256"}),
            )),)),
        )),
        node("encodingDesc", children=(node("p", profile["projection_policy"]["summary"]),)),
        node("revisionDesc", attrs={"status": "candidate"}, children=(
            node("change", "Generated from the exact retained HTML as a nonaccepted LIB-089 candidate.",
                 {"when": str(profile.get("reconstruction_revision_date", "2026-08-31"))}),)),
    ))
    headers = root.findall(f"{{{_TEI}}}teiHeader")
    if len(headers) != 1 or observed(headers[0]) != expected:
        raise ValueError("LIB-089 complete header metadata drifted")


def _closure(repository_root: Path) -> str:
    paths = {
        Path(__file__).resolve(strict=True),
        (repository_root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        (repository_root / "ocd_kernel/reconstruction/verifier.py").resolve(strict=True),
        (repository_root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True),
    }
    records = [
        {
            "path": path.relative_to(repository_root).as_posix(),
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(paths, key=lambda item: item.relative_to(repository_root).as_posix())
    ]
    return _sha(_canonical(records))


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    slug = str(source_manifest.record.get("work_id"))
    if source_manifest.record.get("ticket_id") != "LIB-089":
        raise ValueError("LIB-089 ticket identity drifted")
    manifest_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_manifest")
        != {"path": manifest_path, "sha256": source_manifest.sha256}
        or candidate.manifest.get("converter")
        != dict(source_manifest.record["converter"])  # type: ignore[arg-type]
        or candidate.manifest.get("package_schema")
        != dict(source_manifest.record["package_schema"])  # type: ignore[arg-type]
    ):
        raise ValueError("LIB-089 candidate manifest binding drifted")

    profile_bytes, profile, source, document, blocks, observed_blocks = (
        _profile_and_blocks(source_manifest)
    )
    _check_comment_inventory(profile, document, blocks)
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    policy = _strict_json(policy_bytes, "LIB-089 independent validation policy")
    if (
        policy.get("contract") != "ocd-lib089-validation-policy-v1"
        or policy.get("work_id") != slug
        or policy.get("source_sha256") != _sha(source)
    ):
        raise ValueError("LIB-089 independent policy binding drifted")
    # The producer's disposition labels cannot authorize dropping textual
    # carriers. This route's declared policy preserves every populated block.
    for block, row in zip(blocks, observed_blocks):
        if not str(row["disposition"]).startswith("represented-") and _normalized_text(block):
            raise ValueError("LIB-089 excluded a populated source carrier")
    family_census = _verify_family_census(source_manifest)
    blocker = _verify_blocker(source_manifest)
    represented = [
        (block, row)
        for block, row in zip(blocks, observed_blocks)
        if str(row["disposition"]).startswith("represented-")
    ]
    try:
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-089 TEI is not well formed") from exc
    _verify_header(root, profile, _sha(source))
    source_headings = [
        _normalized_text(node) for node in document.xpath("//h1|//h2|//h3")
    ]
    if source_headings != policy.get("ordered_document_headings"):
        raise ValueError("LIB-089 complete document headings drifted")
    # Locate every heading across the entire HTML, independently of the block
    # selection. The provider page title is represented in the TEI header;
    # remaining headings must remain in the readable body, in source order.
    target_headings = [
        _normalized_text(node) for node in root.xpath(
            "/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title|/t:TEI/t:text/t:body//t:head",
            namespaces={"t": _TEI},
        )
    ]
    if target_headings != source_headings:
        raise ValueError("LIB-089 readable heading coverage or order drifted")
    bodies = root.xpath("/t:TEI/t:text/t:body", namespaces={"t": _TEI})
    if len(bodies) != 1 or len(bodies[0]) != len(represented):
        raise ValueError("LIB-089 represented source-block cardinality drifted")
    fragments = None
    if profile.get("local_fragment_policy") == "resolve-retained-targets":
        fragments = {}
        ordinal = 0
        for block, _ in represented:
            for source_node in block.iter():
                if not isinstance(source_node.tag, str):
                    continue
                ordinal += 1
                names = {source_node.get("id")}
                if source_node.tag == "a":
                    names.add(source_node.get("name"))
                for name in names - {None, ""}:
                    if name in fragments:
                        raise ValueError("LIB-089 source fragment identity is ambiguous")
                    fragments[name] = f"{slug}-source-{ordinal:06d}"
    verifier = _Verifier(slug, document, fragments)
    for (source_block, row), target_block in zip(represented, bodies[0]):
        verifier.compare(
            source_block,
            target_block,
            root_attributes={
                "n": str(row["index"]),
                "subtype": str(row["disposition"])[len("represented-") :],
                "type": "source-block",
            },
        )

    represented_text = [_normalized_text(block) for block, _ in represented]
    element_census = Counter(
        str(node.tag).lower()
        for block, _ in represented
        for node in block.iter()
        if isinstance(node.tag, str)
    )
    expected_accountability = {
        "contract": "ocd-lib089-westminster-source-accountability-v1",
        "ticket_id": "LIB-089",
        "work_id": slug,
        "source_id": source_manifest.record["source_id"],
        "source": {
            "path": source_manifest.record["retained_source_path"],
            "bytes": len(source),
            "sha256": _sha(source),
        },
        "family_member_census": {
            "path": source_manifest.authority_path("family-member-census")
            .relative_to(source_manifest.repository_root)
            .as_posix(),
            "sha256": _sha(family_census),
        },
        "publick_worship_blocker": {
            "path": source_manifest.authority_path("publick-worship-blocker")
            .relative_to(source_manifest.repository_root)
            .as_posix(),
            "sha256": _sha(blocker),
        },
        "html_block_census": observed_blocks,
        "represented_block_count": len(represented),
        "excluded_block_count": len(blocks) - len(represented),
        "represented_word_count": sum(len(value.split()) for value in represented_text),
        "represented_text_sha256": _sha("\n".join(represented_text).encode("utf-8")),
        "represented_element_census": dict(sorted(element_census.items())),
        "source_events": verifier.events,
        "omitted_textual_block_count": 0,
        "duplicate_source_event_count": 0,
        "legacy_json_authority": False,
        "projection_limit": profile["projection_limit"],
    }
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    if (
        _strict_json(accountability_bytes, "LIB-089 source accountability")
        != expected_accountability
        or accountability_bytes != _canonical(expected_accountability)
    ):
        raise ValueError("LIB-089 source accountability drifted")

    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    xsd = etree.XMLSchema(etree.parse(str(xsd_path)))
    if not xsd.validate(etree.ElementTree(root)):
        raise ValueError(f"LIB-089 direct TEI P5 validation failed: {xsd.error_log}")

    authorities = {
        str(item["name"]): {
            key: item[key] for key in ("path", "bytes", "sha256", "role")
        }
        for item in source_manifest.record["authorities"]  # type: ignore[union-attr]
    }
    expected_provenance = {
        "contract": "ocd-lib089-westminster-candidate-provenance-v1",
        "ticket_id": "LIB-089",
        "work_id": slug,
        "source_id": source_manifest.record["source_id"],
        "status": "nonaccepted",
        "publication": False,
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_authority": "exact retained HTML only; existing JSON is excluded",
        "identity": profile["identity"],
        "rights": profile["rights"],
        "authorities": authorities,
        "canonical_data_or_ir_written": False,
    }
    provenance_bytes = candidate.member_bytes("provenance.json")
    if (
        _strict_json(provenance_bytes, "LIB-089 provenance") != expected_provenance
        or provenance_bytes != _canonical(expected_provenance)
    ):
        raise ValueError("LIB-089 provenance or publication boundary drifted")

    unresolved_bytes = candidate.member_bytes("unresolved.jsonl")
    expected_unresolved = _expected_unresolved(slug)
    observed_unresolved = tuple(
        _strict_json(line + b"\n", "LIB-089 unresolved row")
        for line in unresolved_bytes.splitlines()
        if line.strip()
    )
    if observed_unresolved != expected_unresolved or unresolved_bytes != b"".join(
        _canonical(row) for row in expected_unresolved
    ):
        raise ValueError("LIB-089 unresolved decision ledger drifted")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path(
        "source-attribution-readme"
    ).read_bytes():
        raise ValueError("LIB-089 source README drifted")

    closure = _closure(source_manifest.repository_root)
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure,
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        source_sha256=_sha(source),
        xsd_sha256=_sha(xsd_path.read_bytes()),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
