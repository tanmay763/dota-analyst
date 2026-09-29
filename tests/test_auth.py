"""Sign-in with the user's own Stratz token (ADR 0002, 0003), driven over HTTP like Claude does.

Claude's CIMD document is stubbed (conftest.client_documents); Stratz answers the token check
through the `stratz` fixture.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from conftest import (
    CLAUDE_CALLBACK,
    CLIENT_ID,
    PUBLIC_URL,
    RESOURCE,
    STRATZ_TOKEN,
    authorize,
    exchange,
    pkce,
    sign_in,
)
from cryptography.fernet import Fernet

from dota_analyst_mcp import auth
from dota_analyst_mcp.auth import Sealer


def test_metadata_advertises_cimd_public_clients_and_iss(http):
    metadata = http.get("/.well-known/oauth-authorization-server").json()
    assert metadata["issuer"] == PUBLIC_URL
    assert metadata["client_id_metadata_document_supported"] is True
    assert metadata["token_endpoint_auth_methods_supported"] == ["none"]
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["authorization_response_iss_parameter_supported"] is True
    assert "registration_endpoint" not in metadata


def test_an_unauthenticated_mcp_call_points_at_the_resource_metadata(http):
    response = http.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"}
    )
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]
    resource = http.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == RESOURCE
    assert resource["authorization_servers"] == [PUBLIC_URL]


def test_the_connect_page_names_the_client_and_where_it_returns(http):
    _, challenge = pkce()
    connect = authorize(http, challenge)
    page = http.get(connect.headers["location"])
    assert page.status_code == 200
    assert "claude.ai" in page.text and "stratz.com/api" in page.text
    assert page.headers["x-frame-options"] == "DENY"


def test_the_full_flow_issues_tokens_and_returns_iss(http, stratz):
    code, verifier = sign_in(http, stratz)
    response = exchange(http, code, verifier)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"].lower() == "bearer" and body["refresh_token"]
    assert STRATZ_TOKEN not in body["access_token"]  # sealed, not merely encoded


def test_the_redirect_carries_state_and_issuer(http, stratz):
    _, queue = stratz
    _, challenge = pkce()
    connect = authorize(http, challenge)
    request = parse_qs(urlparse(connect.headers["location"]).query)["request"][0]
    queue.append((200, {"data": {"constants": {"gameVersions": []}}}))
    done = http.post("/connect", data={"request": request, "token": STRATZ_TOKEN})
    location = urlparse(done.headers["location"])
    query = parse_qs(location.query)
    assert f"{location.scheme}://{location.netloc}{location.path}" == CLAUDE_CALLBACK
    assert query["state"] == ["st4te"] and query["iss"] == [PUBLIC_URL]


def test_a_token_stratz_rejects_keeps_the_user_on_the_page(http, stratz):
    _, queue = stratz
    _, challenge = pkce()
    connect = authorize(http, challenge)
    request = parse_qs(urlparse(connect.headers["location"]).query)["request"][0]
    queue.append((403, {"message": "A Bearer Token is required"}))
    page = http.post("/connect", data={"request": request, "token": "wrong"})
    assert page.status_code == 400 and "didn" in page.text


def test_a_code_works_once(http, stratz):
    code, verifier = sign_in(http, stratz)
    assert exchange(http, code, verifier).status_code == 200
    again = exchange(http, code, verifier)
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"


def test_a_wrong_code_verifier_is_refused(http, stratz):
    code, _ = sign_in(http, stratz)
    wrong, _ = pkce()
    response = exchange(http, code, wrong)
    assert response.status_code == 400 and response.json()["error"] == "invalid_grant"


def test_an_expired_code_is_refused(http, stratz, clock):
    code, verifier = sign_in(http, stratz)
    clock.now += auth.CODE_TTL + 1
    assert exchange(http, code, verifier).status_code == 400


def test_a_tampered_code_is_refused(http, stratz):
    code, verifier = sign_in(http, stratz)
    tampered = code[:-4] + ("AAAA" if not code.endswith("AAAA") else "BBBB")
    assert exchange(http, tampered, verifier).status_code == 400


def test_refresh_tokens_rotate_and_work_once(http, tokens):
    def refresh(token):
        return http.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": token,
                "client_id": CLIENT_ID,
            },
        )

    first = refresh(tokens["refresh_token"])
    assert first.status_code == 200
    assert first.json()["refresh_token"] != tokens["refresh_token"]
    reused = refresh(tokens["refresh_token"])
    assert reused.status_code == 400 and reused.json()["error"] == "invalid_grant"
    assert refresh(first.json()["refresh_token"]).status_code == 200


def test_a_redirect_outside_the_client_document_is_refused(http):
    _, challenge = pkce()
    response = authorize(http, challenge, redirect_uri="https://evil.example/callback")
    assert response.status_code == 400  # never redirected to an unregistered URI


def test_claude_code_loopback_ports_are_accepted(http, stratz):
    redirect = "http://localhost:53682/callback"
    code, verifier = sign_in(http, stratz, redirect_uri=redirect)
    assert exchange(http, code, verifier, redirect_uri=redirect).status_code == 200


def test_a_loopback_with_another_path_is_refused(http):
    _, challenge = pkce()
    response = authorize(http, challenge, redirect_uri="http://localhost:53682/other")
    assert response.status_code == 400


def test_an_unknown_client_is_refused(http):
    _, challenge = pkce()
    response = http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "https://unknown.example/client.json",
            "redirect_uri": CLAUDE_CALLBACK,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert response.status_code == 400


def test_a_token_for_another_resource_is_not_issued(http):
    _, challenge = pkce()
    response = authorize(http, challenge, resource="https://other.example/mcp")
    location = parse_qs(urlparse(response.headers["location"]).query)
    assert location["error"] == ["invalid_target"]


def test_access_tokens_sealed_for_another_server_are_refused(http, settings, clock):
    other = Sealer(settings.seal_keys).seal(
        "access",
        {
            "client_id": CLIENT_ID,
            "token": STRATZ_TOKEN,
            "resource": "https://other.example/mcp",
            "exp": 9e12,
        },
    )
    response = http.post(
        "/mcp",
        headers={"Authorization": f"Bearer {other}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
    )
    assert response.status_code == 401


def test_access_tokens_sealed_with_another_key_are_refused(http):
    forged = Sealer([Fernet.generate_key().decode()]).seal(
        "access",
        {"client_id": CLIENT_ID, "token": "x", "resource": RESOURCE, "exp": 9e12},
    )
    response = http.post(
        "/mcp",
        headers={"Authorization": f"Bearer {forged}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
    )
    assert response.status_code == 401


def test_a_code_is_never_accepted_as_an_access_token(http, stratz):
    code, _ = sign_in(http, stratz)
    response = http.post(
        "/mcp",
        headers={"Authorization": f"Bearer {code}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
    )
    assert response.status_code == 401


def test_rotating_in_a_new_key_keeps_old_tokens_open(settings):
    old = Sealer(settings.seal_keys)
    blob = old.seal("access", {"exp": 9e12})
    rotated = Sealer([Fernet.generate_key().decode(), *settings.seal_keys])
    assert rotated.open("access", blob, now=0) is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://claude.ai/client.json",  # not https
        "https://127.0.0.1/client.json",  # loopback
        "https://10.0.0.8/client.json",  # private
        "https://169.254.169.254/latest/meta-data",  # link-local (cloud metadata)
        "file:///etc/passwd",
    ],
)
def test_client_documents_are_only_fetched_from_public_https(url, monkeypatch):
    import httpx

    def refuse(*args, **kwargs):
        raise AssertionError("must not fetch")

    monkeypatch.setattr(httpx, "stream", refuse)
    assert auth.fetch_client_document(url) is None
