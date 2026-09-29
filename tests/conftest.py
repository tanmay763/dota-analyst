"""Shared fixtures. No test reaches Stratz or GCP: httpx.post is replaced per test."""

import base64
import hashlib
import secrets
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from dota_analyst_mcp import stratz as stratz_module
from dota_analyst_mcp.app import Settings, create_app
from dota_analyst_mcp.store import LocalStore


class Clock:
    """Starts at the real time: the SDK's token handler checks expiry against time.time()."""

    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return LocalStore(tmp_path / "state", clock=clock)


@pytest.fixture
def stratz(monkeypatch):
    """httpx.post answering with queued responses; records every call."""
    calls, queue = [], []

    def post(url, **kwargs):
        calls.append(kwargs)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        status, body = outcome
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    return calls, queue


@pytest.fixture
def live(store, clock):
    return stratz_module.LiveStratz(
        store, clock=clock, sleep=lambda s: None, min_interval=0
    )


# --- a signed-in client -----------------------------------------------------------------

PUBLIC_URL = "http://127.0.0.1:8000"
RESOURCE = f"{PUBLIC_URL}/mcp"
CLIENT_ID = "https://claude.ai/oauth/mcp-oauth-client-metadata"
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
STRATZ_TOKEN = "friend-stratz-token"


def client_documents(url: str):
    """A stubbed CIMD fetch: Claude's document, and nothing else exists."""
    if url != CLIENT_ID:
        return None
    return (
        {
            "client_id": CLIENT_ID,
            "client_name": "Claude",
            "redirect_uris": [CLAUDE_CALLBACK, "http://localhost/callback"],
        },
        3600,
    )


@pytest.fixture
def settings(store, clock):
    return Settings(
        public_url=PUBLIC_URL,
        seal_keys=[Fernet.generate_key().decode()],
        store=store,
        fetch_document=client_documents,
        clock=clock,
    )


@pytest.fixture
def http(settings):
    with TestClient(
        create_app(settings), base_url=PUBLIC_URL, follow_redirects=False
    ) as client:
        yield client


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def authorize(http, challenge, redirect_uri=CLAUDE_CALLBACK, resource=RESOURCE):
    return http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st4te",
            "resource": resource,
        },
    )


def sign_in(http, stratz, redirect_uri=CLAUDE_CALLBACK) -> tuple[str, str]:
    """Authorize, paste the Stratz token, and return (code, verifier)."""
    _, queue = stratz
    verifier, challenge = pkce()
    connect = authorize(http, challenge, redirect_uri)
    assert connect.status_code == 302, connect.text
    request = parse_qs(urlparse(connect.headers["location"]).query)["request"][0]
    queue.append((200, {"data": {"constants": {"gameVersions": [{"id": 1}]}}}))
    done = http.post("/connect", data={"request": request, "token": STRATZ_TOKEN})
    assert done.status_code == 302, done.text
    query = parse_qs(urlparse(done.headers["location"]).query)
    return query["code"][0], verifier


def exchange(http, code, verifier, redirect_uri=CLAUDE_CALLBACK):
    return http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    )


@pytest.fixture
def tokens(http, stratz):
    code, verifier = sign_in(http, stratz)
    response = exchange(http, code, verifier)
    assert response.status_code == 200, response.text
    return response.json()
