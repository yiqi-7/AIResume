import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = ROOT / "deploy" / "generate_cloudflare_nginx.py"
SPEC = importlib.util.spec_from_file_location("cloudflare_nginx", GENERATOR_PATH)
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def test_generated_guard_checks_cloudflare_peer_before_real_ip_rewrite():
    ipv4 = [
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "104.16.0.0/13",
        "108.162.192.0/18",
    ]
    ipv6 = [
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
    ]
    data = {"success": True, "result": {"ipv4_cidrs": ipv4, "ipv6_cidrs": ipv6}}

    real_ip, guard, count = GENERATOR.build_configs(data)

    assert count == 10
    assert all(f"set_real_ip_from {network};" in real_ip for network in ipv4 + ipv6)
    assert "allow " not in real_ip and "deny all;" not in real_ip
    assert "geo $realip_remote_addr $airesume_from_cloudflare" in guard
    assert "default 0;" in guard
    assert all(f"{network} 1;" in guard for network in ipv4 + ipv6)
    nginx = (ROOT / "deploy" / "nginx.conf.example").read_text(encoding="utf-8")
    assert "if ($airesume_from_cloudflare = 0) { return 403; }" in nginx
