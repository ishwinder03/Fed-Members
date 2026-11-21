"""Polite HTTP fetching: one shared session, ~1 request/second, raw-HTML cache on disk."""
import hashlib
import threading
import time
from pathlib import Path

import requests

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
MIN_INTERVAL = 1.0  # seconds between requests


class Fetcher:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT,
                                     "Accept-Language": "en-US,en;q=0.9"})
        self._lock = threading.Lock()
        self._last = 0.0
        self.requests_made = 0

    def cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    def get(self, url: str, use_cache: bool = True) -> str:
        """Return the page body. Listing pages pass use_cache=False so new items show up."""
        path = self.cache_path(url)
        if use_cache and path.exists():
            return path.read_text(encoding="utf-8")
        with self._lock:
            wait = MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.get(url, timeout=30)
            finally:
                self._last = time.monotonic()
                self.requests_made += 1
        resp.raise_for_status()
        resp.encoding = resp.encoding if resp.encoding and resp.encoding.lower() != "iso-8859-1" else "utf-8"
        text = resp.text
        path.write_text(text, encoding="utf-8")
        return text

    def get_json(self, url: str):
        with self._lock:
            wait = MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.get(url, timeout=30)
            finally:
                self._last = time.monotonic()
                self.requests_made += 1
        resp.raise_for_status()
        return resp.json()
