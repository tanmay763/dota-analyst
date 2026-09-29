"""End-to-end check of a running MCP server, the way a Claude client uses it.

    uv run scripts/e2e_check.py                    # the local server (make serve)
    uv run scripts/e2e_check.py https://<server>   # a deployment (make url)
    uv run scripts/e2e_check.py <url> --cookbook heroStats.winWeek

It signs in as Claude Code does, through Claude Code's real Client ID Metadata Document
and a loopback redirect, pastes the maintainer's STRATZ_TOKEN (from .env, never printed),
then calls every tool over MCP against live Stratz and downloads the hero grid it built.
It also probes the refusals: a wrong Stratz token, a reused code and a missing token.
Prints PASS/FAIL per check and exits 1 on any failure. The project's verify skill
(.claude/skills/verify/SKILL.md) uses it.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
from dotenv import load_dotenv
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
CLIENT_ID = "https://claude.ai/oauth/claude-code-client-metadata"
REDIRECT = "http://localhost:53999/callback"
FETCH = """query ($weeks: Int, $positions: [MatchPlayerPositionType]) {
  heroStats { winWeek(take: $weeks, positionIds: $positions, gameModeIds: [ALL_PICK_RANKED]) {
    week heroId matchCount winCount } }
  constants { heroes { id displayName } }
}"""
TOP_SQL = """SELECT h.displayName AS hero, sum(w.matchCount) AS picks,
       round(sum(w.winCount) / sum(w.matchCount), 4) AS win_rate
FROM d_heroStats_winWeek w JOIN d_constants_heroes h ON h.id = w.heroId
WHERE w.week = (SELECT min(week) FROM d_heroStats_winWeek)
GROUP BY 1 HAVING sum(w.matchCount) >= 200 ORDER BY win_rate DESC LIMIT 5"""

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


def sign_in(base: str, token: str) -> str | None:
    """The whole OAuth flow; returns an access token, or None if a step failed."""
    resource = f"{base}/mcp"
    with httpx.Client(base_url=base, follow_redirects=False, timeout=60) as http:
        unauth = http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        check(
            "unauthenticated /mcp answers 401 with resource_metadata",
            unauth.status_code == 401
            and "resource_metadata" in unauth.headers.get("www-authenticate", ""),
            str(unauth.status_code),
        )
        prm = http.get("/.well-known/oauth-protected-resource/mcp").json()
        check(
            "protected resource is this URL",
            prm.get("resource") == resource,
            prm.get("resource", ""),
        )
        meta = http.get("/.well-known/oauth-authorization-server").json()
        check(
            "authorization server advertises CIMD, iss and public clients",
            meta.get("issuer") == base
            and meta.get("client_id_metadata_document_supported") is True
            and meta.get("authorization_response_iss_parameter_supported") is True
            and meta.get("token_endpoint_auth_methods_supported") == ["none"],
        )
        verifier, challenge = pkce()
        authorize = http.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "e2e",
                "resource": resource,
            },
        )
        if not check(
            "authorize redirects to the connect page",
            authorize.status_code == 302,
            str(authorize.status_code),
        ):
            return None
        request = parse_qs(urlparse(authorize.headers["location"]).query)["request"][0]
        page = http.get("/connect", params={"request": request})
        check(
            "connect page names the client and return host",
            page.status_code == 200
            and "claude.ai" in page.text
            and "localhost" in page.text,
        )
        wrong = http.post(
            "/connect", data={"request": request, "token": "not-a-real-token"}
        )
        check(
            "a wrong Stratz token stays on the page",
            wrong.status_code == 400,
            str(wrong.status_code),
        )
        done = http.post("/connect", data={"request": request, "token": token})
        if not check(
            "the real Stratz token completes sign-in",
            done.status_code == 302,
            str(done.status_code),
        ):
            return None
        query = parse_qs(urlparse(done.headers["location"]).query)
        check(
            "redirect carries state and iss",
            query.get("state") == ["e2e"] and query.get("iss") == [base],
        )
        form = {
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": REDIRECT,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
            "resource": resource,
        }
        exchange = http.post("/token", data=form)
        if not check(
            "code exchanges for tokens",
            exchange.status_code == 200,
            str(exchange.status_code),
        ):
            return None
        tokens = exchange.json()
        check("tokens don't contain the Stratz token", token not in json.dumps(tokens))
        reused = http.post("/token", data=form)
        check(
            "a used code is refused", reused.status_code == 400, str(reused.status_code)
        )
        return tokens["access_token"]


async def tools(base: str, access: str, cookbook_section: str | None) -> None:
    http = httpx2.AsyncClient(
        base_url=base, headers={"Authorization": f"Bearer {access}"}, timeout=120
    )
    async with Client(
        streamable_http_client(f"{base}/mcp", http_client=http)
    ) as client:
        names = sorted(t.name for t in (await client.list_tools()).tools)
        expected = sorted(
            [
                "build_hero_grid",
                "stratz_aggregate",
                "stratz_cookbook",
                "stratz_fetch",
                "stratz_schema_search",
                "stratz_schema_type",
            ]
        )
        check("tools listed", names == expected, ", ".join(names))
        sections = (await client.call_tool("stratz_cookbook", {})).structured_content[
            "sections"
        ]
        check("cookbook lists sections", bool(sections), f"{len(sections)} sections")
        if cookbook_section:
            result = await client.call_tool(
                "stratz_cookbook", {"section": cookbook_section}
            )
            if check(f"cookbook section {cookbook_section!r}", not result.is_error):
                print("\n" + result.structured_content["section"] + "\n")
        found = (
            await client.call_tool("stratz_schema_search", {"term": "herostat"})
        ).structured_content
        check("schema search", "HeroStatsQuery" in found["types"])
        fetched = await client.call_tool(
            "stratz_fetch",
            {"query": FETCH, "variables": {"weeks": 2, "positions": ["POSITION_1"]}},
        )
        if not check(
            "fetch from live Stratz",
            not fetched.is_error,
            "" if not fetched.is_error else fetched.content[0].text[:200],
        ):
            return
        dataset = fetched.structured_content["dataset"]
        shape = [(t["table"], t["rows"]) for t in fetched.structured_content["tables"]]
        check(
            "fetch returns a shape, not rows",
            all(len(t["sample"]) <= 5 for t in fetched.structured_content["tables"]),
            str(shape),
        )
        top = await client.call_tool(
            "stratz_aggregate", {"datasets": {"d": dataset}, "sql": TOP_SQL}
        )
        rows = top.structured_content["rows"] if not top.is_error else []
        check("aggregate over the dataset", bool(rows), str(rows[:3]))
        stamp = await client.call_tool(
            "stratz_aggregate",
            {
                "datasets": {"d": dataset},
                "sql": "SELECT to_timestamp(max(week)) AS latest FROM d_heroStats_winWeek",
            },
        )
        check("aggregate returns time-zone-aware timestamps", not stamp.is_error)
        bad = await client.call_tool("stratz_fetch", {"query": "mutation { x { y } }"})
        check("a mutation is refused", bad.is_error)
        grid = await client.call_tool(
            "build_hero_grid",
            {
                "layouts": [
                    {
                        "name": "e2e check",
                        "rows": [
                            [
                                {
                                    "name": "Top",
                                    "heroes": [r[0] for r in rows[:3]] or ["Axe"],
                                }
                            ]
                        ],
                    }
                ]
            },
        )
        if not check("build a hero grid", not grid.is_error):
            return
        url = grid.structured_content["download_url"]
        check("grid reply carries the download link", url in grid.content[0].text)
    with httpx.Client(timeout=30) as http:
        download = http.get(url)
        check(
            "download serves hero_grid_config.json",
            download.status_code == 200
            and "hero_grid_config.json"
            in download.headers.get("content-disposition", ""),
            str(download.status_code),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "url",
        nargs="?",
        default="http://127.0.0.1:8000",
        help="the server's PUBLIC_URL",
    )
    parser.add_argument(
        "--cookbook",
        metavar="SECTION",
        help="also print this cookbook section as served",
    )
    args = parser.parse_args()
    base = args.url.rstrip("/")
    load_dotenv(ROOT / ".env")
    token = os.environ.get("STRATZ_TOKEN")
    if not token:
        print("e2e_check: STRATZ_TOKEN isn't set (.env)", file=sys.stderr)
        return 2
    print(f"Checking {base}\n")
    access = sign_in(base, token)
    if access:
        asyncio.run(tools(base, access, args.cookbook))
    print(
        f"\n{'All checks passed' if not failures else f'{len(failures)} failed: ' + '; '.join(failures)}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
