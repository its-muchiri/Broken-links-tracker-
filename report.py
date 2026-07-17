"""
Generates CSV, JSON, and HTML outputs from the list of checked links.

All three formats include:
  source_page, broken_link, anchor_text, surrounding_context,
  status_code, error_message, status, final_url, keyword_score, date_checked

The HTML report groups results by source domain and bubbles keyword
matches to the top of each section.
"""
import csv
import html as _html
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_CSV_FIELDS = [
    "source_page",
    "broken_link",
    "anchor_text",
    "surrounding_context",
    "status_code",
    "error_message",
    "status",
    "final_url",
    "keyword_score",
    "suggested_replacement_url",
    "suggested_replacement_score",
    "suggested_replacement_reason",
    "date_checked",
]


# ------------------------------------------------------------------
# Keyword scoring
# ------------------------------------------------------------------

def score_keywords(text: str, keywords: list[str]) -> int:
    """Count how many keywords appear (case-insensitive) in text."""
    if not text or not keywords:
        return 0
    lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in lower)


# ------------------------------------------------------------------
# CSV
# ------------------------------------------------------------------

def save_csv(results: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "source_page": r.get("source_page", ""),
                    "broken_link": r.get("link_url", ""),
                    "anchor_text": r.get("anchor_text", ""),
                    "surrounding_context": r.get("surrounding_context", ""),
                    "status_code": r.get("status_code", ""),
                    "error_message": r.get("error_message", ""),
                    "status": r.get("status", ""),
                    "final_url": r.get("final_url", ""),
                    "keyword_score": r.get("keyword_score", 0),
                    "suggested_replacement_url": r.get("suggested_replacement_url", ""),
                    "suggested_replacement_score": r.get("suggested_replacement_score", ""),
                    "suggested_replacement_reason": r.get("suggested_replacement_reason", ""),
                    "date_checked": r.get("date_checked", ""),
                }
            )
    logger.info("CSV saved → %s", path)


# ------------------------------------------------------------------
# JSON
# ------------------------------------------------------------------

def save_json(results: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info("JSON saved → %s", path)


# ------------------------------------------------------------------
# HTML
# ------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Broken Link Report — {date}</title>
<style>
  :root {{
    --accent: #e63946;
    --blue: #1d3557;
    --mid-blue: #457b9d;
    --light: #f8f9fa;
    --text: #2b2d42;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: system-ui, -apple-system, sans-serif;
    color: var(--text);
    background: #fff;
    max-width: 1300px;
    margin: 0 auto;
    padding: 24px 20px 60px;
  }}
  h1 {{ color: var(--blue); border-bottom: 3px solid var(--accent); padding-bottom: 10px; margin-bottom: 6px; }}
  .meta {{ color: #666; font-size: 0.88em; margin-bottom: 20px; }}
  .keywords-banner {{
    background: #e8f4f8;
    border-left: 4px solid var(--mid-blue);
    padding: 10px 16px;
    margin-bottom: 20px;
    border-radius: 0 6px 6px 0;
    font-size: 0.9em;
  }}
  .stats {{
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    background: var(--light);
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 32px;
  }}
  .stat {{ text-align: center; min-width: 80px; }}
  .stat-num {{ font-size: 2em; font-weight: 700; color: var(--accent); line-height: 1; }}
  .stat-label {{ font-size: 0.78em; color: #666; margin-top: 4px; }}
  h2 {{
    color: var(--blue);
    margin: 36px 0 10px;
    font-size: 1.15em;
    display: flex;
    align-items: baseline;
    gap: 8px;
  }}
  h2 small {{ font-size: 0.8em; color: #888; font-weight: 400; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85em;
    margin-bottom: 8px;
  }}
  thead th {{
    background: var(--blue);
    color: #fff;
    padding: 9px 10px;
    text-align: left;
    white-space: nowrap;
  }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #e0e0e0; vertical-align: top; }}
  tr:hover td {{ background: #f0f7ff; }}
  .broken {{ color: var(--accent); font-weight: 700; }}
  .redirected {{ color: #f4a261; font-weight: 700; }}
  .code {{ font-size: 0.85em; color: #888; display: block; }}
  .context {{ color: #555; max-width: 380px; font-size: 0.82em; line-height: 1.4; }}
  a {{ color: var(--mid-blue); word-break: break-all; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .badge {{
    display: inline-block;
    background: #2a9d8f;
    color: #fff;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.75em;
    margin-left: 6px;
    vertical-align: middle;
    white-space: nowrap;
  }}
  .anchor {{ font-style: italic; color: #333; }}
  @media (max-width: 800px) {{
    .context {{ max-width: 200px; }}
  }}
</style>
</head>
<body>
<h1>Broken Link Finder Report</h1>
<p class="meta">Generated: {date}</p>
{keywords_banner}
<div class="stats">
  <div class="stat"><div class="stat-num">{n_domains}</div><div class="stat-label">Domains Scanned</div></div>
  <div class="stat"><div class="stat-num">{n_total}</div><div class="stat-label">Flagged Links</div></div>
  <div class="stat"><div class="stat-num">{n_broken}</div><div class="stat-label">Broken</div></div>
  <div class="stat"><div class="stat-num">{n_redirected}</div><div class="stat-label">Redirected</div></div>
  <div class="stat"><div class="stat-num">{n_matched}</div><div class="stat-label">Keyword Matches</div></div>
</div>
{sections}
</body>
</html>
"""

_SECTION_TEMPLATE = """\
<h2>{domain} <small>({n_broken} broken · {n_redirected} redirected)</small></h2>
<table>
<thead>
  <tr>
    <th style="width:90px">Status</th>
    <th>Broken / Redirected Link</th>
    <th style="width:200px">Source Page</th>
    <th style="width:140px">Anchor Text</th>
    <th>Context</th>
    <th style="width:220px">Suggested Replacement</th>
  </tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
"""


def _row(r: dict) -> str:
    status = r.get("status", "")
    code = r.get("status_code") or r.get("error_message") or "—"
    link = _html.escape(r.get("link_url", ""))
    source = _html.escape(r.get("source_page", ""))
    anchor = _html.escape(r.get("anchor_text", "") or "—")
    ctx = _html.escape(r.get("surrounding_context", "") or "")
    ctx_short = ctx[:220] + ("…" if len(ctx) > 220 else "")
    score = r.get("keyword_score", 0)
    badge = f'<span class="badge">★ keyword ×{score}</span>' if score > 0 else ""

    # Suggested replacements (top 3)
    replacements = r.get("suggested_replacements") or []
    if replacements:
        repl_items = []
        for rep in replacements[:3]:
            ru = _html.escape(rep["url"])
            reason = _html.escape(rep.get("matched_on", ""))
            repl_items.append(
                f'<div style="margin-bottom:4px">'
                f'<a href="{ru}" target="_blank" rel="noopener noreferrer" '
                f'style="font-size:0.8em">{ru}</a>'
                f'<br><span style="font-size:0.72em;color:#888">matched: {reason}</span>'
                f'</div>'
            )
        repl_cell = "\n".join(repl_items)
    else:
        repl_cell = '<span style="color:#ccc;font-size:0.8em">—</span>'

    return (
        f'<tr>\n'
        f'  <td class="{_html.escape(status)}">{_html.escape(status)}'
        f'<span class="code">{_html.escape(str(code))}</span></td>\n'
        f'  <td><a href="{link}" target="_blank" rel="noopener noreferrer">{link}</a>{badge}</td>\n'
        f'  <td><a href="{source}" target="_blank" rel="noopener noreferrer">{source}</a></td>\n'
        f'  <td class="anchor">{anchor}</td>\n'
        f'  <td class="context">{ctx_short}</td>\n'
        f'  <td>{repl_cell}</td>\n'
        f'</tr>'
    )


def generate_html(
    results: list[dict], path: Path, keywords: list[str] | None = None
) -> None:
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        domain = urlparse(r.get("source_page", "")).netloc or "unknown"
        by_domain[domain].append(r)

    # Within each domain, keyword matches first, then broken before redirected
    for domain in by_domain:
        by_domain[domain].sort(
            key=lambda x: (-x.get("keyword_score", 0), x.get("status") != "broken")
        )

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    n_total = len(results)
    n_broken = sum(1 for r in results if r.get("status") == "broken")
    n_redirected = sum(1 for r in results if r.get("status") == "redirected")
    n_matched = sum(1 for r in results if r.get("keyword_score", 0) > 0)

    keywords_banner = ""
    if keywords:
        kw_escaped = _html.escape(", ".join(keywords))
        keywords_banner = (
            f'<div class="keywords-banner">'
            f"<strong>Topic keywords:</strong> {kw_escaped}"
            f"</div>"
        )

    sections = []
    for domain, items in sorted(by_domain.items()):
        nb = sum(1 for r in items if r.get("status") == "broken")
        nr = sum(1 for r in items if r.get("status") == "redirected")
        rows = "\n".join(_row(r) for r in items)
        sections.append(
            _SECTION_TEMPLATE.format(
                domain=_html.escape(domain),
                n_broken=nb,
                n_redirected=nr,
                rows=rows,
            )
        )

    html = _HTML_TEMPLATE.format(
        date=date_str,
        keywords_banner=keywords_banner,
        n_domains=len(by_domain),
        n_total=n_total,
        n_broken=n_broken,
        n_redirected=n_redirected,
        n_matched=n_matched,
        sections="\n".join(sections),
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("HTML report saved → %s", path)
