"""
delete_dup_terminal_pages.py -- Remove wrongly-placed terminal-fetch duplicates.

After the phantom fix renamed pages in vol_10 and vol_11, the terminal fetcher
re-fetched pages using the stale IA scandata page→leaf mapping. This produced
files at the new positions (e.g. page_0497.jpg) with the content that belongs
at lower positions (e.g. page_0489.jpg). sha256 confirms byte-for-byte identity.

This script deletes the wrongly-placed duplicate files.

vol_10: page_0497-0499.jpg are duplicates of page_0489-0491.jpg
vol_11: page_0506-0508.jpg are duplicates of page_0503-0505.jpg
"""

import pathlib

OCD = pathlib.Path(__file__).parents[2]
VOL10 = OCD / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_10"
VOL11 = OCD / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_11"

TO_DELETE = [
    (VOL10, [497, 498, 499]),
    (VOL11, [506, 507, 508]),
]

for vol_dir, pages in TO_DELETE:
    for pn in pages:
        f = vol_dir / f"page_{pn:04d}.jpg"
        if f.exists():
            f.unlink()
            print(f"Deleted {vol_dir.name}/page_{pn:04d}.jpg")
        else:
            print(f"Already absent: {vol_dir.name}/page_{pn:04d}.jpg")

print()
print("Verification:")
for vol_dir, _ in TO_DELETE:
    present = sorted(int(f.stem.split("_")[1]) for f in vol_dir.glob("page_*.jpg"))
    print(f"  {vol_dir.name}: count={len(present)}, max={max(present)}, last 5={present[-5:]}")
