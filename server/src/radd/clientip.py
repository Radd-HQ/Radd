"""Client-IP resolution behind trusted proxies (spec 102).

`scope["client"]` is the socket peer — behind an ingress/LB that is the proxy,
not the user. The standard fix: when (and only when) the peer is a configured
trusted proxy, walk X-Forwarded-For right-to-left, skipping trusted hops, and
take the first untrusted address — the nearest hop we didn't append ourselves.
An untrusted peer's XFF header is attacker-controlled and ignored entirely.

RADD_TRUSTED_PROXIES is a comma-separated list of IPs/CIDRs ("" = never trust
XFF). Resolution happens once per request in `ClientIpMiddleware`, which stores
the result in `scope["state"]["client_ip"]` (request.state.client_ip); storage
CIDR routing rules read it from there. Deliberately in-app rather than
uvicorn's --proxy-headers so compose, Helm, and host-run behave identically
from one config value.
"""

import ipaddress
import logging
from typing import Any

from radd.config import settings

logger = logging.getLogger(__name__)

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network

FORWARDED_FOR_HEADER = b"x-forwarded-for"


def parse_trusted(value: str) -> tuple[_Network, ...]:
    """Comma-separated IPs/CIDRs -> networks; invalid entries are logged and skipped
    (a typo must not silently turn header trust on or off for the rest)."""
    networks: list[_Network] = []
    for raw in value.split(","):
        entry = raw.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("trusted_proxies: ignoring invalid entry %r", entry)
    return tuple(networks)


def _is_trusted(ip: str, trusted: tuple[_Network, ...]) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in network for network in trusted)


def resolve_client_ip(
    peer_ip: str | None,
    forwarded_for: str | None,
    trusted: tuple[_Network, ...],
) -> str | None:
    """The effective client address (pure, unit-tested).

    Untrusted peer (or no trusted proxies configured) -> the peer itself.
    Trusted peer -> walk XFF right-to-left past trusted hops; first untrusted
    entry wins. An XFF consisting entirely of trusted hops falls back to its
    leftmost entry (every hop was ours; the origin is whatever the first one saw).
    """
    if peer_ip is None or not trusted or not _is_trusted(peer_ip, trusted):
        return peer_ip
    if not forwarded_for:
        return peer_ip
    hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    for hop in reversed(hops):
        if not _is_trusted(hop, trusted):
            return hop
    return hops[0] if hops else peer_ip


class ClientIpMiddleware:
    """Computes the client IP once per http request into scope['state']['client_ip']."""

    def __init__(self, app: Any):
        self.app = app
        self._trusted = parse_trusted(settings.trusted_proxies)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        peer_ip = client[0] if client else None
        forwarded = None
        for name, value in scope.get("headers", ()):
            if name == FORWARDED_FOR_HEADER:
                forwarded = value.decode("latin-1")
                break
        scope.setdefault("state", {})["client_ip"] = resolve_client_ip(
            peer_ip, forwarded, self._trusted
        )
        await self.app(scope, receive, send)
