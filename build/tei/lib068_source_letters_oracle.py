"""Check actual letter relationships, then normalize a clone for baseline checks.

Source-located letter/field extents are shared declared authority reviewed
against the source. This module never imports or invokes the producer.
"""
from copy import deepcopy
import re
from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _tag(name):
    return f"{{{TEI}}}{name}"


def _leaves(node):
    return node.xpath('.//t:seg[@type="source-line"]', namespaces=NS)


def _numbers(node):
    return [int(leaf.get("n", "-1")) for leaf in _leaves(node)]


def _flat(node, expected, lines):
    if node.text or [int(child.get("n", "-1")) for child in node] != expected:
        raise ValueError("LIB-068 letter field carrier arrangement drift")
    for index, (leaf, number) in enumerate(zip(node, expected, strict=True)):
        if leaf.tag != _tag("seg") or dict(leaf.attrib) != {"type": "source-line", "n": str(number)} or "".join(leaf.itertext()) != lines[number - 1]:
            raise ValueError("LIB-068 letter field source content drift")
        if (leaf.tail or "") != ("\n" if index + 1 < len(expected) else ""):
            raise ValueError("LIB-068 letter field line separator drift")


def _component(node, first, last, fields, lines):
    if node.attrib or node.text or node.tail:
        raise ValueError("LIB-068 letter component attributes or text drift")
    tokens = {}
    for n in range(first, last + 1):
        matches = [(i, field) for i, field in enumerate(fields) if field["first"] <= n <= field["last"]]
        if len(matches) > 1:
            raise ValueError("LIB-068 overlapping source letter fields")
        if matches:
            i, field = matches[0]
            tokens[n] = (field["tag"], i)
        else:
            tokens[n] = ("spacing" if not lines[n - 1].strip() else "prose", -1)
    groups = []
    cursor = first
    while cursor <= last:
        end = cursor
        while end < last and tokens[end + 1] == tokens[cursor]:
            end += 1
        groups.append((cursor, end, tokens[cursor][0]))
        cursor = end + 1
    if len(node) != len(groups):
        raise ValueError("LIB-068 source letter field omission or attachment drift")
    for index, (child, (a, b, kind)) in enumerate(zip(node, groups, strict=True)):
        tag = "seg" if kind in {"spacing", "prose"} else kind
        attributes = {"type": "source-letter-spacing"} if kind == "spacing" else {"type": "source-letter-prose"} if kind == "prose" else {"type": "source-recipient"} if kind == "address" else {"type": "source-subscriptions"} if kind == "note" else {}
        if child.tag != _tag(tag) or dict(child.attrib) != attributes or (child.tail or "") != ("\n" if index + 1 < len(groups) else ""):
            raise ValueError("LIB-068 source letter field role drift")
        carrier_parent = child
        if kind == "address":
            if child.text or len(child) != 1 or child[0].tag != _tag("addrLine") or child[0].attrib or child[0].tail:
                raise ValueError("LIB-068 source recipient relationship drift")
            carrier_parent = child[0]
        _flat(carrier_parent, list(range(a, b + 1)), lines)


def verify_and_normalize_letters(scope, work_id, lines, profile):
    """Return checked source carriers in their original paragraph containers."""
    clone = deepcopy(scope)
    rows = profile.get("literary_letters")
    if not isinstance(rows, list) or len(rows) != {"newman-apologia-pro-vita-sua": 9, "donne-devotions-upon-emergent-occasions": 3}[work_id]:
        raise ValueError("LIB-068 declared source document census drift")
    letters = clone.xpath('.//t:floatingText[@type="source-letter" or @type="source-will-excerpt"]', namespaces=NS)
    if len(letters) != len(rows):
        raise ValueError("LIB-068 actual source document census drift")
    for row, letter in zip(rows, letters, strict=True):
        first, last = row["first"], row["last"]
        for field in row["fields"]:
            if field["tag"] == "salute":
                opening = lines[field["first"] - 1].lstrip(' "')
                if not re.match(r"(?:My [Dd]ear |Very Rev(?:erend|\.)|Sir,|_MOST EXCELLENT PRINCE_|We (?:are|remain),|I am,|Your(?:s)? |With sentiments |Accept,)", opening):
                    raise ValueError("LIB-068 declared salutation lacks a source closing or greeting formula")
        if lines[first - 1] != row["first_anchor"] or lines[last - 1] != row["last_anchor"] or not lines[first - 1].strip() or not lines[last - 1].strip():
            raise ValueError("LIB-068 declared source document anchor drift")
        if work_id.startswith("newman-") and not re.search(r'(?:January|February|March|April|May|June|July|August|September|Sept\.|October|November|December).*\b1864\.', lines[first - 1]):
            raise ValueError("LIB-068 source letter dateline not corroborated")
        if dict(letter.attrib) != {"type": row["kind"], "n": str(first), XML_ID: f"{work_id}-document-{first}"} or letter.text or letter.tail:
            raise ValueError("LIB-068 source document identity drift")
        if _numbers(letter) != list(range(first, last + 1)):
            raise ValueError("LIB-068 source document extent or order drift")
        if len(letter) != 1 or letter[0].tag != _tag("body") or letter[0].attrib or letter[0].text or letter[0].tail:
            raise ValueError("LIB-068 embedded source document body drift")
        children = list(letter[0])
        body_first = first
        if row["open_end"] is not None:
            if not children or children[0].tag != _tag("opener"):
                raise ValueError("LIB-068 source document opener absent")
            _component(children.pop(0), first, row["open_end"], row["fields"], lines)
            body_first = row["open_end"] + 1
        if not children or children[-1].tag != _tag("closer"):
            raise ValueError("LIB-068 source document closer absent")
        _component(children.pop(), row["close_first"], last, row["fields"], lines)
        cursor = body_first
        for block in children:
            if cursor >= row["close_first"]:
                raise ValueError("LIB-068 extra source document body block")
            blank = not lines[cursor - 1].strip()
            end = cursor
            while end + 1 < row["close_first"] and bool(not lines[end].strip()) == blank:
                end += 1
            if block.tag != _tag("ab" if blank else "p") or dict(block.attrib) != ({"type": "source-whitespace"} if blank else {}) or block.tail:
                raise ValueError("LIB-068 source document paragraph attachment drift")
            _flat(block, list(range(cursor, end + 1)), lines)
            cursor = end + 1
        if cursor != row["close_first"]:
            raise ValueError("LIB-068 source document body omission")
        carriers = {int(leaf.get("n")): leaf for leaf in _leaves(letter)}
        parent = letter.getparent()
        index = parent.index(letter)
        parent.remove(letter)
        cursor = first
        while cursor <= last:
            blank = not lines[cursor - 1].strip()
            end = cursor
            while end < last and bool(not lines[end].strip()) == blank:
                end += 1
            block = etree.Element(_tag("ab" if blank else "p"))
            if blank:
                block.set("type", "source-whitespace")
            for n in range(cursor, end + 1):
                block.append(carriers[n])
                carriers[n].tail = "\n" if n < end else None
            parent.insert(index, block)
            index += 1
            cursor = end + 1
    return clone
