"""
Validates HTTP status of individual URLs.

Strategy:
  1. Send HEAD (fast, no body transfer).
  2. If server returns 405 (Method Not Allowed), fall back to GET.
  3. On a confirmed broken result, wait retry_delay seconds and try once more.

Status categories returned:
  ok          — 2xx, same or same-apex domain
  broken      — 4xx/5xx, DNS failure, timeout, connection refused
  redirected  — 2xx but final URL is on a different apex domain
"""
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from requests.exceptions import ConnectionError, Timeout

logger = logging.getLogger(__name__)

# Status codes that definitively mean the resource is gone
_BROKEN_CODES = {400, 404, 405, 410, 451, 500, 502, 503, 504}


def _apex_domain(netloc: str) -> str:
    """Strip port and leading 'www.' for a coarse apex-domain comparison."""
    host = netloc.split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _single_attempt(
    url: str, session: requests.Session, timeout: int
) -> dict:
    result = {
        "url": url,
        "status_code": None,
        "status": None,
        "final_url": url,
        "error_message": None,
        "date_checked": datetime.now(timezone.utc).isoformat(),
    }
    try:
        resp = session.head(url, timeout=timeout, allow_redirects=True)

        if resp.status_code == 405:
            # Server rejected HEAD — use GET but don't download the body
            resp = session.get(
                url, timeout=timeout, allow_redirects=True, stream=True
            )
            resp.close()

        result["status_code"] = resp.status_code
        result["final_url"] = resp.url

        original_apex = _apex_domain(urlparse(url).netloc)
        final_apex = _apex_domain(urlparse(resp.url).netloc)

        if resp.status_code in _BROKEN_CODES or resp.status_code >= 400:
            result["status"] = "broken"
        elif original_apex != final_apex:
            # 2xx but landed on a different domain → interesting redirect
            result["status"] = "redirected"
        else:
            result["status"] = "ok"

    except (ConnectionError, OSError) as exc:
        result["status"] = "broken"
        result["error_message"] = f"Connection error: {exc}"
    except Timeout:
        result["status"] = "broken"
        result["error_message"] = "Timeout"
    except Exception as exc:
        result["status"] = "broken"
        result["error_message"] = str(exc)

    return result


def check_link(
    url: str,
    session: requests.Session,
    timeout: int = 10,
    retry_delay: float = 5.0,
) -> dict:
    """
    Check a URL and return a status dict.
    Retries once (after retry_delay seconds) only if the first attempt
    looks broken, to rule out transient server hiccups.
    """
    result = _single_attempt(url, session, timeout)

    if result["status"] == "broken":
        logger.debug("Retrying %s after %.1fs …", url, retry_delay)
        time.sleep(retry_delay)
        retry = _single_attempt(url, session, timeout)
        # Update date to the retry timestamp but keep whichever gives more info
        if retry["status_code"] is not None:
            result = retry
        else:
            result["date_checked"] = retry["date_checked"]

    return result
