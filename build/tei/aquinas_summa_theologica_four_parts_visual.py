"""Capture ticket-09 retained-source versus existing-viewer visual pairs."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import shutil
import sys
import tempfile
from zipfile import ZipFile

from PIL import Image, ImageDraw

LOCAL_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(LOCAL_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(LOCAL_REPO_ROOT))

from build.tei import aquinas_summa_theologica_four_parts as summa
from build.tools.tei_viewer_screenshot import (
    REPO_ROOT,
    _RENDER_PROBE,
    _chromium_path,
    _serve,
    _sync_playwright,
)


CHECKS = {
    17611: (
        ("opening", "id00002"),
        ("middle-q60", "id04038"),
        ("terminal-q119-a2", "id07860"),
        ("unusual-implicit-article-q71", "id04760"),
    ),
    17897: (
        ("opening", "id00002"),
        ("middle-q57", "id03809"),
        ("terminal-q114-a10", "id08135"),
        ("unusual-q38-four-versus-five", "id02693"),
    ),
    18755: (
        ("opening", "id00002"),
        ("middle-q95", "id06530"),
        ("terminal-q189-a10", "id12081"),
        ("unusual-bare-sixth-article", "id01741"),
    ),
    19950: (
        ("opening", "id00002"),
        ("middle-q45", "id03234"),
        ("terminal-q90-a4", "id07408"),
        ("unusual-editorial-insertion-q26-q27", "id01912"),
    ),
}


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _scroll_and_capture(page, xml_id: str) -> tuple[str, bytes]:
    result = page.evaluate(
        """(wanted) => {
          const node = [...document.querySelectorAll('[*|id]')]
            .find(item => item.getAttribute('xml:id') === wanted || item.id === wanted);
          if (!node) return null;
          node.scrollIntoView({block: 'center', inline: 'nearest'});
          return node.innerText || node.textContent || '';
        }""",
        xml_id,
    )
    if result is None:
        raise RuntimeError(f"rendered anchor not found: {xml_id}")
    return _normalized(result), page.screenshot()


def _pair(source_png: bytes, tei_png: bytes, label: str) -> Image.Image:
    source = Image.open(BytesIO(source_png)).convert("RGB")
    tei = Image.open(BytesIO(tei_png)).convert("RGB")
    if source.size != tei.size:
        raise RuntimeError(f"visual viewport mismatch: {source.size} versus {tei.size}")
    header = 72
    paired = Image.new("RGB", (source.width * 2, source.height + header), "white")
    paired.paste(source, (0, header))
    paired.paste(tei, (source.width, header))
    draw = ImageDraw.Draw(paired)
    draw.rectangle((0, 0, paired.width, header), fill="#17212b")
    draw.text((24, 14), label, fill="white")
    draw.text((24, 42), "EXACT RETAINED PROJECT GUTENBERG HTML", fill="#9fd3ff")
    draw.text((source.width + 24, 42), "RENDERED TEI CANDIDATE", fill="#aee8bc")
    draw.line((source.width, 0, source.width, paired.height), fill="#17212b", width=4)
    return paired


def capture(candidate: Path, output_dir: Path, raw_root: Path, port: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="ticket09-visual-", dir=REPO_ROOT / ".scratch"
    ) as temporary:
        stage = Path(temporary)
        staged_candidate = stage / "candidate.tei.xml"
        shutil.copyfile(candidate, staged_candidate)
        for spec in summa.COMPONENTS:
            archive_bytes = (raw_root / spec.archive_name).read_bytes()
            if summa._sha256(archive_bytes) != spec.archive_sha256:
                raise RuntimeError(f"PG {spec.pg_id} archive changed before visual capture")
            with ZipFile(BytesIO(archive_bytes)) as archive:
                for member in (spec.html_member, spec.cover_member):
                    (stage / member).write_bytes(archive.read(member))

        rel_stage = stage.relative_to(REPO_ROOT).as_posix()
        with ExitStack() as stack:
            base = stack.enter_context(_serve(REPO_ROOT, port))
            pw = stack.enter_context(_sync_playwright()())
            browser = pw.chromium.launch(
                executable_path=_chromium_path(), headless=True
            )
            stack.callback(browser.close)
            page = browser.new_page(viewport={"width": 1280, "height": 900})

            for spec in summa.COMPONENTS:
                source_url = f"{base}/{rel_stage}/{spec.html_member}"
                viewer_url = (
                    f"{base}/viewer/index.html?file=../{rel_stage}/candidate.tei.xml"
                )
                for label, source_id in CHECKS[spec.pg_id]:
                    page.goto(source_url, wait_until="domcontentloaded")
                    source_text, source_png = _scroll_and_capture(page, source_id)

                    page.goto(viewer_url, wait_until="networkidle")
                    page.wait_for_selector("text=Loaded", timeout=30_000)
                    stats = page.evaluate(_RENDER_PROBE)
                    if not stats["elements_upgraded"] or stats["paragraphs"] == 0:
                        raise RuntimeError("CETEIcean viewer did not render the candidate")
                    if stats["dangling_refs"]:
                        raise RuntimeError(
                            f"viewer has {stats['dangling_refs']} dangling note references"
                        )
                    tei_id = f"pg{spec.pg_id}-{source_id}"
                    tei_text, tei_png = _scroll_and_capture(page, tei_id)
                    if source_text != tei_text:
                        raise RuntimeError(
                            f"PG {spec.pg_id} visual anchor text differs at {source_id}"
                        )
                    paired = _pair(
                        source_png,
                        tei_png,
                        f"PG {spec.pg_id} | {label} | {source_id} | exact anchor text equal",
                    )
                    paired.save(
                        output_dir / f"pg{spec.pg_id}.{label}.source-vs-tei.png",
                        format="PNG",
                        optimize=True,
                    )


def contact_sheets(output_dir: Path) -> None:
    for pg_id, checks in CHECKS.items():
        images = [
            Image.open(
                output_dir / f"pg{pg_id}.{label}.source-vs-tei.png"
            ).convert("RGB")
            for label, _ in checks
        ]
        width = 1920
        resized = [
            image.resize(
                (width, round(image.height * width / image.width)),
                Image.Resampling.LANCZOS,
            )
            for image in images
        ]
        sheet = Image.new("RGB", (width, sum(image.height for image in resized)), "white")
        top = 0
        for image in resized:
            sheet.paste(image, (0, top))
            top += image.height
        sheet.save(
            output_dir / f"pg{pg_id}.four-check-contact-sheet.png",
            format="PNG",
            optimize=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--port", type=int, default=8949)
    parser.add_argument("--contact-only", action="store_true")
    args = parser.parse_args()
    if args.contact_only:
        contact_sheets(args.output_dir)
        print("wrote 4 contact sheets")
        return 0
    raw_root = args.raw_root or summa.resolve_repo_path(
        summa.REPOSITORY_ROOT, summa.RAW_LOGICAL_ROOT
    )
    capture(args.candidate, args.output_dir, raw_root, args.port)
    contact_sheets(args.output_dir)
    print(f"wrote {sum(len(checks) for checks in CHECKS.values())} visual pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
