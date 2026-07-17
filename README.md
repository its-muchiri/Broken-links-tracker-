# Broken Link Finder

A command-line tool that crawls target websites in your niche, finds broken
outbound links, and generates a report so you can manually pitch your own
content as a replacement resource.

---

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate  # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt
```

---

## Quick Start

```bash
# Copy the example files and fill them in
copy targets.example.txt  targets.txt
copy keywords.example.txt keywords.txt

# Run with defaults (depth=1, 50 pages/domain, 2.5s delay)
python main.py --targets targets.txt --keywords keywords.txt
```

Results land in the `output/` folder:

| File | Contents |
|---|---|
| `broken_links_YYYYMMDD_HHMMSS.csv` | Machine-readable spreadsheet |
| `broken_links_YYYYMMDD_HHMMSS.json` | Full data as JSON |
| `broken_links_YYYYMMDD_HHMMSS.html` | Visual report grouped by domain |

Open the HTML file in any browser. Links flagged with **★ keyword ×N** are
the best candidates — the anchor text or surrounding paragraph matched N of
your topic keywords.

---

## Input Files

### `targets.txt`
One URL per line — the pages (or homepages) of sites in your niche you want to
scan. Lines starting with `#` are treated as comments.

```
https://example-blog.com/resources
https://another-site.com/useful-links
```

### `keywords.txt`
One keyword or phrase per line. Used to score results, not to filter them.

```
digital marketing
SEO guide
content strategy
```

---

## All Options

```
python main.py --help
```

| Flag | Default | Description |
|---|---|---|
| `--targets FILE` | *(required)* | Text file of target URLs |
| `--keywords FILE` | none | Text file of topic keywords |
| `--config FILE` | none | JSON config file (see `config.example.json`) |
| `--depth N` | `1` | How many hops of internal links to follow |
| `--delay SECS` | `2.5` | Pause between page requests (politeness) |
| `--max-pages N` | `50` | Max pages to crawl per target domain |
| `--timeout SECS` | `10` | HTTP request timeout |
| `--output-dir DIR` | `output` | Where to save result files |
| `--format` | `all` | `csv`, `json`, `html`, or `all` |
| `--broken-only` | off | Omit redirected-to-other-domain results |
| `--user-agent STR` | built-in | Override the crawler's User-Agent string |
| `--verbose` / `-v` | off | Show DEBUG-level log output |

### Config file

You can store defaults in a JSON file and override individual values via CLI:

```bash
python main.py --targets targets.txt --config config.example.json --depth 2
```

---

## Output Columns

| Column | Description |
|---|---|
| `source_page` | The page on the target site where the link was found |
| `broken_link` | The dead URL |
| `anchor_text` | The visible hyperlink text |
| `surrounding_context` | Up to 300 chars of the paragraph containing the link |
| `status_code` | HTTP status returned (e.g. 404, 410) |
| `error_message` | DNS/timeout error if no status code was returned |
| `status` | `broken` or `redirected` |
| `final_url` | Where the URL ultimately resolves (for redirects) |
| `keyword_score` | Number of your topic keywords found in anchor + context |
| `date_checked` | UTC ISO timestamp of the check |

---

## Crawl Behaviour

- **robots.txt** is fetched and obeyed for every domain before crawling starts.
- A **crawl delay** (default 2.5 s) is inserted between every page request.
- Each domain is capped at **max pages** (default 50) to prevent runaway crawls.
- Each broken link is **retried once** after a short pause before being confirmed dead.
- The same external URL is only checked once, even if found on multiple pages.

---

## Recommended Workflow

1. **Identify targets** — find resource pages, blog posts, or directories in your
   niche that link to a lot of external content (e.g. Google: `"useful links"
   site:yourniche.com`).
2. **Add them to `targets.txt`** and fill in `keywords.txt` with topics your
   content covers.
3. **Run the tool** and open the HTML report.
4. **Filter by keyword score** — rows with a ★ badge are the strongest match
   for your content.
5. **Manually outreach** to site owners with a personalised pitch explaining
   that the link is broken and you have a relevant replacement. *This tool
   does not send any messages — outreach is entirely up to you.*

---

## Legal & Ethical Notes

- **Check each site's Terms of Service** before crawling. Some sites
  explicitly prohibit automated access.
- **Keep delays reasonable** — the default 2.5 s is polite; do not lower it
  significantly without a good reason.
- **Do not use this tool for unsolicited mass messaging** or any form of spam.
- This tool collects only publicly available link data — no personal or contact
  data is stored.

---

## Project Structure

```
broken_link_finder/
├── main.py          CLI entry point, orchestrates crawl → check → report
├── crawler.py       Fetches pages, extracts external links, respects robots.txt
├── checker.py       HEAD/GET status checking with retry logic
├── report.py        CSV, JSON, and HTML output generation
├── config.py        Config dataclass with JSON-file and CLI override support
├── requirements.txt Python dependencies
├── config.example.json
├── targets.example.txt
└── keywords.example.txt
```
