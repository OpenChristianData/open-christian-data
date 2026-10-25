"""Freeze a successful Donne stage and preflight the maintained visible notices."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from build.tools.prepare_donne_devotions import ROOT, BASE, WORK_ID, EDITION, DATA_NOTICE, canonical
from ocd_kernel.release.notices import notice_texts_for_item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promoted", type=Path, required=True)
    args = parser.parse_args()
    receipt = args.promoted / "stage-receipt.json"
    raw = receipt.read_bytes()
    record = json.loads(raw)
    if record["status"] != "pass" or record["source_facts"]["represented_lines"] != 6842 or record["rows"] != 3:
        raise ValueError("corrected Donne stage incomplete")
    schema = ROOT / "schemas/v2/native-content.schema.json"
    pin = dict(work_id=WORK_ID, receipt=receipt.as_posix(), receipt_sha256=sha256(raw).hexdigest(),
               native_schema_sha256=sha256(schema.read_bytes()).hexdigest())
    (ROOT / BASE / "stage-pin.json").write_bytes(canonical(pin))
    source = BASE / "README.source.md"
    item = dict(item_id=WORK_ID, category="prose", acceptance_path=(EDITION / "acceptance.json").as_posix(),
                public_notices=[dict(source_path=source.as_posix(), source_sha256=sha256((ROOT/source).read_bytes()).hexdigest(),
                notice_path=DATA_NOTICE.as_posix(), notice_sha256=sha256((ROOT/DATA_NOTICE).read_bytes()).hexdigest())])
    notices = notice_texts_for_item(ROOT, item, args.promoted / EDITION / "acceptance.json")
    (ROOT / "reports/_logs/donne-reconciliation-20261001-v2/notice-preflight.json").write_bytes(canonical(dict(
        status="pass", item=item, notice_count=len(notices), method="Maintained cheap notice checker using staged acceptance identity and canonical source/data files; no canonical acceptance claimed.")))
    print(json.dumps(pin))


if __name__ == "__main__":
    main()
