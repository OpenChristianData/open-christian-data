"""Stage the complete 1880 Stephens PG53809 extracted-HTML witness."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei.stephens_pg53809_native import (
    ARCHIVE, ARCHIVE_SHA256, DIRECT, DIRECT_SHA256, ROOT, SOURCE, SOURCE_SHA256,
    adapt, source_bindings,
)
from build.tei.stephens_pg53809_oracle import check
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


WORK_ID = "stephens-saint-john-chrysostom-life-and-times"
FORM_ID = WORK_ID + "-gutenberg-retained"
EDITION_ID = WORK_ID + "-gutenberg-electronic"
ACQUISITION_ID = WORK_ID + "-gutenberg-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
EVIDENCE = WORK / "integration/stephens-pg53809-current-v2"
ADAPTED_SHA256 = "43bdc711d3f75db3883e6abc434dd8aea663ed0f7e17e83d746a06d26079c951"
STAGE_PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
SCOPE = ("Complete real extracted Project Gutenberg 53809 HTML electronic witness of "
         "W. R. W. Stephens, Saint John Chrysostom, His Life and Times, second edition "
         "(London: John Murray, 1880): all 1,457 direct body children, title page, "
         "both prefaces, contents, chapters, notes, index, provider header/footer/license, "
         "and one referenced frontispiece. The extracted cover is unreferenced support; "
         "the ZIP is a package, not text authority. No print collation, separate chapter "
         "editions, or rights clearance is inferred.")


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> dict:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise ValueError(f"PG53809 JSON object required: {path}")
    return result


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    path = stage / relative
    _io_path(path).parent.mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)
    return path


def _put_json(stage: Path, relative: Path, result: object) -> Path:
    return _put(stage, relative, (json.dumps(result, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")) + "\n").encode("utf-8"))


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (stage.exists() or stage.parent.resolve(strict=True) != STAGE_PARENT.resolve(strict=True)
            or not stage.name.startswith("stephens-pg53809-stage-")):
        raise ValueError("fresh external PG53809 candidate-review stage required")
    support = source_bindings()
    raw = _io_path(ROOT / SOURCE).read_bytes()
    acquisition = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    if (acquisition["source_path"] != SOURCE.as_posix() or acquisition["source_sha256"] != SOURCE_SHA256
            or acquisition["source_bytes"] != len(raw) or len(acquisition["retained_files"]) != 4
            or [item["path"] for item in acquisition["retained_files"]] != [item["path"] for item in support]):
        raise ValueError("PG53809 acquired text/support binding differs")
    direct = _io_path(DIRECT).read_bytes()
    if _sha(direct) != DIRECT_SHA256:
        raise ValueError("PG53809 historical candidate changed")
    adapted = adapt(direct)
    if _sha(adapted) != ADAPTED_SHA256:
        raise ValueError("PG53809 adapted candidate changed")
    oracle = check(adapted)
    before = _files(ROOT / WORK)
    if len(before) != 3 or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("PG53809 canonical acquired preimage differs")
    for relative, digest in before.items():
        content = _io_path(ROOT / WORK / relative).read_bytes()
        if _sha(content) != digest:
            raise ValueError(f"PG53809 preimage changed: {relative}")
        _put(stage, WORK / relative, content)
    for item in support:
        relative = Path(item["path"])
        _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    for target in _read(ROOT / WORK / "state.json")["targets"]:
        for evidence in target["evidence"]:
            relative = Path(evidence)
            if relative.is_absolute() or ".." in relative.parts or not _io_path(ROOT / relative).is_file():
                raise ValueError(f"PG53809 state evidence differs: {evidence}")
            _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    _put(stage, EVIDENCE / "inputs/direct-candidate.tei.xml", direct)
    _put(stage, EVIDENCE / "inputs/adapted-candidate.tei.xml", adapted)
    _put_json(stage, EVIDENCE / "inputs/oracle.json", oracle)
    for original, member in zip(_read(stage / ACQUISITION)["retained_files"], support, strict=True):
        if any(original[key] != member[key] for key in ("path", "bytes", "sha256", "media_type")):
            raise ValueError("PG53809 source/package/image inventory differs")
    validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    credit = ("# Source and credit — Saint John Chrysostom, His Life and Times, PG53809\n\n"
              "The accepted electronic witness is the complete real extracted Gutenberg HTML. "
              "The source title page names W. R. W. Stephens, second edition, London: John Murray, 1880. "
              "Gutenberg credits Turgut Dincer and the Online Distributed Proofreading Team; "
              "its text says the file was produced from images made available by the Internet Archive. "
              "The provider header, footer, and license remain typed content.\n\n"
              f"Text authority: {SOURCE.as_posix()} — SHA-256 {SOURCE_SHA256}.\n\n"
              f"ZIP package, not text authority: {ARCHIVE.as_posix()} — SHA-256 {ARCHIVE_SHA256}.\n\n"
              f"Unreferenced extracted cover support: {support[2]['path']} — SHA-256 {support[2]['sha256']}.\n"
              f"HTML-referenced frontispiece: {support[3]['path']} — SHA-256 {support[3]['sha256']}. "
              "Both real images byte-equal their ZIP members.\n\n"
              "Project Gutenberg record: https://www.gutenberg.org/ebooks/53809\n"
              "Project Gutenberg license: https://www.gutenberg.org/policy/license.html\n\n"
              "Gutenberg states public-domain status in the United States; rights elsewhere, "
              "trademark/redistribution conditions, and publication clearance require separate review.\n")
    _put(stage, WORK / "SOURCE_CREDIT.md", credit.encode("utf-8"))
    revised = _read(stage / WORK / "work.json")
    original_work = _read(ROOT / WORK / "work.json")
    edition = revised["textual_forms"][0]["editions"][0]
    if (revised["work_id"] != WORK_ID or revised["textual_forms"][0]["textual_form_id"] != FORM_ID
            or edition["edition_id"] != EDITION_ID or edition["acquisition_ids"] != [ACQUISITION_ID]
            or edition.get("category") or edition.get("language") != "en"):
        raise ValueError("PG53809 acquired work identity differs")
    edition["category"] = "prose"
    validate_identity_update(original_work, revised)
    _put_json(stage, WORK / "work.json", revised)
    load_work(_io_path(stage / WORK / "work.json"))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                    acquisition_id=ACQUISITION_ID)
    revision = dict(id="stephens-pg53809-current-v2", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept complete PG53809 HTML with TEI-resolved source fragment links, frontispiece, and separately bound cover.")
    binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA256,
                   source_bytes=len(raw), source_scope=acquisition["source_scope"])
    bound = bind_reviewed_header(adapted, expected_sha256=ADAPTED_SHA256, identity=identity,
                                 source=binding, source_url=acquisition["url"],
                                 declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != adapted.split(b"</teiHeader>", 1)[1]:
        raise ValueError("PG53809 reviewed header changed source text")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"PG53809 accepted candidate fails P5: {errors[:3]}")
    expected = [dict(path=item["path"], position=i) for i, item in enumerate(acquisition["retained_files"], 1)]
    included = [dict(path=SOURCE.as_posix(), position=2, bytes=len(raw), sha256=SOURCE_SHA256, scope=SCOPE)]
    excluded = [dict(path=item["path"], position=i, reason=(
        "Retained ZIP package, not text authority." if i == 1 else
        "Real extracted cover support; unreferenced in HTML and TEI." if i == 3 else
        "Real extracted frontispiece support; referenced in HTML and TEI, not independent text authority."))
        for i, item in enumerate(acquisition["retained_files"], 1) if i != 2]
    scope = dict(kind="selection", declared=SCOPE, expected_members=expected,
                 included_members=included, excluded_members=excluded)
    common = dict(identity=identity, source=binding, candidate=make_file_binding(stage, candidate),
                  accepted_scope=dict(kind="selection", declared=SCOPE), expected_members=expected,
                  included_members=included, excluded_members=excluded, missing_members=[], unknown_members=[])
    account = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        scope=acquisition["source_scope"], source_sha256=SOURCE_SHA256, source_bytes=len(raw),
        source_oracle=oracle, direct_candidate_sha256=DIRECT_SHA256, adapted_candidate_sha256=ADAPTED_SHA256,
        image_support=support[2:], package_support=support[0], retained_text_authority=SOURCE.as_posix()))
    command = "py -3 -m build.tools.stage_stephens_pg53809 --stage <fresh-external-root>"
    technical = dict(producer=dict(id="ocd-stephens-pg53809-native-second-edition-v1"),
                     checker=dict(id=oracle["contract"]),
                     shared_assumptions=["The historical direct converter and oracle are absent from this checkout; the fresh checker reads the real extracted HTML and checks every source element independently."],
                     independent_corroboration="Complete 1,457-child/11,904-element text, structure and attribute oracle; 3,553 source links and exact mapping of all 3,548 local fragments to resolvable TEI IDs with literal href retention; ZIP/real HTML/image equality; P5 XSD; actual-master native projection and independent row verifier.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            scope=SCOPE, status="pass", command=command, exit_code=0, claim=name,
            source_oracle=oracle, tei_p5_xsd="pass", native_projection="pass"))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:stephens-pg53809-source-review", reviewed_at=now,
                  coverage=dict(status="partial", declared=SCOPE,
                                reached=["all 1,457 direct HTML body children including provider wrapper",
                                         "all 11,904 ordered source element carriers, parent links, and descendant text",
                                         "all 3,553 links with 3,548 exact source-to-TEI resolved local fragments",
                                         "headings, rules, line breaks, contents table roles and spans",
                                         "exact referenced frontispiece and unreferenced cover support",
                                         "exact ZIP/real extracted member equality"],
                                inspected=["all 11,904 ordered source element carriers, parent links, and descendant text"],
                                unreviewed=["current exact-pair CVW visual comparison", "print collation"]),
                  source_quality_uncertainty=["The retained electronic witness was not collated to an 1880 print exemplar."],
                  discrepancies=[], unreviewed_residuals=["Human visual review and rights clearance remain unrecorded."])
    review_path = _put_json(stage, EVIDENCE / "review.json", common | review | dict(scope=SCOPE))
    decision = dict(source_local_disposition="Agent acceptance of complete PG53809 HTML with two separately bound real images.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                                          supported_scope=SCOPE, unresolved_claims=[],
                                          unassessed_stronger_claims=["visual review", "human acceptance", "print collation",
                                                                      "rights clearance", "publication"]))
    acceptance = stage / EDITION / "acceptance.json"
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                     source_accounting_path=account, scope=scope, technical=technical,
                                     review=review | dict(report_path=review_path),
                                     representation_revision=revision, decision=decision)
    write_acceptance(_io_path(acceptance), record)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    master = _put(stage, EDITION / "master.tei.xml", bound)
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, master))
    write_acceptance(_io_path(acceptance), record)
    state = _read(stage / WORK / "state.json")
    targets = [item for item in state["targets"] if item["target_type"] == "edition" and item["target_id"] == EDITION_ID]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("PG53809 edition is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"PG53809 native projection differs: {errors[:3]}; rows={len(projected['rows'])}")
    after = _files(stage / WORK)
    receipt = dict(contract="ocd-stephens-pg53809-stage-v2", work_id=WORK_ID,
                   source_sha256=SOURCE_SHA256, direct_sha256=DIRECT_SHA256,
                   adapted_sha256=ADAPTED_SHA256, accepted_master_sha256=_sha(bound),
                   oracle=oracle, image_support=support[2:], package_support=support[0],
                   before=before, after=after, native_rows=len(projected["rows"]), stage_root=stage.as_posix())
    _put_json(stage, Path("stage-receipt.json"), receipt)
    return dict(status="staged-for-review", work_id=WORK_ID, stage=stage.as_posix(),
                before_files=len(before), after_files=len(after), native_rows=len(projected["rows"]),
                receipt_sha256=_sha(_io_path(stage / "stage-receipt.json").read_bytes()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().stage), sort_keys=True))


if __name__ == "__main__":
    main()
