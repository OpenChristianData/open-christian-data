"""inspect_sword_zld.py
One-time binary format probe for the SWORD Nave zLD module.
Run: py -3 build/scripts/inspect_sword_zld.py

Probes both the rawLD (dict.idx + dict.dat) and zLD (dict.zdx + dict.zdt) files.
Outputs findings needed to write the parser.
"""

import struct
import sys
import zlib
from pathlib import Path

# Force UTF-8 output so we can print Unicode content on Windows cp1252 consoles
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = REPO_ROOT / "raw" / "naves_topical" / "modules" / "lexdict" / "zld" / "nave"

IDX = BASE / "dict.idx"
DAT = BASE / "dict.dat"
ZDX = BASE / "dict.zdx"
ZDT = BASE / "dict.zdt"


def hex_dump(data: bytes, n: int = 80) -> str:
    return " ".join(f"{b:02x}" for b in data[:n])


def probe_rawld():
    print("=" * 60)
    print("RAWLD FORMAT: dict.idx + dict.dat")
    print("=" * 60)
    idx = IDX.read_bytes()
    dat = DAT.read_bytes()
    print(f"dict.idx size: {len(idx):,} bytes")
    print(f"dict.dat size: {len(dat):,} bytes")

    # Try 6-byte entries (same as sword_devotional.py)
    entry_size = 6
    n_entries = len(idx) // entry_size
    print(f"\nIf entry_size=6: {n_entries} entries")
    print("First 10 entries (offset_in_dat:4, size:2):")
    for i in range(min(10, n_entries)):
        off, sz = struct.unpack_from("<IH", idx, i * entry_size)
        raw = dat[off: off + sz]
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = repr(raw[:80])
        print(f"  [{i:4d}] off={off:7d} sz={sz:4d}  content={text[:100]!r}")

    # Last few entries
    print(f"\nLast 5 entries:")
    for i in range(max(0, n_entries - 5), n_entries):
        off, sz = struct.unpack_from("<IH", idx, i * entry_size)
        raw = dat[off: off + sz]
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = repr(raw[:80])
        print(f"  [{i:4d}] off={off:7d} sz={sz:4d}  content={text[:100]!r}")


def probe_zld():
    print("\n" + "=" * 60)
    print("ZLD FORMAT: dict.zdx + dict.zdt")
    print("=" * 60)
    zdx = ZDX.read_bytes()
    zdt = ZDT.read_bytes()
    print(f"dict.zdx size: {len(zdx):,} bytes")
    print(f"dict.zdt size: {len(zdt):,} bytes")
    print(f"dict.zdx first 128 bytes: {hex_dump(zdx, 128)}")
    print(f"dict.zdt first 128 bytes: {hex_dump(zdt, 128)}")

    # Try fixed-size entries in zdx
    print("\nTrying zdx as fixed-size entries:")
    for esz in (4, 6, 8, 10, 12):
        n = len(zdx) // esz
        print(f"  If size={esz}: {n} entries, first entry hex: {zdx[:esz].hex()}")

    # Try first 4 bytes as uint32 count
    if len(zdx) >= 4:
        count = struct.unpack_from("<I", zdx, 0)[0]
        print(f"\nzdx[0:4] as uint32 = {count} (possible entry count?)")

    # Try cstring+suffix in zdx
    print("\nTrying zdx as cstring+suffix entries:")
    for suffix_sz in (4, 6, 8):
        entries = []
        pos = 0
        try:
            while pos < min(len(zdx), 3000) and len(entries) < 8:
                null = zdx.index(b"\x00", pos)
                key = zdx[pos:null].decode("utf-8", errors="replace")
                suffix = zdx[null + 1: null + 1 + suffix_sz]
                if len(suffix) < suffix_sz:
                    break
                entries.append((key, suffix.hex()))
                pos = null + 1 + suffix_sz
            if entries:
                print(f"\n  suffix_sz={suffix_sz}: first {len(entries)} keys found:")
                for k, s in entries[:6]:
                    print(f"    key={k!r:30s}  suffix={s}")
        except (ValueError, UnicodeDecodeError) as e:
            print(f"  suffix_sz={suffix_sz}: failed ({e})")

    # Probe zdt for compressed blocks
    print("\nProbing zdt for compressed blocks:")
    for header_fmt, header_sz, label in [
        ("<I", 4, "(comp_len:4)"),
        ("<II", 8, "(uncomp:4)(comp:4)"),
    ]:
        pos = 0
        found = 0
        print(f"\n  Trying header {label}:")
        while pos < min(len(zdt), 200_000) and found < 4:
            if pos + header_sz > len(zdt):
                break
            vals = struct.unpack_from(header_fmt, zdt, pos)
            comp_len = vals[-1]  # last value is always compressed length
            if comp_len == 0 or comp_len > 500_000:
                print(f"    pos={pos}: vals={vals} -> comp_len unreasonable, stopping")
                break
            block = zdt[pos + header_sz: pos + header_sz + comp_len]
            try:
                plain = zlib.decompress(block)
                print(f"    pos={pos}: header={vals} comp={comp_len} plain={len(plain)} first={plain[:120]!r}")
                found += 1
                pos += header_sz + comp_len
            except zlib.error as e:
                if found == 0 and pos < 10:
                    pos += 1  # try next byte alignment only at start
                else:
                    print(f"    pos={pos}: zlib error: {e}")
                    break


def main():
    print("SWORD Nave zLD Binary Inspection")
    print(f"Base path: {BASE}")
    probe_rawld()
    probe_zld()
    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
