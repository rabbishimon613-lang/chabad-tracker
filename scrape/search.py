"""Direct-API search clients for Tavily + Exa.

Cloud pool sizing: 3 Tavily + 3 Exa keys, picked up from env. Each search
costs against the per-cycle search budget (8/cycle, 80/day).
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from .fleet import budget_guard, _env_keys


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    score: float = 0.0
    raw: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    provider: str
    query: str
    hits: list[SearchHit]
    elapsed_ms: int
    error: Optional[str] = None


def tavily(query: str, *, n: int = 5, timeout: int = 15) -> SearchResult:
    keys = _env_keys("TAVILY")
    if not keys:
        return SearchResult(provider="tavily", query=query, hits=[], elapsed_ms=0, error="no_keys")
    random.shuffle(keys)
    last = None
    for key in keys:
        with budget_guard(kind="search") as b:
            b.searches += 1
        t0 = time.monotonic()
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": key, "query": query, "max_results": n, "search_depth": "basic"},
                timeout=timeout,
            )
            if r.status_code >= 400:
                last = f"{key[-6:]}: HTTP {r.status_code}"
                continue
            data = r.json()
            hits = [
                SearchHit(
                    title=h.get("title", ""),
                    url=h.get("url", ""),
                    snippet=h.get("content", ""),
                    score=h.get("score", 0.0),
                    raw=h,
                )
                for h in data.get("results", [])
            ]
            return SearchResult(
                provider="tavily", query=query, hits=hits,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )
        except requests.RequestException as e:
            last = f"{key[-6:]}: {e}"
            continue
    return SearchResult(provider="tavily", query=query, hits=[], elapsed_ms=0, error=last)


def exa(query: str, *, n: int = 5, timeout: int = 15) -> SearchResult:
    keys = _env_keys("EXA")
    if not keys:
        return SearchResult(provider="exa", query=query, hits=[], elapsed_ms=0, error="no_keys")
    random.shuffle(keys)
    last = None
    for key in keys:
        with budget_guard(kind="search") as b:
            b.searches += 1
        t0 = time.monotonic()
        try:
            r = requests.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": key, "Content-Type": "application/json"},
                json={
                    "query": query, "numResults": n, "type": "neural",
                    "contents": {"text": True},
                },
                timeout=timeout,
            )
            if r.status_code >= 400:
                last = f"{key[-6:]}: HTTP {r.status_code}"
                continue
            data = r.json()
            hits = [
                SearchHit(
                    title=h.get("title", ""),
                    url=h.get("url", ""),
                    snippet=(h.get("text") or "")[:600],
                    score=h.get("score", 0.0),
                    raw=h,
                )
                for h in data.get("results", [])
            ]
            return SearchResult(
                provider="exa", query=query, hits=hits,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )
        except requests.RequestException as e:
            last = f"{key[-6:]}: {e}"
            continue
    return SearchResult(provider="exa", query=query, hits=[], elapsed_ms=0, error=last)


def both(query: str, *, n: int = 4) -> list[SearchHit]:
    """Run both providers, dedupe by URL."""
    seen: dict[str, SearchHit] = {}
    for res in (tavily(query, n=n), exa(query, n=n)):
        for h in res.hits:
            if h.url and h.url not in seen:
                seen[h.url] = h
    return list(seen.values())
