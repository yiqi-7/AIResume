"""Generate nginx trust/allow rules from Cloudflare's published IP range API.

Run as root during deployment, review the generated file, then `nginx -t` and
reload nginx only after checking all other existing site configurations.
"""
import ipaddress
import json
import os
import tempfile
import urllib.request
from pathlib import Path

OUTPUT = Path("/etc/nginx/cloudflare-real-ip.conf")
URL = "https://api.cloudflare.com/client/v4/ips"

request = urllib.request.Request(URL, headers={"Accept": "application/json"})
with urllib.request.urlopen(request, timeout=20) as response:
    if response.status != 200:
        raise SystemExit("Cloudflare IP range endpoint returned an error")
    data = json.loads(response.read(100_000))
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

contents = "# Generated from Cloudflare's official IP API. Do not edit by hand.\n"
contents += "".join(f"set_real_ip_from {network};\n" for network in ranges)
contents += "".join(f"allow {network};\n" for network in ranges)
contents += "deny all;\n"
OUTPUT.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
fd, name = tempfile.mkstemp(prefix="cloudflare-real-ip.", dir=OUTPUT.parent)
try:
    with os.fdopen(fd, "w", encoding="ascii") as target:
        target.write(contents)
        target.flush()
        os.fsync(target.fileno())
    os.chmod(name, 0o644)
    os.replace(name, OUTPUT)
except Exception:
    try:
        os.unlink(name)
    except OSError:
        pass
    raise
print(f"Wrote {len(ranges)} Cloudflare network ranges to {OUTPUT}; validate nginx before reload.")
