"""Public HTTPS endpoints with DNS pinning for user-supplied model services."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from .schemas import Problem


def public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and (
        address.sixtofour or address.teredo or address in ipaddress.ip_network("64:ff9b::/96")
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def validate_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        url = httpx.URL(value)
        if (
            len(value) > 2048
            or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
            or "\\" in value
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not url.host
            or "%" in parsed.netloc
            or parsed.port == 0
        ):
            raise ValueError()
        try:
            address = ipaddress.ip_address(url.host)
        except ValueError:
            if "." not in url.host or url.host.endswith((".localhost", ".local", ".internal")):
                raise ValueError() from None
        else:
            if not public_ip(str(address)):
                raise ValueError()
        return str(url).rstrip("/")
    except (ValueError, httpx.InvalidURL):
        raise Problem(
            "MODEL_URL_INVALID", "API 地址须为公网 HTTPS 地址，不能包含账号、查询参数或片段。", 422
        ) from None


async def public_addresses(host: str, port: int) -> list[str]:
    try:
        async with asyncio.timeout(5):
            records = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
        addresses = list(dict.fromkeys(record[4][0] for record in records))
        if not addresses or any(not public_ip(address) for address in addresses):
            raise ValueError()
        return addresses
    except (OSError, ValueError, TimeoutError):
        raise Problem(
            "MODEL_URL_UNREACHABLE", "API 地址无法解析到可访问的公网服务，请检查地址。", 422
        ) from None


class PublicAPITransport(httpx.AsyncBaseTransport):
    def __init__(self, transport=None):
        # No cross-host connection reuse when two domains resolve to the same IP.
        self.transport = transport or httpx.AsyncHTTPTransport(
            trust_env=False, limits=httpx.Limits(max_connections=4, max_keepalive_connections=0)
        )

    async def handle_async_request(self, request):
        validate_base_url(str(request.url))
        addresses = await public_addresses(request.url.host, request.url.port or 443)
        headers = request.headers.copy()
        headers["Host"] = request.url.netloc.decode("ascii")
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=addresses[0]),
            headers=headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": request.url.host},
        )
        return await self.transport.handle_async_request(pinned)

    async def aclose(self):
        await self.transport.aclose()
