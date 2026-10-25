from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei import aquinas_summa_theologica_four_parts as summa


NS = summa.NS
RAW_ROOT = summa.resolve_repo_path(summa.REPOSITORY_ROOT, summa.RAW_LOGICAL_ROOT)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not all((RAW_ROOT / spec.archive_name).is_file() for spec in summa.COMPONENTS),
        reason="ticket-09 retained local source packages are unavailable",
    ),
]


@pytest.fixture(scope="module")
def built() -> tuple[etree._ElementTree, dict[str, object]]:
    return summa.build_tei()


def _by_pg(accounting: dict[str, object]) -> dict[int, dict[str, object]]:
    return {
        int(component["project_gutenberg_id"]): component
        for component in accounting["components"]
    }


def _copy_tree(tree: etree._ElementTree) -> etree._ElementTree:
    return etree.ElementTree(etree.fromstring(etree.tostring(tree)))


def test_exact_sources_full_unit_projection_and_bounds(
    built: tuple[etree._ElementTree, dict[str, object]],
) -> None:
    tree, accounting = built
    assert accounting["component_order"] == [
        "prima-pars",
        "prima-secundae",
        "secunda-secundae",
        "tertia-pars",
    ]
    assert accounting["total_source_units"] == 35_488
    assert accounting["total_tei_units"] == 35_488
    assert accounting["total_semantic_questions"] == 512
    assert accounting["total_article_markers"] == 2_666
    assert accounting["total_semantic_articles"] == 2_669
    assert accounting["source_visible_text_sha256"] == accounting[
        "tei_visible_text_sha256"
    ]
    assert accounting["print_page_milestones"] == 0
    assert accounting["supplement_included"] is False
    assert accounting["fifth_component_included"] is False
    assert tree.xpath("count(//t:pb)", namespaces=NS) == 0

    expected = {
        17611: (119, 584, 2, "5c10e2866fa6325f81454fd2e7887525001a388d092966ef874534339e36656a"),
        17897: (114, 619, 10, "c506ea69344c26950a2db21193f3d3f1741c99ed17be1385abe3cac79b88f60a"),
        18755: (189, 917, 10, "e5e6b07cf0aa3d3e90ec51c7a167c08f03141f04553e183a758feff0a8e0735c"),
        19950: (90, 549, 4, "00c9773347b58936e9d3af41786767d9c2739cd6b1b7d4ab298d728bb0ae1249"),
    }
    for pg_id, component in _by_pg(accounting).items():
        questions, articles, terminal_article, digest = expected[pg_id]
        assert component["semantic_question_count"] == questions
        assert component["semantic_article_count"] == articles
        assert component["terminal_question"] == questions
        assert component["tei_unit_count"] == component["source_unit_count"]
        assert component["source_visible_text_sha256"] == digest
        assert component["tei_visible_text_sha256"] == digest
        assert component["archive_members"][0]["path"] == f"pg{pg_id}-images.html"
        assert component["archive_members"][1]["path"] == f"{pg_id}-cover.png"
        component_node = tree.xpath(
            "//t:div[@type='component' and @corresp=$landing]",
            namespaces=NS,
            landing=f"https://www.gutenberg.org/ebooks/{pg_id}",
        )[0]
        contents_ids = component_node.xpath(
            ".//t:div[@type='contents']//*[@corresp]/@xml:id", namespaces=NS
        )
        assert contents_ids == [
            f"pg{pg_id}-id{number:05d}"
            for number in range(
                int(summa.CONTENTS_START_IDS[pg_id][2:]),
                int(next(spec for spec in summa.COMPONENTS if spec.pg_id == pg_id).main_start_id[2:]),
            )
        ]
        terminal = tree.xpath(
            "//t:div[@type='component' and @corresp=$landing]"
            "//t:div[@type='question' and @n=$question]"
            "/t:div[@type='article'][last()]",
            namespaces=NS,
            landing=f"https://www.gutenberg.org/ebooks/{pg_id}",
            question=str(questions),
        )[0]
        assert terminal.get("n") == str(terminal_article)

    visible = " ".join(" ".join(tree.getroot().itertext()).split())
    assert "The Project Gutenberg eBook of Summa Theologica" not in visible
    assert "THE FULL PROJECT GUTENBERG LICENSE" not in visible
    assert "NOTE TO THIS ELECTRONIC EDITION" in visible
    assert "To the Blessed Virgin Mary Immaculate Seat of Wisdom" in visible


def test_source_anomalies_are_literal_but_semantic_positions_are_sequential(
    built: tuple[etree._ElementTree, dict[str, object]],
) -> None:
    tree, accounting = built
    components = _by_pg(accounting)
    assert components[17611]["source_question_heading_gaps"] == [116]
    assert components[17897]["source_question_heading_gaps"] == [1]
    assert components[18755]["source_question_heading_gaps"] == [183]
    assert components[19950]["source_question_heading_gaps"] == []
    assert components[17611]["recovered_article_start_source_ids"] == [
        "pg17611-id04760",
        "pg17611-id04775",
    ]
    assert components[17897]["recovered_article_start_source_ids"] == [
        "pg17897-id01743"
    ]
    assert components[18755]["unnumbered_article_source_ids"] == [
        "pg18755-id03600",
        "pg18755-id05498",
        "pg18755-id08340",
        "pg18755-id09033",
    ]
    assert components[18755]["q811_source_ids"] == ["pg18755-id11244"]
    assert components[17897]["source_question_38_article_count_conflict"] == {
        "descriptor_source_id": "pg17897-id02693",
        "descriptor_claimed_articles": 4,
        "inquiries_source_id": "pg17897-id02694",
        "inquiry_count": 5,
        "article_source_ids": [
            "pg17897-id02700",
            "pg17897-id02710",
            "pg17897-id02720",
            "pg17897-id02730",
            "pg17897-id02740",
        ],
        "semantic_article_count": 5,
    }

    expected_malformed_labels = {
        17611: [
            "pg17611-id00429",
            "pg17611-id00580",
            "pg17611-id00640",
            "pg17611-id00664",
            "pg17611-id00799",
            "pg17611-id03802",
            "pg17611-id03967",
            "pg17611-id06598",
        ],
        17897: [
            "pg17897-id03419",
            "pg17897-id05514",
            "pg17897-id06656",
        ],
        18755: [
            "pg18755-id01741",
            "pg18755-id03012",
            "pg18755-id03600",
            "pg18755-id05498",
            "pg18755-id07111",
            "pg18755-id08340",
            "pg18755-id08780",
            "pg18755-id09033",
        ],
        19950: ["pg19950-id00602"],
    }
    expected_unnumbered_labels = {
        17611: [],
        17897: [],
        18755: [
            "pg18755-id03600",
            "pg18755-id05498",
            "pg18755-id08340",
            "pg18755-id09033",
        ],
        19950: [],
    }

    expected_article_mismatches = {
        17611: [
            "pg17611-id01589",
            "pg17611-id02144",
            "pg17611-id02605",
            "pg17611-id04068",
            "pg17611-id04254",
            "pg17611-id05846",
            "pg17611-id07340",
        ],
        17897: ["pg17897-id00196", "pg17897-id04097"],
        18755: [
            "pg18755-id01367",
            "pg18755-id01378",
            "pg18755-id06041",
            "pg18755-id07173",
            "pg18755-id09179",
            "pg18755-id09771",
            "pg18755-id10335",
            "pg18755-id10882",
        ],
        19950: ["pg19950-id03573", "pg19950-id04399"],
    }
    expected_question_mismatches = {
        17611: ["pg17611-id02960"],
        17897: [],
        18755: ["pg18755-id03380", "pg18755-id11244"],
        19950: ["pg19950-id07334"],
    }
    for pg_id, component in components.items():
        assert component["malformed_article_source_ids"] == expected_malformed_labels[pg_id]
        assert component["unnumbered_article_source_ids"] == expected_unnumbered_labels[pg_id]
        assert component["article_label_mismatch_source_ids"] == expected_article_mismatches[pg_id]
        assert component["question_label_mismatch_source_ids"] == expected_question_mismatches[pg_id]

    for question in tree.xpath("//t:div[@type='question']", namespaces=NS):
        articles = question.xpath("./t:div[@type='article']", namespaces=NS)
        assert [int(article.get("n")) for article in articles] == list(
            range(1, len(articles) + 1)
        )
    q181_a3 = tree.xpath(
        "//*[@xml:id='pg18755-id11244']", namespaces=NS
    )[0]
    assert "Q. 811, Art. 3" in " ".join(q181_a3.itertext())
    assert q181_a3.getparent().get("n") == "3"
    assert q181_a3.getparent().getparent().get("n") == "181"


def test_part_three_editorial_insertion_is_standalone_with_three_columns(
    built: tuple[etree._ElementTree, dict[str, object]],
) -> None:
    tree, _ = built
    insertion = tree.xpath(
        "//t:div[@type='editorial-insertion']", namespaces=NS
    )
    assert len(insertion) == 1
    insertion = insertion[0]
    bound_ids = insertion.xpath(
        ".//*[@corresp]/@xml:id", namespaces=NS
    )
    assert bound_ids[0] == "pg19950-id01912"
    assert bound_ids[-1] == "pg19950-id01941"
    assert len(bound_ids) == 30
    columns = insertion.xpath(
        "./t:div[@type='editorial-column']", namespaces=NS
    )
    assert [column.get("n") for column in columns] == ["1", "2", "3"]
    assert [
        column.xpath(".//*[@corresp]/@xml:id", namespaces=NS) for column in columns
    ] == [
        [f"pg19950-id{number:05d}" for number in range(1916, 1924)],
        [f"pg19950-id{number:05d}" for number in range(1924, 1931)],
        [f"pg19950-id{number:05d}" for number in range(1931, 1938)],
    ]
    prose = tree.xpath("//*[@xml:id='pg19950-id01938']", namespaces=NS)[0]
    assert prose.getparent().get("type") == "editorial-commentary"
    assert prose.getparent().getparent() is insertion
    q26 = tree.xpath(
        "//t:div[@xml:id='tertia-pars-question-26']", namespaces=NS
    )[0]
    q27 = tree.xpath(
        "//t:div[@xml:id='tertia-pars-question-27']", namespaces=NS
    )[0]
    assert q26.getnext().get("type") == "editorial-insertion"
    assert insertion.getnext().get(summa.XML_ID) == q27.get(summa.XML_ID)


def test_relaxng_semantic_validation_and_fresh_process_determinism(
    built: tuple[etree._ElementTree, dict[str, object]],
    tmp_path: Path,
) -> None:
    tree, _ = built
    serialized = etree.tostring(
        tree, encoding="UTF-8", xml_declaration=True, pretty_print=True
    )
    validated = summa.validate_tei(serialized)
    assert validated["tei_p5_relaxng_valid"] is True
    assert validated["component_count"] == 4
    assert validated["source_bound_unit_count"] == 35_488
    assert [component["article_count"] for component in validated["components"]] == [
        584,
        619,
        917,
        549,
    ]
    assert validated["unresolved_analysis_reference_count"] == 0
    local_categories = {
        node.get(summa.XML_ID)
        for node in tree.xpath("//t:taxonomy/t:category", namespaces=NS)
    }
    assert local_categories == set(summa.ANALYSIS_CATEGORIES)
    assert {
        token[1:]
        for value in tree.xpath("//@ana")
        for token in value.split()
        if token.startswith("#")
    } <= local_categories

    first_cwd = tmp_path / "first-cwd"
    second_cwd = tmp_path / "second-cwd"
    first_cwd.mkdir()
    second_cwd.mkdir()
    module_path = Path(summa.__file__).resolve()
    first_candidate = tmp_path / "first.tei.xml"
    second_candidate = tmp_path / "second.tei.xml"
    first_accounting = tmp_path / "first.accounting.json"
    second_accounting = tmp_path / "second.accounting.json"
    for cwd, candidate, accounting in (
        (first_cwd, first_candidate, first_accounting),
        (second_cwd, second_candidate, second_accounting),
    ):
        subprocess.run(
            [
                sys.executable,
                str(module_path),
                "--output",
                str(candidate),
                "--accounting-output",
                str(accounting),
            ],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    assert first_candidate.read_bytes() == second_candidate.read_bytes()
    assert first_accounting.read_bytes() == second_accounting.read_bytes()
    parsed = json.loads(first_accounting.read_text(encoding="utf-8"))
    assert parsed["candidate_sha256"] == summa._sha256(first_candidate.read_bytes())
    assert parsed["tei_relaxng_sha256"] == validated["tei_relaxng_sha256"]


def test_validator_rejects_omission_reordering_and_inline_loss(
    built: tuple[etree._ElementTree, dict[str, object]],
) -> None:
    tree, _ = built

    omitted = _copy_tree(tree)
    removable = omitted.xpath(
        "//t:p[@corresp][following-sibling::t:p[@corresp]]", namespaces=NS
    )[0]
    removable.getparent().remove(removable)
    with pytest.raises(summa.ConversionError, match="source-unit identity/order"):
        summa.validate_tei(etree.tostring(omitted))

    reordered = _copy_tree(tree)
    first = reordered.xpath(
        "//t:p[@corresp][following-sibling::*[1][self::t:p and @corresp]]",
        namespaces=NS,
    )[0]
    second = first.getnext()
    parent = first.getparent()
    first_index = parent.index(first)
    parent.remove(second)
    parent.insert(first_index, second)
    with pytest.raises(summa.ConversionError, match="source-unit identity/order"):
        summa.validate_tei(etree.tostring(reordered))

    italics_lost = _copy_tree(tree)
    etree.strip_tags(italics_lost, f"{{{summa.TEI_NS}}}hi")
    with pytest.raises(summa.ConversionError, match="italic projection"):
        summa.validate_tei(etree.tostring(italics_lost))

    breaks_lost = _copy_tree(tree)
    etree.strip_tags(breaks_lost, f"{{{summa.TEI_NS}}}lb")
    with pytest.raises(summa.ConversionError, match="line-break projection"):
        summa.validate_tei(etree.tostring(breaks_lost))


def test_converter_rejects_same_output_path(tmp_path: Path) -> None:
    same = tmp_path / "same.xml"
    with pytest.raises(summa.ConversionError, match="outputs must be distinct"):
        summa.convert(output_path=same, accounting_path=same)
