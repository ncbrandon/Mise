"""HTTP fetching with SSRF protection (the server usually lives on a home LAN)."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

from ..config import get_settings

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_BYTES = 8 * 1024 * 1024


class FetchError(Exception):
    pass


def _check_host(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise FetchError("Only http(s) URLs are supported")
    if get_settings().allow_private_fetch:
        return
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        raise FetchError(f"Could not resolve {p.hostname}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise FetchError("Refusing to fetch a private network address")


def fetch(url: str, timeout: float = 20.0) -> tuple[str, bytes, str]:
    """Return (final_url, body, content_type). Follows up to 6 redirects, checking each hop."""
    current = url
    with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=False) as client:
        for _ in range(7):
            _check_host(current)
            with client.stream("GET", current) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    current = urljoin(current, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    raise FetchError(f"The site answered {r.status_code}")
                chunks, size = [], 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise FetchError("Page is too large")
                    chunks.append(chunk)
                return str(r.url), b"".join(chunks), r.headers.get("content-type", "")
    raise FetchError("Too many redirects")


def fetch_html(url: str) -> tuple[str, str]:
    final, body, ctype = fetch(url)
    enc = "utf-8"
    if "charset=" in ctype:
        enc = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
    try:
        return final, body.decode(enc, errors="replace")
    except LookupError:
        return final, body.decode("utf-8", errors="replace")
