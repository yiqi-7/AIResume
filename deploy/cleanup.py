"""Call the running API's cleanup, so cleanup shares its session locks.

Run as the airesume systemd service user; read token from EnvironmentFile.
Never print the token or response body.
"""
import os
import urllib.request

req = urllib.request.Request(
    "http://127.0.0.1:8010/admin/cleanup", method="POST",
    headers={"Authorization": "Bearer " + os.environ["RESUME_ADMIN_TOKEN"],
             "X-Resume-Client": "web"},
)
with urllib.request.urlopen(req, timeout=30) as response:
    if response.status != 200:
        raise SystemExit("Cleanup call failed")
