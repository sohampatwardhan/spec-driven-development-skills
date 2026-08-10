"""Bounded, injectable HTTP primitives for advisory-source clients.

Network access crosses a trust boundary here: callers receive bytes or decoded JSON, never a
live response object, and diagnostics never retain credentials or unbounded remote content.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import socket
import time
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


_CREDENTIAL_KEY = r"(?:[a-z0-9_.-]*(?:refresh[_-]?token|private[_-]?token|token|key|secret|password|passwd)|authorization|cookie)"
_SENSITIVE_QUERY = re.compile(rf"(?i)([?&]{_CREDENTIAL_KEY})=([^&#\s]+)")
_SENSITIVE_JSON = re.compile(
    rf"(?i)([\"']?{_CREDENTIAL_KEY}[\"']?\s*:\s*[\"']?)(?:bearer\s+|basic\s+)?[^\"',}}\s]+"
)
_SENSITIVE_HEADER = re.compile(
    rf"(?i)(\b{_CREDENTIAL_KEY}\b\s*[:=]\s*)(?:bearer\s+|basic\s+)?[^\s,;]+"
)
_URL_USERINFO = re.compile(r"(?i)(https?://)[^/@\s]+@")
_SENSITIVE_HEADER_NAME = re.compile(rf"(?i)^(?:{_CREDENTIAL_KEY}|proxy-authorization|cookie)$")


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Reject cross-host redirects that could forward authentication material."""

    def redirect_request(self, req: Request, fp: object, code: int, msg: str,
                         headers: Mapping[str, str], newurl: str) -> Request | None:
        original = urlsplit(req.full_url)
        redirected = urlsplit(newurl)
        original_origin = (original.scheme.lower(), (original.hostname or "").lower(),
                           original.port or (443 if original.scheme.lower() == "https" else 80))
        redirected_origin = (redirected.scheme.lower(), (redirected.hostname or "").lower(),
                             redirected.port or (443 if redirected.scheme.lower() == "https" else 80))
        has_credentials = any(
            _SENSITIVE_HEADER_NAME.fullmatch(key) for key, _value in req.header_items()
        )
        if original_origin != redirected_origin and has_credentials:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class HttpResponse:
    """Represent a fully buffered response with no executable transport state.

    The body is bounded by the transport before it is exposed so a remote service cannot cause
    the audit process to retain an unbounded response in memory.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    """Define the injectable, side-effecting boundary used by source clients.

    Implementations must respect the supplied connection/read limits and maximum response size;
    tests use this narrow protocol to prove source behavior without contacting live services.
    """

    def request(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None,
                connect_timeout: float, read_timeout: float, max_bytes: int) -> HttpResponse:
        """Return one bounded response or raise a connection/read error."""


class HttpRequestError(RuntimeError):
    """Report an HTTP failure using a deliberately redacted, bounded diagnostic."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def redact_diagnostic(value: object, secrets: tuple[str, ...] = ()) -> str:
    """Return a bounded diagnostic that cannot reveal configured credentials.

    Remote error text is useful for source availability evidence, but it must stay inert and must
    not become an accidental credential channel in reports or logs.
    """

    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = _SENSITIVE_QUERY.sub(r"\1=[REDACTED]", text)
    text = _SENSITIVE_JSON.sub(r"\1[REDACTED]", text)
    text = _SENSITIVE_HEADER.sub(r"\1[REDACTED]", text)
    text = _URL_USERINFO.sub(r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)(bearer|basic)\s+[^\s,;]+", r"\1 [REDACTED]", text)
    return text[:512]


class StdlibHttpTransport:
    """Perform a single standard-library HTTP request with strict byte and time bounds.

    This is intentionally unopinionated about retries so policy stays testable in
    :class:`RetryingHttpClient`. ``urllib``'s timeout applies while opening the request; the
    response socket receives the explicit read timeout when the implementation exposes it.
    Authenticated redirects may remain on the exact origin only; rejecting cross-origin redirects
    prevents GitHub or NVD credentials from following a remotely controlled Location header.
    """

    def request(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None,
                connect_timeout: float, read_timeout: float, max_bytes: int) -> HttpResponse:
        """Fetch one response, rejecting a body larger than ``max_bytes``.

        ``HTTPError`` is returned as a response so callers can decide whether its status is
        transient; connection and timeout failures remain exceptions because they have no HTTP
        evidence to classify.
        """

        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            response = build_opener(_SafeRedirectHandler()).open(request, timeout=connect_timeout)
        except HTTPError as error:
            return self._read_response(error, read_timeout, max_bytes)
        except (URLError, socket.timeout, TimeoutError, OSError) as error:
            raise HttpRequestError(f"transport failure: {error}") from error
        return self._read_response(response, read_timeout, max_bytes)

    @staticmethod
    def _read_response(response: object, read_timeout: float, max_bytes: int) -> HttpResponse:
        raw_socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if raw_socket is not None:
            raw_socket.settimeout(read_timeout)
        body = response.read(max_bytes + 1)  # type: ignore[attr-defined]
        if len(body) > max_bytes:
            raise HttpRequestError(f"response exceeded {max_bytes} byte limit")
        headers = {str(key): str(value) for key, value in response.headers.items()}  # type: ignore[attr-defined]
        return HttpResponse(int(response.getcode()), headers, body)  # type: ignore[attr-defined]


class RetryingHttpClient:
    """Make bounded JSON requests with at most three transient attempts.

    Authentication and other non-transient client errors never retry. Retry-After values are
    capped so an advisory service cannot stall an audit indefinitely, and every exposed
    diagnostic passes through the redaction boundary.
    """

    def __init__(self, transport: HttpTransport | None = None, *, connect_timeout: float = 5.0,
                 read_timeout: float = 15.0, max_bytes: int = 1_000_000, max_attempts: int = 3,
                 max_retry_after: float = 30.0, sleeper: Callable[[float], None] = time.sleep,
                 secrets: tuple[str, ...] = ()) -> None:
        """Configure explicit bounds and an optional fake transport for deterministic tests."""

        self.transport = transport or StdlibHttpTransport()
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_bytes = max_bytes
        self.max_attempts = min(3, max(1, max_attempts))
        self.max_retry_after = max(0.0, max_retry_after)
        self.sleeper = sleeper
        self.secrets = secrets
        self.last_diagnostic = ""

    def request_json(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                     payload: object | None = None) -> object:
        """Return a JSON value or raise a redacted :class:`HttpRequestError`.

        JSON is decoded only after transport bounds have been applied. The decoded value remains
        ordinary data; callers must not treat descriptions or metadata as commands.
        """

        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request_headers = {"Accept": "application/json"}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        response = self._request(method, url, request_headers, body)
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            diagnostic = redact_diagnostic(f"invalid JSON from {url}: {error}", self.secrets)
            self.last_diagnostic = diagnostic
            raise HttpRequestError(diagnostic, status=response.status) from error

    def _request(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> HttpResponse:
        failure: HttpRequestError | None = None
        for attempt in range(self.max_attempts):
            try:
                response = self.transport.request(method, url, headers, body, self.connect_timeout,
                                                  self.read_timeout, self.max_bytes)
                if len(response.body) > self.max_bytes:
                    raise HttpRequestError(f"response exceeded {self.max_bytes} byte limit")
                if 200 <= response.status < 300:
                    self.last_diagnostic = ""
                    return response
                failure = HttpRequestError(
                    redact_diagnostic(f"HTTP {response.status} from {url}: {response.body[:256]!r}", self.secrets),
                    status=response.status,
                )
                if response.status not in (408, 425, 429) and not 500 <= response.status <= 599:
                    break
                delay = self._retry_delay(response.headers, attempt)
            except HttpRequestError as error:
                failure = HttpRequestError(redact_diagnostic(error, self.secrets), status=error.status)
                if "response exceeded" in str(error):
                    break
                delay = min(self.max_retry_after, 0.05 * (2 ** attempt))
            except (OSError, TimeoutError) as error:
                failure = HttpRequestError(redact_diagnostic(f"transport failure: {error}", self.secrets))
                delay = min(self.max_retry_after, 0.05 * (2 ** attempt))
            if attempt + 1 < self.max_attempts:
                self.sleeper(delay)
        assert failure is not None
        self.last_diagnostic = str(failure)
        raise failure

    def _retry_delay(self, headers: Mapping[str, str], attempt: int) -> float:
        retry_after = next((value for key, value in headers.items() if key.lower() == "retry-after"), "")
        try:
            return min(self.max_retry_after, max(0.0, float(retry_after)))
        except ValueError:
            return min(self.max_retry_after, 0.05 * (2 ** attempt))
