"""Relocated OCR diagnostic; run it from the EzraOCR repository."""
import sys


def main() -> int:
    print("This OCR diagnostic moved to EzraOCR. From that repository run: "
          "py -3 ezra/tools/probe_nsh_scandata.py [volumes]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
