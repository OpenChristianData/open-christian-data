"""Concrete L599 header/state/native proposal only; no acceptance or staging."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from build.tei import l599_slave_trade_source_facts as facts
from ocd_kernel.library.identities import validate_record
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header

LOG = ROOT / "reports/_logs/l599-slave-trade-existing-20261004-v1"
HOME = ROOT / "sources/manifest-acquisitions/l599-slave-trade-header-proposal-v1"
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/l599-readable-source-20261004-v4/package")
REVIEW = LOG / "root-final-source-review-v4.json"
REVIEW_SHA = "1d0ae14608dbbed908e3b493c5279b1e32b32b351b93026d8da51fc9fbd7ab38"
N = "{http://www.tei-c.org/ns/1.0}"
OLD_STATUS = "Nonaccepted source-to-TEI candidate for retained Wikisource contributor transcription. Rights and attribution review remain unresolved; publication is not authorized."
CURRENT_STATUS = ("Evidence-backed retained Wikisource TEI master representation. Technical agent source review passed. "
                  "Technical acceptance is recorded separately in acceptance and state sidecars; dated nonaccepted "
                  "source-package labels describe preserved historical evidence. The Appendix and Notes A-C remain "
                  "source gaps. Human and print review, complete contributor-history attribution, rights clearance, "
                  "and publication remain unresolved; publication is not authorized.")
REVISION_ID = "l599-slave-trade-retained-readable-20261004-v1"
REVISION_NOTE = ("Existing retained Wikisource title reconstructed in its source-defined main-transclusion context; "
                 "complete retained XML administration, contributor credit, attached notes, links, source styling "
                 "and quotation ownership conserved. Appendix and Notes A-C remain explicit unretained gaps. "
                 "Current stable work, form, edition and acquisition identity bound after technical source review.")


def pin(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def parse(raw):
    return etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_blank_text=False))


def bound(raw, acquisition, revision):
    if facts.sha(raw) != facts.REPAIRED_TEI_PIN or raw.count(OLD_STATUS.encode()) != 1:
        raise ValueError("L599 frozen content/publication statement differs")
    root = parse(raw)
    header = root.find(N + "teiHeader")
    ns = {"t": N[1:-1]}
    historical = {"pointers": header.xpath(".//t:sourceDesc//t:ptr/@target", namespaces=ns),
                  "sha256": header.xpath(".//t:idno[@type='sha256']/text()", namespaces=ns)}
    source = {key: acquisition[key] for key in ["source_path", "source_sha256", "source_bytes", "source_scope"]}
    prepared = raw.replace(OLD_STATUS.encode(), CURRENT_STATUS.encode(), 1)
    result = bind_reviewed_header(prepared, expected_sha256=facts.sha(prepared), identity=facts.IDENTITY,
                                  source=source, source_url=acquisition["url"], declared_scope=acquisition["source_scope"],
                                  revision=revision, historical_source_description=historical)
    if result.split(b"</teiHeader>", 1)[1] != raw.split(b"</teiHeader>", 1)[1]:
        raise ValueError("L599 accepted-header proposal changed exact source text bytes")
    return result


def inverse(actual, raw, acquisition, revision):
    if actual != bound(raw, acquisition, revision):
        raise ValueError("L599 actual header is not exact ordered recomputation")
    restored = actual
    open_bibl = b'<bibl xmlns="http://www.tei-c.org/ns/1.0" type="ocd-acceptance-binding">'
    if restored.count(open_bibl) != 1:
        raise ValueError("L599 exact added binding boundary differs")
    start = restored.index(open_bibl)
    end = restored.index(b"</bibl>", start) + len(b"</bibl>")
    binding = restored[start:end]
    restored = restored[:start] + restored[end:]
    existing_revision = parse(raw).find(N + "teiHeader/" + N + "revisionDesc")
    opening, closing = ((b'<revisionDesc xmlns="http://www.tei-c.org/ns/1.0">', b"</revisionDesc>") if existing_revision is None
                        else (b'<change xmlns="http://www.tei-c.org/ns/1.0" xml:id="' + revision["id"].encode() + b'"', b"</change>"))
    if restored.count(opening) != 1:
        raise ValueError("L599 exact revision addition boundary differs")
    start = restored.index(opening)
    end = restored.index(closing, start) + len(closing)
    added_revision = restored[start:end]
    restored = (restored[:start] + restored[end:]).replace(CURRENT_STATUS.encode(), OLD_STATUS.encode(), 1)
    if restored != raw:
        raise ValueError("L599 deleting only header additions/status renewal did not recover whole original bytes")
    return restored, {"binding_sha256": facts.sha(binding), "revision_sha256": facts.sha(added_revision),
                      "whole_document_byte_inverse": True, "source_text_bytes_unchanged": True}


def prepare():
    if HOME.exists() or pin(REVIEW)["sha256"] != REVIEW_SHA:
        raise ValueError("Preserve existing draft or root source review differs")
    if pin(LOG / "source-final-review-v4.json")["sha256"] != "02216de04b0c5660b61022e8160b5894e0107148ae6f43b7d64312f1ab90016e":
        raise ValueError("L599 completed source packet differs")
    originals = facts.original_identity()["records"]
    work, state, acquisition = [row["record"] for row in originals]
    for name, value in [("work", work), ("state", state), ("acquisition", acquisition)]:
        validate_record(name, value, context="L599 preserved original")
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    revision = {"id": REVISION_ID, "date": at[:10], "note": REVISION_NOTE}
    raw = (PACKAGE / "content.tei.xml").read_bytes()
    master = bound(raw, acquisition, revision)
    recovered, inverse_report = inverse(master, raw, acquisition, revision)
    schema = etree.XMLSchema(etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"), etree.XMLParser(resolve_entities=False, no_network=True)))
    if not schema.validate(parse(master)):
        raise ValueError("L599 header proposal P5 failed: " + str(schema.error_log.last_error))
    edition = "forms/" + facts.IDENTITY["textual_form_id"] + "/editions/" + facts.IDENTITY["edition_id"]
    proposal = json.loads(json.dumps(state))
    target = next(row for row in proposal["targets"] if row["target_type"] == "edition" and row["target_id"] == facts.IDENTITY["edition_id"])
    target.update(stage="accepted", updated_at=at, reason=PROMOTED_MASTER_REASON,
                  evidence=["library/works/" + facts.WORK + "/" + edition + "/master.tei.xml",
                            "library/works/" + facts.WORK + "/" + edition + "/acceptance.json",
                            REVIEW.relative_to(ROOT).as_posix(), (LOG / "source-final-review-v4.json").relative_to(ROOT).as_posix()])
    validate_record("state", proposal, context="L599 proposed future accepted state; not installed")
    if [r for r in proposal["targets"] if r["target_type"] == "acquisition"] != [r for r in state["targets"] if r["target_type"] == "acquisition"]:
        raise ValueError("L599 proposal changed original acquisition target")
    HOME.mkdir()
    (HOME / "candidate.tei.xml").write_bytes(master)
    (HOME / "inverse-source-candidate.tei.xml").write_bytes(recovered)
    (HOME / "original-reviewed-header.xml").write_bytes(etree.tostring(parse(raw).find(N + "teiHeader"), encoding="UTF-8"))
    (HOME / "state-proposal.json").write_bytes(facts.enc(proposal))
    (HOME / "SOURCE_CREDIT.md").write_bytes((PACKAGE / "README.source.md").read_bytes())
    for row in originals:
        (HOME / ("original-" + Path(row["path"]).name)).write_bytes((ROOT / row["snapshot"]).read_bytes())
    record = {"status": "P5-valid-header-and-state-proposal-only", "identity": facts.IDENTITY, "created_at": at, "revision": revision,
              "source_review": pin(REVIEW), "source_packet": pin(LOG / "source-final-review-v4.json"),
              "source_candidate": pin(PACKAGE / "content.tei.xml"), "header_bound_candidate": pin(HOME / "candidate.tei.xml"),
              "exact_inverse": inverse_report, "state_proposal": pin(HOME / "state-proposal.json"),
              "reader_scope": {"category": "prose", "language": "en", "collection": False, "edition_title": work["textual_forms"][0]["editions"][0]["title"],
                               "declared_reading": facts.SCOPE, "source_scope": acquisition["source_scope"],
                               "Appendix_and_Notes_A_C": "unretained; unknown extent", "source_revision_credit": pin(HOME / "SOURCE_CREDIT.md")},
              "unchanged_original_identity": originals,
              "files": [pin(p) for p in sorted(HOME.iterdir())],
              "qualification": "No acceptance sidecar, installation stage, reader admission or canonical change. Future state is a schema-valid proposal only. Agent source review remains separate from human/print review, full contributor history, rights clearance and publication."}
    (HOME / "proposal.json").write_bytes(facts.enc(record))
    return pin(HOME / "proposal.json")


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
