"""Trusted reverse-proxy and request-origin helpers."""

from functools import lru_cache
import ipaddress
import os
import re

from fastapi import Request


_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_host(value: str) -> str:
    """Return one canonical hostname without a port or trailing root dot."""

    if not isinstance(value, str):
        raise ValueError("host must be a string")
    candidate = value.strip()
    if not candidate or "," in candidate or "://" in candidate:
        raise ValueError("host must contain one bare hostname")
    if any(character in candidate for character in "/?#@"):
        raise ValueError("host must be a bare hostname")

    if candidate.startswith("["):
        closing = candidate.find("]")
        if closing < 0:
            raise ValueError("invalid bracketed host")
        hostname = candidate[1:closing]
        suffix = candidate[closing + 1 :]
        if suffix:
            if not suffix.startswith(":") or not _valid_port(suffix[1:]):
                raise ValueError("invalid host port")
    elif candidate.count(":") == 1:
        hostname, port = candidate.rsplit(":", 1)
        if not _valid_port(port):
            raise ValueError("invalid host port")
    else:
        hostname = candidate

    hostname = hostname.rstrip(".")
    if not hostname:
        raise ValueError("host is empty")
    try:
        return ipaddress.ip_address(hostname).compressed.lower()
    except ValueError:
        pass

    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("invalid IDNA hostname") from exc
    if len(ascii_hostname) > 253:
        raise ValueError("hostname is too long")
    labels = ascii_hostname.split(".")
    if any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise ValueError("invalid hostname")
    return ascii_hostname


def _valid_port(value: str) -> bool:
    return value.isdecimal() and 1 <= int(value) <= 65535


@lru_cache(maxsize=64)
def _parse_proxy_cidrs(raw_value: str) -> tuple[ipaddress._BaseNetwork, ...]:
    networks = []
    for item in raw_value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    return _parse_proxy_cidrs(os.getenv("TRUSTED_PROXY_CIDRS", ""))


def is_trusted_proxy(value: str | None) -> bool:
    try:
        address = ipaddress.ip_address(value or "")
    except ValueError:
        return False
    return any(address in network for network in trusted_proxy_networks())


def resolve_client_ip(request: Request) -> str:
    """Resolve X-Forwarded-For from right to left across trusted proxies."""

    peer = request.client.host if request.client is not None else "unknown"
    if not is_trusted_proxy(peer):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return peer
    try:
        chain = [
            ipaddress.ip_address(item.strip())
            for item in forwarded.split(",")
            if item.strip()
        ]
    except ValueError:
        return peer
    if not chain:
        return peer
    for address in reversed(chain):
        if not any(address in network for network in trusted_proxy_networks()):
            return address.compressed
    return chain[0].compressed


def resolve_request_host(request: Request) -> str:
    """Use a proxy-supplied original Host only when the immediate peer is trusted."""

    direct_host = request.headers.get("host", "")
    forwarded_host = request.headers.get("x-forwarded-host", "")
    if forwarded_host and request.client is not None and is_trusted_proxy(request.client.host):
        return normalize_host(forwarded_host)
    return normalize_host(direct_host)
