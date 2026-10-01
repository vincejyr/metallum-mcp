"""Polite HTTP client for pymetal.

pymetal's stock client impersonates Chrome's TLS fingerprint and rotates a
random User-Agent on every request. We don't need either (plain requests are
served fine) and the site's robots.txt asks for a 3s crawl delay, so this
subclass sends an honest, fixed User-Agent and serialises all requests with a
minimum gap between them.

Discography pages also go into a small SQLite cache on disk, so review-stat
scans across many bands survive restarts and don't re-crawl the site.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from pymetal.http import Client, Response

MIN_INTERVAL_S = float(os.environ.get("MA_MIN_INTERVAL_MS", "3000")) / 1000
CACHE_TTL_S = float(os.environ.get("MA_CACHE_TTL_MS", str(30 * 60 * 1000))) / 1000
DISK_CACHE_TTL_S = float(os.environ.get("MA_DISK_CACHE_TTL_DAYS", "7")) * 86400
DISK_CACHE_DIR = Path(os.environ.get("MA_CACHE_DIR", Path.home() / ".cache" / "metallum-mcp"))
# Pages that change rarely and are fetched in bulk; everything else stays memory-only.
DISK_CACHE_PREFIXES = ("band/discography/",)
# Fixtures for evals: "record" fetches live and saves every response; "replay" serves only
# saved responses and never touches the network. Off unless both variables are set.
FIXTURE_MODE = os.environ.get("MA_FIXTURE_MODE", "")
FIXTURE_DB = os.environ.get("MA_FIXTURES", "")
FIXTURE_MISS = "FIXTURE_MISS"
USER_AGENT = os.environ.get(
    "MA_USER_AGENT", "Mozilla/5.0 (compatible; metallum-mcp/1.0; personal use)"
)


class PoliteClient(Client):
    def __init__(self) -> None:
        # impersonate=None: plain curl, no browser TLS fingerprint.
        super().__init__(impersonate=None, cache_ttl=CACHE_TTL_S)
        self._throttle = threading.Lock()
        self._last_request = 0.0
        # Total row count of the last datatable (search/browse) response, per thread.
        # Each tool call runs in its own worker thread, so this can't leak across calls.
        self.last_total = threading.local()
        self._disk: Optional[sqlite3.Connection] = None
        self._disk_lock = threading.Lock()
        self._fixtures: Optional[sqlite3.Connection] = None
        if FIXTURE_MODE or FIXTURE_DB:
            if FIXTURE_MODE not in ("record", "replay") or not FIXTURE_DB:
                raise RuntimeError("Set both MA_FIXTURES=<path> and MA_FIXTURE_MODE=record|replay.")
            self._fixtures = sqlite3.connect(FIXTURE_DB, check_same_thread=False)
            self._fixtures.execute(
                "CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, status INTEGER, content BLOB, text TEXT)"
            )
        elif DISK_CACHE_TTL_S > 0:
            try:
                DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                self._disk = sqlite3.connect(DISK_CACHE_DIR / "cache.sqlite", check_same_thread=False)
                self._disk.execute(
                    "CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, ts REAL, content BLOB, text TEXT)"
                )
            except (OSError, sqlite3.Error):
                self._disk = None  # cache is an optimisation; run without it

    def _disk_get(self, url: str) -> Optional[tuple[bytes, str]]:
        if self._disk is None or not url.startswith(tuple(self.base_url + p for p in DISK_CACHE_PREFIXES)):
            return None
        with self._disk_lock:
            row = self._disk.execute("SELECT ts, content, text FROM pages WHERE url = ?", (url,)).fetchone()
        if row is None or time.time() - row[0] > DISK_CACHE_TTL_S:
            return None
        return row[1], row[2]

    def _disk_put(self, url: str, content: bytes, text: str) -> None:
        if self._disk is None or not url.startswith(tuple(self.base_url + p for p in DISK_CACHE_PREFIXES)):
            return
        with self._disk_lock:
            self._disk.execute(
                "INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?)", (url, time.time(), content, text)
            )
            self._disk.commit()

    @staticmethod
    def _fixture_key(url: str, params: Optional[Mapping[str, Any]]) -> str:
        items = sorted((k, str(v)) for k, v in (params or {}).items())
        return url + ("?" + "&".join(f"{k}={v}" for k, v in items) if items else "")

    def _fixture_get(self, url: str, params: Optional[Mapping[str, Any]]) -> Optional[Response]:
        key = self._fixture_key(url, params)
        with self._disk_lock:
            row = self._fixtures.execute("SELECT status, content, text FROM responses WHERE key = ?", (key,)).fetchone()
        if row is None:
            if FIXTURE_MODE == "replay":
                raise RuntimeError(f"{FIXTURE_MISS}: no recorded response for {key}")
            return None
        if row[0] == 404:
            raise LookupError(f"Not found on Metal Archives: {url}")
        return Response(row[1], row[2], url=url, from_cache=True)

    def _fixture_put(self, url: str, params: Optional[Mapping[str, Any]], status: int, content: bytes, text: str) -> None:
        with self._disk_lock:
            self._fixtures.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?)",
                (self._fixture_key(url, params), status, content, text),
            )
            self._fixtures.commit()

    def get_json(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        data = super().get_json(path, params=params)
        if isinstance(data, dict) and "iTotalRecords" in data:
            self.last_total.value = int(data.get("iTotalRecords") or 0)
        return data

    def get(
        self,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        use_cache: bool = True,
    ) -> Response:
        url = path if path.startswith("http") else self.base_url + path.lstrip("/")
        key = self._key("GET", url, params)
        if self._fixtures is not None:
            recorded = self._fixture_get(url, params)
            if recorded is not None:
                return recorded
        elif use_cache:
            cached = self._cache_get(key)
            if cached is not None:
                return Response(*cached, url=url, from_cache=True)
            if not params:
                cached = self._disk_get(url)
                if cached is not None:
                    self._cache_put(key, *cached)
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
        content, text = r.content, r.text
        if self._fixtures is not None and r.status_code in (200, 404):
            self._fixture_put(url, params, r.status_code, content, text)
        if r.status_code == 404:
            raise LookupError(f"Not found on Metal Archives: {url}")
        final_url = getattr(r, "url", url) or url
        if use_cache and r.status_code == 200:
            self._cache_put(key, content, text)
            if not params:
                self._disk_put(url, content, text)
        return Response(content, text, url=final_url, from_cache=False)
