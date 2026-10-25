"""Independent source oracle and mutation checks for the 1852 Ursinus commentary."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from statistics import median
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import fitz

SOURCE = "raw/internet-archive/commentary-on-heidelberg-catechism/commdrza00ursi"
DEST = "candidate-reviews/manifest-acquisition-20261002/ursinus-heidelberg-commentary-v8"
T = "{http://www.tei-c.org/ns/1.0}"
XID = "{http://www.w3.org/XML/1998/namespace}id"
PIN = {
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
        for block in iter(lambda: stream.read(1024*1024), b""):
            value.update(block)
    return value.hexdigest()

def norm(text: str) -> str:
    return " ".join(text.split())

def _n(label: str, refs: tuple[int, ...], *children: dict, number: int | None = None) -> dict:
    node = {"label": label, "refs": refs, "children": list(children)}
    if number is not None:
        node["n"] = str(number)
    return node


# Independent scan transcriptions. Each record pins figure carriers, the
# page-level layout type, list semantics, title, and exact node-to-OCR links.
SOURCE_LAYOUTS = {
    205: {"figure_type": "source_branch_diagram", "list_type": "source_diagram_brace_hierarchy", "title_paragraph": 3,
        "paragraphs": tuple(range(3, 32)), "title": "A table of those things which fall under the providence of God.",
        "description": "Retained scan of the providence table; its printed braces and the source-linked branch hierarchy preserve the grouping of creatures and events while the page body keeps the provider OCR stream."},
    489: {"figure_type": "source_comparison_table", "list_type": "source_table_row_pairings", "title_paragraph": 8,
        "paragraphs": tuple(range(8, 53)), "title": "A comparison between the Type and the Thing signified.",
        "description": "Retained scan of a two-column comparison table; the standOff list records its thirteen numbered row pairings while the page body preserves the provider OCR stream."},
    529: {"figure_type": "source_branch_diagram", "list_type": "source_diagram_brace_hierarchy", "title_paragraph": 5,
        "paragraphs": tuple(range(5, 19)), "title": "A Table of Good Works.",
        "description": "Retained scan of a nested table of good works; brace relationships are represented in standOff while the page body preserves the provider OCR stream."},
    552: {"figure_type": "source_branch_diagram", "list_type": "source_diagram_brace_hierarchy", "title_paragraph": 3,
        "paragraphs": tuple(range(3, 29)), "title": "A table of the third division of the Decalogue.",
        "description": "Retained scan of the third division of the Decalogue; its printed braces and the source-linked branch hierarchy preserve immediate and mediated worship while the page body keeps the provider OCR stream."},
    578: {"figure_type": "source_branch_diagram", "list_type": "source_diagram_brace_hierarchy", "title_paragraph": 5,
        "paragraphs": tuple(range(5, 20)), "title": "A table of images according to their distinctions.",
        "description": "Retained scan of a nested classification of images; brace relationships are represented in standOff while the page body preserves the provider OCR stream."},
    613: {"figure_type": "source_branch_diagram", "list_type": "source_diagram_brace_hierarchy", "title_paragraph": 4,
        "paragraphs": tuple(range(4, 15)), "title": "A table respecting the distinction of the Sabbath.",
        "description": "Retained scan of a Sabbath classification table; branch relationships are represented in standOff while the page body preserves the provider OCR stream."},
    639: {"figure_type": "source_branch_diagram", "list_type": "source_diagram_brace_hierarchy", "title_paragraph": 3,
        "paragraphs": tuple(range(3, 24)), "title": "A table of the sixth commandment.",
        "description": "Retained scan of the sixth-commandment prohibition and preservation table; branch relationships are represented in standOff while the page body preserves the provider OCR stream."},
}

def expected_graph(leaf: int) -> dict:
    if leaf == 205:
        return _n("The whole world is governed by the providence of God; and in the whole world,", (7,),
            _n("1. All things generally, which providence is called universal, or general.", (4,)),
            _n("2. Each thing particularly, which providence is called particular or special. The things which are specially directed are,", (9,11,13,14,15,16,17,19),
                _n("1. Every single creature", (8,10,12),
                    _n("1. Irrational, of which kind some are,", (5,), _n("1. Living,", (5,)), _n("2. Without life.", (5,))),
                    _n("2. Rational, such are,", (22,),
                        _n("1. Angels,", (6,), _n("1. Good angels working freely and willingly that which is good", (6,)), _n("2. Bad angels working freely and willingly that which is evil", (6,))),
                        _n("2. Men,", (25,), _n("1. Good men, doing freely and willingly that which is good.", (6,)), _n("2. Wicked men, doing freely & willingly: that which is evil.", (6,))))),
                _n("2. Every single event,", (18,20,21),
                    _n("1. Casual,", (23,), _n("1. Good,", (26,)), _n("2. Evil.", (27,))),
                    _n("2. Contingent,", (24,), _n("1. Good,", (28,)), _n("2. Evil.", (29,))),
                    _n("3. Necessary.", (24,), _n("1. Good.", (30,)), _n("2. Evil.", (31,))))))
    if leaf == 489:
        rows = [
            ("1. A lamb from the flock", (10,), "1. Christ a true man. Is. 53 : 2, 3, and John 1 : 14.", (28,29)),
            ("2. Without blemish, set apart", (11,), "2. Without sin. Is. 53 : 5, 7, 8. Heb. 7 : 26.", (30,31)),
            ("3. To be slain and roasted.", (12,), "3. Who suffered and died. 1 Cor. 5 : 7.", (32,33)),
            ("4. No bone was broken.", (13,), "4. He died without having his bones broken. John 19 : 36.", (34,35)),
            ("5. Was slain in the evening.", (14,), "5. In the end of the world. Heb. 1 : 2; 9 : 26.", (36,37)),
            ("6. The posts were to be sprinkled with blood,", (15,16), "6. His satisfaction is imputed unto us. Is. 53 : 5. Rom. 3 : 24.", (38,39)),
            ("7. That the destroyer might pass over the houses of the Israelites.", (17,18), "7. That we might be delivered from eternal death. Heb. 2 : 14.", (40,41)),
            ("8. It was to be eaten, and that in every family.", (19,20), "8. There must be an application of Christ to every one by faith. Rom. 1 : 17. John 6 : 47.", (42,43)),
            ("9. It was all to be eaten.", (21,), "9. According to all the articles of our faith. Tim. 3 : 16.", (44,45)),
            ("10. Without leavened bread.", (22,), "10. Without hypocrisy. 1 Cor. 5 : 8.", (46,)),
            ("11. With bitter herbs.", (23,), "11. With the endurance of the cross. Matt. 10 : 38.", (47,48)),
            ("12. With haste, and in the attire of travellers.", (24,25), "12. With a desire to progress in the Christian life, and with the expectation of eternal life. Luke 8 : 15. Heb. 13 : 9, 15.", (49,50)),
            ("13. By the circumcised alone.", (26,), "13. None but the regenerate eat him, and to these alone is he profitable, and they alone receive not the sacrament to their condemnation. John 6 : 56. Heb. 13 : 10. 1 Cor. 11 : 26.", (51,52)),
        ]
        row_nodes = [
            _n("", left_refs + right_refs,
                _n(left, left_refs), _n(right, right_refs), number=index)
            for index, (left, left_refs, right, right_refs) in enumerate(rows, 1)
        ]
        column_headers = _n("", (9,27),
            _n("The Type was,", (9,)), _n("The Thing signified is,", (27,)))
        row_group = _n("", tuple(range(10,27)) + tuple(range(28,53)), *row_nodes)
        return _n("A comparison between the Type and the Thing signified.", (8,), column_headers, row_group)
    if leaf == 529:
        return _n("Of good works some are,", (6,),
            _n("1. Truly good, which, according to the definition of good works, are done.", (7,),
                _n("1. According to the command of God.", (9,)), _n("2. Of faith.", (10,)), _n("3. To the glory of God.", (13,14,)),
                _n("These are either", (12,), _n("Perfect, as the works of angels, of man before the fall, and in the life to come.", (11,)),
                    _n("Imperfect, as the works of the regenerate in this life.", (13,14,15,)))),
            _n("2. Apparently good, which include such as are,", (8,),
                _n("1. Commanded by God, and are in their own nature good, but become evil by an accident, not being done in the manner, nor with the end with which they ought to be performed.", (16,)),
                _n("2. Commanded by men, for the sake of religion, such as the traditions, the counsels, and precepts of the Pharisees and Papists. (Matt. 15 : 9.) “In vain do they worship me,” &c.", (17,18,))))
    if leaf == 552:
        return _n("The Decalogue commands the worship of God in general, which is,", (4,),
            _n("Immediate, or towards God alone.— This is either", (5,),
                _n("Internal,", (7,), _n("Concerning the one true God; as in commandment I.", (10,)), _n("Concerning the worship of God under a proper form; as in commandment II.", (10,11,))),
                _n("External which is either", (8,), _n("Private, as in III.", (12,13,)), _n("Public, as in IV.", (14,)))),
            _n("Mediate, or towards our neighbor, on account of God. This is either", (6,),
                _n("External which consists in the", (9,), _n("The duties of superiors to those who are under them, and contrariwise as in V.", (15,16,17,)),
                    _n("Preservation.", (20,22,), _n("Of life and safety, whether of ourselves or of others, as in VI.", (18,19,21,23,)), _n("Of chastity, as in VII.", (24,)), _n("Of goods, and possessions, as in VIII.", (25,26,)), _n("Of truth, as in XI.", (27,)))),
                _n("Internal, which consists in a proper moderation and regulation of the desires of the heart, that no one desire, or think any thing contrary to all or any of the former commandments, as in", (28,))))
    if leaf == 578:
        return _n("Images are, some", (7,), _n("Natural.", (6,)),
            _n("Artificial; of which some are", (9,12), _n("Graven;", (8,)), _n("Cast;", (11,)), _n("Painted;", (10,)),
                _n("These are distinguished by their matter, object and end, and are either images of", (13,),
                    _n("God, which are positively condemned in this commandment and throughout the whole Scriptures; and that because they detract from the divine majesty, and make an idol of God.", (14,)),
                    _n("Creatures, which are either", (15,),
                        _n("Lawful, which are not set up in churches, & which do not lead to idolatry—which are for civil purposes, or ornaments.", (15,)),
                        _n("Unlawful, such as are set up in churches, and lead to idolatry.", (16,17,18,19,))))))
    if leaf == 613:
        return _n("The Sabbath, or an abstinence from work, is either", (5,), _n("1. Internal, moral, and spiritual, as rest from sin.", (4,)),
            _n("2. External and ceremonial, instituted by God either", (6,),
                _n("1. Immediately in the Old Testament, as", (8,), _n("The Sabbath", (7,), _n("1. Of days, as the", (9,),
                    _n("Seventh day.", (10,)), _n("Feast days, as the Passover, Pentecost, &c.", (11,))),
                    _n("1. Of months, as the new moons.", (12,)), _n("3. Of years, as every seventh year.", (13,)))),
                _n("2. Mediately through the church in the New Testament, as the Lord’s day.", (14,))))
    if leaf == 639:
        return _n("The sixth commandment, Thou shalt not kill,", (4,11,),
            _n("1. Forbids every unlawful injury inflicted upon our own or our neighbor’s life & safety. Our neighbor may be injured either", (5,),
                _n("1. By forsaking him, or by not assisting him according to our ability, which includes a neglect of the duties which are required for the preservation of life.", (6,)),
                _n("2. By wronging or injuring him, which is done either", (8,),
                    _n("1. By external force, or violence, as by", (9,), _n("1. Murder.", (9,)), _n("2. Slandering.", (9,)), _n("3. Injuries of every description.", (9,14,))),
                    _n("2. By internal affections such as", (10,), _n("1. Anger.", (15,)),
                        _n("2. Hatred.", (15,)), _n("3. Desire of revenge.", (15,))))),
            _n("2. Commands the preservation of our own and of our neighbor’s life and safety. This is done either", (7,),
                _n("1. By not injuring any one. Those ought not to injure others, who are", (12,), _n("1. Not provoked, which belongs to justice.", (16,)),
                    _n("2. Who are provoked, which is the province of gentleness and equity.", (17,)), _n("3. Whether provoked or not, which is peculiar to peaceableness.", (18,))),
                _n("2. By rendering assistance to others. This is done either", (13,),
                    _n("1. By repelling injuries from our neighbor, which is done by", (19,), _n("1. Commutative justice in punishing.", (20,)), _n("2. Fortitude.", (21,)), _n("3. Indignation.", (21,))),
                    _n("2. By helping our neighbor, as", (22,), _n("1. By humanity.", (22,)), _n("2. By mercy.", (22,)), _n("3. By friendship.", (23,))))))
    raise ValueError("unexpected source-layout leaf")


def _flat_graph(root: dict, leaf: int, path: tuple[int, ...] = (1,)) -> list[dict]:
    record = {"xml_id": "ia-leaf-%04d-node-%s" % (leaf, "-".join(map(str, path))),
        "label": root["label"],
        "corresp": ["#ia-leaf-%04d-para-%03d" % (leaf, ref) for ref in root["refs"]],
        "facs": "#ia-pb-%04d" % leaf}
    if root.get("n") is not None:
        record["n"] = str(root["n"])
    output = [record]
    for index, child in enumerate(root["children"], 1):
        output.extend(_flat_graph(child, leaf, path + (index,)))
    return output


def check_graph(actual: ET.Element, expected: dict, leaf: int, source: dict) -> None:
    def read(node: ET.Element, wanted: dict, path: tuple[int, ...]) -> None:
        wanted_id = "ia-leaf-%04d-node-%s" % (leaf, "-".join(map(str, path)))
        if norm(node.text or "") != wanted["label"]:
            raise ValueError("source-layout node label differs at leaf %d path %s" % (leaf,path))
        if node.attrib.get(XID) != wanted_id:
            raise ValueError("source-layout node identity/path differs at leaf %d path %s" % (leaf,path))
        if node.attrib.get("n") != wanted.get("n"):
            raise ValueError("source-layout row number differs at leaf %d path %s" % (leaf,path))
        refs = node.attrib.get("corresp", "").split()
        expected_refs = ["#ia-leaf-%04d-para-%03d" % (leaf, ref) for ref in wanted["refs"]]
        if refs != expected_refs:
            raise ValueError("source-layout OCR paragraph links differ at leaf %d path %s" % (leaf,path))
        if node.attrib.get("facs") != "#ia-pb-%04d" % leaf:
            raise ValueError("source-layout scan link differs at leaf %d path %s" % (leaf,path))
        page = source["pages"][leaf-1]
        for ref in refs:
            match = re.fullmatch(r"#ia-leaf-%04d-para-(\d{3})" % leaf, ref)
            if not match or int(match.group(1)) > len(page["paragraph_lines"]):
                raise ValueError("source-layout OCR paragraph link is outside its page at leaf %d path %s" % (leaf,path))
            index = int(match.group(1))-1
            rect = page["paragraph_rects"][index]
            if not any(norm(line) for line in page["paragraph_lines"][index]) or not rect or rect[2] <= rect[0] or rect[3] <= rect[1]:
                raise ValueError("source-layout OCR paragraph lacks source text or coordinates at leaf %d path %s" % (leaf,path))
        nested = node.find("./"+T+"list")
        children = nested.findall("./"+T+"item") if nested is not None else []
        if len(children) != len(wanted["children"]):
            raise ValueError("source-layout child count differs at leaf %d path %s" % (leaf,path))
        if children:
            expected_type = (
                "table-structure" if leaf == 489 and path == (1,) else
                "table-column-headings" if leaf == 489 and path == (1,1) else
                "table-rows" if leaf == 489 and path == (1,2) else
                "paired-table-cells" if leaf == 489 and len(path) == 3 and path[:2] == (1,2) else
                "brace-children"
            )
            if nested.attrib.get("type") != expected_type:
                raise ValueError("source-layout nested list type differs at leaf %d path %s" % (leaf,path))
            for index, (child, expected_child) in enumerate(zip(children, wanted["children"]), 1):
                read(child, expected_child, path+(index,))
        elif nested is not None:
            raise ValueError("source-layout leaf node has an empty nested list at leaf %d path %s" % (leaf,path))

    read(actual, expected, (1,))

def home(root: Path) -> Path:
    config = json.loads((root / ".ocd-storage.json").read_text(encoding="utf-8"))
    return Path(config["library_root"]).resolve(strict=True)

def paths(root: Path, destination: Path | None = None) -> tuple[Path, Path]:
    library = home(root)
    return library / SOURCE, (destination.resolve() if destination else library / DEST)

def contents_anchors(page: ET.Element, leaf: int) -> list[dict]:
    """Read source right-margin labels and left-side OCR words from geometry."""
    words = []
    for pi, para in enumerate(page.findall("./HIDDENTEXT//PARAGRAPH"), 1):
        for li, line in enumerate(para.findall("./LINE"), 1):
            line_id = "ia-leaf-%04d-para-%03d-line-%02d" % (leaf, pi, li)
            for word in line.findall("./WORD"):
                x1, y1, x2, y2 = map(int, word.attrib["coords"].split(","))
                words.append((x1, (y1+y2)//2, x2, (word.text or "").strip(), line_id))
    headers = [w[1] for w in words if w[3].lower() == "page" and w[0] >= 2200]
    if len(headers) != 1:
        raise ValueError("contents right-column header differs at leaf %d" % leaf)
    first_y = headers[0]+25
    numbered_x = [w[0] for w in words if w[1] > first_y and w[0] >= 2200
                  and len(w[3]) <= 5 and re.search(r"\d", w[3])]
    if not numbered_x:
        raise ValueError("contents number region missing at leaf %d" % leaf)
    center = median(numbered_x)
    right = sorted((w for w in words if w[1] > first_y and
                   ((w[2] >= 2350 and len(w[3]) <= 12 and re.search(r"\d$",w[3])) or
                    (w[0] >= center-80 and re.fullmatch(r"[A-Za-z]{1,3}",w[3])))),
                   key=lambda w:(w[1],w[0]))
    groups = []
    for word in right:
        if groups and word[1]-groups[-1][-1][1] <= 20:
            groups[-1].append(word)
        else:
            groups.append([word])
    anchors = [max(group,key=lambda w:w[2]) for group in groups]
    result = []
    previous_y = first_y
    for ordinal, anchor in enumerate(anchors,1):
        left = [w for w in words if previous_y < w[1] <= anchor[1]+24 and w[0] < 2300
                and w[3] and w is not anchor]
        result.append({"leaf":leaf,"row":ordinal,"y":anchor[1],
                       "raw_page_label":anchor[3],"number_line_id":anchor[4],
                       "left_words":dict(Counter(token for w in left for token in w[3].split())),
                       "left_line_words":{line_id:dict(Counter(token for w in left if w[4] == line_id for token in w[3].split()))
                                          for line_id in dict.fromkeys(w[4] for w in left)}})
        previous_y = anchor[1]+24
    return result

def source_oracle(root: Path) -> dict:
    source, _ = paths(root)
    for name, expected in PIN.items():
        if sha(source/name) != expected:
            raise ValueError("source identity mismatch: " + name)
    names = sorted(p.name for p in source.iterdir() if p.is_file())
    if names != sorted(PIN):
        raise ValueError("source member envelope mismatch")
    receipt = json.loads((source/"acquisition-receipt.json").read_text(encoding="utf-8"))
    inventory = (source/"member-inventory.tsv").read_text(encoding="utf-8").splitlines()[1:]
    if receipt["item_identifier"] != "commdrza00ursi" or {line.split("\t",1)[0] for line in inventory} != {item["remote_name"] for item in receipt["provider_member_inventory"]}:
        raise ValueError("provider member inventory mismatch")
    leaves = ET.parse(source/"scandata.xml").getroot().findall("./pageData/page")
    if len(leaves) != 722 or [int(p.attrib["leafNum"]) for p in leaves] != list(range(722)):
        raise ValueError("scandata envelope mismatch")
    if [(leaves[i].findtext("pageType"), leaves[i].findtext("addToAccessFormats")) for i in (0,721)] != [("Color Card","false"), ("Color Card","false")]:
        raise ValueError("excluded calibration-card identity mismatch")
    numbers = json.loads((source/"page-numbers.json").read_text(encoding="utf-8"))["pages"]
    if [p["leafNum"] for p in numbers] != list(range(1,721)):
        raise ValueError("page-number sidecar envelope mismatch")
    with fitz.open(source/"scan.pdf") as pdf:
        if pdf.page_count != 720:
            raise ValueError("PDF envelope mismatch")
        pdf_anchors = {}
        for leaf in (11,13,35,49,51,205,552,709):
            pdf_anchors[str(leaf)] = norm(pdf[leaf-1].get_text())[:200]
    pages = ET.parse(source/"ocr.xml").getroot().findall("./BODY/OBJECT")
    if len(pages) != 720:
        raise ValueError("OCR page count mismatch")
    records = []
    contents = []
    ordered_words = []
    for leaf, page in enumerate(pages,1):
        source_id = page.attrib.get("usemap")
        if source_id != "commdrza00ursi_%04d.djvu" % leaf:
            raise ValueError("OCR source page ID/order mismatch")
        paragraphs = []
        paragraph_rects = []
        for paragraph in page.findall("./HIDDENTEXT//PARAGRAPH"):
            lines = []
            boxes = []
            for line in paragraph.findall("./LINE"):
                words = [word.text or "" for word in line.findall("./WORD")]
                ordered_words.extend(words)
                lines.append(norm(" ".join(words)))
                for word in line.findall("./WORD"):
                    coords = word.attrib.get("coords")
                    if coords:
                        boxes.append(tuple(map(int, coords.split(","))))
            paragraphs.append(lines)
            if boxes:
                paragraph_rects.append([min(min(box[0],box[2]) for box in boxes), min(min(box[1],box[3]) for box in boxes), max(max(box[0],box[2]) for box in boxes), max(max(box[1],box[3]) for box in boxes)])
            else:
                paragraph_rects.append(None)
        if 35 <= leaf <= 48:
            contents.extend(contents_anchors(page, leaf))
        layout_feature = None
        records.append({
            "leaf": leaf, "source_page_id": source_id,
            "section": "front" if leaf <= 50 else "body" if leaf <= 709 else "back",
            "page_type": leaves[leaf].findtext("pageType"),
            "printed_page_label": numbers[leaf-1].get("pageNumber") or "",
            "paragraph_lines": paragraphs, "paragraph_rects": paragraph_rects, "layout_feature": layout_feature,
        })
    text = norm((source/"ocr.txt").read_text(encoding="utf-8"))
    if norm(" ".join(ordered_words)) != text:
        raise ValueError("OCR XML and TXT wording/order differs")
    return {
        "source": SOURCE, "source_hashes": {name: sha(source/name) for name in names},
        "method": "Source-only expectations from stdlib XML traversal, independently of the converter or its accounting. Shared dependency: both routes parse retained OCR XML; the independently retained OCR TXT agrees in full normalized word order. PDF anchor extraction corroborates scan mapping but is not whole-page visual proofreading.",
        "prior_exposure": "The converter's page-count findings were known before this oracle was written; no blind-discovery claim.",
        "scan_leaves": 722, "access_pdf_pages": 720, "ocr_objects": 720,
        "excluded_leaves": [
            {"leaf": 0, "page_type": "Color Card", "access": False},
            {"leaf": 721, "page_type": "Color Card", "access": False}
        ],
        "pdf_text_anchors": pdf_anchors,
        "ocr_text_normalized_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "pages": records, "contents_anchors": contents,
    }

def verify_candidate_uris(top: ET.Element, destination: Path, source: Path, verified_scan_hash: str | None = None) -> dict:
    ids = {node.attrib[XID] for node in top.iter() if XID in node.attrib}
    parents = {child: parent for parent in top.iter() for child in parent}
    scan = (source / "scan.pdf").resolve(strict=True)
    scan_hash = verified_scan_hash if verified_scan_hash is not None else sha(scan)
    if scan_hash != PIN["scan.pdf"]:
        raise ValueError("retained facsimile target hash differs")
    checked_internal = 0
    checked_facsimiles = 0
    link_attributes = ("target", "corresp", "next", "prev", "sameAs", "copyOf", "synch", "facs", "spanTo", "url")
    for node in top.iter():
        for attribute in link_attributes:
            value = node.attrib.get(attribute)
            if not value:
                continue
            for reference in value.split():
                parsed = urlsplit(reference)
                if parsed.scheme or parsed.netloc or parsed.query:
                    raise ValueError("unsupported or nonlocal candidate URI")
                if not parsed.path:
                    identifier = unquote(parsed.fragment)
                    if not identifier:
                        raise ValueError("internal candidate URI is malformed")
                    if identifier not in ids:
                        raise ValueError("internal candidate URI target is absent")
                    checked_internal += 1
                    continue
                if attribute not in {"facs", "url"}:
                    raise ValueError("unexpected external candidate URI attribute")
                if Path(unquote(parsed.path)).is_absolute():
                    raise ValueError("candidate URI target must be package-relative")
                try:
                    target = (destination / Path(unquote(parsed.path))).resolve(strict=True)
                except OSError as error:
                    raise ValueError("candidate facsimile URI target does not resolve") from error
                if target != scan:
                    raise ValueError("candidate facsimile URI target does not resolve to retained scan.pdf")
                match = re.fullmatch(r"page=([1-9][0-9]*)", unquote(parsed.fragment))
                ancestor = parents.get(node)
                while ancestor is not None and not (ancestor.tag == T + "div" and ancestor.attrib.get("type") == "scan_page"):
                    ancestor = parents.get(ancestor)
                if match is None or ancestor is None or int(match.group(1)) != int(ancestor.attrib["n"]):
                    raise ValueError("facsimile URI page fragment differs from its TEI page")
                checked_facsimiles += 1
    return {"internal_references_resolved": checked_internal, "facsimile_references_resolved": checked_facsimiles, "facsimile_target_sha256": scan_hash}

def verify_tree(tree: ET.ElementTree, oracle: dict, destination: Path, source: Path, verified_scan_hash: str | None = None) -> dict:
    top = tree.getroot()
    uri_report = verify_candidate_uris(top, destination, source, verified_scan_hash)
    groups = {}
    all_pages = []
    for section in ("front","body","back"):
        group = top.find("./"+T+"text/"+T+section+"/"+T+"div")
        if group is None:
            raise ValueError("section missing: "+section)
        pages = group.findall("./"+T+"div")
        groups[section] = pages
        all_pages.extend(pages)
    if len(all_pages) != 720:
        raise ValueError("page count differs")
    line_count = 0
    para_count = 0
    empty_count = 0
    for expected, actual in zip(oracle["pages"], all_pages):
        leaf = expected["leaf"]
        if actual.attrib.get(XID) != "ia-leaf-%04d" % leaf or actual.attrib.get("n") != str(leaf):
            raise ValueError("page order/source ID differs at leaf %d" % leaf)
        role = ("cover" if leaf in (1,720) else "title_page" if leaf == 11 else "copyright" if leaf == 12 else
                "translators_preface" if 13 <= leaf <= 16 else "introduction" if 17 <= leaf <= 33 else
                "contents" if 35 <= leaf <= 48 else "commentary_half_title" if leaf == 49 else
                "commentary" if 51 <= leaf <= 709 else "terminal" if leaf >= 710 else "preliminary")
        if actual.attrib.get("subtype") != role:
            raise ValueError("page role differs at leaf %d" % leaf)
        feature = expected["layout_feature"]
        if actual.attrib.get("rend") != ("source_layout_unresolved:" + feature if feature else None):
            raise ValueError("layout disposition differs at leaf %d" % leaf)
        if actual not in groups[expected["section"]]:
            raise ValueError("section attachment differs at leaf %d" % leaf)
        pb = actual.find("./"+T+"pb")
        if pb is None or pb.attrib.get(XID) != "ia-pb-%04d" % leaf:
            raise ValueError("facsimile/page anchor differs at leaf %d" % leaf)
        if pb.attrib.get("n") != (expected["printed_page_label"] or str(leaf)):
            raise ValueError("page label differs at leaf %d" % leaf)
        if leaf in SOURCE_LAYOUTS:
            figures = actual.findall("./"+T+"figure")
            if len(figures) != 1 or figures[0].attrib.get(XID) != "ia-leaf-%04d-diagram" % leaf:
                raise ValueError("source-layout figure differs at leaf %d" % leaf)
            graphic = figures[0].find("./"+T+"graphic")
            description = figures[0].find("./"+T+"figDesc")
            layout = SOURCE_LAYOUTS[leaf]
            if (figures[0].attrib.get("type") != layout["figure_type"] or graphic is None
                    or graphic.attrib.get("url") is None or description is None
                    or norm(description.text or "") != layout["description"]):
                raise ValueError("source-layout figure type, facsimile, or description differs at leaf %d" % leaf)
            expected_refs = " ".join(
                "#ia-leaf-%04d-para-%03d" % (leaf, paragraph)
                for paragraph in layout["paragraphs"]
            )
            if figures[0].attrib.get("corresp") != expected_refs:
                raise ValueError("source-layout figure carrier links differ at leaf %d" % leaf)
        elif actual.findall("./"+T+"figure"):
            raise ValueError("unexpected source-layout figure at leaf %d" % leaf)
        paragraphs = [child for child in actual if child.tag in {T+"p", T+"ab"}]
        if len(paragraphs) != len(expected["paragraph_lines"]):
            raise ValueError("paragraph count differs at leaf %d" % leaf)
        if not paragraphs:
            gaps = actual.findall("./"+T+"gap")
            if len(gaps) != 1 or gaps[0].attrib.get("reason") != "no_ocr_text":
                raise ValueError("blank-page disposition differs at leaf %d" % leaf)
            empty_count += 1
        elif actual.find("./"+T+"gap") is not None:
            raise ValueError("unexpected gap at leaf %d" % leaf)
        for pi, (expected_lines, para) in enumerate(zip(expected["paragraph_lines"], paragraphs),1):
            if para.attrib.get(XID) != "ia-leaf-%04d-para-%03d" % (leaf,pi):
                raise ValueError("paragraph source ID differs at leaf %d" % leaf)
            lbs = para.findall("./"+T+"lb")
            if len(lbs) != len(expected_lines):
                raise ValueError("line count differs at leaf %d paragraph %d" % (leaf,pi))
            if [norm(lb.tail or "") for lb in lbs] != expected_lines:
                raise ValueError("line text/order differs at leaf %d paragraph %d" % (leaf,pi))
            if [lb.attrib.get("n") for lb in lbs] != [str(i) for i in range(1,len(lbs)+1)]:
                raise ValueError("line ordinal differs at leaf %d paragraph %d" % (leaf,pi))
            line_count += len(lbs)
            para_count += 1
    toc = top.find("./"+T+"standOff/"+T+"list[@type='scan_derived_contents_rows']")
    if toc is None:
        raise ValueError("source contents row list missing")
    items = [item for item in toc.findall("./"+T+"item") if "n" in item.attrib]
    if len(items) != len(oracle["contents_anchors"]):
        raise ValueError("source contents row count differs")
    all_line_ids = {lb.attrib.get(XID) for lb in top.findall(".//"+T+"lb")}
    for expected, item in zip(oracle["contents_anchors"],items):
        leaf, row = expected["leaf"], expected["row"]
        if item.attrib.get(XID) != "ia-contents-leaf-%04d-row-%02d" % (leaf,row):
            raise ValueError("source contents row order/ID differs at leaf %d row %d" % (leaf,row))
        if item.attrib.get("n") != expected["raw_page_label"]:
            raise ValueError("source contents raw page label differs at leaf %d row %d" % (leaf,row))
        refs = item.attrib.get("corresp","").split()
        if not refs or "#"+expected["number_line_id"] not in refs or any(not ref.startswith("#ia-leaf-%04d-" % leaf) or ref[1:] not in all_line_ids for ref in refs):
            raise ValueError("source contents row links differ at leaf %d row %d" % (leaf,row))
        actual_words = Counter((item.text or "").split())
        if not actual_words or actual_words - Counter(expected["left_words"]):
            raise ValueError("source contents topic words differ at leaf %d row %d" % (leaf,row))
        linked_words = Counter()
        for ref in refs:
            linked_words.update(expected["left_line_words"].get(ref[1:],{}))
        if actual_words - linked_words:
            raise ValueError("source contents topic links differ at leaf %d row %d" % (leaf,row))
    for leaf, pi in [(11,1),(11,2),(11,6),(13,2),(17,1),(35,1),(49,1),(51,1),(51,2),(709,5)]:
        page = all_pages[leaf-1]
        para = [x for x in page if x.tag in {T+"p",T+"ab"}][pi-1]
        if para.tag != T+"ab" or para.attrib.get("rend") != "heading":
            raise ValueError("source display heading marker differs at leaf %d paragraph %d" % (leaf,pi))
    stand_off = top.find("./"+T+"standOff")
    if stand_off is None:
        raise ValueError("source-layout standOff missing")
    hierarchies = {}
    for item in stand_off.findall("./"+T+"list"):
        identifier = item.attrib.get(XID, "")
        match = re.fullmatch(r"ia-leaf-(\d{4})-diagram-hierarchy", identifier)
        if match:
            hierarchies[int(match.group(1))] = item
    if set(hierarchies) != set(SOURCE_LAYOUTS):
        raise ValueError("source-layout hierarchy pages differ")
    for leaf, layout in SOURCE_LAYOUTS.items():
        graph = hierarchies[leaf]
        figure = all_pages[leaf-1].find("./"+T+"figure")
        expected_figure_refs = ["#ia-leaf-%04d-para-%03d" % (leaf, paragraph) for paragraph in layout["paragraphs"]]
        if figure is None or figure.attrib.get("corresp", "").split() != expected_figure_refs:
            raise ValueError("source-layout figure carrier links differ at leaf %d" % leaf)
        if graph.attrib.get("type") != layout["list_type"]:
            raise ValueError("source-layout hierarchy type differs at leaf %d" % leaf)
        head = graph.find("./"+T+"head")
        expected_title_ref = "#ia-leaf-%04d-para-%03d" % (leaf, layout["title_paragraph"])
        if (head is None or norm("".join(head.itertext())) != layout["title"]
                or head.attrib.get("corresp") != expected_title_ref):
            raise ValueError("source-layout hierarchy title or title-carrier link differs at leaf %d" % leaf)
        if graph.attrib.get("corresp") != "#ia-leaf-%04d-diagram" % leaf:
            raise ValueError("source-layout hierarchy links wrong source figure at leaf %d" % leaf)
        graph_items = graph.findall("./"+T+"item")
        if len(graph_items) != 1:
            raise ValueError("source-layout hierarchy root count differs at leaf %d" % leaf)
        check_graph(graph_items[0], expected_graph(leaf), leaf, oracle)
    header = top.find("./"+T+"teiHeader")
    header_text = norm(" ".join(header.itertext())) if header is not None else ""
    for anchor in ("Zacharias Ursinus","G. W. Williard","1852","commdrza00ursi"):
        if anchor not in header_text:
            raise ValueError("edition header identity differs: "+anchor)
    layout_crosswalk = [{"scan_leaf": leaf, "pdf_page_number": leaf, "printed_page_label": oracle["pages"][leaf-1]["printed_page_label"] or None} for leaf in sorted(SOURCE_LAYOUTS)]
    diagram_leaves = [leaf for leaf in sorted(SOURCE_LAYOUTS) if SOURCE_LAYOUTS[leaf]["figure_type"] == "source_branch_diagram"]
    return {"passed": True, "pages": 720, "paragraphs": para_count, "lines": line_count, "empty_ocr_pages": empty_count, "contents_rows": len(items), "diagram_scan_leaves": diagram_leaves, "source_layout_scan_leaves": sorted(SOURCE_LAYOUTS), "source_layout_page_crosswalk": layout_crosswalk, "source_text_sha256": oracle["ocr_text_normalized_sha256"], "candidate_uri_closure": uri_report}

def check(root: Path, destination: Path | None = None) -> dict:
    source, dest = paths(root, destination)
    oracle_path = dest/"source-oracle.json"
    oracle = json.loads(oracle_path.read_text(encoding="utf-8")) if oracle_path.exists() else source_oracle(root)
    fresh = source_oracle(root)
    if oracle != fresh:
        raise ValueError("stored source oracle stale")
    candidate = dest/"candidate.xml"
    if not candidate.exists():
        candidate = dest/"content.tei.xml"
    tree = ET.parse(candidate)
    result = verify_tree(tree, oracle, dest, source)
    expected_features = {row["leaf"]: row["layout_feature"] for row in oracle["pages"] if row["layout_feature"]}
    accounting_path = dest/"source-accounting.json"
    if accounting_path.exists():
        unresolved = [json.loads(line) for line in (dest/"unresolved.jsonl").read_text(encoding="utf-8").splitlines()]
        if {row["leaf"]: row["feature"] for row in unresolved} != expected_features or len(unresolved) != len(expected_features):
            raise ValueError("unresolved layout ledger differs from source expectations")
        accounting = json.loads(accounting_path.read_text(encoding="utf-8"))
        if {row["leaf"]: row["feature"] for row in accounting["unresolved_layout_features"]} != expected_features:
            raise ValueError("source accountability layout ledger differs")
        row_map = json.loads((dest/"contents-row-map.json").read_text(encoding="utf-8"))["rows"]
        if [(r["leaf"],r["row"],r["y"],r["raw_page_label"]) for r in row_map] != [(r["leaf"],r["row"],r["y"],r["raw_page_label"]) for r in oracle["contents_anchors"]]:
            raise ValueError("contents row map differs from source anchors")
        if accounting["contents_row_count"] != len(row_map) or sum(accounting["contents_rows_by_leaf"].values()) != len(row_map):
            raise ValueError("contents row accounting differs")
    else:
        accounting = json.loads((dest/"source-accountability.json").read_text(encoding="utf-8"))
        if accounting.get("source_layout_scan_leaves") != result["source_layout_scan_leaves"]:
            raise ValueError("candidate package source-layout accounting differs")
        if accounting.get("source_layout_page_crosswalk") != result["source_layout_page_crosswalk"]:
            raise ValueError("candidate package source-layout crosswalk differs")
        if len(accounting.get("contents_row_map", [])) != len(oracle["contents_anchors"]):
            raise ValueError("candidate package contents row accounting differs")
    result["open_structural_layout_pages"] = sorted(expected_features)
    result["candidate_sha256"] = sha(candidate)
    if candidate.name == "candidate.xml":
        (dest/"oracle-verification.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return result

def mutations(root: Path, destination: Path | None = None) -> list[dict]:
    source, dest = paths(root, destination)
    verified_scan_hash = sha(source/"scan.pdf")
    if verified_scan_hash != PIN["scan.pdf"]:
        raise ValueError("retained facsimile target hash differs")
    oracle_path = dest/"source-oracle.json"
    oracle = json.loads(oracle_path.read_text(encoding="utf-8")) if oracle_path.exists() else source_oracle(root)
    candidate_path = dest/"candidate.xml"
    if not candidate_path.exists():
        candidate_path = dest/"content.tei.xml"
    results = []
    def exercise(name, expected_error, mutate):
        tree = ET.parse(candidate_path)
        mutate(tree)
        try:
            verify_tree(tree,oracle,dest,source,verified_scan_hash)
        except ValueError as error:
            observed = str(error)
            if expected_error not in observed:
                raise ValueError(name+" rejected for wrong reason: "+observed)
            results.append({"mutation":name,"rejected":True,"reason":observed})
        else:
            raise ValueError(name+" was not rejected")
    def page(tree, leaf):
        return tree.getroot().find(".//"+T+"div[@type='scan_page'][@n='%d']" % leaf)
    def omit(tree):
        target = page(tree,401)
        parent = tree.getroot().find("./"+T+"text/"+T+"body/"+T+"div")
        parent.remove(target)
    def reorder(tree):
        parent = tree.getroot().find("./"+T+"text/"+T+"body/"+T+"div")
        children=list(parent)
        i=children.index(page(tree,400))
        parent.remove(children[i+1]); parent.insert(i,children[i+1])
    def text_change(tree):
        target=page(tree,300)
        lb=target.find(".//"+T+"lb")
        lb.tail=(lb.tail or "")+" INVENTED"
    def heading_change(tree):
        target=page(tree,49)
        para=target.find("./"+T+"ab")
        para.attrib.pop("rend")
    def facsimile_change(tree):
        original = page(tree,709).find("./"+T+"pb").attrib["facs"].split("#",1)[0]
        page(tree,709).find("./"+T+"pb").set("facs",original+"#page=708")
    def facsimile_missing_target(tree):
        page(tree,709).find("./"+T+"pb").set("facs","scan.pdf#page=709")
    def label_change(tree):
        page(tree,709).find("./"+T+"pb").set("n","658")
    def contents_label_change(tree):
        tree.getroot().find("./"+T+"standOff/"+T+"list/"+T+"item[@n]").set("n","999")
    def contents_link_change(tree):
        tree.getroot().find("./"+T+"standOff/"+T+"list/"+T+"item[@n]").attrib.pop("corresp")
    def contents_link_wrong_line(tree):
        item = tree.getroot().find("./"+T+"standOff/"+T+"list/"+T+"item[@n]")
        item = [x for x in tree.getroot().find("./"+T+"standOff/"+T+"list").findall("./"+T+"item") if x.attrib.get(XID) == "ia-contents-leaf-0035-row-03"][0]
        refs = item.attrib["corresp"].split()
        refs[0] = "#ia-leaf-0035-para-001-line-01"
        item.set("corresp"," ".join(refs))
    def diagram_change(tree):
        original = page(tree,205).find("./"+T+"figure/"+T+"graphic").attrib["url"].split("#",1)[0]
        page(tree,205).find("./"+T+"figure/"+T+"graphic").set("url",original+"#page=204")
    def diagram_omit_edge(tree):
        graph=tree.getroot().find("./"+T+"standOff/"+T+"list[@type='source_diagram_brace_hierarchy'][@corresp='#ia-leaf-0205-diagram']")
        root_item=graph.find("./"+T+"item")
        root_item.find("./"+T+"list").remove(root_item.find("./"+T+"list/"+T+"item[2]"))
    def diagram_reorder_siblings(tree):
        graph=tree.getroot().find("./"+T+"standOff/"+T+"list[@type='source_diagram_brace_hierarchy'][@corresp='#ia-leaf-0552-diagram']")
        nested=graph.find("./"+T+"item/"+T+"list")
        children=nested.findall("./"+T+"item")
        nested.remove(children[1]); nested.insert(0,children[1])
    def diagram_wrong_parent(tree):
        graph=tree.getroot().find("./"+T+"standOff/"+T+"list[@type='source_diagram_brace_hierarchy'][@corresp='#ia-leaf-0552-diagram']")
        mediate=graph.find("./"+T+"item/"+T+"list/"+T+"item[2]")
        external=mediate.find("./"+T+"list/"+T+"item[1]")
        preserve=external.find("./"+T+"list/"+T+"item[2]")
        external.find("./"+T+"list").remove(preserve)
        mediate.find("./"+T+"list").append(preserve)
    def diagram_wrong_creature_parent(tree):
        graph=tree.getroot().find("./"+T+"standOff/"+T+"list[@type='source_diagram_brace_hierarchy'][@corresp='#ia-leaf-0205-diagram']")
        creature=graph.find("./"+T+"item/"+T+"list/"+T+"item[2]/"+T+"list/"+T+"item[1]")
        living=creature.find("./"+T+"list/"+T+"item[1]/"+T+"list/"+T+"item[1]")
        rational=creature.find("./"+T+"list/"+T+"item[2]")
        angels=rational.find("./"+T+"list/"+T+"item[1]")
        rational.find("./"+T+"list").remove(angels)
        living_list=living.find("./"+T+"list")
        if living_list is None:
            living_list=ET.SubElement(living,T+"list",{"type":"brace-children"})
        living_list.append(angels)
    def diagram_omit_commandment_one(tree):
        graph=tree.getroot().find("./"+T+"standOff/"+T+"list[@type='source_diagram_brace_hierarchy'][@corresp='#ia-leaf-0552-diagram']")
        node=next(x for x in graph.findall(".//"+T+"item") if x.attrib.get(XID)=="ia-leaf-0552-node-1-1-1-1")
        node.text=node.text.replace("as in commandment I.","as in commandment.")
    def diagram_absorb_following_heading(tree):
        graph=tree.getroot().find("./"+T+"standOff/"+T+"list[@type='source_diagram_brace_hierarchy'][@corresp='#ia-leaf-0552-diagram']")
        node=next(x for x in graph.findall(".//"+T+"item") if x.attrib.get(XID)=="ia-leaf-0552-node-1-2-2")
        node.text += " GENERAL RULES."
    def diagram_omit_figure_carrier(tree):
        figure = page(tree,552).find("./"+T+"figure")
        refs = figure.attrib.get("corresp", "").split()
        refs.remove("#ia-leaf-0552-para-028")
        figure.set("corresp", " ".join(refs))
    def layout_list(tree, leaf):
        lists = tree.getroot().findall("./"+T+"standOff/"+T+"list")
        return next(item for item in lists if item.attrib.get(XID) == "ia-leaf-%04d-diagram-hierarchy" % leaf)
    def table_reorder_rows(tree):
        rows = layout_list(tree,489).find("./"+T+"item/"+T+"list[@type='table-structure']/"+T+"item[2]/"+T+"list[@type='table-rows']")
        children = rows.findall("./"+T+"item")
        rows.remove(children[1]); rows.insert(0,children[1])
    def table_unlink_cell(tree):
        row = layout_list(tree,489).find("./"+T+"item/"+T+"list[@type='table-structure']/"+T+"item[2]/"+T+"list[@type='table-rows']/"+T+"item[6]")
        cell = row.find("./"+T+"list/"+T+"item[1]")
        cell.set("corresp", "#ia-leaf-0489-para-010")
    def table_wrong_list_type(tree):
        layout_list(tree,489).set("type", "source_diagram_brace_hierarchy")
    def good_works_omit_branch(tree):
        graph = layout_list(tree,529)
        apparent = graph.find("./"+T+"item/"+T+"list/"+T+"item[2]")
        graph.find("./"+T+"item/"+T+"list").remove(apparent)
    def images_omit_distinction(tree):
        graph = layout_list(tree,578)
        branch = graph.find("./"+T+"item/"+T+"list/"+T+"item[2]/"+T+"list/"+T+"item[4]")
        graph.find("./"+T+"item/"+T+"list/"+T+"item[2]/"+T+"list").remove(branch)
    def sabbath_change_ordinal(tree):
        graph = layout_list(tree,613)
        months = next(item for item in graph.findall(".//"+T+"item") if item.attrib.get(XID) == "ia-leaf-0613-node-1-2-1-1-3")
        months.text = "2. Of months, as the new moons"
    def sixth_wrong_parent(tree):
        graph = layout_list(tree,639)
        root_list = graph.find("./"+T+"item/"+T+"list")
        prohibition, preservation = root_list.findall("./"+T+"item")
        branch = preservation.find("./"+T+"list/"+T+"item[1]/"+T+"list/"+T+"item[1]")
        preservation.find("./"+T+"list/"+T+"item[1]/"+T+"list").remove(branch)
        prohibition.find("./"+T+"list/"+T+"item[2]/"+T+"list").append(branch)
    for name, reason, mutation in [
        ("omit-page","page count",omit),("reorder-pages","page order",reorder),
        ("invent-text","line text/order",text_change),("erase-heading","source display heading",heading_change),
        ("wrong-facsimile-page","facsimile URI page fragment",facsimile_change),
        ("missing-facsimile-target","candidate facsimile URI target does not resolve",facsimile_missing_target),
        ("wrong-page-label","page label",label_change),
        ("mislink-diagram-page","facsimile URI page fragment",diagram_change),
        ("omit-diagram-edge","source-layout",diagram_omit_edge),
        ("reorder-diagram-branches","source-layout",diagram_reorder_siblings),
        ("wrong-diagram-parent","source-layout",diagram_wrong_parent),
        ("wrong-diagram-creature-parent","source-layout",diagram_wrong_creature_parent),
        ("omit-scan-visible-commandment-I","source-layout",diagram_omit_commandment_one),
        ("merge-following-heading-into-diagram","source-layout",diagram_absorb_following_heading),
        ("omit-diagram-figure-carrier","source-layout",diagram_omit_figure_carrier),
        ("reorder-comparison-table-rows","source-layout node label",table_reorder_rows),
        ("mislink-comparison-table-cell","source-layout OCR paragraph links",table_unlink_cell),
        ("change-comparison-table-list-type","source-layout hierarchy type",table_wrong_list_type),
        ("omit-good-works-class","source-layout child count",good_works_omit_branch),
        ("omit-image-distinction-branch","source-layout child count",images_omit_distinction),
        ("correct-scan-numbering-by-inference","source-layout node label",sabbath_change_ordinal),
        ("reparent-sixth-commandment-branch","source-layout child count",sixth_wrong_parent),
        ("wrong-contents-label","source contents raw page label",contents_label_change),
        ("erase-contents-links","source contents row links",contents_link_change),
        ("alter-contents-topic-link","source contents topic links",contents_link_wrong_line)]:
        exercise(name,reason,mutation)
    if candidate_path.name == "candidate.xml":
        (dest/"mutation-results.json").write_text(json.dumps(results,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return results

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=("source","check","mutations"))
    parser.add_argument("--repository-root",type=Path,required=True)
    parser.add_argument("--destination",type=Path)
    args=parser.parse_args()
    root=args.repository_root.resolve(strict=True)
    _,dest=paths(root,args.destination)
    if args.action=="source":
        dest.mkdir(parents=True,exist_ok=True)
        outcome=source_oracle(root)
        (dest/"source-oracle.json").write_text(json.dumps(outcome,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"source_oracle_pages":len(outcome["pages"]),"excluded_leaves":outcome["excluded_leaves"]}))
    elif args.action=="check":
        print(json.dumps(check(root,args.destination),sort_keys=True))
    else:
        print(json.dumps(mutations(root,args.destination),sort_keys=True))

