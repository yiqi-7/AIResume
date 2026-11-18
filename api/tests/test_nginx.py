import http.client
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.test_cloudflare_nginx import GENERATOR, ROOT


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self):
        value = self.headers.get("X-Forwarded-For", "").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(value)))
        self.end_headers()
        self.wfile.write(value)

    def log_message(self, *args):
        pass


def test_nginx_origin_guard_and_visitor_ip_with_running_proxy(tmp_path):
    nginx = os.environ.get("TEST_NGINX_PATH")
    if not nginx:
        pytest.skip("TEST_NGINX_PATH is required for the isolated nginx runtime test")
    backend = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    allowed_port, denied_port, redirect_port = free_port(), free_port(), free_port()
    process = None
    try:
        # The loopback peer simulates an approved reverse proxy in this isolated fixture.
        data = {"success": True, "result": {
            "ipv4_cidrs": ["127.0.0.1/32"] + [f"192.0.{i}.0/24" for i in range(8)],
            "ipv6_cidrs": ["2001:db8::/32"],
        }}
        trust, guard, _ = GENERATOR.build_configs(data)
        trust_path, guard_path = tmp_path / "realip.conf", tmp_path / "guard.conf"
        trust_path.write_text(trust)
        guard_path.write_text(guard)
        source = (ROOT / "deploy" / "nginx.conf.example").read_text(encoding="utf-8")
        source = source.replace("listen 443 ssl;", f"listen 127.0.0.1:{allowed_port};")
        source = source.replace("listen 80;", f"listen 127.0.0.1:{redirect_port};")
        source = source.replace("/etc/nginx/cloudflare-real-ip.conf", trust_path.as_posix())
        source = source.replace("http://127.0.0.1:8010", f"http://127.0.0.1:{backend.server_port}")
        source = "\n".join(line for line in source.splitlines()
                           if not line.strip().startswith(("ssl_certificate ", "ssl_certificate_key ")))
        # A second listener has no approved peers, so a forged header must not bypass its guard.
        extra_guard = "geo $realip_remote_addr $untrusted_peer { default 0; }"
        denied = f"server {{ listen 127.0.0.1:{denied_port}; "
        denied += f"include {trust_path.as_posix()}; real_ip_header CF-Connecting-IP; "
        denied += "if ($untrusted_peer = 0) { return 403; } location / { return 200; } }"
        config = tmp_path / "nginx.conf"
        config.write_text(
            f"pid {tmp_path.as_posix()}/nginx.pid; error_log stderr notice;\n"
            "events {}\nhttp { access_log off;\n"
            f"include {guard_path.as_posix()};\n{extra_guard}\n{source}\n{denied}\n}}",
            encoding="utf-8",
        )
        subprocess.run([nginx, "-t", "-p", str(tmp_path), "-c", str(config)],
                       check=True, capture_output=True, timeout=10)
        process = subprocess.Popen(
            [nginx, "-p", str(tmp_path), "-c", str(config), "-g", "daemon off; master_process off;"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", allowed_port), timeout=0.2):
                    break
            except OSError:
                if process.poll() is not None:
                    pytest.fail("Isolated nginx exited before becoming ready")
                time.sleep(0.05)
        else:
            pytest.fail("Isolated nginx did not become ready")

        def request(port, path):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.request("GET", path, headers={"CF-Connecting-IP": "198.51.100.7"})
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        assert request(allowed_port, "/api/probe") == (200, b"198.51.100.7")
        assert request(allowed_port, "/admin/stats")[0] == 404
        assert request(denied_port, "/api/probe")[0] == 403
    finally:
        if process:
            process.terminate()
            process.wait(timeout=10)
        backend.shutdown()
        backend.server_close()
