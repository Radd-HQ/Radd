"""Where a user-supplied URL may make this server send a request (RADD-1546).

Webhook endpoints and the automation HTTP actions call a URL someone typed,
from the server's own place on the network. Unchecked, that URL can name the
loopback interface, a private range or a cloud metadata address, and the
delivery log then reports what answered.

Two checks, because one is not enough:

- **`check_url`**, when the URL is saved: refuses what is wrong on its face (a
  scheme other than http/https, credentials in the URL, a literal non-public
  address). It resolves nothing — a save must not depend on DNS.
- **`post`**, when the request is sent: resolves the host, checks EVERY address
  it resolves to, and connects to the checked address. The name is not resolved
  a second time, so an answer cannot change between the check and the call.
  Redirects are not followed.

An operator who needs internal targets lists them in
`RADD_OUTBOUND_ALLOWED_HOSTS` (hostnames and CIDRs). Nothing non-public is
reachable until it is listed.

Not for the connectors an instance admin configures (VCS, SSO, AI, storage):
naming internal services is what those settings are for.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from radd.config import settings
from radd.exceptions import RaddError

_SCHEMES = {"http": 80, "https": 443}
Address = ipaddress.IPv4Address | ipaddress.IPv6Address


class OutboundRefused(RaddError):
    """The URL may not be called from this server (-> 422 at save; a failed
    delivery, with this message, at send)."""


def _allowed() -> tuple[set[str], list[ipaddress.IPv4Network | ipaddress.IPv6Network]]:
    hosts: set[str] = set()
    networks = []
    for entry in settings.outbound_allowed_hosts.split(","):
        entry = entry.strip().lower()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            hosts.add(entry)
    return hosts, networks


def _literal(host: str) -> Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _public(address: Address) -> bool:
    """Globally routable, and nothing else. `is_global` is False for loopback,
    RFC 1918, link-local (the metadata range), CGNAT, unique-local, multicast
    and the unspecified address. An IPv4 address wearing an IPv6 prefix is
    judged as the IPv4 address it is."""
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return address.is_global and not address.is_multicast


def _reachable(address: Address, networks: list) -> bool:
    return _public(address) or any(address in network for network in networks)


def _refuse(host: str, address: Address | None = None) -> OutboundRefused:
    where = f"{host} ({address})" if address is not None and str(address) != host else host
    return OutboundRefused(
        f"{where} is not a public address, and this server does not call private, loopback or "
        "link-local addresses on a user's behalf. An operator can allow an internal target with "
        "RADD_OUTBOUND_ALLOWED_HOSTS."
    )


def _parts(url: str) -> tuple[str, str, int]:
    """(scheme, host, port), or `OutboundRefused` for a URL that is not a plain
    http(s) address."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise OutboundRefused(f"not a usable URL: {error}") from error
    scheme = parsed.scheme.lower()
    if scheme not in _SCHEMES:
        raise OutboundRefused("only http and https URLs can be called")
    if not parsed.hostname:
        raise OutboundRefused("the URL names no host")
    if parsed.username or parsed.password:
        raise OutboundRefused("a URL with a user name or password in it cannot be called")
    return scheme, parsed.hostname.lower().rstrip("."), port or _SCHEMES[scheme]


def check_url(url: str) -> None:
    """Refuse a URL that is wrong on its face. No DNS: see the module docstring."""
    _scheme, host, _port = _parts(url)
    hosts, networks = _allowed()
    if host in hosts:
        return
    address = _literal(host)
    if address is None:
        if host == "localhost" or host.endswith(".localhost"):
            raise _refuse(host)
        return  # a name: judged when it is resolved, at send
    if not _reachable(address, networks):
        raise _refuse(host, address)


async def resolve(url: str) -> tuple[str, str, int, Address]:
    """(scheme, host, port, the address to connect to) — every address the host
    resolves to has been checked, and the first is the one returned."""
    scheme, host, port = _parts(url)
    hosts, networks = _allowed()
    literal = _literal(host)
    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
        except socket.gaierror as error:
            raise OutboundRefused(f"{host} does not resolve: {error}") from error
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
        if not addresses:
            raise OutboundRefused(f"{host} does not resolve")
    if host not in hosts:
        for address in addresses:
            if not _reachable(address, networks):
                raise _refuse(host, address)
    return scheme, host, port, addresses[0]


async def post(
    client: httpx.AsyncClient, url: str, *, content: bytes | str, headers: dict[str, str]
) -> httpx.Response:
    """POST to a user-supplied URL, at an address that has been checked.

    The request is addressed to the vetted IP; `Host` and the TLS server name
    carry the original hostname, so virtual hosting and certificate
    verification behave as if the name had been dialled."""
    scheme, host, port, address = await resolve(url)
    parsed = urlsplit(url)
    literal = f"[{address}]" if address.version == 6 else str(address)
    default_port = port == _SCHEMES[scheme]
    target = parsed._replace(netloc=literal if default_port else f"{literal}:{port}").geturl()
    request = client.build_request(
        "POST",
        target,
        content=content,
        headers={**headers, "Host": host if default_port else f"{host}:{port}"},
        extensions={"sni_hostname": host} if scheme == "https" else {},
    )
    return await client.send(request, follow_redirects=False)
