"""Encode explicitly retained letters/documents without changing source carriers."""
from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _tag(name):
    return f"{{{TEI}}}{name}"


def _append_lines(parent, carriers, first, last):
    for n in range(first, last + 1):
        leaf = carriers[n]
        parent.append(leaf)
        leaf.tail = "\n" if n < last else None


def _body(parent, carriers, lines, first, last):
    while first <= last:
        blank = not lines[first - 1].strip()
        end = first
        while end < last and bool(not lines[end].strip()) == blank:
            end += 1
        node = etree.SubElement(parent, _tag("ab") if blank else _tag("p"))
        if blank:
            node.set("type", "source-whitespace")
        _append_lines(node, carriers, first, end)
        first = end + 1


def _fields(parent, carriers, lines, first, last, fields):
    indexed = {row["first"]: row for row in fields if first <= row["first"] <= last}
    while first <= last:
        if first in indexed:
            row = indexed[first]
            end = row["last"]
            if end > last:
                raise ValueError("LIB-068 letter field crosses its source component")
            node = etree.SubElement(parent, _tag(row["tag"]))
            if row["tag"] == "address":
                node.set("type", "source-recipient")
                leaf_parent = etree.SubElement(node, _tag("addrLine"))
            else:
                leaf_parent = node
                if row["tag"] == "note":
                    node.set("type", "source-subscriptions")
        else:
            blank = not lines[first - 1].strip()
            end = first
            while end < last and end + 1 not in indexed and bool(not lines[end].strip()) == blank:
                end += 1
            node = etree.SubElement(parent, _tag("seg"))
            node.set("type", "source-letter-spacing" if blank else "source-letter-prose")
            leaf_parent = node
        _append_lines(leaf_parent, carriers, first, end)
        node.tail = "\n" if end < last else None
        first = end + 1


def apply_letters(scope, work_id, lines, profile):
    """Replace only the declared contiguous paragraph/whitespace intervals."""
    rows = profile.get("literary_letters")
    if not isinstance(rows, list):
        raise ValueError("LIB-068 source letter inventory absent")
    for row in rows:
        first, last = row["first"], row["last"]
        if lines[first - 1] != row["first_anchor"] or lines[last - 1] != row["last_anchor"]:
            raise ValueError("LIB-068 source letter anchor drift")
        selected = scope.xpath('.//t:seg[@type="source-line"]', namespaces={"t": TEI})
        carriers = {int(node.get("n")): node for node in selected if first <= int(node.get("n")) <= last}
        if sorted(carriers) != list(range(first, last + 1)):
            raise ValueError("LIB-068 source letter line coverage drift")
        first_block, last_block = carriers[first].getparent(), carriers[last].getparent()
        parent = first_block.getparent()
        if last_block.getparent() is not parent:
            raise ValueError("LIB-068 source letter crosses a declared section")
        begin, end = parent.index(first_block), parent.index(last_block)
        original = list(parent)[begin:end + 1]
        if any(node.tag not in {_tag("p"), _tag("ab")} for node in original):
            raise ValueError("LIB-068 letter interval overlaps another special structure")
        original_numbers = [int(leaf.get("n")) for node in original for leaf in node.iter(_tag("seg")) if leaf.get("type") == "source-line"]
        if original_numbers != list(range(first, last + 1)):
            raise ValueError("LIB-068 source letter boundary cuts a source block")
        letter = etree.Element(_tag("floatingText"), type=row["kind"], n=str(first))
        letter.set(XML_ID, f"{work_id}-document-{first}")
        letter_body = etree.SubElement(letter, _tag("body"))
        cursor = first
        if row["open_end"] is not None:
            opener = etree.SubElement(letter_body, _tag("opener"))
            _fields(opener, carriers, lines, cursor, row["open_end"], row["fields"])
            cursor = row["open_end"] + 1
        _body(letter_body, carriers, lines, cursor, row["close_first"] - 1)
        closer = etree.SubElement(letter_body, _tag("closer"))
        _fields(closer, carriers, lines, row["close_first"], last, row["fields"])
        for node in original:
            parent.remove(node)
        parent.insert(begin, letter)
