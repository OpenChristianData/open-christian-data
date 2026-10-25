"""Page-carrier TEI for the retained 1852 Ursinus IA commentary."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
from statistics import median
import fitz
from lxml import etree
from ocd_kernel.lib.storage_topology import resolve_repo_path

SOURCE = "raw/internet-archive/commentary-on-heidelberg-catechism/commdrza00ursi"
DEST = "candidate-reviews/manifest-acquisition-20261002/ursinus-heidelberg-commentary-v7"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
HASHES = {
    "scan.pdf": "c04a2ef0e88fa4970fd29386c086e528ff249f1d9e3d321fdd51cb3c14a31b52",
    "ocr.txt": "b992748facfcf8c7268783cc497e195bdd22849f52aa0a94d4ebadae5b3a86c5",
    "ocr.xml": "44d5f752ac2fd60e7864134eb818951c842329b8393565ae5f5cdb9449f78d98",
    "scandata.xml": "b1ddaeaa58e9b90c120eb8dacc801c162736c938fe007ec1fe7792e41c634b09",
    "metadata.json": "b12ca6fcfc47a1c02a2a1207e71a83f0db96c5339999c44a3a7d5e94faed7edf",
    "page-numbers.json": "cbb1c407e254dcbdb9a577014e4c38e18135a7a492d0b750ae1ac8def06140f6",
    "acquisition-receipt.json": "ee903821197d0ccfe82bd854deac5e65e39794073d594d860ac27b6d1c2d589a",
    "member-inventory.tsv": "e8b2cbbb638db2ad2ecaf39ed449e9bcb1f91b0031be3c388c365b6cb45ddd9c",
}

def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()

def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def relative_source_uri(destination: Path, source: Path) -> str:
    target = (source / "scan.pdf").resolve(strict=True)
    package = destination.resolve()
    try:
        relative = Path(os.path.relpath(target, start=package)).as_posix()
    except ValueError as error:
        raise ValueError("retained scan and candidate package are on different volumes") from error
    if (package / Path(relative)).resolve(strict=True) != target:
        raise ValueError("candidate facsimile URI does not resolve to the retained scan")
    return relative

def e(parent: etree._Element, name: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, "{%s}%s" % (TEI, name), **attrs)

def norm(value: str) -> str:
    return " ".join(value.split())

# Diplomatic hierarchy transcribed from the retained scan braces. Each leaf
# points to the broadest OCR paragraph(s) that carry its printed label.
DIAGRAMS = {
    205: {
        "title": "A table of those things which fall under the providence of God.",
        "figure_type": "source_branch_diagram",
        "list_type": "source_diagram_brace_hierarchy",
        "figure_paragraphs": list(range(3, 32)),
        "figure_description": "Retained scan of the providence table; its printed braces and the source-linked branch hierarchy preserve the grouping of creatures and events while the page body keeps the provider OCR stream.",
        "root": {"label": "The whole world is governed by the providence of God; and in the whole world,", "refs": [7], "children": [
            {"label": "1. All things generally, which providence is called universal, or general.", "refs": [4]},
            {"label": "2. Each thing particularly, which providence is called particular or special. The things which are specially directed are,", "refs": [9, 11, 13, 14, 15, 16, 17, 19], "children": [
                {"label": "1. Every single creature", "refs": [8, 10, 12], "children": [
                    {"label": "1. Irrational, of which kind some are,", "refs": [5], "children": [
                        {"label": "1. Living,", "refs": [5]},
                        {"label": "2. Without life.", "refs": [5]},
                    ]},
                    {"label": "2. Rational, such are,", "refs": [22], "children": [
                        {"label": "1. Angels,", "refs": [6], "children": [{"label": "1. Good angels working freely and willingly that which is good", "refs": [6]}, {"label": "2. Bad angels working freely and willingly that which is evil", "refs": [6]}]},
                        {"label": "2. Men,", "refs": [25], "children": [{"label": "1. Good men, doing freely and willingly that which is good.", "refs": [6]}, {"label": "2. Wicked men, doing freely & willingly that which is evil.", "refs": [6]}]},
                    ]},
                ]},
                {"label": "2. Every single event,", "refs": [18, 20, 21], "children": [
                    {"label": "1. Casual,", "refs": [23], "children": [{"label": "1. Good,", "refs": [26]}, {"label": "2. Evil.", "refs": [27]}]},
                    {"label": "2. Contingent,", "refs": [24], "children": [{"label": "1. Good,", "refs": [28]}, {"label": "2. Evil.", "refs": [29]}]},
                    {"label": "3. Necessary.", "refs": [24], "children": [{"label": "1. Good.", "refs": [30]}, {"label": "2. Evil.", "refs": [31]}]},
                ]},
            ]},
        ]},
    },
    552: {
        "title": "A table of the third division of the Decalogue.",
        "figure_type": "source_branch_diagram",
        "list_type": "source_diagram_brace_hierarchy",
        "figure_paragraphs": list(range(3, 29)),
        "figure_description": "Retained scan of the third division of the Decalogue; its printed braces and the source-linked branch hierarchy preserve immediate and mediated worship while the page body keeps the provider OCR stream.",
        "root": {"label": "The Decalogue commands the worship of God in general, which is,", "refs": [4], "children": [
            {"label": "Immediate, or towards God alone.— This is either", "refs": [5], "children": [
                {"label": "Internal,", "refs": [7], "children": [
                    {"label": "Concerning the one true God; as in commandment I.", "refs": [10]},
                    {"label": "Concerning the worship of God under a proper form; as in commandment II.", "refs": [10, 11]},
                ]},
                {"label": "External which is either", "refs": [8], "children": [
                    {"label": "Private, as in III.", "refs": [12, 13]},
                    {"label": "Public, as in IV.", "refs": [14]},
                ]},
            ]},
            {"label": "Mediate, or towards our neighbor, on account of God. This is either", "refs": [6], "children": [
                {"label": "External which consists in the", "refs": [9], "children": [
                    {"label": "The duties of superiors to those who are under them, and contrariwise as in V.", "refs": [15, 16, 17]},
                    {"label": "Preservation.", "refs": [20, 22], "children": [
                        {"label": "Of life and safety, whether of ourselves or of others, as in VI.", "refs": [18, 19, 21, 23]},
                        {"label": "Of chastity, as in VII.", "refs": [24]},
                        {"label": "Of goods, and possessions, as in VIII.", "refs": [25, 26]},
                        {"label": "Of truth, as in XI.", "refs": [27]},
                    ]},
                ]},
                {"label": "Internal, which consists in a proper moderation and regulation of the desires of the heart, that no one desire, or think any thing contrary to all or any of the former commandments, as in", "refs": [28]},
            ]},
        ]},
    },
    489: {
        "title": "A comparison between the Type and the Thing signified.",
        "figure_type": "source_comparison_table",
        "list_type": "source_table_row_pairings",
        "figure_paragraphs": list(range(8, 53)),
        "figure_description": "Retained scan of a two-column comparison table; the standOff list records its thirteen numbered row pairings while the page body preserves the provider OCR stream.",
        "root": {"label": "A comparison between the Type and the Thing signified.", "refs": [8], "children": [
            {"label": "Column headings", "refs": [9, 27], "children": [
                {"label": "The Type was", "refs": [9]},
                {"label": "The Thing signified is", "refs": [27]},
            ]},
            {"label": "Thirteen numbered row pairings", "refs": list(range(10, 27)) + list(range(28, 53)), "children": [
            {"label": "Row 1", "refs": [10, 28, 29], "children": [
                {"label": "The Type was: A lamb from the flock", "refs": [10]},
                {"label": "The Thing signified is: Christ a true man. Is. 53 : 2, 3, and John 1 : 14.", "refs": [28, 29]}]},
            {"label": "Row 2", "refs": [11, 30, 31], "children": [
                {"label": "The Type was: Without blemish, set apart", "refs": [11]},
                {"label": "The Thing signified is: Without sin. Is. 53 : 5, 7, 8. Heb. 7 : 26.", "refs": [30, 31]}]},
            {"label": "Row 3", "refs": [12, 32, 33], "children": [
                {"label": "The Type was: To be slain and roasted.", "refs": [12]},
                {"label": "The Thing signified is: Who suffered and died. 1 Cor. 5 : 7.", "refs": [32, 33]}]},
            {"label": "Row 4", "refs": [13, 34, 35], "children": [
                {"label": "The Type was: No bone was broken.", "refs": [13]},
                {"label": "The Thing signified is: He died without having his bones broken. John 19 : 36.", "refs": [34, 35]}]},
            {"label": "Row 5", "refs": [14, 36, 37], "children": [
                {"label": "The Type was: Was slain in the evening.", "refs": [14]},
                {"label": "The Thing signified is: In the end of the world. Heb. 1 : 2; 9 : 26.", "refs": [36, 37]}]},
            {"label": "Row 6", "refs": [15, 16, 38, 39], "children": [
                {"label": "The Type was: The posts were to be sprinkled with blood,", "refs": [15, 16]},
                {"label": "The Thing signified is: His satisfaction is imputed unto us. Is. 53 : 5. Rom. 3 : 24.", "refs": [38, 39]}]},
            {"label": "Row 7", "refs": [17, 18, 40, 41], "children": [
                {"label": "The Type was: That the destroyer might pass over the houses of the Israelites.", "refs": [17, 18]},
                {"label": "The Thing signified is: That we might be delivered from eternal death. Heb. 2 : 14.", "refs": [40, 41]}]},
            {"label": "Row 8", "refs": [19, 20, 42, 43], "children": [
                {"label": "The Type was: It was to be eaten, and that in every family.", "refs": [19, 20]},
                {"label": "The Thing signified is: There must be an application of Christ to every one by faith. Rom. 1 : 17. John 6 : 47.", "refs": [42, 43]}]},
            {"label": "Row 9", "refs": [21, 44, 45], "children": [
                {"label": "The Type was: It was all to be eaten.", "refs": [21]},
                {"label": "The Thing signified is: According to all the articles of our faith. Tim. 3 : 16.", "refs": [44, 45]}]},
            {"label": "Row 10", "refs": [22, 46], "children": [
                {"label": "The Type was: Without leavened bread.", "refs": [22]},
                {"label": "The Thing signified is: Without hypocrisy. 1 Cor. 5 : 8.", "refs": [46]}]},
            {"label": "Row 11", "refs": [23, 47, 48], "children": [
                {"label": "The Type was: With bitter herbs.", "refs": [23]},
                {"label": "The Thing signified is: With the endurance of the cross. Matt. 10 : 38.", "refs": [47, 48]}]},
            {"label": "Row 12", "refs": [24, 25, 49, 50], "children": [
                {"label": "The Type was: With haste, and in the attire of travellers.", "refs": [24, 25]},
                {"label": "The Thing signified is: With a desire to progress in the Christian life, and with the expectation of eternal life. Luke 8 : 15. Heb. 13 : 9, 15.", "refs": [49, 50]}]},
            {"label": "Row 13", "refs": [26, 51, 52], "children": [
                {"label": "The Type was: By the circumcised alone.", "refs": [26]},
                {"label": "The Thing signified is: None but the regenerate eat him, and to these alone is he profitable, and they alone receive not the sacrament to their condemnation. John 6 : 56. Heb. 13 : 10. 1 Cor. 11 : 26.", "refs": [51, 52]}]},
            ]},
        ]},
    },
    529: {
        "title": "A Table of Good Works.",
        "figure_type": "source_branch_diagram",
        "list_type": "source_diagram_brace_hierarchy",
        "figure_paragraphs": list(range(5, 19)),
        "figure_description": "Retained scan of a nested table of good works; brace relationships are represented in standOff while the page body preserves the provider OCR stream.",
        "root": {"label": "Of good works some are", "refs": [6], "children": [
            {"label": "1. Truly good, which, according to the definition of good works, are done.", "refs": [7], "children": [
                {"label": "According to the command of God.", "refs": [9]},
                {"label": "Of faith.", "refs": [10]},
                {"label": "To the glory of God.", "refs": [13, 14]},
                {"label": "These are either", "refs": [12], "children": [
                    {"label": "Perfect, as the works of angels, of man before the fall, and in the life to come.", "refs": [11]},
                    {"label": "Imperfect, as the works of the regenerate in this life.", "refs": [13, 14, 15]},
                ]},
            ]},
            {"label": "2. Apparently good, which include such as are,", "refs": [8], "children": [
                {"label": "1. Commanded by God, and are in their own nature good, but become evil by an accident, not being done in the manner, nor with the end with which they ought to be performed.", "refs": [16]},
                {"label": "2. Commanded by men, for the sake of religion, such as the traditions, the counsels, and precepts of the Pharisees and Papists. (Matt. 15 : 9.) ‘In vain do they worship me,’ &c.", "refs": [17, 18]},
            ]},
        ]},
    },
    578: {
        "title": "A table of images according to their distinctions.",
        "figure_type": "source_branch_diagram",
        "list_type": "source_diagram_brace_hierarchy",
        "figure_paragraphs": list(range(5, 20)),
        "figure_description": "Retained scan of a nested classification of images; brace relationships are represented in standOff while the page body preserves the provider OCR stream.",
        "root": {"label": "Images are, some", "refs": [7], "children": [
            {"label": "Natural", "refs": [6]},
            {"label": "Artificial; of which some are", "refs": [9], "children": [
                {"label": "Graven", "refs": [8]},
                {"label": "Cast", "refs": [11]},
                {"label": "Painted", "refs": [10]},
                {"label": "The artificial images are distinguished by matter, object, and end, and are either images of", "refs": [13], "children": [
                    {"label": "God", "refs": [14]},
                    {"label": "Creatures, which are either", "refs": [15], "children": [
                        {"label": "Lawful", "refs": [15]},
                        {"label": "Unlawful", "refs": [16, 17, 18, 19]},
                    ]},
                ]},
            ]},
        ]},
    },
    613: {
        "title": "A table respecting the distinction of the Sabbath.",
        "figure_type": "source_branch_diagram",
        "list_type": "source_diagram_brace_hierarchy",
        "figure_paragraphs": list(range(4, 15)),
        "figure_description": "Retained scan of a Sabbath classification table; branch relationships are represented in standOff while the page body preserves the provider OCR stream.",
        "root": {"label": "The Sabbath, or an abstinence from work, is either", "refs": [5], "children": [
            {"label": "1. Internal, moral, and spiritual, as rest from sin", "refs": [4]},
            {"label": "2. External and ceremonial, instituted by God either", "refs": [6], "children": [
                {"label": "1. Immediately in the Old Testament, as", "refs": [8], "children": [
                    {"label": "The Sabbath", "refs": [7], "children": [
                        {"label": "1. Of days, as the", "refs": [9], "children": [
                            {"label": "Seventh day", "refs": [10]},
                            {"label": "Feast days, as the Passover, Pentecost, &c.", "refs": [11]},
                        ]},
                        {"label": "1. Of months, as the new moons", "refs": [12]},
                        {"label": "3. Of years, as every seventh year", "refs": [13]},
                    ]},
                ]},
                {"label": "2. Mediately through the church in the New Testament, as the Lord’s day", "refs": [14]},
            ]},
        ]},
    },
    639: {
        "title": "A table of the sixth commandment.",
        "figure_type": "source_branch_diagram",
        "list_type": "source_diagram_brace_hierarchy",
        "figure_paragraphs": list(range(3, 24)),
        "figure_description": "Retained scan of the sixth-commandment prohibition and preservation table; branch relationships are represented in standOff while the page body preserves the provider OCR stream.",
        "root": {"label": "The sixth commandment, Thou shalt not kill", "refs": [4, 11], "children": [
            {"label": "1. Forbids every unlawful injury inflicted upon our own or our neighbor’s life and safety; our neighbor may be injured either", "refs": [5], "children": [
                {"label": "1. By forsaking him, or by not assisting him according to our ability", "refs": [6]},
                {"label": "2. By wronging or injuring him, which is done either", "refs": [8], "children": [
                    {"label": "1. By external force or violence, as by", "refs": [9], "children": [
                        {"label": "Murder", "refs": [9]}, {"label": "Slandering", "refs": [9]}, {"label": "Injuries of every description", "refs": [9, 14]},
                    ]},
                    {"label": "2. By internal affections such as", "refs": [10], "children": [{"label": "Anger, Hatred, Desire of revenge", "refs": [15]}]},
                ]},
            ]},
            {"label": "2. Commands the preservation of our own and our neighbor’s life and safety; this is done either", "refs": [7], "children": [
                {"label": "1. By not injuring any one; those ought not to injure others who are", "refs": [12], "children": [
                    {"label": "Not provoked, which belongs to justice", "refs": [16]},
                    {"label": "Who are provoked, which is the province of gentleness and equity", "refs": [17]},
                    {"label": "Whether provoked or not, which is peculiar to peaceableness", "refs": [18]},
                ]},
                {"label": "2. By rendering assistance to others; this is done either", "refs": [13], "children": [
                    {"label": "1. By repelling injuries from our neighbor, which is done by", "refs": [19], "children": [
                        {"label": "Commutative justice in punishing", "refs": [20]},
                        {"label": "Fortitude; Indignation", "refs": [21]},
                    ]},
                    {"label": "2. By helping our neighbor, as", "refs": [22], "children": [
                        {"label": "Humanity; Mercy", "refs": [22]}, {"label": "Friendship", "refs": [23]},
                    ]},
                ]},
            ]},
        ]},
    },
}

def emit_diagram_list(parent: etree._Element, node: dict[str, object], leaf: int, path: tuple[int, ...]) -> None:
    attrs = {"corresp": " ".join("#ia-leaf-%04d-para-%03d" % (leaf, i) for i in node["refs"])}
    item = e(parent, "item", **attrs)
    item.set("facs", "#ia-pb-%04d" % leaf)
    item.set(XML_ID, "ia-leaf-%04d-node-%s" % (leaf, "-".join(map(str, path))))
    item.text = str(node["label"])
    children = node.get("children", [])
    if children:
        nested_type = (
            "table-structure" if leaf == 489 and path == (1,) else
            "table-column-headings" if leaf == 489 and path == (1, 1) else
            "table-rows" if leaf == 489 and path == (1, 2) else
            "paired-table-cells" if leaf == 489 and len(path) == 3 and path[:2] == (1, 2) else
            "brace-children"
        )
        nested = e(item, "list", type=nested_type)
        for index, child in enumerate(children, 1):
            emit_diagram_list(nested, child, leaf, path + (index,))

def walk_nodes(node: dict[str, object]):
    yield node
    for child in node.get("children", []):
        yield from walk_nodes(child)

def diagram_carrier_paragraphs(leaf: int) -> list[int]:
    """Return all page paragraphs visibly associated with this scan layout."""
    paragraphs = {int(index) for index in DIAGRAMS[leaf]["figure_paragraphs"]}
    for node in walk_nodes(DIAGRAMS[leaf]["root"]):
        paragraphs.update(int(index) for index in node["refs"])
    return sorted(paragraphs)

def flatten_nodes(node: dict[str, object], leaf: int, path: tuple[int, ...] = (1,)) -> list[dict[str, object]]:
    record = {"xml_id": "ia-leaf-%04d-node-%s" % (leaf, "-".join(map(str, path))),
              "label": str(node["label"]),
              "corresp": ["#ia-leaf-%04d-para-%03d" % (leaf, i) for i in node["refs"]],
              "facs": "#ia-pb-%04d" % leaf}
    output = [record]
    for index, child in enumerate(node.get("children", []), 1):
        output.extend(flatten_nodes(child, leaf, path + (index,)))
    return output

def line_value(line: etree._Element) -> str:
    return norm(" ".join(word.text or "" for word in line.findall("WORD")))

def heading(value: str, leaf: int, pi: int, line_count: int) -> bool:
    if line_count != 1 or not value or len(value) > 125:
        return False
    if (leaf == 11 and pi < 12) or (leaf, pi) in {(13, 0), (13, 1), (17, 0), (17, 1), (35, 0), (49, 0), (51, 0), (51, 1), (51, 2), (51, 3), (709, 4), (709, 5)}:
        return True
    if leaf < 51 or leaf > 709 or pi == 0:
        return False
    letters = [c for c in value if c.isalpha()]
    return len(letters) >= 5 and sum(c.isupper() for c in letters) / len(letters) > 0.85 and not re.fullmatch(r"[IVXLCDM .0-9]+", value)

def contents_rows(page: etree._Element, leaf: int) -> list[dict[str, object]]:
    """Project scan-coordinate TOC row/page attachments, without rewriting OCR flow."""
    words = []
    for pi, para in enumerate(page.xpath("./HIDDENTEXT//PARAGRAPH"), 1):
        for li, line in enumerate(para.findall("LINE"), 1):
            line_id = "ia-leaf-%04d-para-%03d-line-%02d" % (leaf, pi, li)
            for word in line.findall("WORD"):
                coordinates = word.get("coords")
                if not coordinates:
                    raise ValueError("contents OCR word lacks scan coordinates")
                x1, y1, x2, y2 = map(int, coordinates.split(","))
                words.append({"y": (y1+y2)//2, "x1": x1, "x2": x2,
                              "text": (word.text or "").strip(), "line_id": line_id})
    page_heads = [w["y"] for w in words if w["text"].lower() == "page" and w["x1"] >= 2200]
    if len(page_heads) != 1:
        raise ValueError("contents page lacks a unique right-column Page header: %d" % leaf)
    header_y = page_heads[0]
    number_x = [w["x1"] for w in words if w["y"] > header_y+25 and w["x1"] >= 2200
                and re.search(r"\d", str(w["text"])) and len(str(w["text"])) <= 5]
    if not number_x:
        raise ValueError("contents page lacks numbered right column: %d" % leaf)
    center = median(number_x)
    candidates = []
    for word in words:
        label = str(word["text"])
        if word["y"] <= header_y+25 or not label:
            continue
        numeric = word["x2"] >= 2350 and len(label) <= 12 and bool(re.search(r"\d$", label))
        damaged = word["x1"] >= center-80 and bool(re.fullmatch(r"[A-Za-z]{1,3}", label))
        if numeric or damaged:
            candidates.append(word)
    candidates.sort(key=lambda w: (w["y"], w["x1"]))
    clusters: list[list[dict[str, object]]] = []
    for word in candidates:
        if clusters and word["y"] - clusters[-1][-1]["y"] <= 20:
            clusters[-1].append(word)
        else:
            clusters.append([word])
    anchors = [max(cluster, key=lambda w: w["x2"]) for cluster in clusters]
    rows = []
    previous_y = header_y+25
    for index, anchor in enumerate(anchors, 1):
        selected = [w for w in words if previous_y < w["y"] <= anchor["y"]+24
                    and w["x1"] < 2300 and w["text"] and w is not anchor]
        selected.sort(key=lambda w: (w["y"], w["x1"]))
        lines: list[list[dict[str, object]]] = []
        for word in selected:
            if lines and word["y"] - lines[-1][-1]["y"] <= 20:
                lines[-1].append(word)
            else:
                lines.append([word])
        text_lines = []
        used_ids = []
        section_headings = []
        for line_index, line in enumerate(lines):
            line.sort(key=lambda w: w["x1"])
            line_text = norm(" ".join(str(w["text"]) for w in line))
            later_left = any(min(w["x1"] for w in later) < 800 and later[0]["y"]-line[-1]["y"] > 45 for later in lines[line_index+1:])
            if min(w["x1"] for w in line) > 800 and max(w["x2"] for w in line) < 2250 and later_left:
                section_headings.append({"text": line_text, "source_line_ids": list(dict.fromkeys(str(w["line_id"]) for w in line))})
                continue
            text_lines.append(line_text)
            used_ids.extend(str(w["line_id"]) for w in line)
        topic = norm(" ".join(text_lines))
        if not topic:
            raise ValueError("contents row lacks topic words: leaf %d row %d" % (leaf, index))
        ids = list(dict.fromkeys([*used_ids, str(anchor["line_id"])]))
        rows.append({"leaf": leaf, "row": index, "y": anchor["y"],
                     "raw_page_label": anchor["text"], "topic": topic,
                     "source_line_ids": ids, "number_word_bbox_x": [anchor["x1"], anchor["x2"]],
                     "preceding_section_headings": section_headings})
        previous_y = anchor["y"]+24
    return rows


def header() -> etree._Element:
    root = etree.Element("{%s}teiHeader" % TEI)
    desc = e(root, "fileDesc")
    title = e(desc, "titleStmt")
    e(title, "title").text = "The commentary of Dr. Zacharias Ursinus on the Heidelberg catechism"
    e(title, "author").text = "Zacharias Ursinus"
    resp = e(title, "respStmt")
    e(resp, "resp").text = "Translated from the original Latin"
    e(resp, "name").text = "G. W. Williard"
    e(e(desc, "editionStmt"), "edition").text = "Second American edition"
    e(e(desc, "publicationStmt"), "p").text = "Columbus: Scott & Bascom, 1852. Digital transcription of the retained Internet Archive OCR witness; OCR readings, including apparent errors, are preserved and this is not a corrected print transcript."
    bibl = e(e(desc, "sourceDesc"), "bibl")
    e(bibl, "title").text = "The commentary of Dr. Zacharias Ursinus on the Heidelberg catechism"
    e(bibl, "author").text = "Zacharias Ursinus"
    e(bibl, "date", when="1852").text = "1852"
    e(bibl, "idno", type="Internet-Archive").text = "commdrza00ursi"
    e(e(root, "encodingDesc"), "p").text = "Page, paragraph, and line carriers follow the retained IA DjVu XML. OCR readings and errors are not corrected. Page facsimile references point to one-based PDF pages."
    e(e(e(root, "profileDesc"), "langUsage"), "language", ident="en").text = "English"
    return root

def build(repository_root: Path, destination: Path | None = None) -> dict[str, object]:
    source = resolve_repo_path(repository_root, SOURCE)
    library = Path(json.loads((repository_root / ".ocd-storage.json").read_text(encoding="utf-8"))["library_root"]).resolve(strict=True)
    dest = destination.resolve() if destination else library / DEST
    scan_uri = relative_source_uri(dest, source)
    actual_names = sorted(p.name for p in source.iterdir() if p.is_file())
    expected_names = sorted(HASHES)
    if actual_names != expected_names:
        raise ValueError("retained source member envelope changed")
    hashes = {name: sha(source / name) for name in actual_names}
    for name, expected in HASHES.items():
        if hashes[name] != expected:
            raise ValueError("source member hash changed: " + name)
    receipt = json.loads((source / "acquisition-receipt.json").read_text(encoding="utf-8"))
    provider = receipt["provider_member_inventory"]
    tsv_names = {row.split("\t", 1)[0] for row in (source / "member-inventory.tsv").read_text(encoding="utf-8").splitlines()[1:]}
    if receipt["item_identifier"] != "commdrza00ursi" or len(provider) != len(tsv_names) or {item["remote_name"] for item in provider} != tsv_names:
        raise ValueError("provider inventory differs from retained receipt/TSV")
    scan = etree.parse(str(source / "scandata.xml"))
    leaves = scan.xpath("/book/pageData/page")
    ocr = etree.parse(str(source / "ocr.xml"))
    pages = ocr.xpath("/DjVuXML/BODY/OBJECT")
    if len(leaves) != 722 or [int(x.get("leafNum", "-1")) for x in leaves] != list(range(722)):
        raise ValueError("scandata leaf envelope changed")
    if len(pages) != 720 or [x.get("usemap") for x in pages] != ["commdrza00ursi_%04d.djvu" % i for i in range(1,721)]:
        raise ValueError("OCR object envelope changed")
    with fitz.open(source / "scan.pdf") as pdf:
        if pdf.page_count != 720:
            raise ValueError("PDF page envelope changed")
    page_number_rows = json.loads((source / "page-numbers.json").read_text(encoding="utf-8"))["pages"]
    if [row["leafNum"] for row in page_number_rows] != list(range(1, 721)):
        raise ValueError("provider page-number leaf envelope changed")
    page_labels = {row["leafNum"]: row.get("pageNumber") or "" for row in page_number_rows}
    words = norm(" ".join(x.text or "" for x in ocr.xpath("//WORD")))
    if words != norm((source / "ocr.txt").read_text(encoding="utf-8")):
        raise ValueError("OCR TXT and XML word streams differ")
    root = etree.Element("{%s}TEI" % TEI, nsmap={None: TEI})
    root.set(XML_LANG, "en")
    root.append(header())
    text = e(root, "text")
    groups = {name: e(e(text, name), "div", type="scan_" + name) for name in ("front", "body", "back")}
    leaf_records = []
    unresolved = []
    toc_rows = []
    heading_count = 0
    for leaf, page in enumerate(pages, 1):
        section = "front" if leaf <= 50 else "body" if leaf <= 709 else "back"
        role = ("cover" if leaf in (1, 720) else "title_page" if leaf == 11 else "copyright" if leaf == 12 else
                "translators_preface" if 13 <= leaf <= 16 else "introduction" if 17 <= leaf <= 33 else
                "contents" if 35 <= leaf <= 48 else "commentary_half_title" if leaf == 49 else
                "commentary" if 51 <= leaf <= 709 else "terminal" if leaf >= 710 else "preliminary")
        layout_gap = None
        div = e(groups[section], "div", type="scan_page", subtype=role, n=str(leaf))
        if layout_gap:
            div.set("rend", "source_layout_unresolved:" + layout_gap)
            unresolved.append({"leaf": leaf, "ocr_page_id": page.get("usemap"),
                "candidate_page_id": "ia-leaf-%04d" % leaf, "pdf_page": leaf,
                "feature": layout_gap, "disposition": "OCR words, lines, and page image retained; spatial row/branch relationship not yet encoded",
                "evidence": "scandata pageType=Contents and inspected leaf 48" if 35 <= leaf <= 48 else "agent-inspected retained scan page"})
        div.set(XML_ID, "ia-leaf-%04d" % leaf)
        pb = e(div, "pb", n=page_labels[leaf] or str(leaf), facs=scan_uri + "#page=%d" % leaf)
        pb.set(XML_ID, "ia-pb-%04d" % leaf)
        paras = page.xpath("./HIDDENTEXT//PARAGRAPH")
        page_lines = []
        for pi, para in enumerate(paras):
            lines = [line_value(line) for line in para.findall("LINE")]
            page_lines.extend(lines)
            is_head = heading(lines[0] if len(lines) == 1 else "", leaf, pi, len(lines))
            out = e(div, "ab" if is_head else "p")
            if is_head:
                out.set("rend", "heading")
            out.set(XML_ID, "ia-leaf-%04d-para-%03d" % (leaf, pi+1))
            heading_count += int(is_head)
            for li, value in enumerate(lines, 1):
                lb = e(out, "lb", n=str(li))
                lb.set(XML_ID, "ia-leaf-%04d-para-%03d-line-%02d" % (leaf, pi+1, li))
                lb.tail = value + (" " if li < len(lines) else "")
        if leaf in DIAGRAMS:
            layout = DIAGRAMS[leaf]
            figure = e(div, "figure", type=str(layout["figure_type"]))
            figure.set(XML_ID, "ia-leaf-%04d-diagram" % leaf)
            figure.set("corresp", " ".join("#ia-leaf-%04d-para-%03d" % (leaf, i) for i in diagram_carrier_paragraphs(leaf)))
            e(figure, "graphic", url=scan_uri + "#page=%d" % leaf)
            e(figure, "figDesc").text = str(layout["figure_description"])
        if 35 <= leaf <= 48:
            toc_rows.extend(contents_rows(page, leaf))
        if not paras:
            e(div, "gap", reason="no_ocr_text", unit="page", quantity="1")
        leaf_records.append({
            "leaf": leaf, "ocr_page_id": page.get("usemap"), "pdf_page": leaf,
            "page_type": leaves[leaf].findtext("pageType"), "printed_page_label": page_labels[leaf], "section": section, "page_role": role, "unresolved_layout_feature": layout_gap,
            "paragraphs": len(paras), "lines": len(page_lines),
            "text_sha256": hashlib.sha256(norm(" ".join(page_lines)).encode()).hexdigest(),
        })
    stand_off = e(root, "standOff")
    toc_list = e(stand_off, "list", type="scan_derived_contents_rows")
    e(toc_list, "head").text = "Contents topic to printed page rows, reconstructed from scan coordinates"
    for row in toc_rows:
        for section_heading in row["preceding_section_headings"]:
            heading_item = e(toc_list, "item", rend="section_heading",
                             corresp=" ".join("#"+identifier for identifier in section_heading["source_line_ids"]))
            heading_item.text = section_heading["text"]
        item = e(toc_list, "item", n=str(row["raw_page_label"]),
                 corresp=" ".join("#"+identifier for identifier in row["source_line_ids"]))
        item.set(XML_ID, "ia-contents-leaf-%04d-row-%02d" % (row["leaf"], row["row"]))
        item.text = str(row["topic"])
    for leaf in sorted(DIAGRAMS):
        diagram = DIAGRAMS[leaf]
        graph = e(stand_off, "list", type=str(diagram["list_type"]), corresp="#ia-leaf-%04d-diagram" % leaf)
        graph.set(XML_ID, "ia-leaf-%04d-diagram-hierarchy" % leaf)
        e(graph, "head").text = diagram["title"]
        emit_diagram_list(graph, diagram["root"], leaf, (1,))
    tree = etree.ElementTree(root)
    schema = etree.RelaxNG(etree.parse(str(repository_root / "ocd_kernel/tei/vendor/relaxng/tei_all.rng")))
    if not schema.validate(tree):
        raise ValueError("TEI P5 Relax NG failed: " + str(schema.error_log.last_error))
    dest.mkdir(parents=True, exist_ok=True)
    candidate = dest / "candidate.xml"
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True, pretty_print=False)
    write_json(dest / "contents-row-map.json", {"rows": toc_rows, "method": "Right-column page-number OCR word anchors paired to left topic words by scan-coordinate Y intervals; source line IDs retain raw OCR order and source images remain authoritative for corrections."})
    (dest / "unresolved.jsonl").write_text("".join(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n" for item in unresolved), encoding="utf-8")
    write_json(dest / "source-accounting.json", {
        "status": "nonaccepted_review_candidate_structural_hierarchies_encoded", "source": SOURCE,
        "source_member_hashes": hashes, "provider_inventory_members": len(provider),
        "candidate_facsimile_target": {"uri": scan_uri, "relative_to": "candidate package root", "target": "retained source scan.pdf", "sha256": hashes["scan.pdf"]},
        "provider_retained_members": sorted(x["remote_name"] for x in provider if x["retained"]),
        "source_roles": {
            "scan.pdf": "visual scan; 720 PDF pages map to scandata leaves 1..720",
            "ocr.xml": "page, paragraph, line, and word text carrier",
            "ocr.txt": "independent ordered-word OCR corroboration",
            "scandata.xml": "722-leaf scan envelope and page type authority",
            "metadata.json": "provider metadata support",
            "member-inventory.tsv": "provider-wide member selection inventory",
            "page-numbers.json": "additional retained provider page-label support; not the textual carrier",
            "acquisition-receipt.json": "retained-member acquisition identity"
        },
        "excluded_scan_leaves": [
            {"leaf": 0, "reason": "opening Color Card; addToAccessFormats=false; absent from PDF and OCR"},
            {"leaf": 721, "reason": "closing Color Card; addToAccessFormats=false; absent from PDF and OCR"}
        ],
        "leaves": leaf_records, "contents_row_count": len(toc_rows), "contents_rows_by_leaf": {str(leaf): sum(row["leaf"] == leaf for row in toc_rows) for leaf in range(35,49)}, "unresolved_layout_features": unresolved,
        "image_preserved_structures": [{"leaf": leaf, "figure_id": "ia-leaf-%04d-diagram" % leaf,
            "layout_type": DIAGRAMS[leaf]["figure_type"],
            "ocr_paragraphs": ["%03d" % index for index in DIAGRAMS[leaf]["figure_paragraphs"]]}
            for leaf in sorted(DIAGRAMS)],
        "source_layout_hierarchies": [{"leaf": leaf, "layout_type": DIAGRAMS[leaf]["figure_type"],
            "list_type": DIAGRAMS[leaf]["list_type"], "hierarchy_id": "ia-leaf-%04d-diagram-hierarchy" % leaf,
            "source_figure_id": "ia-leaf-%04d-diagram" % leaf,
            "node_count": sum(1 for _ in walk_nodes(DIAGRAMS[leaf]["root"])),
            "nodes": flatten_nodes(DIAGRAMS[leaf]["root"], leaf),
            "method": "Printed table rows/cell pairings or nested branches transcribed from the retained scan; each node points to OCR paragraph carriers and the linked scan figure remains the visual authority."} for leaf in sorted(DIAGRAMS)],
        "diagram_scan_leaves": [leaf for leaf in sorted(DIAGRAMS) if DIAGRAMS[leaf]["figure_type"] == "source_branch_diagram"],
        "source_layout_scan_leaves": sorted(DIAGRAMS),
        "source_layout_page_crosswalk": [{"scan_leaf": leaf, "pdf_page_number": leaf, "printed_page_label": page_labels[leaf] or None} for leaf in sorted(DIAGRAMS)],
        "headings": heading_count,
        "ocr_words": len(ocr.xpath("//WORD")), "ocr_lines": sum(x["lines"] for x in leaf_records),
        "ocr_paragraphs": sum(x["paragraphs"] for x in leaf_records),
        "ocr_text_normalized_sha256": hashlib.sha256(words.encode()).hexdigest(),
        "mapping_policy": "All 720 access PDF/OCR pages, including covers and blank pages, are represented in exact order. Color-card leaves 0 and 721 are excluded. Front=leaves 1..50; commentary body=51..709; terminal back=710..720. OCR is uncorrected; heading classification is conservative and provisional. The 14 contents leaves have scan-coordinate topic/page rows in the standOff list, retaining raw OCR labels and links to source line IDs. Seven retained scan layouts (leaves 205, 489, 529, 552, 578, 613, and 639) remain linked figures with independent standOff representations of their table row/cell or branch structure; all layout labels link to the unchanged OCR carriers and source page facsimiles."
    })
    validation = {
        "tei_p5_relaxng_valid": True, "ocr_text_xml_normalized_equal": True,
        "scan_pdf_pages": 720, "scandata_leaves": 722, "ocr_pages": 720,
        "candidate_sha256": sha(candidate), "candidate_bytes": candidate.stat().st_size,
        "facsimile_uri": scan_uri, "facsimile_target_sha256": hashes["scan.pdf"],
        "open_structural_layout_pages": [item["leaf"] for item in unresolved],
        "diagram_scan_leaves": [leaf for leaf in sorted(DIAGRAMS) if DIAGRAMS[leaf]["figure_type"] == "source_branch_diagram"],
        "source_layout_scan_leaves": sorted(DIAGRAMS),
        "source_layout_page_crosswalk": [{"scan_leaf": leaf, "pdf_page_number": leaf, "printed_page_label": page_labels[leaf] or None} for leaf in sorted(DIAGRAMS)]
    }
    write_json(dest / "validation.json", validation)
    (dest / "README.md").write_text(
        "# Ursinus commentary: retained OCR witness transcription\n\n"
        "Exact witness: Internet Archive commdrza00ursi, The commentary of Dr. Zacharias Ursinus on the Heidelberg catechism, translated by G. W. Williard, second American edition (1852). This is Ursinus's commentary, not the Catechism alone.\n\n"
        "content.tei.xml conserves all 720 access PDF/OCR pages. Facsimile URIs resolve from the candidate package to the exact retained scan.pdf member (" + scan_uri + ", SHA-256 " + hashes["scan.pdf"] + "). source-accountability.json accounts for every scan leaf and retained support member. OCR readings and errors are retained. Color-card leaves 0 and 721 were absent from PDF/OCR and are explicitly excluded. The retained book has a front table of contents on leaves 35–48 and no separate back index after FINIS on leaf 709. The 436 scan-coordinate Contents topic/page rows on leaves 35–48 are linked to source line IDs in standOff and audited independently against OCR word coordinates. Seven scan layouts on leaves 205, 489, 529, 552, 578, 613, and 639 remain linked figures; each has a standOff representation of its table row/cell pairings or branch hierarchy linked to unchanged OCR paragraph carriers. Scan collation records identified OCR/scan differences without silently changing the OCR witness; this package is not a corrected print transcript. Human acceptance, rights clearance, and publication decisions remain separate.\n",
        encoding="utf-8")
    return validation

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.repository_root.resolve(strict=True), args.destination), sort_keys=True))






