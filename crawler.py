"""
Crawls a target URL (and internal links up to a configurable depth),
extracts all outbound external links with anchor text and context.
Respects robots.txt and enforces polite crawl delays.
"""
import logging
import time
from collections import deque
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Tags whose text makes good surrounding context
_CONTEXT_TAGS = ("p", "li", "td", "blockquote", "article", "section", "div")


class Crawler:
    def __init__(
        self,
        user_agent: str,
        crawl_delay: float,
        max_pages_per_domain: int,
        timeout: int = 10,
    ):
        self.user_agent = user_agent
        self.crawl_delay = crawl_delay
        self.max_pages = max_pages_per_domain
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._robots_cache: dict[str, RobotFileParser] = {}

    # ------------------------------------------------------------------
    # robots.txt
    # ------------------------------------------------------------------

    def _robots_for(self, url: str) -> RobotFileParser:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        if robots_url not in self._robots_cache:
            rp = RobotFileParser()
            rp.set_url(robots_url)
            try:
                rp.read()
            except Exception as exc:
                logger.debug("Could not read robots.txt for %s: %s", robots_url, exc)
            self._robots_cache[robots_url] = rp
        return self._robots_cache[robots_url]

    def _allowed(self, url: str) -> bool:
        try:
            return self._robots_for(url).can_fetch(self.user_agent, url)
        except Exception:
            return True  # assume allowed on error

    # ------------------------------------------------------------------
    # Context extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _surrounding_context(tag, max_chars: int = 300) -> str:
        parent = tag.find_parent(_CONTEXT_TAGS)
        if parent is None:
            return ""
        text = parent.get_text(separator=" ", strip=True)
        return text[:max_chars]

    # ------------------------------------------------------------------
    # Public crawl entry point
    # ------------------------------------------------------------------

    def crawl(self, start_url: str, depth: int = 1) -> list[dict]:
        """
        BFS-crawl start_url up to `depth` hops through internal pages.
        Returns a list of dicts representing discovered external links.
        """
        parsed_start = urlparse(start_url)
        base_netloc = parsed_start.netloc

        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(start_url, 0)])
        results: list[dict] = []
        pages_crawled = 0

        while queue and pages_crawled < self.max_pages:
            url, current_depth = queue.popleft()
            clean_url = url.split("#")[0]  # strip fragments

            if clean_url in visited:
                continue
            visited.add(clean_url)

            if not self._allowed(clean_url):
                logger.info("robots.txt disallows: %s", clean_url)
                continue

            logger.info("Crawling [depth=%d]: %s", current_depth, clean_url)
            try:
                resp = self._session.get(clean_url, timeout=self.timeout)
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("Failed to fetch %s — %s", clean_url, exc)
                time.sleep(self.crawl_delay)
                continue

            content_type = resp.headers.get("Content-Type", "")
            if "html" not in content_type:
                time.sleep(self.crawl_delay)
                continue

            pages_crawled += 1
            soup = BeautifulSoup(resp.text, "lxml")

            for a_tag in soup.find_all("a", href=True):
                raw_href = a_tag["href"].strip()
                abs_url = urljoin(clean_url, raw_href)
                parsed_link = urlparse(abs_url)

                if parsed_link.scheme not in ("http", "https"):
                    continue

                link_netloc = parsed_link.netloc
                anchor_text = a_tag.get_text(strip=True)
                context = self._surrounding_context(a_tag)

                if link_netloc and link_netloc != base_netloc:
                    # External link — record it
                    results.append(
                        {
                            "source_page": clean_url,
                            "link_url": abs_url,
                            "anchor_text": anchor_text,
                            "surrounding_context": context,
                        }
                    )
                elif link_netloc == base_netloc and current_depth < depth:
                    # Internal link — enqueue for next depth level
                    candidate = abs_url.split("#")[0]
                    if candidate not in visited:
                        queue.append((candidate, current_depth + 1))

            time.sleep(self.crawl_delay)

        logger.info(
            "Finished crawling %s: %d pages, %d external links found",
            start_url,
            pages_crawled,
            len(results),
        )
        return results
