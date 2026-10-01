"""Polite HTTP client for pymetal.

pymetal's stock client impersonates Chrome's TLS fingerprint and rotates a
random User-Agent on every request. We don't need either (plain requests are
served fine) and the site's robots.txt asks for a 3s crawl delay, so this
subclass sends an honest, fixed User-Agent and serialises all requests with a
minimum gap between them.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Mapping, Optional

from pymetal.http import Client, Response

MIN_INTERVAL_S = float(os.environ.get("MA_MIN_INTERVAL_MS", "3000")) / 1000
CACHE_TTL_S = float(os.environ.get("MA_CACHE_TTL_MS", str(30 * 60 * 1000))) / 1000
USER_AGENT = os.environ.get(
    "MA_USER_AGENT", "Mozilla/5.0 (compatible; metallum-mcp/1.0; personal use)"
)


class PoliteClient(Client):
    def __init__(self) -> None:
        # impersonate=None: plain curl, no browser TLS fingerprint.
        super().__init__(impersonate=None, cache_ttl=CACHE_TTL_S)
        self._throttle = threading.Lock()
        self._last_request = 0.0

    def get(
        self,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        use_cache: bool = True,
    ) -> Response:
        url = path if path.startswith("http") else self.base_url + path.lstrip("/")
        key = self._key("GET", url, params)
        if use_cache:
            cached = self._cache_get(key)
            if cached is not None:
                return Response(*cached, url=url, from_cache=True)

        with self._throttle:
            wait = self._last_request + MIN_INTERVAL_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            r = self.session.get(url, params=params, headers={"User-Agent": USER_AGENT})

        if r.status_code in (403, 429, 503):
            raise RuntimeError(
                f"Metal Archives refused the request (HTTP {r.status_code}). "
                "It may be rate limiting; try again in a few minutes."
            )
        if r.status_code == 404:
            raise LookupError(f"Not found on Metal Archives: {url}")
        content, text = r.content, r.text
        final_url = getattr(r, "url", url) or url
        if use_cache and r.status_code == 200:
            self._cache_put(key, content, text)
        return Response(content, text, url=final_url, from_cache=False)
