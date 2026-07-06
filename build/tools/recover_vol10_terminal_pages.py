"""
recover_vol10_terminal_pages.py -- one-shot recovery of NSH vol_10 pages 497-499.

Context
-------
The primary IA scan ("NewSchaffHerzogEncyclopediaOfReligious") was missing the
final body pages of volume 10 and carried a scandata page_count of 508. Direct
inspection of an edition-matched alternate scan
("the-new-schaff-herzog-encylopedia-volume-10", a Stanford copy) established:

  * printed page 496 == "Sohm" running header -- identical to the repo's page 496,
    confirming the alternate is the same edition/pagination.
  * leaves 517/518/519 carry printed pages 497/498/499 (real article content:
    Solomon, Son of God, etc.).
  * leaf 519 (page 499) ends with "END OF VOLUME X." -- the volume body ends at 499.
  * leaves 520+ are blank endpapers / the back cover (verified by image).

Therefore:
  * pages 497, 498, 499 are recovered from the alternate (this script).
  * pages 500-508 DO NOT EXIST; page_count is corrected 508 -> 499 and the nine
    phantom permanently_missing gap records are removed.

This is a one-shot patch (idempotent: re-running re-fetches the same three pages
and re-applies the same correction). It is NOT part of the routine pipeline.
"""

import hashlib
import io
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_ia_pages import (  # noqa: E402
    JPEG_QUALITY,
    USER_AGENT,
    load_manifest,
    write_manifest_atomic,
)
from PIL import Image  # noqa: E402
from remotezip import RemoteZip  # noqa: E402

REPO_ROOT = Path(__file__).parents[2]
VOL_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_10"
MANIFEST = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_10.manifest.json"

ALT_ITEM = "the-new-schaff-herzog-encylopedia-volume-10"
ZIP_NAME = "The New Schaff-Herzog Encylopedia, Volume 10_jp2.zip"
PREFIX = ZIP_NAME.replace("_jp2.zip", "")

# (leaf in alternate item, printed page in repo)
RECOVER = [(517, 497), (518, 498), (519, 499)]
CORRECT_PAGE_COUNT = 499          # volume body ends at p499 ("END OF VOLUME X")
DROP_GAP_PAGES = set(range(497, 509))  # 497-499 now present; 500-508 never existed

REPLACEMENT_REASON = (
    "Missing from primary scan. Recovered from edition-matched alternate IA item "
    "(the-new-schaff-herzog-encylopedia-volume-10, Stanford copy; printed page 496 "
    "matches the primary 'Sohm' page). Volume body ends at p499 ('END OF VOLUME X'); "
    "the primary scandata page_count of 508 was inflated -- pages 500-508 do not exist."
)


def main() -> int:
    zip_url = f"https://archive.org/download/{ALT_ITEM}/" + urllib.parse.quote(ZIP_NAME)
    headers = {"User-Agent": USER_AGENT}

    new_entries = []
    with RemoteZip(zip_url, headers=headers, timeout=120) as rz:
        names = rz.namelist()
        for leaf, page in RECOVER:
            internal = f"{PREFIX}_jp2/{PREFIX}_{leaf:04d}.jp2"
            if internal not in names:
                cand = [n for n in names if f"_{leaf:04d}.jp2" in n]
                if not cand:
                    raise RuntimeError(f"leaf {leaf} not found in {ZIP_NAME}")
                internal = cand[0]
            jp2 = rz.read(internal)
            img = Image.open(io.BytesIO(jp2))
            image_mode = img.mode
            image_size = list(img.size)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
            jpeg = buf.getvalue()
            jpeg_path = VOL_DIR / f"page_{page:04d}.jpg"
            jpeg_path.write_bytes(jpeg)
            sha256 = "sha256:" + hashlib.sha256(jpeg).hexdigest()
            entry = {
                "page_num": page,
                "ia_leaf_id": f"{leaf:04d}",
                "ia_filename": f"{ZIP_NAME}/{internal}",
                "local_path": jpeg_path.relative_to(REPO_ROOT).as_posix(),
                "sha256": sha256,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "image_mode": image_mode,
                "image_size": image_size,
                "ia_item_id": ALT_ITEM,
                "provenance": {
                    "source_item_id": ALT_ITEM,
                    "source_leaf": leaf,
                    "derivation": "direct",
                    "crop_box": None,
                    "replacement_reason": REPLACEMENT_REASON,
                    "validation_status": "visual_header_confirmed",
                    "dimension_variance": True,
                },
            }
            new_entries.append(entry)
            print(f"recovered page {page} <- leaf {leaf}  size={image_size}  {sha256[:23]}...")

    # --- manifest correction ---
    manifest = load_manifest(MANIFEST)
    pages = [e for e in manifest.get("pages", []) if e.get("page_num") not in {p for _, p in RECOVER}]
    pages.extend(new_entries)
    pages.sort(key=lambda e: e["page_num"])
    manifest["pages"] = pages

    old_count = manifest.get("page_count")
    manifest["page_count"] = CORRECT_PAGE_COUNT

    gaps = [g for g in manifest.get("gaps", []) if g.get("page_num") not in DROP_GAP_PAGES]
    dropped = len(manifest.get("gaps", [])) - len(gaps)
    manifest["gaps"] = gaps

    # Remove the now-stale leaf-gap warning about page 500.
    warnings = manifest.get("manifest_warnings", [])
    new_warnings = [w for w in warnings if "page_num 500" not in w]
    if len(new_warnings) != len(warnings):
        manifest["manifest_warnings"] = new_warnings

    write_manifest_atomic(MANIFEST, manifest)

    print()
    print(f"page_count {old_count} -> {CORRECT_PAGE_COUNT}")
    print(f"pages[] entries: {len(pages)}")
    print(f"gap records dropped: {dropped} (pages 497-508)")
    print(f"stale warnings removed: {len(warnings) - len(new_warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
