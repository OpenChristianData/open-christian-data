"""Census and convert a bounded Spurgeon MTP HTML proof wave to TEI.

The production JSON parser is intentionally not an input to this module.  The
proof wave reads the cached HTML directly so that list containers, list items,
and the source's other observed inline carriers can be audited before they are
projected to string-only sermon records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

from lxml import etree, html

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT
from build.parsers.spurgeon_mtp import BASE_URL, text_to_osis
from ocd_kernel.tei.writer import serialize, stamp_header, tei_el

RAW_DIR = REPO_ROOT / "raw" / "spurgeon_sermons" / "html"
CENSUS_PATH = REPO_ROOT / "ir" / "census" / "spurgeon-mtp.proof-wave.census.json"
TEI_PATH = REPO_ROOT / "ir" / "spurgeon" / "spurgeon-mtp.proof-wave.tei.xml"
CENSUS_SCHEMA = "tei-census-v1"
FAMILY_FILE_COUNT = 3_547


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _sermon_number(path: Path) -> int:
    try:
        return int(path.stem)
    except ValueError as exc:
        raise ValueError(f"Expected a numeric sermon filename, got {path.name}") from exc


def _html_files(raw_dir: Path) -> list[Path]:
    paths = sorted(raw_dir.glob("*.html"), key=_sermon_number)
    if len(paths) != FAMILY_FILE_COUNT:
        raise ValueError(f"Expected {FAMILY_FILE_COUNT} cached sermon files, found {len(paths)}")
    return paths


def _article(path: Path) -> etree._Element:
    tree = html.fromstring(path.read_bytes())
    articles = tree.xpath(
        './/article[contains(concat(" ", normalize-space(@class), " "), " sermon ")]'
    )
    if len(articles) != 1:
        raise ValueError(f"Expected one sermon article in {path}, found {len(articles)}")
    return articles[0]


def _tag_counts(article: etree._Element) -> Counter[str]:
    return Counter(
        element.tag.lower()
        for element in article.iter()
        if isinstance(element.tag, str)
    )


def _list_summary(article: etree._Element) -> dict[str, int | dict[str, int]]:
    lists = [element for element in article.iter() if element.tag in {"ol", "ul"}]
    items = [element for element in article.iter() if element.tag == "li"]
    nested = [
        element
        for element in lists
        if any(parent.tag in {"ol", "ul"} for parent in element.iterancestors())
    ]
    forms = Counter(
        f"{element.tag}[type={element.get('type')}]" if element.get("type") else element.tag
        for element in lists
    )
    return {
        "lists": len(lists),
        "ordered_lists": sum(1 for element in lists if element.tag == "ol"),
        "bulleted_lists": sum(1 for element in lists if element.tag == "ul"),
        "list_items": len(items),
        "nested_lists": len(nested),
        "forms": dict(sorted(forms.items())),
    }


def _select_proof_numbers(summaries: dict[int, dict[str, object]]) -> list[int]:
    multiple_direct = [
        number
        for number, summary in summaries.items()
        if int(summary["direct_ol_ul"]) >= 2
    ]
    nested = [number for number, summary in summaries.items() if int(summary["nested_lists"]) > 0]
    plain = [
        number
        for number, summary in summaries.items()
        if int(summary["article_ol"]) == 0 and int(summary["article_ul"]) == 0
    ]
    if not multiple_direct or not nested or not plain:
        raise ValueError("Could not select ordered-list, nested-list, and plain control witnesses")
    selected = sorted({min(multiple_direct), min(nested), min(plain)})
    if len(selected) != 3:
        raise ValueError(f"Selection rule produced an unexpected proof set: {selected}")
    return selected


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _scope_hash(paths: Iterable[Path]) -> str:
    material = "\n".join(f"{path.name}:{_file_hash(path)}" for path in paths)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def census_spurgeon_mtp(raw_dir: str | Path = RAW_DIR, selected_numbers: list[int] | None = None) -> dict:
    """Census the full cached family, then record the bounded proof wave."""
    root = Path(raw_dir)
    paths = _html_files(root)
    summaries: dict[int, dict[str, object]] = {}
    family_tags: Counter[str] = Counter()
    family_lists: Counter[str] = Counter()
    family_files_with: Counter[str] = Counter()
    family_forms: Counter[str] = Counter()
    family_nested_lists = 0

    for path in paths:
        number = _sermon_number(path)
        article = _article(path)
        tags = _tag_counts(article)
        list_summary = _list_summary(article)
        direct_lists = [child for child in article if child.tag in {"ol", "ul"}]
        family_tags.update(tags)
        family_lists.update(
            {
                "ol": int(list_summary["ordered_lists"]),
                "ul": int(list_summary["bulleted_lists"]),
                "li": int(list_summary["list_items"]),
            }
        )
        family_forms.update(list_summary["forms"])
        family_files_with.update(
            {
                "ol": int(tags["ol"] > 0),
                "ul": int(tags["ul"] > 0),
                "article_list": int(bool(direct_lists)),
                "plain_control": int(not tags["ol"] and not tags["ul"]),
            }
        )
        family_nested_lists += int(list_summary["nested_lists"])
        summaries[number] = {
            "article_ol": tags["ol"],
            "article_ul": tags["ul"],
            "direct_ol_ul": len(direct_lists),
            "nested_lists": int(list_summary["nested_lists"]),
        }

    selected = selected_numbers or _select_proof_numbers(summaries)
    if selected != sorted(selected) or len(selected) != 3:
        raise ValueError("The proof wave must contain exactly three sorted sermon numbers")
    selected_paths = [root / f"{number}.html" for number in selected]
    selected_features: Counter[str] = Counter()
    selected_forms: Counter[str] = Counter()
    selected_tag_counts: Counter[str] = Counter()
    selected_files: list[dict[str, str]] = []
    for path in selected_paths:
        article = _article(path)
        tags = _tag_counts(article)
        lists = _list_summary(article)
        selected_tag_counts.update(tags)
        selected_features.update(
            {
                "sermons": 1,
                "ordered_lists": int(lists["ordered_lists"]),
                "bulleted_lists": int(lists["bulleted_lists"]),
                "list_items": int(lists["list_items"]),
                "nested_lists": int(lists["nested_lists"]),
                "paragraphs": tags["p"],
                "blockquotes": tags["blockquote"],
                "line_breaks": tags["br"],
                "scripture_reference_spans": tags["span"],
                "italic_runs": tags["em"],
                "bold_runs": tags["strong"],
                "code_runs": tags["code"],
            }
        )
        selected_forms.update(lists["forms"])
        selected_files.append(
            {
                "path": _display_path(path),
                "sha256": _file_hash(path),
            }
        )

    return {
        "census_schema": CENSUS_SCHEMA,
        "source": {
            "type": "sermon_html",
            "family": "spurgeon-mtp-html",
            "path": _display_path(root),
            "file_count": len(paths),
            "scope": {
                "selected_sermons": selected,
                "selection_rule": (
                    "lowest-numbered sermon with at least two direct article lists; "
                    "lowest-numbered sermon with a nested list; and lowest-numbered "
                    "sermon with no article ol/ul, deduplicated and sorted"
                ),
            },
            "files": selected_files,
            "sha256": _scope_hash(selected_paths),
        },
        "family_census": {
            "sermon_files": len(paths),
            "article_tags": dict(sorted(family_tags.items())),
            "list_elements": dict(family_lists),
            "files_with_ol": family_files_with["ol"],
            "files_with_ul": family_files_with["ul"],
            "files_with_article_lists": family_files_with["article_list"],
            "files_without_article_ol_ul": family_files_with["plain_control"],
            "nested_list_elements": family_nested_lists,
            "list_forms": dict(sorted(family_forms.items())),
            "note": (
                "All 3,547 raw pages contain a site-navigation ul outside the sermon article; "
                "the family list counts above are restricted to article content."
            ),
        },
        "features": {
            key: {"count": value}
            for key, value in sorted(selected_features.items())
        },
        "selected_wave": {
            "tag_counts": dict(sorted(selected_tag_counts.items())),
            "list_forms": dict(sorted(selected_forms.items())),
            "notes": [
                "The selected wave contains ordered ol[type=a] carriers only; no sermon article contains ul.",
                "Sermon 317 exercises the one selected nested-list form, including its malformed-looking duplicate text carrier.",
                "Sermon 15 is the plain article control.",
            ],
        },
    }


def _append_text(parent: etree._Element, text: str | None) -> None:
    cleaned = _clean_text(text)
    if not cleaned:
        return
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + cleaned
    else:
        parent.text = (parent.text or "") + cleaned


def _append_inline_element(parent: etree._Element, source: etree._Element) -> None:
    tag = source.tag
    if tag == "span" and source.get("class") == "reference":
        raw = _clean_text("".join(source.itertext()))
        attrs: dict[str, str] = {"type": "scripture"}
        osis = text_to_osis(raw)
        if osis:
            attrs["cRef"] = " ".join(osis)
        target = tei_el("ref", attrs)
        _copy_inline(source, target)
        parent.append(target)
        return
    if tag == "br":
        parent.append(tei_el("lb"))
        return
    wrappers = {
        "em": ("hi", {"rend": "italic"}),
        "strong": ("hi", {"rend": "bold"}),
        "code": ("seg", {"type": "source-code"}),
    }
    if tag not in wrappers:
        raise ValueError(f"Unsupported inline tag in Spurgeon proof wave: <{tag}>")
    output_tag, attrs = wrappers[tag]
    target = tei_el(output_tag, attrs)
    _copy_inline(source, target)
    parent.append(target)


def _copy_inline(source: etree._Element, target: etree._Element) -> None:
    _append_text(target, source.text)
    for child in source:
        _append_inline_element(target, child)
        _append_text(target, child.tail)


def _convert_paragraph(source: etree._Element, xml_id: str) -> etree._Element:
    target = tei_el("p", {"xml:id": xml_id})
    _copy_inline(source, target)
    return target


def _convert_item(source: etree._Element, xml_id: str) -> etree._Element:
    item = tei_el("item", {"xml:id": xml_id})
    current_p: etree._Element | None = None

    def ensure_p() -> etree._Element:
        nonlocal current_p
        if current_p is None:
            current_p = tei_el("p", {"xml:id": f"{xml_id}-p"})
            item.append(current_p)
        return current_p

    if _clean_text(source.text):
        _append_text(ensure_p(), source.text)
    for child_index, child in enumerate(source, start=1):
        if child.tag in {"ol", "ul"}:
            current_p = None
            item.append(_convert_list(child, f"{xml_id}-list-{child_index}"))
        elif child.tag == "p":
            current_p = None
            item.append(_convert_paragraph(child, f"{xml_id}-p-{child_index}"))
        else:
            _append_inline_element(ensure_p(), child)
        if _clean_text(child.tail):
            _append_text(ensure_p(), child.tail)
    return item


def _convert_list(source: etree._Element, xml_id: str) -> etree._Element:
    if source.tag not in {"ol", "ul"}:
        raise ValueError(f"Expected a list source element, got <{source.tag}>")
    attrs: dict[str, str] = {
        "xml:id": xml_id,
        "type": "ordered" if source.tag == "ol" else "bulleted",
    }
    if source.get("type"):
        attrs["rend"] = source.get("type") or ""
    target = tei_el("list", attrs)
    item_number = 0
    for child in source:
        if child.tag != "li":
            raise ValueError(f"Unexpected <{child.tag}> inside <{source.tag}>")
        item_number += 1
        item_id = f"{xml_id}-item-{item_number}"
        target.append(_convert_item(child, item_id))
        _append_text(target, child.tail)
    return target


def convert_spurgeon_mtp_to_tei(
    raw_dir: str | Path = RAW_DIR,
    output_path: str | Path = TEI_PATH,
    selected_numbers: list[int] | None = None,
    census: dict | None = None,
) -> Path:
    """Convert selected cached sermon HTML files directly to one TEI artifact."""
    root = Path(raw_dir)
    census_data = census or census_spurgeon_mtp(root, selected_numbers)
    selected = census_data["source"]["scope"]["selected_sermons"]
    tei = tei_el("TEI")
    tei.append(
        stamp_header(
            title="Metropolitan Tabernacle Pulpit — bounded list-carrier proof wave",
            author="C. H. Spurgeon",
            contributors=["The Kingdom Collective HTML transcription"],
            source_url=BASE_URL.replace("{n}", "{sermon-number}"),
            source_sha256=census_data["source"]["sha256"],
            print_source=(
                "Cached Kingdom Collective HTML; this artifact is a proof wave, not a "
                f"family-wide migration ({len(selected)} of {census_data['source']['file_count']} sermon files)."
            ),
        )
    )
    text = tei_el("text", {"xml:lang": "en"})
    body = tei_el("body")
    for number in selected:
        path = root / f"{number}.html"
        article = _article(path)
        sermon_id = f"spurgeon-mtp-{number}"
        div = tei_el("div", {"xml:id": sermon_id, "type": "sermon", "n": str(number)})
        h1 = article.find("h1")
        if h1 is None:
            raise ValueError(f"Missing sermon title in {path}")
        div.append(tei_el("head", {"xml:id": f"{sermon_id}-head"}, _clean_text("".join(h1.itertext()))))
        blockquote_number = 0
        paragraph_number = 0
        list_number = 0
        for child in article:
            if child.tag == "h1":
                continue
            if child.tag == "p":
                paragraph_number += 1
                div.append(_convert_paragraph(child, f"{sermon_id}-p-{paragraph_number}"))
            elif child.tag == "blockquote":
                blockquote_number += 1
                attrs = {"xml:id": f"{sermon_id}-quote-{blockquote_number}"}
                if blockquote_number == 1:
                    attrs["type"] = "primary-reference"
                quote = tei_el("quote", attrs)
                for quote_index, quote_child in enumerate(child, start=1):
                    if quote_child.tag == "p":
                        quote.append(
                            _convert_paragraph(
                                quote_child,
                                f"{sermon_id}-quote-{blockquote_number}-p-{quote_index}",
                            )
                        )
                    else:
                        raise ValueError(f"Unsupported blockquote child <{quote_child.tag}> in {path}")
                div.append(quote)
            elif child.tag in {"ol", "ul"}:
                list_number += 1
                div.append(_convert_list(child, f"{sermon_id}-list-{list_number}"))
            else:
                raise ValueError(f"Unsupported direct sermon child <{child.tag}> in {path}")
        body.append(div)
    text.append(body)
    tei.append(text)
    output = Path(output_path)
    serialize(etree.ElementTree(tei), output)
    return output


def write_census(
    raw_dir: str | Path = RAW_DIR,
    census_path: str | Path = CENSUS_PATH,
    selected_numbers: list[int] | None = None,
) -> dict:
    census = census_spurgeon_mtp(raw_dir, selected_numbers)
    path = Path(census_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(census, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return census


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--census", type=Path, default=CENSUS_PATH)
    parser.add_argument("--output", type=Path, default=TEI_PATH)
    parser.add_argument("--census-only", action="store_true")
    args = parser.parse_args()
    census = write_census(args.raw_dir, args.census)
    print(
        "Census: "
        f"{census['source']['file_count']} files; "
        f"{census['family_census']['list_elements']['ol']} article ol; "
        f"{census['family_census']['list_elements']['ul']} article ul; "
        f"selected {census['source']['scope']['selected_sermons']}"
    )
    if not args.census_only:
        convert_spurgeon_mtp_to_tei(args.raw_dir, args.output, census=census)
        print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
