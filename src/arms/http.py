"""A small HTTP client with decomposed timings.

Standard library only, deliberately. The alternative is a dependency whose
connection pooling would hide exactly the thing being measured: this study cares
about DNS, TCP and TLS setup separately from server time, because the vendor's
latency claim is presumably server-side and a reader needs to see the difference.

Connections are NOT reused. Every call pays full setup, for every arm, so the
comparison stays paired and honest -- and so the numbers resemble what an
enforce-mode hook would actually pay when it spawns a fresh process per call.
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from .base import ArmError, Timing


class TimedHTTPSConnection:
    """Opens a connection by hand so DNS, TCP and TLS can be timed separately."""

    def __init__(self, url: str, timeout: float):
        self.parsed = urlparse(url)
        self.timeout = timeout
        self.timing = Timing()

    def request(self, payload: dict[str, Any], headers: dict[str, str]) -> tuple[int, bytes]:
        host = self.parsed.hostname or ""
        port = self.parsed.port or (443 if self.parsed.scheme == "https" else 80)
        body = json.dumps(payload).encode("utf-8")

        t0 = time.perf_counter()
        try:
            addrinfo = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise ArmError("dns", str(exc)) from exc
        t_dns = time.perf_counter()

        family, socktype, proto, _, sockaddr = addrinfo[0]
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(self.timeout)
        try:
            sock.connect(sockaddr)
        except (socket.timeout, OSError) as exc:
            sock.close()
            raise ArmError("connection", str(exc)) from exc
        t_conn = time.perf_counter()

        if self.parsed.scheme == "https":
            context = ssl.create_default_context()
            try:
                sock = context.wrap_socket(sock, server_hostname=host)
            except ssl.SSLError as exc:
                sock.close()
                raise ArmError("tls", str(exc)) from exc
        t_tls = time.perf_counter()

        try:
            path = self.parsed.path or "/"
            if self.parsed.query:
                path = f"{path}?{self.parsed.query}"
            lines = [f"POST {path} HTTP/1.1", f"Host: {host}", "Connection: close",
                     f"Content-Length: {len(body)}"]
            lines += [f"{k}: {v}" for k, v in headers.items()]
            sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body)

            chunks: list[bytes] = []
            first = sock.recv(65536)
            t_ttfb = time.perf_counter()
            chunks.append(first)
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except socket.timeout as exc:
            raise ArmError("timeout", str(exc)) from exc
        except OSError as exc:
            raise ArmError("connection", str(exc)) from exc
        finally:
            sock.close()

        t_end = time.perf_counter()
        self.timing = Timing(
            dns_ms=(t_dns - t0) * 1000,
            connect_ms=(t_conn - t_dns) * 1000,
            tls_ms=(t_tls - t_conn) * 1000,
            ttfb_ms=(t_ttfb - t0) * 1000,
            total_ms=(t_end - t0) * 1000,
        )

        raw = b"".join(chunks)
        head, _, response_body = raw.partition(b"\r\n\r\n")
        try:
            status = int(head.split(b" ")[1])
        except (IndexError, ValueError) as exc:
            raise ArmError("malformed_response", head[:200].decode("latin-1")) from exc

        if b"Transfer-Encoding: chunked" in head or b"transfer-encoding: chunked" in head:
            response_body = _dechunk(response_body)
        return status, response_body


def _dechunk(body: bytes) -> bytes:
    out = bytearray()
    while body:
        line, _, rest = body.partition(b"\r\n")
        try:
            size = int(line.split(b";")[0], 16)
        except ValueError:
            return bytes(out) or body
        if size == 0:
            break
        out += rest[:size]
        body = rest[size + 2:]
    return bytes(out)


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float):
    """POST and return (parsed_json, Timing). Raises ArmError on any failure."""
    conn = TimedHTTPSConnection(url, timeout)
    status, body = conn.request(payload, {"Content-Type": "application/json", **headers})
    if status == 429:
        raise ArmError("rate_limit", body[:500].decode("utf-8", "replace"))
    if status >= 500:
        raise ArmError("server_error", f"HTTP {status}: {body[:500].decode('utf-8', 'replace')}")
    if status >= 400:
        raise ArmError("client_error", f"HTTP {status}: {body[:500].decode('utf-8', 'replace')}")
    try:
        return json.loads(body), conn.timing
    except json.JSONDecodeError as exc:
        raise ArmError("malformed_response", body[:500].decode("utf-8", "replace")) from exc
