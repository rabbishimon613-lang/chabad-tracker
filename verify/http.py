"""Raw-HTTP fetcher with per-process page cache.

Verifier doctrine (buildroad §"Verifier infra rules"):
- All page-fetch layers (1, 2, 3, 4, 5, 6, 10) use raw HTTP, NEVER Tavily/Exa.
  Search budget is preserved for discovery.
- Per-cycle page cache in /tmp keyed by URL — one fetch satisfies multiple layers.
- Wayback submission fire-and-forget.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

CACHE_DIR = Path(os.environ.get("VERIFY_CACHE_DIR", "/tmp/chabad-verify-cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "ChabadTrackerVerifier/0.1 (+https://github.com/rabbishimon613-lang/chabad-tracker)"
)
DEFAULT_TIMEOUT = 12
MAX_BYTES = 4 * 1024 * 1024  # 4MB cap — most legitimate news/court pages fit comfortably.


@dataclass
class FetchResult:
    url: str
    status: int                   # HTTP status; 0 = network error
    text: str                     # decoded body (may be empty on HEAD or error)
    final_url: str                # after redirects
    elapsed_ms: int
    from_cache: bool
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400


def _cache_key(url: str) -> Path:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return CACHE_DIR / f"{h}.txt"


def head(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> FetchResult:
    """HEAD request — Layer 1 (URL liveness). Never cached; cheap enough."""
    t0 = time.monotonic()
    try:
        r = requests.head(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        return FetchResult(
            url=url, status=r.status_code, text="",
            final_url=str(r.url),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            from_cache=False,
        )
    except requests.RequestException as e:
        # Some servers reject HEAD outright (405). Fall through to a tiny GET.
        if isinstance(e, requests.exceptions.HTTPError):
            return FetchResult(
                url=url, status=0, text="", final_url=url,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                from_cache=False, error=str(e),
            )
        return FetchResult(
            url=url, status=0, text="", final_url=url,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            from_cache=False, error=str(e),
        )


def get(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> FetchResult:
    """GET with per-process cache. Body limited to MAX_BYTES."""
    cache_path = _cache_key(url)
    if cache_path.exists():
        try:
            payload = cache_path.read_text(encoding="utf-8", errors="replace")
            head, _, body = payload.partition("\n---\n")
            status, final_url = head.split("\t", 1)
            return FetchResult(
                url=url, status=int(status), text=body, final_url=final_url,
                elapsed_ms=0, from_cache=True,
            )
        except Exception:
            cache_path.unlink(missing_ok=True)

    t0 = time.monotonic()
    try:
        r = requests.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            stream=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*"},
        )
        content = b""
        for chunk in r.iter_content(chunk_size=16 * 1024):
            content += chunk
            if len(content) >= MAX_BYTES:
                break
        # Best-effort decode.
        encoding = r.encoding or "utf-8"
        try:
            text = content.decode(encoding, errors="replace")
        except LookupError:
            text = content.decode("utf-8", errors="replace")
        result = FetchResult(
            url=url, status=r.status_code, text=text,
            final_url=str(r.url),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            from_cache=False,
        )
        # Cache only successful responses.
        if result.ok:
            cache_path.write_text(
                f"{result.status}\t{result.final_url}\n---\n{result.text}",
                encoding="utf-8",
            )
        return result
    except requests.RequestException as e:
        return FetchResult(
            url=url, status=0, text="", final_url=url,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            from_cache=False, error=str(e),
        )


def clear_cache() -> int:
    """Drop the entire on-disk cache. Returns files removed."""
    n = 0
    for f in CACHE_DIR.glob("*.txt"):
        f.unlink(missing_ok=True)
        n += 1
    return n
