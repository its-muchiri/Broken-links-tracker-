"""
Central configuration dataclass.

Priority (highest to lowest):
  1. CLI flags          (applied in main.py after construction)
  2. JSON --config file (from_file)
  3. Environment vars   (.env or shell environment)
  4. Hardcoded defaults
"""
import json
import os
from dataclasses import asdict, dataclass

from dotenv import load_dotenv

load_dotenv()  # reads .env into os.environ if present; no-op if file missing


def _user_agent_from_env() -> str:
    name    = os.environ.get("CONTACT_NAME",    "YourName")
    website = os.environ.get("CONTACT_WEBSITE", "https://yourwebsite.com")
    email   = os.environ.get("CONTACT_EMAIL",   "your@email.com")
    return f"BrokenLinkFinder/1.0 ({name}; +{website}; contact:{email})"


@dataclass
class Config:
    crawl_depth:          int   = int(  os.environ.get("CRAWL_DEPTH",           "1"))
    crawl_delay:          float = float(os.environ.get("CRAWL_DELAY",           "2.5"))
    max_pages_per_domain: int   = int(  os.environ.get("MAX_PAGES_PER_DOMAIN",  "50"))
    request_timeout:      int   = int(  os.environ.get("REQUEST_TIMEOUT",       "10"))
    retry_delay:          float = float(os.environ.get("RETRY_DELAY",           "5.0"))
    user_agent:           str   = _user_agent_from_env()
    output_dir:           str   = os.environ.get("OUTPUT_DIR", "output")

    @classmethod
    def from_file(cls, path: str) -> "Config":
        """Load from a JSON config file; env vars are the baseline, file overrides them."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
