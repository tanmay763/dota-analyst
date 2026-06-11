"""Stratz GraphQL client with a disk cache keyed by query hash.

Import `fetch()` from analysis scripts, or use the CLI, which prints the path
of the cached response file — never the payload — so bulk data stays on disk
and out of LLM context:

    uv run .claude/skills/stratz-analysis/scripts/client.py \
        --query 'query { ... }' [--variables '{"k": 1}'] [--ttl-days 7]

Rules (see DESIGN.md): never embed "now"/current timestamps in the query text
(kills cache hits); pass changing values as variables only if they must change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

STRATZ_URL = "https://api.stratz.com/graphql"
MAX_ATTEMPTS = 5
MIN_INTERVAL_S = 0.35  # stay well under Stratz's 20 req/s and 250 req/min limits


def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _repo_root()
RAW_DIR = REPO_ROOT / "data" / "raw"

load_dotenv(REPO_ROOT / ".env")

_last_request_at = 0.0


class StratzError(RuntimeError):
    """GraphQL-level errors returned by the Stratz API."""


class _RetryableHTTP(Exception):
    def __init__(self, status: int, retry_after: str | None):
        super().__init__(f"retryable HTTP {status}")
        self.retry_after = retry_after


def _token() -> str:
    token = os.getenv("STRATZ_TOKEN")
    if not token:
        raise RuntimeError(
            f"STRATZ_TOKEN is not set; export it or add it to {REPO_ROOT / '.env'}"
        )
    return token


def _throttle() -> None:
    global _last_request_at
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _call_stratz(query: str, variables: dict | None) -> dict:
    headers = {"Authorization": f"Bearer {_token()}", "User-Agent": "STRATZ_API"}
    backoff = 1.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle()
        try:
            resp = httpx.post(
                STRATZ_URL,
                headers=headers,
                json={"query": query, "variables": variables},
                timeout=60,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                raise _RetryableHTTP(resp.status_code, resp.headers.get("Retry-After"))
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.TransportError, _RetryableHTTP) as e:
            if attempt == MAX_ATTEMPTS:
                raise
            retry_after = getattr(e, "retry_after", None)
            delay = float(retry_after) if retry_after else backoff
            print(
                f"stratz: attempt {attempt} failed ({e}); retrying in {delay:.1f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
            backoff *= 2
            continue

        if payload.get("errors"):
            raise StratzError(json.dumps(payload["errors"]))
        return payload["data"]
    raise AssertionError("unreachable")


def cache_key(query: str, variables: dict | None = None) -> str:
    canonical = json.dumps(
        {"q": " ".join(query.split()), "v": variables}, sort_keys=True
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def cache_path(query: str, variables: dict | None = None) -> Path:
    return RAW_DIR / f"{cache_key(query, variables)}.json"


def _age_days(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 86400


def fetch(query: str, variables: dict | None = None, ttl_days: float = 7) -> dict:
    """Return the `data` payload for a query, served from data/raw/ when fresh."""
    path = cache_path(query, variables)
    if path.exists() and _age_days(path) < ttl_days:
        return json.loads(path.read_text())

    data = _call_stratz(query, variables)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    path.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "query": query,
                "variables": variables,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a Stratz GraphQL query into data/raw/ and print the cache path."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query", help="GraphQL query string")
    source.add_argument("--query-file", help="path to a file containing the query")
    parser.add_argument("--variables", help="variables as a JSON object")
    parser.add_argument("--ttl-days", type=float, default=7)
    args = parser.parse_args()

    query = args.query if args.query else Path(args.query_file).read_text()
    variables = json.loads(args.variables) if args.variables else None

    fetch(query, variables, ttl_days=args.ttl_days)
    print(cache_path(query, variables))


if __name__ == "__main__":
    main()
