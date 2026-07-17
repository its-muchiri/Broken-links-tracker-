#!/usr/bin/env python3
"""
Replacement Verifier — checks whether your pitched URLs are now live
on the source pages you contacted.

Input file format (pitches.txt) — pipe-separated, one per line:
  source_page_url | your_replacement_url

  Example:
    https://law-blog.com/resources | https://american-counsel.com/medical-malpractice-lawyer-guide/
    https://lawschool.edu/links    | https://american-counsel.com/best-personal-injury-lawyer-for-spinal/

Status codes returned:
  confirmed   — your URL appears as a clickable link on the source page  (green)
  pending     — source page is live but your URL is not linked yet        (yellow)
  page_gone   — the source page itself is now broken / unreachable        (red)
  blocked     — robots.txt disallows fetching the source page             (grey)
  error       — page could not be fetched for another reason              (grey)

Run:
  python verify.py --pitches pitches.txt
  python verify.py --pitches pitches.txt --format html --output-dir output
"""
import argparse
import csv
import html as _html
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from config import Config

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _normalise(url: str) -> str:
    """Strip trailing slash and lowercase scheme+host for comparison."""
    p = urlparse(url.strip().rstrip("/"))
    return f"{p.scheme}://{p.netloc.lower()}{p.path}"


def _load_pitches(path: str) -> list[dict]:
    """Parse pitches.txt → list of {source_page, your_url}."""
    entries = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "|" not in line:
                logger.warning("Line %d skipped (no | separator): %s", lineno, line)
                continue
            parts = line.split("|", 1)
            source = parts[0].strip()
            your   = parts[1].strip()
            if source and your:
                entries.append({"source_page": source, "your_url": your})
            else:
                logger.warning("Line %d skipped (empty field): %s", lineno, line)
    return entries


_robots_cache: dict[str, RobotFileParser] = {}

def _can_fetch(url: str, user_agent: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    if robots_url not in _robots_cache:
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
        except Exception:
            pass
        _robots_cache[robots_url] = rp
    try:
        return _robots_cache[robots_url].can_fetch(user_agent, url)
    except Exception:
        return True


# ------------------------------------------------------------------
# Core verification
# ------------------------------------------------------------------

def verify_pitch(
    source_page: str,
    your_url: str,
    session: requests.Session,
    user_agent: str,
    timeout: int = 10,
    crawl_delay: float = 2.5,
) -> dict:
    """
    Fetch source_page and look for your_url in its outbound links.
    Returns a result dict with status, context found, and metadata.
    """
    result = {
        "source_page": source_page,
        "your_url": your_url,
        "status": None,
        "status_code": None,
        "link_text": "",
        "link_context": "",
        "error_message": "",
        "date_checked": datetime.now(timezone.utc).isoformat(),
    }

    if not _can_fetch(source_page, user_agent):
        result["status"] = "blocked"
        result["error_message"] = "Disallowed by robots.txt"
        return result

    try:
        resp = session.get(source_page, timeout=timeout)
        result["status_code"] = resp.status_code
    except requests.exceptions.Timeout:
        result["status"] = "error"
        result["error_message"] = "Timeout"
        return result
    except Exception as exc:
        result["status"] = "error"
        result["error_message"] = str(exc)
        return result

    if resp.status_code >= 400:
        result["status"] = "page_gone"
        return result

    content_type = resp.headers.get("Content-Type", "")
    if "html" not in content_type:
        result["status"] = "error"
        result["error_message"] = f"Non-HTML content type: {content_type}"
        return result

    soup = BeautifulSoup(resp.text, "lxml")
    your_norm = _normalise(your_url)

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        abs_href = urljoin(source_page, href)
        if _normalise(abs_href) == your_norm:
            # Found it — grab anchor text and surrounding context
            anchor_text = a_tag.get_text(strip=True)
            parent = a_tag.find_parent(["p", "li", "div", "td", "article"])
            context = parent.get_text(separator=" ", strip=True)[:300] if parent else ""
            result["status"] = "confirmed"
            result["link_text"] = anchor_text
            result["link_context"] = context
            return result

    result["status"] = "pending"
    return result


# ------------------------------------------------------------------
# Output
# ------------------------------------------------------------------

_CSV_FIELDS = [
    "source_page", "your_url", "status", "status_code",
    "link_text", "link_context", "error_message", "date_checked",
]

_STATUS_COLOUR = {
    "confirmed": "#2a9d8f",
    "pending":   "#f4a261",
    "page_gone": "#e63946",
    "blocked":   "#aaa",
    "error":     "#aaa",
}

_STATUS_LABEL = {
    "confirmed": "✔ Confirmed",
    "pending":   "⏳ Pending",
    "page_gone": "✘ Page gone",
    "blocked":   "⊘ Blocked",
    "error":     "⚠ Error",
}


def _save_csv(results: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    logger.info("CSV saved → %s", path)


def _save_html(results: list[dict], path: Path) -> None:
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    n_confirmed = sum(1 for r in results if r["status"] == "confirmed")
    n_pending   = sum(1 for r in results if r["status"] == "pending")
    n_gone      = sum(1 for r in results if r["status"] == "page_gone")
    n_other     = len(results) - n_confirmed - n_pending - n_gone

    rows_html = []
    for r in results:
        colour = _STATUS_COLOUR.get(r["status"], "#aaa")
        label  = _STATUS_LABEL.get(r["status"],  r["status"])
        src    = _html.escape(r["source_page"])
        your   = _html.escape(r["your_url"])
        ctx    = _html.escape(r.get("link_context") or r.get("error_message") or "")
        ctx_s  = ctx[:280] + ("…" if len(ctx) > 280 else "")
        txt    = _html.escape(r.get("link_text") or "—")
        code   = r.get("status_code") or ""

        rows_html.append(f"""
<tr>
  <td style="color:{colour};font-weight:700;white-space:nowrap">{label}
    <span style="display:block;font-size:0.78em;color:#999;font-weight:400">{_html.escape(str(code))}</span>
  </td>
  <td style="font-size:0.82em"><a href="{src}" target="_blank" rel="noopener">{src}</a></td>
  <td style="font-size:0.82em"><a href="{your}" target="_blank" rel="noopener">{your}</a></td>
  <td style="font-size:0.82em;font-style:italic">{txt}</td>
  <td style="font-size:0.8em;color:#555;max-width:340px">{ctx_s}</td>
</tr>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Replacement Verification Report — {date_str}</title>
<style>
  body{{font-family:system-ui,sans-serif;max-width:1300px;margin:0 auto;padding:24px 20px 60px;color:#2b2d42}}
  h1{{color:#1d3557;border-bottom:3px solid #e63946;padding-bottom:10px;margin-bottom:6px}}
  .meta{{color:#666;font-size:.88em;margin-bottom:20px}}
  .stats{{display:flex;gap:16px;flex-wrap:wrap;background:#f8f9fa;border-radius:10px;padding:18px 20px;margin-bottom:28px}}
  .stat{{text-align:center;min-width:90px}}
  .stat-num{{font-size:2em;font-weight:700;line-height:1}}
  .stat-label{{font-size:.78em;color:#666;margin-top:4px}}
  table{{width:100%;border-collapse:collapse;font-size:.88em}}
  thead th{{background:#1d3557;color:#fff;padding:9px 10px;text-align:left;white-space:nowrap}}
  td{{padding:8px 10px;border-bottom:1px solid #e0e0e0;vertical-align:top}}
  tr:hover td{{background:#f0f7ff}}
  a{{color:#457b9d;word-break:break-all;text-decoration:none}}
  a:hover{{text-decoration:underline}}
  .tip{{background:#e8f4f8;border-left:4px solid #457b9d;padding:10px 16px;
        margin-bottom:24px;border-radius:0 6px 6px 0;font-size:.88em}}
</style>
</head>
<body>
<h1>Replacement Verification Report</h1>
<p class="meta">Generated: {date_str}</p>
<div class="tip">
  <strong>How to use:</strong> <span style="color:#2a9d8f;font-weight:700">Confirmed</span> rows mean your link is live on that page.
  <span style="color:#f4a261;font-weight:700">Pending</span> rows need a follow-up.
  <span style="color:#e63946;font-weight:700">Page gone</span> means the source page itself has since disappeared.
</div>
<div class="stats">
  <div class="stat"><div class="stat-num" style="color:#2a9d8f">{n_confirmed}</div><div class="stat-label">Confirmed</div></div>
  <div class="stat"><div class="stat-num" style="color:#f4a261">{n_pending}</div><div class="stat-label">Pending</div></div>
  <div class="stat"><div class="stat-num" style="color:#e63946">{n_gone}</div><div class="stat-label">Page Gone</div></div>
  <div class="stat"><div class="stat-num" style="color:#aaa">{n_other}</div><div class="stat-label">Error / Blocked</div></div>
  <div class="stat"><div class="stat-num" style="color:#1d3557">{len(results)}</div><div class="stat-label">Total Pitched</div></div>
</div>
<table>
<thead>
  <tr>
    <th style="width:110px">Status</th>
    <th>Source Page (site you pitched)</th>
    <th>Your URL (replacement)</th>
    <th style="width:160px">Anchor Text</th>
    <th>Context / Notes</th>
  </tr>
</thead>
<tbody>
{"".join(rows_html)}
</tbody>
</table>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("HTML report saved → %s", path)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="verify",
        description=(
            "Check whether your pitched replacement URLs are now live "
            "on the source pages you contacted."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--pitches", required=True, metavar="FILE",
        help="Pitches file: 'source_page | your_url', one per line.",
    )
    p.add_argument(
        "--config", metavar="FILE",
        help="JSON config file (uses same settings as main.py).",
    )
    p.add_argument(
        "--delay", type=float, metavar="SECS",
        help="Delay between requests in seconds (default: 2.5).",
    )
    p.add_argument(
        "--timeout", type=int, metavar="SECS",
        help="HTTP timeout in seconds (default: 10).",
    )
    p.add_argument(
        "--output-dir", metavar="DIR",
        help="Directory to write output files into (default: output).",
    )
    p.add_argument(
        "--format", choices=["csv", "html", "all"], default="all",
        help="Output format (default: all).",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return p


def main() -> int:
    parser = _build_parser()
    args   = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    cfg = Config.from_file(args.config) if args.config else Config()
    if args.delay is not None:      cfg.crawl_delay     = args.delay
    if args.timeout is not None:    cfg.request_timeout = args.timeout
    if args.output_dir is not None: cfg.output_dir      = args.output_dir

    pitches = _load_pitches(args.pitches)
    if not pitches:
        logger.error("No valid entries found in %s", args.pitches)
        return 1

    logger.info("Verifying %d pitches …", len(pitches))

    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = cfg.user_agent

    results = []
    for i, pitch in enumerate(pitches, 1):
        logger.info("[%d/%d] %s", i, len(pitches), pitch["source_page"])
        result = verify_pitch(
            source_page=pitch["source_page"],
            your_url=pitch["your_url"],
            session=session,
            user_agent=cfg.user_agent,
            timeout=cfg.request_timeout,
            crawl_delay=cfg.crawl_delay,
        )
        results.append(result)
        status_icon = {"confirmed": "✔", "pending": "⏳", "page_gone": "✘"}.get(result["status"], "⚠")
        logger.info("  %s %s", status_icon, result["status"].upper())
        time.sleep(cfg.crawl_delay)

    # Sort: confirmed first, then pending, then gone/errors
    _order = {"confirmed": 0, "pending": 1, "page_gone": 2, "blocked": 3, "error": 4}
    results.sort(key=lambda r: _order.get(r["status"], 9))

    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    fmt = args.format

    if fmt in ("csv", "all"):
        _save_csv(results, out_dir / f"verification_{ts}.csv")

    if fmt in ("html", "all"):
        _save_html(results, out_dir / f"verification_{ts}.html")

    n_confirmed = sum(1 for r in results if r["status"] == "confirmed")
    n_pending   = sum(1 for r in results if r["status"] == "pending")
    logger.info(
        "Done — %d confirmed, %d pending, %d other. Output in: %s/",
        n_confirmed, n_pending, len(results) - n_confirmed - n_pending, out_dir,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
