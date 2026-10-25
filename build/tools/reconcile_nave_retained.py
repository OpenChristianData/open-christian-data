"""Reconcile the retained Nave package with its actual extracted binary sources.

This does not import or run the converter, reconstruct TEI, or alter authority.
The historical independent oracle's strict binary decoder and source signature
are reused explicitly; fresh packaging and accepted-header proof are separate.
"""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei import naves_topical_bible_oracle as oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.topical_indexes import project_topical_indexes_document


ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "reports/_logs/naves-topical-bible-current-reconciliation-20261002-v1"
RETAINED = Path("D:/Library/Open Christian Data/candidate-reviews/l876-naves-topical-crosswire-v3-v2")
EXPECTED_TEI = "eb8504033ade25981d56ec6249b87b5184c599cc70270cca3cee650ad2adf1f5"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise FileExistsError(f"Frozen Nave evidence differs: {path}")
    else:
        path.write_bytes(raw)


def main():
    module = ROOT / "raw/naves_topical/modules/lexdict/zld/nave"
    files = {name: (module / name).read_bytes() for name in ("dict.idx", "dict.dat", "dict.zdx", "dict.zdt")}
    conf = (ROOT / "raw/naves_topical/mods.d/nave.conf").read_bytes()
    archive = (ROOT / "raw/naves_topical/Nave.zip").read_bytes()
    candidate = (RETAINED / "package/content.tei.xml").read_bytes()
    if sha(candidate) != EXPECTED_TEI:
        raise ValueError("Historical Nave TEI drifted")
    blocks, rows = oracle._inflate_source(files["dict.idx"], files["dict.dat"], files["dict.zdx"], files["dict.zdt"])
    oracle._census(blocks, rows)
    tree, markup = oracle._verify_candidate_tei(candidate, rows)
    extracted = {"modules/lexdict/zld/nave/" + name: value for name, value in files.items()}
    extracted["mods.d/nave.conf"] = conf
    archive_members = oracle._raw_archive(archive, extracted)
    accountability = json.loads((RETAINED / "package/source-accountability.json").read_bytes())
    expected = oracle._expected_accountability(blocks, rows, markup, archive_members)
    if accountability != expected:
        raise ValueError("Historical Nave accountability differs from actual binary source")
    body = tree.find("{http://www.tei-c.org/ns/1.0}text")
    reference_counts = Counter()
    attributes = {}
    empty_references = 0
    for node in body.iter():
        tag = etree.QName(node).localname
        attributes.setdefault(tag, set()).update(node.attrib)
        if tag == "ref":
            reference_counts[node.get("type", "topic-target")] += 1
            if not "".join(node.itertext()):
                empty_references += 1
    context = {"identity": {"work_id": "naves-topical-bible", "textual_form_id": "naves-topical-bible-retained-electronic", "edition_id": "naves-topical-bible-retained-electronic-witness"}, "language": "en", "representation_revision": "nave-retained-native-technical-v1", "edition_title": "Nave SWORD module v3 retained electronic witness"}
    try:
        project_topical_indexes_document(RETAINED / "package/content.tei.xml", **context)
    except PipelineError as exc:
        located_failure = str(exc)
    else:
        raise ValueError("Unexpected current generic support: review actual result")
    manifest = json.loads((RETAINED / "package/manifest.json").read_bytes())
    for member in manifest["members"]:
        raw = (RETAINED / "package" / member["name"]).read_bytes()
        if len(raw) != member["bytes"] or sha(raw) != member["sha256"]:
            raise ValueError(f"Retained package member drift: {member['name']}")
        save(LOG / "historical-package" / member["name"], raw)
    save(LOG / "historical-package/manifest.json", (RETAINED / "package/manifest.json").read_bytes())
    save(LOG / "historical-validation.json", (RETAINED / "validation.json").read_bytes())
    report = {
        "status": "pass", "observed_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Actual extracted source -> strict independent binary decode -> exact historical native XML comparison and complete source accountability; no converter or historical full-package oracle invoked.",
        "independence": "Historical oracle uses stdlib ElementTree for source fragments, manual raw-ZIP/DEFLATE validation and lxml actual candidate traversal. This is reused oracle proof, not a second independent implementation; root direct comparison remains separate.",
        "candidate_sha256": sha(candidate), "text_sha256": sha(etree.tostring(body)),
        "source_members": {name: {"bytes": len(value), "sha256": sha(value)} for name, value in files.items()},
        "support_conf_sha256": sha(conf), "acquisition_archive_sha256": sha(archive),
        "decoder_path": "build/tei/naves_topical_bible_oracle.py", "decoder_sha256": sha((ROOT / "build/tei/naves_topical_bible_oracle.py").read_bytes()),
        "reviewer_sha256": sha(Path(__file__).read_bytes()),
        "entry_count": len(rows), "block_count": len(blocks), "markup_counts": markup,
        "reference_counts": dict(reference_counts), "empty_reference_labels": empty_references,
        "native_attributes": {name: sorted(values) for name, values in attributes.items()},
        "ordered_source_units": [{key: row[key] for key in ("ordinal", "dictionary_key", "payload_n", "block", "entry_in_block", "payload_sha256", "payload_body_sha256")} for row in rows],
        "accountability_exact": True, "format_terminators_and_padding_explicit": True,
        "actual_current_projector_failure": located_failure,
        "qualification": "No rights, print-edition identity, human acceptance or publication judgment. Header/current package/accepted linkage remain separate.",
    }
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    save(LOG / "retained-source-native-review.json", raw)
    print(json.dumps({"status": "pass", "report_sha256": sha(raw), "entries": len(rows), "blocks": len(blocks), "markup_counts": markup, "reference_counts": dict(reference_counts), "empty_reference_labels": empty_references, "actual_current_projector_failure": located_failure}))


if __name__ == "__main__":
    main()
