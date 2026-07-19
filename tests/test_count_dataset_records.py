import json
from pathlib import Path


def _write_resource(
    path: Path,
    *,
    resource_id: str,
    title: str | None,
    author: str | None,
    schema_type: str,
    data,
    provenance: dict | None = None,
    extra_meta: dict | None = None,
) -> None:
    meta = {
        "id": resource_id,
        "author": author,
        "schema_type": schema_type,
        "license": "public-domain",
        "provenance": provenance or {},
    }
    if extra_meta is not None:
        meta.update(extra_meta)
    if title is not None:
        meta["title"] = title
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"meta": meta, "data": data}, indent=2) + "\n",
        encoding="utf-8",
    )


def test_title_level_work_catalog_groups_reference_volumes(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "reference" / "ce-vol01.json",
        resource_id="catholic-encyclopedia-vol01",
        title="The Catholic Encyclopedia",
        author="Various contributors",
        schema_type="reference_entry",
        data=[{"id": "a"}, {"id": "b"}],
        provenance={"source_edition": "Volume 1"},
    )
    _write_resource(
        data_root / "reference" / "ce-vol02.json",
        resource_id="catholic-encyclopedia-vol02",
        title="The Catholic Encyclopedia",
        author="Various contributors",
        schema_type="reference_entry",
        data=[{"id": "c"}],
        provenance={"source_edition": "Volume 2"},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["work_units"] == 1
    work = catalog.works[0]
    assert work["title"] == "The Catholic Encyclopedia"
    assert work["file_count"] == 2
    assert work["top_level_records"] == 3
    assert work["metadata_fields"]["provenance.source_edition"] == ["Volume 1", "Volume 2"]


def test_distinct_author_led_works_with_shared_resource_id_get_unique_work_ids(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    for author, filename in (("W.H. Bennett", "jer.json"), ("Marcus Dods", "gen.json")):
        _write_resource(
            data_root / "commentaries" / "expositors-bible" / filename,
            resource_id="expositors-bible",
            title="The Expositor's Bible",
            author=author,
            schema_type="commentary",
            data=[],
        )

    from build.tools.count_dataset_records import collect_work_catalog

    works = collect_work_catalog(data_root).works

    assert {work["work_id"] for work in works} == {
        "expositors-bible--marcus-dods",
        "expositors-bible--w-h-bennett",
    }


def test_catalog_identity_snapshot_is_compact_authoritative_and_deterministic(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="A Work",
        author="An Author",
        schema_type="structured_text",
        data={"sections": []},
    )
    from build.tools.count_dataset_records import (
        catalog_identity_snapshot,
        collect_work_catalog,
        serialize_catalog_identity,
    )

    catalog = collect_work_catalog(data_root)
    snapshot = catalog_identity_snapshot(catalog)

    assert snapshot == {
        "identity": "work-catalog-identity-v1",
        "works": [
            {
                "author": "An Author",
                "category": "structured-text",
                "category_label": "Books and Long-Form Works",
                "file_count": 1,
                "resource_ids": ["work"],
                "schema_types": ["structured_text"],
                "source_paths": ["structured-text/work.json"],
                "title": "A Work",
                "work_id": "work",
            }
        ],
    }
    assert serialize_catalog_identity(catalog) == serialize_catalog_identity(
        collect_work_catalog(data_root)
    )
    assert b"methodology" not in serialize_catalog_identity(catalog)


def test_church_fathers_quote_dump_is_one_source_collection_unit(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "church-fathers" / "augustine.json",
        resource_id="augustine-of-hippo",
        title=None,
        author="Augustine of Hippo",
        schema_type="church_fathers",
        data=[{"quote": "one"}, {"quote": "two"}],
        provenance={"source": "HistoricalChristianFaith/Commentaries-Database"},
    )
    _write_resource(
        data_root / "church-fathers" / "chrysostom.json",
        resource_id="john-chrysostom",
        title=None,
        author="John Chrysostom",
        schema_type="church_fathers",
        data=[{"quote": "three"}],
        provenance={"source": "HistoricalChristianFaith/Commentaries-Database"},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["work_units"] == 1
    work = catalog.works[0]
    assert work["work_id"] == "church-fathers-quotations"
    assert work["title"] == "Church Fathers verse-reference quotations"
    assert work["author_count"] == 2
    assert work["top_level_records"] == 3
    assert "missing_title" not in work["audit_flags"]
    assert catalog.summary["source_author_labels"] == 2


def test_catalog_surfaces_missing_metadata_and_renders_html(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "untitled.json",
        resource_id="untitled-work",
        title=None,
        author=None,
        schema_type="structured_text",
        data={"sections": [{"heading": "Intro", "blocks": [{"text": "Body."}]}]},
    )

    from build.tools.count_dataset_records import collect_work_catalog, render_catalog_html

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["work_units"] == 1
    work = catalog.works[0]
    assert "missing_title" in work["audit_flags"]
    assert "missing_author" in work["audit_flags"]
    assert "needs_bibliographic_review" in work["audit_flags"]

    html = render_catalog_html(catalog)
    assert "<table" in html
    assert "untitled-work" in html
    assert "missing_title" in html
    assert "<pre>" not in html
    assert "<dt>Resource ID</dt>" in html


def test_lexicon_is_an_auxiliary_tool_not_a_public_work_category(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    lexicon_path = data_root / "lexicon" / "archaic_forms_en.json"
    lexicon_path.parent.mkdir(parents=True, exist_ok=True)
    lexicon_path.write_text(json.dumps({"shew": "show"}) + "\n", encoding="utf-8")
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="A Work",
        author="An Author",
        schema_type="structured_text",
        data={"sections": []},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["work_units"] == 1
    assert "lexicon" not in catalog.summary["works_by_category"]
    assert catalog.works[0]["category_label"] == "Books and Long-Form Works"


def test_topical_schema_is_cataloged_as_topical_even_under_legacy_reference_path(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "reference" / "torrey.json",
        resource_id="torreys-topical-textbook",
        title="Torrey's New Topical Textbook",
        author="R. A. Torrey",
        schema_type="topical_reference",
        data=[{"topic": "Prayer"}],
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["works_by_category"] == {"topical-reference": 1}
    assert catalog.works[0]["category_label"] == "Topical Bibles and Indexes"


def test_publication_date_is_derived_from_original_publication_year(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "catechisms" / "outlines.json",
        resource_id="outlines",
        title="Outlines of Theology",
        author="A. A. Hodge",
        schema_type="catechism_qa",
        data=[{"question": "Q?", "answer": "A."}],
        provenance={"source_edition": "1879 edition"},
        extra_meta={"original_publication_year": 1879},
    )

    from build.tools.count_dataset_records import (
        collect_work_catalog,
        render_catalog_html,
        render_catalog_markdown,
    )

    catalog = collect_work_catalog(data_root)

    assert catalog.works[0]["publication_date"] == "1879"
    assert "<th>Publication date</th>" in render_catalog_html(catalog)
    assert "| Category | Title | Author | Publication date |" in render_catalog_markdown(catalog)


def test_hymn_collection_renders_as_summary_not_individual_hymn_rows(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "hymns" / "hymnary-pd" / "collection.json",
        resource_id="hymnary-pd",
        title="Public Domain Hymns (Hymnary.org)",
        author=None,
        schema_type="hymn_collection",
        data=[
            {
                "title": "First Hymn",
                "hymnal_title": "Test Hymnal",
                "hymnal_year": 1900,
                "year_written": 1850,
                "language": "en",
            },
            {
                "title": "Second Hymn",
                "hymnal_title": "Other Hymnal",
                "hymnal_year": 1910,
                "year_written": None,
                "language": "en",
            },
        ],
        provenance={"source_edition": "Hymnary.org export"},
    )

    from build.tools.count_dataset_records import collect_work_catalog, render_catalog_html

    catalog = collect_work_catalog(data_root)
    work = catalog.works[0]

    assert work["publication_date"] == "Hymnal publication years 1900-1910"
    assert work["hymn_summary"]["hymn_entries"] == 2

    html = render_catalog_html(catalog)
    assert "Hymn collection coverage" in html
    assert "2 hymn entries" in html
    assert "First Hymn" not in html


def test_slug_equivalent_human_title_is_not_flagged_as_internal_id(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "catechisms" / "westminster-shorter-catechism.json",
        resource_id="westminster-shorter-catechism",
        title="Westminster Shorter Catechism",
        author="Westminster Assembly",
        schema_type="catechism_qa",
        data=[{"question": "Q?", "answer": "A."}],
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.works[0]["audit_flags"] == ["missing_source_edition"]


def test_nsh_pipeline_reference_artifacts_are_out_of_dataset_scope(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "reference" / "schaff" / "encyclopedia" / "1908-1914" / "original" / "vol_01.json",
        resource_id="schaff-herzog-encyclopedia",
        title="New Schaff-Herzog Encyclopedia of Religious Knowledge",
        author=None,
        schema_type="reference_entry",
        data=[{"id": "a"}],
    )
    _write_resource(
        data_root / "reference" / "schaff-herzog-encyclopedia.json",
        resource_id="schaff-herzog-encyclopedia",
        title="Schaff-Herzog Encyclopedia of Religious Knowledge",
        author="Philip Schaff",
        schema_type="reference_entry",
        data=[{"id": "b"}],
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["work_units"] == 1
    assert catalog.summary["top_level_records"] == 1
    assert catalog.works[0]["title"] == "Schaff-Herzog Encyclopedia of Religious Knowledge"


def test_known_dataset_labels_are_flagged_for_public_title_review(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "commentaries" / "calvin" / "genesis.json",
        resource_id="calvin",
        title="Calvin's Collected Commentaries",
        author="John Calvin",
        schema_type="commentary",
        data=[{"commentary_text": "Text."}],
        provenance={"source_edition": "CrossWire SWORD module"},
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert "official_title_unconfirmed" in catalog.works[0]["audit_flags"]


def test_summary_counts_legacy_huggingface_flattened_rows(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_resource(
        data_root / "structured-text" / "work.json",
        resource_id="work",
        title="Work",
        author="Author",
        schema_type="structured_text",
        data={
            "work_id": "work",
            "sections": [
                {
                    "content_blocks": ["one", "two"],
                    "children": [{"content_blocks": ["three"]}],
                }
            ],
        },
    )
    _write_resource(
        data_root / "doctrinal-documents" / "doc.json",
        resource_id="doc",
        title="Doc",
        author="Author",
        schema_type="doctrinal_document",
        data={
            "document_id": "doc",
            "units": [
                {"children": [{"content": "one"}, {"content": "two"}]},
            ],
        },
    )

    from build.tools.count_dataset_records import collect_work_catalog

    catalog = collect_work_catalog(data_root)

    assert catalog.summary["top_level_records"] == 2
    assert catalog.summary["legacy_hf_export_records"] == 5
    assert catalog.summary["legacy_hf_export_records_by_schema"] == {
        "doctrinal_document": 2,
        "structured_text": 3,
    }
