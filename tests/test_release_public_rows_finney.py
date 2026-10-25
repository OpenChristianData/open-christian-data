"""Exact Finney 1878 public scope and private publisher-layer inverse."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.projection.categories.prose import project_accepted_prose
from ocd_kernel.projection.native_content import readable_content
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release import public_rows as boundary
from ocd_kernel.release.work_metadata import compose_work_metadata


ITEM = boundary.FINNEY_ITEM
ACCEPTANCE = boundary.FINNEY_ACCEPTANCE_SHA256
MASTER = boundary.FINNEY_MASTER_SHA256


def digest(value):
    return sha256(canonical_bytes(value)).hexdigest()


def paragraph(value):
    return {"kind": "paragraph", "attributes": {},
            "content": [{"kind": "text", "text": value}]}


def division(children):
    return {"kind": "division", "attributes": {}, "content": children}


def fixture(monkeypatch):
    front = [paragraph(f"Historical title line {n}") for n in range(19)]
    front[17] = paragraph("PRES. J. H. FAIRCHILD")
    front += [paragraph("COLPORTER KEMP" if n == 4 else
                        "Second Edition 1946" if n == 10 else
                        f"Later imprint {n}") for n in range(14)]
    main = [paragraph(f"Historical lecture {n}") for n in range(107)]
    main[104] = division([paragraph("INDEX."), paragraph("A; Ability, 336.")])
    main[105] = {"kind": "text", "text": "\n"}
    main[106] = division([paragraph("PUBLISHER’S EPILOGUE"),
                          paragraph("It has been a high honor to republish Finney."),
                          paragraph("Rev. Joseph Elon Kemp")])
    work = {"kind": "division", "attributes": {"type": "work"},
            "content": [division(front), paragraph("separator"),
                        division([paragraph("NOTE BY THE EDITOR."),
                                  paragraph("J. H. F. OBERLIN COLLEGE, 1878.")]),
                        paragraph("separator"),
                        division([paragraph("George Redford, historical preface")]),
                        paragraph("separator"), division(main),
                        paragraph("separator"),
                        division([paragraph("Indexes"),
                                  paragraph("Index of Scripture References")]),
                        paragraph("separator")]}
    row = {"record_id": "finney-synthetic", "license": boundary.FINNEY_LICENSE,
           "structure": [work],
           "source_references": [{"raw": f"historical-{n}",
                                  "source_child_path": [3, n]} for n in range(692)]
                                 + [{"raw": f"index-{n}",
                                     "source_child_path": [4, n]} for n in range(1413)]}
    row["text"] = readable_content(work)
    public = deepcopy(row)
    del public["structure"][0]["content"][0]["content"][19:]
    del public["structure"][0]["content"][6]["content"][105:]
    public["text"] = readable_content(public["structure"][0])
    monkeypatch.setattr(boundary, "FINNEY_PRIVATE_ROW_SHA256", digest(row))
    monkeypatch.setattr(boundary, "FINNEY_PUBLIC_ROW_SHA256", digest(public))
    monkeypatch.setattr(boundary, "FINNEY_FRONT_TAIL_SHA256", digest(front[19:]))
    monkeypatch.setattr(boundary, "FINNEY_MAIN_TAIL_SHA256", digest(main[105:]))
    return [row]


def transform(rows):
    return boundary.public_rows_with_omissions(
        rows, item_id=ITEM, acceptance_sha256=ACCEPTANCE,
        master_sha256=MASTER)


def restore(rows, receipt):
    return boundary.restore_private_source_locations(
        rows, receipt, item_id=ITEM, acceptance_sha256=ACCEPTANCE,
        master_sha256=MASTER)


def test_historical_lectures_editor_and_indexes_survive_exact_inverse(monkeypatch):
    private = fixture(monkeypatch)
    public, receipt = transform(private)
    assert restore(public, receipt) == private
    text = public[0]["text"]
    assert "Historical lecture 103" in text
    assert "NOTE BY THE EDITOR." in text
    assert "George Redford" in text
    assert "INDEX." in text and "Index of Scripture References" in text
    assert "COLPORTER KEMP" not in text
    assert "PUBLISHER’S EPILOGUE" not in text
    assert len(public[0]["source_references"]) == 2105
    assert not _scan(public, "Finney synthetic public rows")


@pytest.mark.parametrize("mutation", ["text", "editor", "lecture", "printed_index",
                                      "generated_index", "reference", "license",
                                      "front_receipt", "epilogue_receipt", "authority"])
def test_public_semantics_and_private_receipt_cannot_drift(monkeypatch, mutation):
    private = fixture(monkeypatch)
    public, receipt = transform(private)
    public, receipt = deepcopy(public), deepcopy(receipt)
    work = public[0]["structure"][0]
    if mutation == "text":
        public[0]["text"] = "changed"
    elif mutation == "editor":
        work["content"][2]["content"][0]["content"][0]["text"] = "changed"
    elif mutation == "lecture":
        work["content"][6]["content"][50]["content"][0]["text"] = "changed"
    elif mutation == "printed_index":
        work["content"][6]["content"][104]["content"][0]["content"][0]["text"] = "changed"
    elif mutation == "generated_index":
        work["content"][8]["content"][1]["content"][0]["text"] = "changed"
    elif mutation == "reference":
        public[0]["source_references"].pop()
    elif mutation == "license":
        public[0]["license"] = "different rights scope"
    elif mutation == "front_receipt":
        receipt["removed_front_tail"][4]["content"][0]["text"] = "changed"
    elif mutation == "epilogue_receipt":
        receipt["removed_main_tail"][1]["content"][1]["content"][0]["text"] = "changed"
    else:
        receipt["authority"]["finney_scope_evidence_sha256"] = "0" * 64
    with pytest.raises(PipelineError):
        restore(public, receipt)


def test_legacy_receipt_cannot_bypass_finney_contract(monkeypatch):
    private = fixture(monkeypatch)
    public, _ = transform(private)
    with pytest.raises(PipelineError):
        restore(public, {"contract": boundary.CONTRACT, "item_id": ITEM,
                         "row_count": 1, "omissions": []})


def test_wrong_acceptance_or_license_refuses_transform(monkeypatch):
    private = fixture(monkeypatch)
    with pytest.raises(PipelineError):
        boundary.public_rows_with_omissions(
            private, item_id=ITEM, acceptance_sha256="0" * 64,
            master_sha256=MASTER)
    private[0]["license"] = "unreviewed rights scope"
    with pytest.raises(PipelineError):
        transform(private)


def test_real_assembler_license_and_metadata_pretransform():
    root = Path(__file__).resolve().parents[1]
    acceptance_path = (root / "library/works/finney-systematic-theology/forms/finney-systematic-theology-english/editions/finney-systematic-theology-ccel-thml-electronic/acceptance.json")
    projected = project_accepted_prose(root, acceptance_path=acceptance_path)
    licensed = [dict(row, license=boundary.FINNEY_LICENSE) for row in projected["rows"]]
    private, receipt = compose_work_metadata(root, licensed, projected["receipt"])
    public, omissions = boundary.public_rows_with_omissions(
        private, item_id=ITEM,
        acceptance_sha256=sha256(acceptance_path.read_bytes()).hexdigest(),
        master_sha256=receipt["master_sha256"])
    assert restore(public, omissions) == private
    assert digest(public[0]) == boundary.FINNEY_PUBLIC_ROW_SHA256
    assert not _scan(public, "Finney real selected public row")
