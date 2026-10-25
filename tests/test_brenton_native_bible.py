"""Focused carrier regression for the accepted Brenton table route."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import bible, brenton_native_bible as brenton
from ocd_kernel.release.features import configuration_features
from ocd_kernel.release.public_allowlist import render_dataset_card
from ocd_kernel.release.typed_rows import compare_rows, encode_rows


def test_exact_brenton_tables_and_unnumbered_opening_are_public_units() -> None:
    master = (
        bible.ROOT / "library/works/brenton-septuagint/forms/"
        "brenton-septuagint-retained-en/editions/brenton-septuagint-electronic/master.tei.xml"
    )
    original, _ = bible._read(master)
    versification = brenton._public_versification(
        f"source-native:retained-member-set:{brenton.MEMBER_SET_SHA256}"
    )
    units, inventory, bindings = brenton._producer_units(
        original, bible._paths(original), "Brenton Septuagint", versification
    )
    assert [binding["row_count"] for binding in bindings] == [12, 39]
    assert len(units) == 52
    assert units[0][0]["table_cells"] == [
        {"column": "label", "text": ""},
        {"column": "1", "text": "Heb."},
        {"column": "2", "text": "for Hebrew."},
    ]
    assert units[-1][0]["locator"]["kind"] == "source-paragraph"
    assert "Jeremias sat weeping" in units[-1][0]["text"]
    assert all("source-usfm:" not in str(row) for row, _ in units)
    assert sum(item["disposition"] == "private-source-marker" for item in inventory) == 153
    brenton._validate_rows([row for row, _ in units])

    damaged = copy.deepcopy(original)
    table = next(node for node in damaged.iter() if bible._local(node.tag) == "table")
    table[0][1].set("n", "3")
    with pytest.raises(PipelineError, match="table column 1 differs"):
        brenton._producer_units(damaged, bible._paths(damaged), "Brenton Septuagint", versification)


def test_mixed_brenton_source_units_have_typed_and_streaming_readers(tmp_path) -> None:
    import datasets

    versification = brenton._public_versification(
        f"source-native:retained-member-set:{brenton.MEMBER_SET_SHA256}"
    )
    table = brenton._row(
        record_id=f"{brenton.IDENTITY['edition_id']}:table-FRT-001",
        text="Heb. | for Hebrew.",
        locator={"kind": "source-table-row", "source_member": "FRT", "row": 1,
                 "source_order": 1, "versification": versification},
        title="Brenton Septuagint",
        table_cells=[{"column": "label", "text": ""},
                     {"column": "1", "text": "Heb."},
                     {"column": "2", "text": "for Hebrew."}],
    )
    verse = copy.deepcopy(table)
    verse.pop("table_cells")
    verse["record_id"] = f"{brenton.IDENTITY['edition_id']}:verse-000001"
    verse["sequence"] = 2
    verse["text"] = "In the beginning"
    verse["locator"] = {
        "kind": "verse", "book": "GEN", "book_osis": "brenton-GEN",
        "chapter": 1, "verse": "1", "versification": versification,
        "source_order": 2, "reference_origin": "tei-verse-components",
        "reference_status": "unsupported-verse-components",
    }
    opening = brenton._row(
        record_id=f"{brenton.IDENTITY['edition_id']}:source-paragraph-LAM-001",
        text="Jeremias sat weeping",
        locator={"kind": "source-paragraph", "source_member": "LAM",
                 "source_type": "paragraph-break", "chapter": 1,
                 "source_order": 3, "versification": versification},
        title="Brenton Septuagint",
    )
    opening["sequence"] = 3
    rows = [table, verse, opening]
    brenton._validate_rows(rows)
    features = configuration_features(rows)
    public = tmp_path / "public"
    data = public / "data/bible"
    data.mkdir(parents=True)
    arrow = data / "train.arrow"
    arrow_bytes = encode_rows(rows, features)
    arrow.write_bytes(arrow_bytes)
    (data / "train.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
    )
    (public / "README.md").write_text(
        render_dataset_card([{"category": "bible", "path": "public/data/bible/train.jsonl",
                              "row_count": 3, "features": features,
                              "typed_companion": {"path": "public/data/bible/train.arrow",
                                                  "sha256": hashlib.sha256(arrow_bytes).hexdigest()}}]),
        encoding="utf-8", newline="\n",
    )
    for streaming in (False, True):
        loaded = datasets.load_dataset(
            str(public), name="bible", split="train", streaming=streaming,
            cache_dir=str(tmp_path / "cache"),
        )
        compare_rows(rows, list(loaded))
