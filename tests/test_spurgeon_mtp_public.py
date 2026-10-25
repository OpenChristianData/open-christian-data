"""Bounded MTP omission and serialized inverse mutation regression."""

from copy import deepcopy
import json

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release import spurgeon_mtp_public as mtp


def _fixture_rows(monkeypatch):
    rows = []
    for index in range(3550):
        number = str(index + 5000)
        subtype = "primary-article"
        if index == 694:
            number, subtype = "708", "supplemental-aig-sermon-content"
        elif index == 1684:
            number, subtype = "1698", "supplemental-spurgeon-archive-sermon-content"
        elif index == 3018:
            number, subtype = "3032", "supplemental-aig-sermon-content"
        rows.append({"work_id": "spurgeon-mtp", "edition_id": "spurgeon-mtp-retained-electronic",
                     "record_id": f"fixture:{index}", "sequence": index + 1,
                     "license": mtp.LICENSE, "text": f"Sermon {number}",
                     "structure": [{"kind": "division", "attributes": {
                         "number": number, "subtype": subtype, "type": "sermon"}, "content": []}]})
    monkeypatch.setattr(mtp, "OMITTED", tuple({
        "index": index, "number": number, "record_id": rows[index]["record_id"],
        "source_only_sha256": mtp._digest({key: value for key, value in rows[index].items()
                                            if key != "license"})}
        for index, number in ((694, "708"), (3018, "3032"))))
    return rows


def test_exact_two_modernized_rows_only_and_reversible_mutation_guard(monkeypatch):
    rows = _fixture_rows(monkeypatch)
    authority = {"acceptance_sha256": mtp.ACCEPTANCE_SHA256,
                 "master_sha256": mtp.MASTER_SHA256}
    public, artifact = mtp.public_rows(rows, **authority)
    assert len(public) == 3548
    assert [entry["number"] for entry in artifact["omitted_rows"]] == ["708", "3032"]
    assert mtp.restore_private_rows(public, json.loads(json.dumps(artifact)), **authority) == rows
    bad_hidden = deepcopy(artifact)
    bad_hidden["omitted_rows"][0]["row"]["text"] += "changed"
    with pytest.raises(PipelineError):
        mtp.restore_private_rows(public, bad_hidden, **authority)
    bad_public = deepcopy(public)
    bad_public[0]["text"] += "changed"
    with pytest.raises(PipelineError):
        mtp.restore_private_rows(bad_public, artifact, **authority)
    with pytest.raises(PipelineError):
        mtp.public_rows(rows, acceptance_sha256="0" * 64,
                        master_sha256=mtp.MASTER_SHA256)
