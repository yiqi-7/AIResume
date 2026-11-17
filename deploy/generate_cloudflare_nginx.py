"""Generate nginx Cloudflare trust and origin-guard rules from its published IP ranges.

Run as root during deployment, review both generated files, then `nginx -t` and
reload nginx only after checking all other existing site configurations.
"""
import ipaddress
import json
import os
import tempfile
import urllib.request
from pathlib import Path

OUTPUT = Path("/etc/nginx/cloudflare-real-ip.conf")
GUARD_OUTPUT = Path("/etc/nginx/conf.d/airesume-cloudflare-origin-guard.conf")
URL = "https://api.cloudflare.com/client/v4/ips"


def build_configs(data):
    if data.get("success") is not True:
        raise SystemExit("Cloudflare IP range response was not successful")

    ranges = []
    for key, version in (("ipv4_cidrs", 4), ("ipv6_cidrs", 6)):
        items = data.get("result", {}).get(key)
        if not isinstance(items, list) or not items:
            raise SystemExit(f"Cloudflare {key} list was empty")
        for value in items:
            network = ipaddress.ip_network(value, strict=True)
            if network.version != version:
                raise SystemExit("Cloudflare range family mismatch")
            ranges.append(str(network))
    if len(ranges) > 128 or len(ranges) < 10:
        raise SystemExit("Cloudflare IP range count is outside the expected bounds")

    header = "# Generated from Cloudflare's official IP API. Do not edit by hand.\n"
    real_ip = header + "".join(f"set_real_ip_from {network};\n" for network in ranges)
    origin_guard = header + "geo $realip_remote_addr $airesume_from_cloudflare {\n"
    origin_guard += "    default 0;\n"
    origin_guard += "".join(f"    {network} 1;\n" for network in ranges)
    origin_guard += "}\n"
    return real_ip, origin_guard, len(ranges)


def write_atomic(output: Path, contents: str):
    output.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as target:
            target.write(contents)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(name, 0o644)
        os.replace(name, output)
    except Exception:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise


def main():
    request = urllib.request.Request(URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise SystemExit("Cloudflare IP range endpoint returned an error")
        data = json.loads(response.read(100_000))
    real_ip, origin_guard, count = build_configs(data)
    write_atomic(OUTPUT, real_ip)
    write_atomic(GUARD_OUTPUT, origin_guard)
    print(f"Wrote {count} Cloudflare ranges to {OUTPUT} and {GUARD_OUTPUT}; validate nginx before reload.")


if __name__ == "__main__":
    main()
