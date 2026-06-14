"""Direct-API fleet client for cloud + local Researcher.

Keys come from env vars set by Actions secrets in the cloud, or from
`/Volumes/EOS_DIGITAL/llm-fleet/.env` locally (caller's responsibility).

Providers (cloud pool sizing from buildroad):
    Cerebras  ×4  — fast 8B/70B Llama family, free tier generous
    Groq      ×2  — same family, secondary
    OpenRouter×3  — fallback / variety

All providers expose OpenAI-compatible /chat/completions. We round-robin
across keys and fail over across providers on any non-2xx.

Budget tracking writes to ops/budget.json in `finally` blocks so crashes
still record spend.
"""
from __future__ import annotations

import json
import os
import random
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import requests

BUDGET_FILE = Path(os.environ.get("BUDGET_FILE", "ops/budget.json"))


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

@dataclass
class Budget:
    fleet_calls: int = 0
    searches:   int = 0
    cycle_start: str = ""

    @classmethod
    def load(cls) -> "Budget":
        if not BUDGET_FILE.exists():
            return cls(cycle_start=datetime.now(timezone.utc).isoformat())
        try:
            data = json.loads(BUDGET_FILE.read_text())
            today = datetime.now(timezone.utc).date().isoformat()
            if data.get("date") != today:
                return cls(cycle_start=datetime.now(timezone.utc).isoformat())
            return cls(
                fleet_calls=data.get("fleet_calls", 0),
                searches=data.get("searches", 0),
                cycle_start=data.get("cycle_start", ""),
            )
        except Exception:
            return cls(cycle_start=datetime.now(timezone.utc).isoformat())

    def save(self) -> None:
        BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        BUDGET_FILE.write_text(json.dumps({
            "date": datetime.now(timezone.utc).date().isoformat(),
            "cycle_start": self.cycle_start,
            "fleet_calls": self.fleet_calls,
            "searches": self.searches,
        }, indent=2))


class BudgetExceeded(RuntimeError):
    pass


# Per-cycle hard caps (buildroad).
MAX_FLEET_CALLS_PER_CYCLE = 40
MAX_SEARCHES_PER_CYCLE    = 8
MAX_FLEET_CALLS_PER_DAY   = 1000
MAX_SEARCHES_PER_DAY      = 80


@contextmanager
def budget_guard(*, kind: str) -> Iterator[Budget]:
    """Pre-flight check; raise if budget already exhausted."""
    b = Budget.load()
    if kind == "fleet" and b.fleet_calls >= MAX_FLEET_CALLS_PER_DAY:
        raise BudgetExceeded(f"daily fleet budget hit ({b.fleet_calls})")
    if kind == "search" and b.searches >= MAX_SEARCHES_PER_DAY:
        raise BudgetExceeded(f"daily search budget hit ({b.searches})")
    try:
        yield b
    finally:
        b.save()


# ---------------------------------------------------------------------------
# Providers — OpenAI-compat /chat/completions
# ---------------------------------------------------------------------------

def _env_keys(prefix: str) -> list[str]:
    """Pick up CEREBRAS_KEY_1..N, or fall back to CEREBRAS_API_KEYS (csv)."""
    numbered = sorted(
        [(k, v) for k, v in os.environ.items() if k.startswith(prefix + "_KEY_") and v],
        key=lambda kv: kv[0],
    )
    if numbered:
        return [v for _, v in numbered]
    csv = os.environ.get(f"{prefix}_API_KEYS", "")
    return [k.strip() for k in csv.split(",") if k.strip()]


PROVIDERS = [
    {
        "name": "cerebras",
        "url":  "https://api.cerebras.ai/v1/chat/completions",
        "keys_env": "CEREBRAS",
        "model": "llama3.1-8b",
    },
    {
        "name": "groq",
        "url":  "https://api.groq.com/openai/v1/chat/completions",
        "keys_env": "GROQ",
        "model": "llama-3.1-8b-instant",
    },
    {
        "name": "openrouter",
        "url":  "https://openrouter.ai/api/v1/chat/completions",
        "keys_env": "OPENROUTER",
        "model": "meta-llama/llama-3.1-8b-instruct:free",
    },
]


@dataclass
class FleetResult:
    provider: str
    model: str
    text: str
    elapsed_ms: int
    error: Optional[str] = None


def chat(
    *,
    system: str,
    user: str,
    temperature: float = 0.2,
    timeout: int = 25,
    response_format_json: bool = False,
) -> FleetResult:
    """Round-robin over providers and keys. First success wins.

    Counts a call against the per-cycle / per-day budget on every ATTEMPT,
    successful or not — so a flapping key still trips the brake.
    """
    last_error = "no providers configured"
    for prov in PROVIDERS:
        keys = _env_keys(prov["keys_env"])
        if not keys:
            continue
        random.shuffle(keys)
        for key in keys:
            with budget_guard(kind="fleet") as b:
                b.fleet_calls += 1
            t0 = time.monotonic()
            payload = {
                "model": prov["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "temperature": temperature,
            }
            if response_format_json:
                payload["response_format"] = {"type": "json_object"}
            try:
                r = requests.post(
                    prov["url"],
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type":  "application/json",
                    },
                    json=payload,
                    timeout=timeout,
                )
                if r.status_code >= 400:
                    last_error = f"{prov['name']}/{key[-6:]}: HTTP {r.status_code}"
                    continue
                data = r.json()
                text = data["choices"][0]["message"]["content"]
                return FleetResult(
                    provider=prov["name"],
                    model=prov["model"],
                    text=text,
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                )
            except (requests.RequestException, KeyError, ValueError) as e:
                last_error = f"{prov['name']}/{key[-6:]}: {e}"
                continue
    return FleetResult(provider="none", model="", text="", elapsed_ms=0, error=last_error)
