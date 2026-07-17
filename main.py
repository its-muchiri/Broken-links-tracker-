#!/usr/bin/env python3
"""
Broken Link Finder — CLI entry point.

Usage examples:
  python main.py --targets targets.txt --keywords keywords.txt --my-urls my_urls.txt
  python main.py --targets targets.txt --keywords keywords.txt --depth 2 --max-pages 100
  python main.py --targets targets.txt --config my_config.json --format html
  python main.py --targets targets.txt --broken-only
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import requests

from checker import check_link
from config import Config
from crawler import Crawler
from matcher import build_index, find_replacements
from report import generate_html, save_csv, save_json, score_keywords

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _load_lines(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="ignore") as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]


def _deduplicate(extracted: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    unique = []
    for item in extracted:
        key = (item["source_page"], item["link_url"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


# ------------------------------------------------------------------
# CLI argument parsing
# ------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="broken-link-finder",
        description=(
            "Crawl target sites, detect broken/dead outbound links, "
            "and generate a report for link-building outreach."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--targets", required=True, metavar="FILE",
        help="Text file with target URLs to crawl, one per line.",
    )
    p.add_argument(
        "--keywords", metavar="FILE",
        help="Text file with topic keywords (one per line) used to score relevance.",
    )
    p.add_argument(
        "--my-urls", metavar="FILE",
        help="Text file with YOUR replacement URLs (one per line). "
             "The tool will suggest the best match for every broken link found.",
    )
    p.add_argument(
        "--config", metavar="FILE",
        help="JSON config file to load default settings from.",
    )
    p.add_argument(
        "--depth", type=int, metavar="N",
        help="Crawl depth inside each target domain (default: 1).",
    )
    p.add_argument(
        "--delay", type=float, metavar="SECS",
        help="Polite delay between page requests in seconds (default: 2.5).",
    )
    p.add_argument(
        "--max-pages", type=int, metavar="N",
        help="Max internal pages to crawl per domain (default: 50).",
    )
    p.add_argument(
        "--timeout", type=int, metavar="SECS",
        help="HTTP request timeout in seconds (default: 10).",
    )
    p.add_argument(
        "--output-dir", metavar="DIR",
        help="Directory to write output files into (default: output).",
    )
    p.add_argument(
        "--format",
        choices=["csv", "json", "html", "all"],
        default="all",
        help="Output format(s) to generate (default: all).",
    )
    p.add_argument(
        "--user-agent", metavar="STRING",
        help="Override the User-Agent string sent with requests.",
    )
    p.add_argument(
        "--broken-only", action="store_true",
        help="Only report broken links; skip redirected-to-other-domain links.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return p


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # --- Build config (file → CLI overrides) ---
    cfg = Config.from_file(args.config) if args.config else Config()
    if args.depth is not None:        cfg.crawl_depth = args.depth
    if args.delay is not None:        cfg.crawl_delay = args.delay
    if args.max_pages is not None:    cfg.max_pages_per_domain = args.max_pages
    if args.timeout is not None:      cfg.request_timeout = args.timeout
    if args.output_dir is not None:   cfg.output_dir = args.output_dir
    if args.user_agent is not None:   cfg.user_agent = args.user_agent

    # --- Load inputs ---
    target_urls = _load_lines(args.targets)
    if not target_urls:
        logger.error("No URLs found in %s", args.targets)
        return 1

    keywords  = _load_lines(args.keywords) if args.keywords else []
    my_urls   = _load_lines(args.my_urls)  if args.my_urls  else []
    url_index = build_index(my_urls) if my_urls else []

    logger.info(
        "Config — depth:%d  delay:%.1fs  max-pages:%d  timeout:%ds",
        cfg.crawl_depth, cfg.crawl_delay, cfg.max_pages_per_domain, cfg.request_timeout,
    )
    logger.info(
        "Targets: %d  |  Keywords: %d  |  My replacement URLs: %d",
        len(target_urls), len(keywords), len(my_urls),
    )

    # --- Output directory ---
    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------
    # Phase 1: Crawl
    # ----------------------------------------------------------------
    crawler = Crawler(
        user_agent=cfg.user_agent,
        crawl_delay=cfg.crawl_delay,
        max_pages_per_domain=cfg.max_pages_per_domain,
        timeout=cfg.request_timeout,
    )

    all_extracted: list[dict] = []
    for url in target_urls:
        logger.info("━━━ Crawling: %s ━━━", url)
        links = crawler.crawl(url, depth=cfg.crawl_depth)
        all_extracted.extend(links)

    all_extracted = _deduplicate(all_extracted)
    logger.info("Unique external links to check: %d", len(all_extracted))

    if not all_extracted:
        logger.info("No external links found — nothing to check.")
        return 0

    # ----------------------------------------------------------------
    # Phase 2: Check links (with per-URL cache)
    # ----------------------------------------------------------------
    check_session = requests.Session()
    check_session.headers["User-Agent"] = cfg.user_agent

    url_cache: dict[str, dict] = {}
    flagged: list[dict] = []
    total = len(all_extracted)

    for i, item in enumerate(all_extracted, 1):
        link_url = item["link_url"]

        if link_url in url_cache:
            check_result = url_cache[link_url]
        else:
            logger.info("[%d/%d] Checking: %s", i, total, link_url)
            check_result = check_link(
                link_url,
                check_session,
                timeout=cfg.request_timeout,
                retry_delay=cfg.retry_delay,
            )
            url_cache[link_url] = check_result

        status = check_result.get("status")
        if status == "broken" or (status == "redirected" and not args.broken_only):
            anchor  = item.get("anchor_text") or ""
            context = item.get("surrounding_context") or ""

            replacements = find_replacements(
                anchor_text=anchor,
                context=context,
                broken_url=link_url,
                index=url_index,
            ) if url_index else []

            record = {
                **item,
                **check_result,
                "link_url": link_url,
                "keyword_score": score_keywords(anchor + " " + context, keywords),
                "suggested_replacements": replacements,
                # Flat top-1 for CSV convenience
                "suggested_replacement_url":   replacements[0]["url"]        if replacements else "",
                "suggested_replacement_score":  replacements[0]["score"]      if replacements else 0,
                "suggested_replacement_reason": replacements[0]["matched_on"] if replacements else "",
            }
            flagged.append(record)
            logger.info(
                "  ↳ %s [%s]%s",
                status.upper(),
                check_result.get("status_code") or check_result.get("error_message"),
                f"  → {replacements[0]['url']}" if replacements else "",
            )

    n_broken     = sum(1 for r in flagged if r.get("status") == "broken")
    n_redirected = sum(1 for r in flagged if r.get("status") == "redirected")
    logger.info(
        "Results: %d broken, %d redirected (from %d links checked)",
        n_broken, n_redirected, len(url_cache),
    )

    if not flagged:
        logger.info("No broken or redirected links found.")
        return 0

    # Sort: keyword matches first → broken before redirected → URL alphabetical
    flagged.sort(
        key=lambda x: (
            -x.get("keyword_score", 0),
            x.get("status") != "broken",
            x.get("link_url", ""),
        )
    )

    # ----------------------------------------------------------------
    # Phase 3: Output
    # ----------------------------------------------------------------
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    fmt = args.format

    if fmt in ("csv", "all"):
        save_csv(flagged, out_dir / f"broken_links_{ts}.csv")

    if fmt in ("json", "all"):
        save_json(flagged, out_dir / f"broken_links_{ts}.json")

    if fmt in ("html", "all"):
        generate_html(flagged, out_dir / f"broken_links_{ts}.html", keywords=keywords)

    logger.info("Done. Output in: %s/", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
