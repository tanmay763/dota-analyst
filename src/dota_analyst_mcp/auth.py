"""OAuth 2.1 sign-in where the user pastes their own Stratz token (ADR 0002, 0003).

Clients identify themselves with a Client ID Metadata Document (CIMD): the client_id is an
HTTPS URL we fetch for its redirect URIs, so there is no client store. The authorization
request, the code and both tokens are Fernet-sealed blobs carrying what they need (the
Stratz token, PKCE challenge, redirect URI, resource, expiry), so any instance can open
them. The only state is single-use markers in the store: each code and refresh token `jti`
is marked when redeemed, and a second redemption is refused.
"""

import ipaddress
import json
import secrets
import socket
import time
from collections.abc import Callable
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import (
    InvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthMetadata,
    OAuthToken,
)
from pydantic import AnyUrl

from dota_analyst_mcp.store import Store

REQUEST_TTL = 15 * 60  # the connect page stays usable this long
CODE_TTL = 5 * 60
ACCESS_TTL = 3600
REFRESH_TTL = 90 * 24 * 3600
CIMD_TIMEOUT = 5.0
CIMD_MAX_BYTES = 64 * 1024
CIMD_DEFAULT_TTL = 3600
CIMD_MAX_TTL = 24 * 3600
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


# --- sealing ----------------------------------------------------------------------------


class Sealer:
    """Fernet-sealed JSON with a kind, so a code can never be read as a token."""

    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("at least one sealing key is required")
        self._fernet = MultiFernet([Fernet(k) for k in keys])

    def seal(self, kind: str, claims: dict) -> str:
        return self._fernet.encrypt(
            json.dumps({"kind": kind, **claims}).encode()
        ).decode()

    def open(self, kind: str, blob: str, now: float) -> dict | None:
        """The claims, or None if the blob is forged, of another kind or expired."""
        try:
            claims = json.loads(self._fernet.decrypt(blob.encode()))
        except (InvalidToken, ValueError, TypeError):
            return None
        if claims.get("kind") != kind or claims.get("exp", 0) < now:
            return None
        return claims


# --- clients (CIMD) ---------------------------------------------------------------------


def _is_loopback(url: AnyUrl | str) -> bool:
    parsed = urlparse(str(url))
    return parsed.scheme == "http" and (parsed.hostname or "") in LOOPBACK_HOSTS


def _without_port(url: AnyUrl | str) -> tuple[str, str, str, str]:
    parsed = urlparse(str(url))
    return parsed.scheme, parsed.hostname or "", parsed.path or "/", parsed.query


class CimdClient(OAuthClientInformationFull):
    """A public client described by its metadata document."""

    def validate_scope(self, requested_scope: str | None) -> list[str] | None:
        # This server has no scopes; whatever a client asks for grants nothing extra.
        return [] if requested_scope is None else requested_scope.split()

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is None:
            if self.redirect_uris and len(self.redirect_uris) == 1:
                return self.redirect_uris[0]
            raise InvalidRedirectUriError("redirect_uri is required")
        registered = self.redirect_uris or []
        if redirect_uri in registered:
            return redirect_uri
        # Native clients (Claude Code) redirect to a loopback port chosen per session
        # (RFC 8252 §7.3): match loopback URIs with the port ignored.
        if _is_loopback(redirect_uri) and any(
            _is_loopback(r) and _without_port(r) == _without_port(redirect_uri)
            for r in registered
        ):
            return redirect_uri
        raise InvalidRedirectUriError(
            f"Redirect URI '{redirect_uri}' is not in the client's metadata"
        )


def _public_host(host: str) -> bool:
    """Refuse client_id URLs that resolve to private, loopback or link-local addresses."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            return False
    return bool(infos)


def fetch_client_document(url: str) -> tuple[dict, int] | None:
    """GET a CIMD document with SSRF guards; returns (document, cache seconds) or None."""
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not _public_host(parsed.hostname)
    ):
        return None
    try:
        with httpx.stream(
            "GET",
            url,
            timeout=CIMD_TIMEOUT,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        ) as response:
            if response.status_code != 200:
                return None
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > CIMD_MAX_BYTES:
                    return None
            ttl = CIMD_DEFAULT_TTL
            for part in response.headers.get("cache-control", "").split(","):
                name, _, value = part.strip().partition("=")
                if name == "max-age" and value.isdigit():
                    ttl = min(int(value), CIMD_MAX_TTL)
            return json.loads(body), ttl
    except (httpx.HTTPError, ValueError):
        return None


# --- the provider -----------------------------------------------------------------------


class StratzAccessToken(AccessToken):
    stratz_token: str


class StratzAuthorizationCode(AuthorizationCode):
    stratz_token: str
    jti: str


class StratzRefreshToken(RefreshToken):
    stratz_token: str
    jti: str


class StratzOAuthProvider:
    """`OAuthAuthorizationServerProvider` for the MCP SDK, sealing everything it issues."""

    def __init__(
        self,
        issuer: str,
        resource: str,
        sealer: Sealer,
        store: Store,
        fetch_document: Callable[
            [str], tuple[dict, int] | None
        ] = fetch_client_document,
        clock: Callable[[], float] = time.time,
    ):
        self.issuer = issuer.rstrip("/")
        self.resource = resource
        self._sealer = sealer
        self._store = store
        self._fetch_document = fetch_document
        self._clock = clock
        self._clients: dict[str, tuple[float, CimdClient]] = {}

    # --- clients --------------------------------------------------------------------------

    async def get_client(self, client_id: str) -> CimdClient | None:
        now = self._clock()
        cached = self._clients.get(client_id)
        if cached and cached[0] > now:
            return cached[1]
        fetched = self._fetch_document(client_id)
        if fetched is None:
            return None
        document, ttl = fetched
        uris = document.get("redirect_uris")
        if (
            document.get("client_id") != client_id
            or not isinstance(uris, list)
            or not uris
        ):
            return None
        try:
            client = CimdClient(
                client_id=client_id,
                client_name=document.get("client_name"),
                redirect_uris=uris,
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
            )
        except ValueError:
            return None
        self._clients[client_id] = (now + ttl, client)
        return client

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError(
            "Clients register by Client ID Metadata Document only."
        )

    # --- authorization --------------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if params.resource and params.resource.rstrip("/") != self.resource.rstrip("/"):
            raise AuthorizeError(
                "invalid_target", f"This server only issues tokens for {self.resource}"
            )
        request = self._sealer.seal(
            "request",
            {
                "client_id": client.client_id,
                "redirect_uri": str(params.redirect_uri),
                "explicit": params.redirect_uri_provided_explicitly,
                "challenge": params.code_challenge,
                "state": params.state,
                "exp": self._clock() + REQUEST_TTL,
            },
        )
        return construct_redirect_uri(f"{self.issuer}/connect", request=request)

    def open_request(self, blob: str) -> dict | None:
        """The pending authorization behind a connect page, or None if it expired."""
        return self._sealer.open("request", blob, self._clock())

    def complete(self, request: dict, stratz_token: str) -> str:
        """The client redirect carrying a fresh code, once the Stratz token checked out."""
        code = self._sealer.seal(
            "code",
            {
                "client_id": request["client_id"],
                "redirect_uri": request["redirect_uri"],
                "explicit": request["explicit"],
                "challenge": request["challenge"],
                "token": stratz_token,
                "jti": secrets.token_urlsafe(16),
                "exp": self._clock() + CODE_TTL,
            },
        )
        return construct_redirect_uri(
            request["redirect_uri"], code=code, state=request["state"], iss=self.issuer
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> StratzAuthorizationCode | None:
        claims = self._sealer.open("code", authorization_code, self._clock())
        if claims is None or claims["client_id"] != client.client_id:
            return None
        return StratzAuthorizationCode(
            code=authorization_code,
            scopes=[],
            expires_at=claims["exp"],
            client_id=claims["client_id"],
            code_challenge=claims["challenge"],
            redirect_uri=AnyUrl(claims["redirect_uri"]),
            redirect_uri_provided_explicitly=claims["explicit"],
            resource=self.resource,
            stratz_token=claims["token"],
            jti=claims["jti"],
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: StratzAuthorizationCode,
    ) -> OAuthToken:
        if not self._store.create(f"jti/{authorization_code.jti}"):
            raise TokenError("invalid_grant", "authorization code already used")
        return self._issue(client.client_id, authorization_code.stratz_token)

    # --- tokens ---------------------------------------------------------------------------

    def _issue(self, client_id: str, stratz_token: str) -> OAuthToken:
        now = self._clock()
        access = self._sealer.seal(
            "access",
            {
                "client_id": client_id,
                "token": stratz_token,
                "resource": self.resource,
                "exp": now + ACCESS_TTL,
            },
        )
        refresh = self._sealer.seal(
            "refresh",
            {
                "client_id": client_id,
                "token": stratz_token,
                "jti": secrets.token_urlsafe(16),
                "exp": now + REFRESH_TTL,
            },
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TTL,
            refresh_token=refresh,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> StratzRefreshToken | None:
        claims = self._sealer.open("refresh", refresh_token, self._clock())
        if claims is None or claims["client_id"] != client.client_id:
            return None
        return StratzRefreshToken(
            token=refresh_token,
            client_id=claims["client_id"],
            scopes=[],
            expires_at=int(claims["exp"]),
            resource=self.resource,
            stratz_token=claims["token"],
            jti=claims["jti"],
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: StratzRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Rotation (OAuth 2.1 for public clients): each refresh token works once.
        if not self._store.create(f"jti/{refresh_token.jti}"):
            raise TokenError("invalid_grant", "refresh token already used")
        return self._issue(client.client_id, refresh_token.stratz_token)

    async def load_access_token(self, token: str) -> StratzAccessToken | None:
        claims = self._sealer.open("access", token, self._clock())
        if claims is None:
            return None
        return StratzAccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=[],
            expires_at=int(claims["exp"]),
            resource=claims["resource"],
            stratz_token=claims["token"],
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # Sealed tokens can't be revoked one by one; rotating the sealing keys revokes all.
        return None

    async def exchange_identity_assertion(self, client, params) -> OAuthToken:
        raise TokenError(
            "unsupported_grant_type", "The JWT bearer grant is not supported"
        )

    # --- metadata -------------------------------------------------------------------------

    def metadata(self) -> OAuthMetadata:
        """RFC 8414 metadata advertising CIMD, public clients and `iss` (the SDK's default
        metadata advertises none of them)."""
        return OAuthMetadata(
            issuer=self.issuer,
            authorization_endpoint=f"{self.issuer}/authorize",
            token_endpoint=f"{self.issuer}/token",
            response_types_supported=["code"],
            grant_types_supported=["authorization_code", "refresh_token"],
            token_endpoint_auth_methods_supported=["none"],
            code_challenge_methods_supported=["S256"],
            client_id_metadata_document_supported=True,
            authorization_response_iss_parameter_supported=True,
        )
