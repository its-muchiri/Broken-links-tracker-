"""
Matches a broken link (by its anchor text, surrounding context, and URL)
against a list of your own URLs, returning the best replacement candidates.

Matching is keyword-overlap based: each URL slug is tokenised on hyphens,
then scored against the tokens found in the broken link's text signals.
No external API or ML model required.
"""
import re
from urllib.parse import urlparse

# Words that appear in nearly every URL and carry no topic signal
_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on",
    "at", "by", "with", "is", "are", "was", "be", "it",
    "lawyer", "attorney", "legal", "law", "guide", "expert",
    "best", "top", "rated", "ultimate", "choosing", "finding",
    "help", "near", "me", "your", "my", "our", "how",
    "rights", "claim", "claims", "case", "cases", "justice",
    "counsel", "american", "2", "3",
}


def _tokens(text: str) -> set[str]:
    """Lowercase words from text, stripped of stopwords and short tokens."""
    words = re.split(r"[\s\-_/]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _slug(url: str) -> str:
    return urlparse(url).path.strip("/")


def build_index(my_urls: list[str]) -> list[tuple[str, set[str]]]:
    """Pre-tokenise all your URLs into (url, token_set) pairs."""
    return [(url, _tokens(_slug(url))) for url in my_urls]


def find_replacements(
    anchor_text: str,
    context: str,
    broken_url: str,
    index: list[tuple[str, set[str]]],
    top_n: int = 3,
) -> list[dict]:
    """
    Score each of your URLs against the broken link's signals.
    Returns up to top_n matches, sorted by score descending.
    Only returns entries with score > 0.
    """
    # Build a combined token bag from all signals
    signal = (
        _tokens(anchor_text)
        | _tokens(context)
        | _tokens(_slug(broken_url))
    )

    if not signal:
        return []

    scored = []
    for url, url_tokens in index:
        overlap = signal & url_tokens
        if overlap:
            scored.append(
                {
                    "url": url,
                    "score": len(overlap),
                    "matched_on": ", ".join(sorted(overlap)),
                }
            )

    scored.sort(key=lambda x: -x["score"])
    return scored[:top_n]
