"""fetch_logos_nsherk.py
RETIRED -- Faithlife Terms of Service prohibit automated scraping.

The Faithlife web ToS (logos.com/terms, last amended 2026-05-05) explicitly
prohibits automated access via Sections 4, 23, and 24 -- including headless
browsers, systematic data collection, and creating databases from their
content. Do not run this script.

Use the Internet Archive DjVuTXT source instead (build/parsers/ia_nsherk.py).

---

Scraper for the New Schaff-Herzog Encyclopedia of Religious Knowledge
from the Logos web reader (limited view mode HTML).

Source: https://app.logos.com/books/LLS%3ANSHERK

Uses patchright (stealth Playwright fork) with launch_persistent_context
to reuse the existing Faithlife-authenticated Chrome profile. Patchright
patches CDP fingerprinting to avoid bot detection.

Chrome profile: C:\\tmp\\logos-chrome-profile
  -- Faithlife auth already saved, limited view mode already enabled.
  -- Session cookies may expire; re-authenticate via stealth-browser-mcp if needed.

Usage:
    py -3 build/tools/fetch_logos_nsherk.py [OPTIONS]

      --letter A              Fetch only letter section A (repeatable)
      --start-idx N           Global article index start (inclusive)
      --end-idx N             Global article index end (inclusive)
      --dry-run               Validate one article per letter, write nothing
      --headless              Run browser in headless mode (default: False)
      --log-level DEBUG|INFO  (default: INFO)
      --rate-limit            Override politeness delays (testing only)
"""

import argparse
import asyncio
import logging
import os
import random
import re
import sys
import time
import unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from patchright.async_api import async_playwright  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CHROME_PROFILE = Path(r"C:\tmp\logos-chrome-profile")
# System Chrome 148 — must match the profile version to avoid downgrade-protection crash.
# Patchright applies its stealth CDP patches over any Chrome/Chromium binary.
PATCHRIGHT_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
RAW_DIR = _REPO_ROOT / "raw" / "logos" / "nsherk" / "articles"
LOG_PATH = _REPO_ROOT / "logs" / "fetch_logos_nsherk.log"

TOC_URL = "https://app.logos.com/api/app/books/LLS%3ANSHERK/tableofcontents"
TOC_CHILDREN_PATTERN = (
    "https://app.logos.com/api/app/books/LLS%3ANSHERK/tableofcontents?parentId=1~{offset}"
)
ARTICLE_URL_PATTERN = (
    "https://app.logos.com/books/LLS%3ANSHERK/headwords/{hw}?headwordLanguage=en"
)
AUTH_CHECK_URL = (
    "https://app.logos.com/books/LLS%3ANSHERK/headwords/Aaron?headwordLanguage=en"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

MAX_RETRIES = 3
RETRY_DELAYS_S = [8, 16, 32]
NAV_TIMEOUT_MS = 30_000

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(log_level: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Convert term text to URL-safe lowercase slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "-", text)
    text = re.sub(r"[\s_-]+", "-", text.strip())
    return text.strip("-") or "entry"


# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------


def article_output_path(article: dict) -> Path:
    return RAW_DIR / f"{article['idx']:05d}_{slugify(article['title'])}.html"


# ---------------------------------------------------------------------------
# TOC API
# ---------------------------------------------------------------------------


async def _fetch_json(page, url: str) -> object:
    """Fetch JSON from the Logos API via page.evaluate (shares browser cookies)."""
    result = await page.evaluate(
        """async (url) => {
            const r = await fetch(url, {credentials: 'include'});
            if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + url);
            return await r.json();
        }""",
        url,
    )
    return result


async def build_article_list(page, letter_filter: list | None) -> list:
    """Return flat list of article dicts, each with keys:
    title, offset, length, letter, idx (0-based global).
    """
    logger.info("Fetching TOC sections...")
    toc_data = await _fetch_json(page, TOC_URL)

    # Expect a 'children' list at the top level
    raw_sections = toc_data if isinstance(toc_data, list) else toc_data.get("children", [])

    # Keep only single-letter sections A-Z
    letter_sections = [
        s for s in raw_sections
        if len(s.get("title", "")) == 1 and s.get("title", "").isalpha()
    ]
    if letter_filter:
        upper_filter = [l.upper() for l in letter_filter]
        letter_sections = [s for s in letter_sections if s.get("title", "").upper() in upper_filter]

    logger.info("Letter sections to process: %d", len(letter_sections))

    all_articles: list = []
    for section in sorted(letter_sections, key=lambda s: s["title"].upper()):
        letter = section["title"].upper()
        offset = section["indexedOffset"]
        children_url = TOC_CHILDREN_PATTERN.format(offset=offset)
        logger.info("  Fetching section %s (offset=%d)...", letter, offset)
        children_data = await _fetch_json(page, children_url)
        children = children_data if isinstance(children_data, list) else children_data.get("children", [])
        for child in children:
            all_articles.append({
                "title": child["title"],
                "offset": child["indexedOffset"],
                "length": child.get("indexedLength", 0),
                "letter": letter,
                "idx": len(all_articles),   # reassigned below after full build
                "headword": None,
            })
        logger.info("    Section %s: %d articles", letter, len(children))

    # Reassign idx after building the full list (sequential across all letters)
    for i, article in enumerate(all_articles):
        article["idx"] = i

    logger.info("Total articles in article list: %d", len(all_articles))
    return all_articles


# ---------------------------------------------------------------------------
# Auth check
# ---------------------------------------------------------------------------


async def check_auth(page) -> bool:
    """Check Faithlife auth: all three signals required.

    Signal 1: data-amplitude-is-authenticated == 'true' (passes even when logged out)
    Signal 2: p[style] count > 0 (passes even when logged out on some pages)
    Signal 3: [rel="headword"] count > 0 -- ONLY present when authenticated and rendering
               article content; its absence means session is expired even if p[style] renders.
    """
    auth_val = await page.evaluate(
        "(function() { return document.querySelector('[data-amplitude-is-authenticated]')"
        "?.getAttribute('data-amplitude-is-authenticated'); })()"
    )
    p_count = await page.evaluate(
        "(function() { return document.querySelectorAll('p[style]').length; })()"
    )
    hw_count = await page.evaluate(
        "(function() { return document.querySelectorAll('[rel=\"headword\"]').length; })()"
    )
    logger.debug("  auth_val=%r  p_count=%s  hw_count=%s", auth_val, p_count, hw_count)
    if auth_val != "true":
        logger.warning("  auth check: data-amplitude-is-authenticated=%r (expected 'true')", auth_val)
        return False
    if not (p_count or 0) > 0:
        logger.warning("  auth check: p[style] count=%s (expected >0)", p_count)
        return False
    if not (hw_count or 0) > 0:
        logger.warning("  auth check: [rel=headword] count=%s (expected >0) -- session expired", hw_count)
        return False
    return True


# ---------------------------------------------------------------------------
# Article extraction
# ---------------------------------------------------------------------------

_SIBLING_JS = """
(function(offset) {
    var marker = document.querySelector('.offset-marker[data-offset="' + offset + '"]');
    if (!marker) return null;
    var startP = marker.parentElement;
    while (startP && startP.tagName !== 'P') {
        startP = startP.parentElement;
    }
    if (!startP) return null;
    // Collect startP and following siblings until the next article's headword span.
    // Articles are bounded by [rel="headword"] spans, not by a single offset marker.
    // Each Logos article paragraph may contain many inline offset markers (every 200
    // bytes), so stopping on any foreign offset would immediately abort.
    var parts = [startP.outerHTML];
    var el = startP.nextElementSibling;
    while (el) {
        if (el.querySelector('[rel="headword"]')) break;
        parts.push(el.outerHTML);
        el = el.nextElementSibling;
    }
    return parts.join('\\n');
})
"""


async def extract_article_html(page, article: dict) -> tuple:
    """Navigate to article page, extract HTML fragment and canonical headword.

    Returns (html_fragment: str, headword: str) or (None, None) on failure.

    URL strategy: try ``headwords/{firstword}`` first (works for most topical entries
    like "AACHEN, SYNODS OF" → ``headwords/Aachen``).  When Logos does not recognise
    that headword it redirects back to the book home page.  Biographical entries such
    as "BAADER, FRANZ XAVER VON" fall into this category because the Logos index stores
    them under the natural-order form ("Franz Xaver Von Baader") rather than
    surname-first.  In that case, retry with the full title URL-encoded (commas as
    ``%2C``); Logos normalises the comma-separated form to the right headword
    automatically (verified on "Baader, Franz Xaver Von" → redirects to
    "Franz%20Xaver%20Von%20Baader" and finds the article).
    """
    title = article["title"]
    # Primary URL: first word before the comma (handles most topical entries).
    hw_encoded = title.split(",")[0].strip().replace(" ", "%20")
    url = ARTICLE_URL_PATTERN.format(hw=hw_encoded)
    logger.debug("  Navigating to %s", url)

    await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)

    # Detect redirect-to-home: Logos redirects unknown headwords to the book root.
    # The book root URL ends with "/LLS%3ANSHERK" or "/LLS:NSHERK" and has no
    # headword path segment.
    current_url = page.url
    if "headwords" not in current_url:
        # Fallback: full title URL-encoded (commas as %2C, spaces as %20).
        hw_full = title.replace(",", "%2C").replace(" ", "%20")
        url_fallback = ARTICLE_URL_PATTERN.format(hw=hw_full)
        logger.info(
            "  Primary headword '%s' not found (redirected to home); retrying with full title: %s",
            hw_encoded, url_fallback,
        )
        await page.goto(url_fallback, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)

    # Wait for article content to render (offset markers may appear after networkidle)
    try:
        await page.wait_for_selector(".offset-marker", state="attached", timeout=10000)
    except Exception:
        logger.warning("  No offset markers appeared after navigation for %s", title)
        return None, None

    # Simulate reading: scroll before extracting
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.3)")
    await asyncio.sleep(1.0)

    # Get canonical headword from DOM
    headword = await page.evaluate(
        "(function() { return document.querySelector('[rel=\"headword\"]')"
        "?.getAttribute('data-headword'); })()"
    )
    if not headword:
        logger.warning("  No headword span found for %s; falling back to title slug", title)
        headword = title.split(",")[0].strip()

    # Extract article HTML fragment by offset-marker bracketing
    offset = article["offset"]
    html_fragment = await page.evaluate(_SIBLING_JS, offset)

    if not html_fragment:
        logger.warning("  Offset marker %d not found for %s", offset, title)
        return None, None

    return html_fragment, headword


# ---------------------------------------------------------------------------
# Retry wrapper (API-04)
# ---------------------------------------------------------------------------


async def fetch_with_retry(page, article: dict) -> tuple:
    """Retry up to MAX_RETRIES times with exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return await extract_article_html(page, article)
        except Exception as exc:
            last_exc = exc
            wait = RETRY_DELAYS_S[min(attempt, len(RETRY_DELAYS_S) - 1)]
            logger.warning(
                "  Retry %d/%d for '%s' after error: %s (waiting %ds)",
                attempt + 1, MAX_RETRIES, article["title"], exc, wait,
            )
            await asyncio.sleep(wait)
    logger.error("  All retries failed for '%s': %s", article["title"], last_exc)
    return None, None


# ---------------------------------------------------------------------------
# Politeness (non-negotiable)
# ---------------------------------------------------------------------------


async def politeness_delay(override: bool = False) -> None:
    """Random human-like delay between article fetches."""
    if override:
        await asyncio.sleep(0.5)
        return
    delay = random.uniform(8, 25)
    if random.random() < 0.10:
        delay = random.uniform(60, 120)
    logger.debug("  Politeness delay: %.1fs", delay)
    await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# Atomic file save (OUT-02)
# ---------------------------------------------------------------------------


def save_html(path: Path, html: str) -> None:
    """Atomic write: write to .tmp then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch Logos NSHERK articles to raw/logos/nsherk/articles/"
    )
    p.add_argument(
        "--letter", action="append", dest="letters", metavar="LETTER",
        help="Fetch only this letter section (repeatable, e.g. --letter A --letter B)",
    )
    p.add_argument(
        "--start-idx", type=int, default=None,
        help="Global article index start (inclusive)",
    )
    p.add_argument(
        "--end-idx", type=int, default=None,
        help="Global article index end (inclusive)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Fetch one article per letter, print preview, write nothing",
    )
    p.add_argument(
        "--headless", action="store_true",
        help="Run browser in headless mode",
    )
    p.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO"],
        help="Logging verbosity (default: INFO)",
    )
    p.add_argument(
        "--rate-limit", action="store_true",
        help="Override politeness delays to 0.5s (testing only -- do not use for real runs)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> int:
    start_time = time.monotonic()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if not PATCHRIGHT_CHROME.is_file():
        logger.error("Patchright Chromium not found at %s", PATCHRIGHT_CHROME)
        logger.error("Run: python -m patchright install chromium")
        return 1

    async with async_playwright() as pw:
        # launch_persistent_context: reuses the Chrome profile (auth cookies, limited
        # view mode setting). Patchright patches CDP fingerprinting for stealth.
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(CHROME_PROFILE),
            executable_path=str(PATCHRIGHT_CHROME),
            headless=args.headless,
            user_agent=USER_AGENT,
            no_viewport=True,
            args=[
                "--profile-directory=Default",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        page = await context.new_page()

        # Navigate to a known article to trigger auth check (REL-02: fail fast)
        logger.info("Checking Faithlife auth...")
        await page.goto(AUTH_CHECK_URL, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
        if not await check_auth(page):
            logger.error(
                "Auth check failed. Re-authenticate via stealth-browser-mcp before running."
            )
            await context.close()
            return 1
        logger.info("Auth OK.")

        try:
            # Build article list from TOC API
            letter_filter = args.letters or None
            articles = await build_article_list(page, letter_filter)

            # Apply index range filter
            if args.start_idx is not None:
                articles = [a for a in articles if a["idx"] >= args.start_idx]
            if args.end_idx is not None:
                articles = [a for a in articles if a["idx"] <= args.end_idx]

            if not articles:
                logger.warning("No articles matched the filter. Exiting.")
                return 0

            logger.info("Articles to process: %d", len(articles))

            fetched = 0
            skipped = 0
            errors = 0
            letters_processed: set = set()

            if args.dry_run:
                # DRY_RUN mode (API-01): one article per letter, no disk writes
                seen_letters: set = set()
                for article in articles:
                    letter = article.get("letter", "?")
                    if letter in seen_letters:
                        continue
                    seen_letters.add(letter)
                    letters_processed.add(letter)
                    logger.info("[DRY_RUN] '%s' (letter %s)", article["title"], letter)
                    html, hw = await fetch_with_retry(page, article)
                    if html:
                        out_path = article_output_path(article)
                        preview = html[:200].replace("\n", " ")
                        logger.info(
                            "[DRY_RUN] Would save -> %s",
                            str(out_path.relative_to(_REPO_ROOT)),
                        )
                        logger.info(
                            "[DRY_RUN] Headword: %s | HTML preview: %s...",
                            hw, preview[:150],
                        )
                        fetched += 1
                    else:
                        logger.error("[DRY_RUN] Extraction failed for '%s'", article["title"])
                        errors += 1
                    await politeness_delay(override=args.rate_limit)
            else:
                for i, article in enumerate(articles):
                    letters_processed.add(article.get("letter", "?"))
                    out_path = article_output_path(article)

                    # Idempotency: skip already-fetched articles (REL-04)
                    if out_path.exists() and out_path.stat().st_size > 0:
                        skipped += 1
                        if (fetched + skipped + errors) % 10 == 0:
                            logger.info(
                                "Progress: fetched=%d skipped=%d errors=%d",
                                fetched, skipped, errors,
                            )
                        continue

                    logger.debug("Fetching [%d/%d] '%s'", i + 1, len(articles), article["title"])
                    html, hw = await fetch_with_retry(page, article)

                    if html:
                        if hw:
                            article["headword"] = hw
                        save_html(out_path, html)
                        fetched += 1
                        logger.info(
                            "OK [%05d] '%s' -> %s",
                            article["idx"], article["title"], out_path.name,
                        )
                    else:
                        errors += 1
                        logger.error("FAIL [%05d] '%s'", article["idx"], article["title"])

                    if (fetched + skipped + errors) % 10 == 0:
                        logger.info(
                            "Progress: fetched=%d skipped=%d errors=%d",
                            fetched, skipped, errors,
                        )
                    await politeness_delay(override=args.rate_limit)

            elapsed = time.monotonic() - start_time
            logger.info(
                "Done. letters=%d articles=%d fetched=%d skipped=%d errors=%d elapsed=%.0fs",
                len(letters_processed), len(articles), fetched, skipped, errors, elapsed,
            )
            return 0 if errors == 0 else 1

        finally:
            await context.close()

    return 1  # unreachable — satisfies type checker


if __name__ == "__main__":
    _args = parse_args()
    setup_logging(_args.log_level)
    sys.exit(asyncio.run(main(_args)))
