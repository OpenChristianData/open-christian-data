"""Freeze a successful YLT retained Bible stage and preflight the maintained visible notices."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_ylt_current import ROOT, BASE, WORK_ID, EDITION, DATA_NOTICE, canonical
from ocd_kernel.release.notices import notice_texts_for_item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promoted", type=Path, required=True)
    args = parser.parse_args()
    receipt = args.promoted / "stage-receipt.json"
    raw = receipt.read_bytes()
    record = json.loads(raw)
    if record["status"] != "pass" or record["source_facts"]["verse_carriers"] != 31102 or record["rows"] != 31102:
        raise ValueError("corrected YLT retained Bible stage incomplete")
    relevant = ['schemas/v2/tei/controlled-values.json','schemas/v2/tei/extensions.json','schemas/v2/tei/profile-registry.json','ocd_kernel/reconstruction/verifier.py','build/lib/tei_xsd.py','ocd_kernel/lib/storage_topology.py']
    relevant += [p.relative_to(ROOT).as_posix() for p in (ROOT/'ocd_kernel/tei/vendor/xsd').glob('*.xsd')]
    closure={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in relevant}
    pin = dict(work_id=WORK_ID, receipt=receipt.as_posix(), receipt_sha256=sha256(raw).hexdigest(),
               relevant_dependency_supplement=closure, qualification="Relevant Bible/identity/P5 closure; unrelated liturgy/native policies excluded. Supplement measured at freeze, not asserted as original stage before-pin.")
    (ROOT / BASE / "stage-pin.json").write_bytes(canonical(pin))
    source = BASE / "publication/ylt/README.source.md"
    item = dict(item_id=WORK_ID, category="bible", acceptance_path=(EDITION / "acceptance.json").as_posix(),
                public_notices=[dict(source_path=source.as_posix(), source_sha256=sha256((ROOT/source).read_bytes()).hexdigest(),
                notice_path=DATA_NOTICE.as_posix(), notice_sha256=sha256((ROOT/DATA_NOTICE).read_bytes()).hexdigest())])
    notices = notice_texts_for_item(ROOT, item, args.promoted / EDITION / "acceptance.json")
    (ROOT / "reports/_logs/ylt-current-reconciliation-20261002-v1/notice-preflight.json").write_bytes(canonical(dict(
        status="pass", item=item, notice_count=len(notices), method="Maintained cheap notice checker using staged acceptance identity and canonical source/data files; no canonical acceptance claimed.")))
    print(json.dumps(pin))


if __name__ == "__main__":
    main()
