"""Preserve TCP A23804 while exposing its sole work text to native projection."""
from hashlib import sha256

from lxml import etree

SOURCE_SHA256 = "4ce798180f8b9ef8c9b9cd9200b50a9c324ab858c7aad07d1e7d22931ee2a5f1"
NS = "{http://www.tei-c.org/ns/1.0}"


def adapt_whole_duty_prayer(original: bytes) -> tuple[bytes, dict]:
    """Remove only the two empty unary shell wrappers, with an exact inverse."""
    if sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("TCP A23804 adapter source hash differs")
    root = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    outer = root.find(NS + "text")
    if outer is None or outer.attrib or [n.tag for n in outer] != [NS + "group"]:
        raise ValueError("TCP A23804 outer shell differs")
    group = outer[0]
    if group.attrib or [n.tag for n in group] != [NS + "text"]:
        raise ValueError("TCP A23804 group shell differs")
    inner = group[0]
    if [n.tag for n in inner] != [NS + name for name in ("front", "body", "back")]:
        raise ValueError("TCP A23804 work text differs")
    opening = b"\n   <text>\n      <group>\n         "
    closing = b"\n      </group>\n   </text>"
    start = original.index(b"</teiHeader>") + len(b"</teiHeader>")
    end = original.rindex(b"</text>")
    close_start = end - len(b"\n      </group>\n   ")
    if original[start:start + len(opening)] != opening or original[close_start:close_start + len(closing)] != closing:
        raise ValueError("TCP A23804 shell byte boundaries differ")
    prefix, work, suffix = original[:start], original[start + len(opening):close_start], original[close_start + len(closing):]
    adapted = prefix + b"\n   " + work + suffix
    if prefix + opening + work + closing + suffix != original:
        raise ValueError("TCP A23804 shell inverse differs")
    parsed = etree.fromstring(adapted, etree.XMLParser(resolve_entities=False, no_network=True))
    if etree.tostring(parsed.find(NS + "text"), method="c14n", with_tail=False) != etree.tostring(inner, method="c14n", with_tail=False):
        raise ValueError("TCP A23804 complete work subtree changed")
    return adapted, {
        "contract": "ocd-a23804-single-work-shell-adapter-v1",
        "source_sha256": SOURCE_SHA256,
        "adapted_sha256": sha256(adapted).hexdigest(),
        "exact_byte_inverse": "pass",
        "complete_work_subtree_c14n": "pass",
        "original_header_bytes": "unchanged",
        "disposition": "Two anonymous unary text/group wrappers and their indentation are accounted as electronic container shell; sole inner work text, language, front/body/back, all source content and attachments are unchanged.",
        "removed_opening_utf8": opening.decode("utf-8"),
        "removed_closing_utf8": closing.decode("utf-8"),
    }
