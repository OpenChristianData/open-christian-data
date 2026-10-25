"""Probe native projection and cross-boundary word links for reviewed flat spans."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb829_flat_slices as flat
from ocd_kernel.projection.categories.native_documents import project_document, verify_document


OUTPUT = flat.ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb829-flat-projection-probe-20260926.json"
PROBE = Path(r"C:\Scratch\b829f\projection-probe")


def probe() -> dict:
    _source, root, divisions, plan = flat._source()
    PROBE.mkdir(parents=True, exist_ok=True)
    rows = []
    for entry in sorted(plan["works"], key=lambda value: value["work_id"]):
        work_id = entry["work_id"]
        work = json.loads((flat.ROOT / "library/works" / work_id / "work.json").read_bytes())
        selected, _start, _end = flat._slice(divisions, entry)
        candidate = flat._candidate(root, selected, work)
        path = PROBE / f"{work_id}.tei.xml"
        flat._write_once(path, candidate)
        ids = {node.get(flat.XML_ID) for node in selected.iter() if node.get(flat.XML_ID)}
        outside = [{"word": node.get(flat.XML_ID), "corresp": node.get("corresp"),
                    "outside": [ref for ref in (node.get("corresp") or "").split()
                                if not ref.startswith("#") or ref[1:] not in ids]}
                   for node in selected.iter() if node.tag == f"{flat.TEI}w"
                   and any(not ref.startswith("#") or ref[1:] not in ids
                           for ref in (node.get("corresp") or "").split())]
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                    "edition_id": edition["edition_id"]}
        try:
            projected = project_document(path, identity=identity, language="la",
                                         representation_revision=f"{work_id}-bsb829-flat-slices-v1",
                                         edition_title=edition["title"],
                                         _allow_acceptance_metadata=True, category="prose")
            errors = verify_document(path, projected["rows"], projected["receipt"],
                                     identity=identity, language="la",
                                     representation_revision=f"{work_id}-bsb829-flat-slices-v1",
                                     edition_title=edition["title"],
                                     _allow_acceptance_metadata=True, category="prose")
            projection = "pass" if len(projected["rows"]) == 1 and not errors else "fail"
            failure = errors[:3]
        except (ValueError, RuntimeError) as error:
            projection = "fail"
            failure = [str(error)]
        rows.append({"work_id": work_id, "division": entry["division"],
                     "candidate_sha256": sha256(candidate).hexdigest(),
                     "outside_word_links": outside, "projection": projection,
                     "failure": failure})
    return {"contract": "ocd-openmgh-bsb829-flat-projection-probe-v1",
            "source_sha256": flat.SOURCE_SHA, "selection_plan_sha256": flat.PLAN_SHA,
            "rows": rows}


def main() -> int:
    result = probe()
    content = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if OUTPUT.exists() and OUTPUT.read_bytes() != content:
        raise ValueError("existing projection probe differs")
    OUTPUT.write_bytes(content)
    print(json.dumps({"pass": sum(row["projection"] == "pass" for row in result["rows"]),
                      "fail": sum(row["projection"] == "fail" for row in result["rows"]),
                      "receipt": OUTPUT.as_posix(),
                      "sha256": sha256(content).hexdigest()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
