"""Linux-only UDS worker. Run via the paired systemd socket and service units."""

import asyncio
import errno
import os
import signal
import socket
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

MAX_BYTES = 5 * 1024 * 1024
TASK_SECONDS = 30
TMP_BYTES = 96 * 1024 * 1024
MEMORY_BYTES = 384 * 1024 * 1024


def validate_sandbox():
    """Fail closed if launched outside the required OS isolation boundaries."""
    if sys.platform != "linux" or os.geteuid() == 0:
        raise RuntimeError("Pagination requires the unprivileged Linux sandbox service")
    import resource

    status = Path("/proc/self/status").read_text()
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    if fields.get("NoNewPrivs", "").strip() != "1" or int(fields["CapEff"].strip(), 16):
        raise RuntimeError("Pagination requires NoNewPrivileges and no capabilities")
    try:
        network = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError as exc:
        if exc.errno not in {errno.EPERM, errno.EACCES, errno.EAFNOSUPPORT}:
            raise RuntimeError("Cannot verify pagination network isolation") from None
    else:
        network.close()
        raise RuntimeError("Pagination requires a kernel block on network sockets")
    mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    if not any(line.split()[4] == "/tmp" and " - tmpfs " in line for line in mounts):
        raise RuntimeError("Pagination requires a private tmpfs at /tmp")
    fs = os.statvfs("/tmp")
    if fs.f_blocks * fs.f_frsize > TMP_BYTES or tempfile.gettempdir() != "/tmp":
        raise RuntimeError("Pagination requires a bounded temporary filesystem")
    try:
        os.listdir("/run")
    except PermissionError:
        pass
    else:
        raise RuntimeError("Pagination must not access unrelated local service sockets")
    for protected in ["/etc/airesume", "/var/lib/airesume"]:
        try:
            os.listdir(protected)
        except (FileNotFoundError, PermissionError):
            pass
        else:
            raise RuntimeError("Pagination must not access API configuration or sessions")
    group = next(line[3:] for line in Path("/proc/self/cgroup").read_text().splitlines()
                 if line.startswith("0::"))
    root = Path("/sys/fs/cgroup")
    cgroup = (root / group.lstrip("/")).resolve()
    if not cgroup.is_relative_to(root):
        raise RuntimeError("Pagination requires cgroup v2 resource limits")
    for name, maximum in [("memory.max", MEMORY_BYTES), ("pids.max", 64)]:
        value = (cgroup / name).read_text().strip()
        if value == "max" or not 0 < int(value) <= maximum:
            raise RuntimeError("Pagination requires finite memory and process limits")
    if (cgroup / "memory.swap.max").read_text().strip() != "0":
        raise RuntimeError("Pagination temporary content must not be swapped")
    if resource.getrlimit(resource.RLIMIT_CORE)[0] != 0:
        raise RuntimeError("Pagination core dumps must be disabled")
    file_limit = resource.getrlimit(resource.RLIMIT_FSIZE)[0]
    if file_limit == resource.RLIM_INFINITY or not 0 < file_limit <= 32 * 1024 * 1024:
        raise RuntimeError("Pagination requires a finite file size limit")


async def task_process(directory: Path):
    # No inherited model credentials or application environment in the child.
    environment = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "HOME": str(directory), "TMPDIR": str(directory), "SAL_USE_VCLPLUGIN": "svp",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.pagecheck_task", str(directory),
        cwd=Path(__file__).resolve().parents[1], env=environment,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
    )
    try:
        stdout, _ = await process.communicate()
        if process.returncode == 4:
            return None, "ACTIVE_CONTENT"
        if process.returncode or not stdout.strip().isdigit() or len(stdout) > 16:
            return None, "PAGECHECK_FAILED"
        return int(stdout.strip()), None
    finally:
        # Also reap descendants if the task exits before its layout engine does.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


def create_worker():
    slot = asyncio.BoundedSemaphore(1)
    state = {"active": 0}

    @asynccontextmanager
    async def lifespan(app):
        validate_sandbox()
        yield

    worker = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @worker.get("/healthz")
    async def health():
        return {"status": "ok", "isolated": True, "active_jobs": state["active"],
                "temporary_jobs": len(list(Path("/tmp").glob("pagecheck-*")))}

    @worker.post("/count")
    async def count(request: Request):
        if slot.locked():
            return JSONResponse({"code": "PAGECHECK_BUSY"}, status_code=429)
        await slot.acquire()
        state["active"] = 1
        try:
            async with asyncio.timeout(TASK_SECONDS):
                # The service mounts this tmpfs privately; normal disks are read-only.
                with tempfile.TemporaryDirectory(prefix="pagecheck-", dir="/tmp") as scratch:
                    directory = Path(scratch)
                    received = 0
                    with (directory / "source.docx").open("wb") as source:
                        async for chunk in request.stream():
                            received += len(chunk)
                            if received > MAX_BYTES:
                                return JSONResponse({"code": "FILE_TOO_LARGE"}, status_code=413)
                            source.write(chunk)
                    pages, error = await task_process(directory)
                    if error:
                        return JSONResponse({"code": error}, status_code=422)
                    if not pages:
                        return JSONResponse({"code": "PAGECHECK_FAILED"}, status_code=422)
                    if pages > 8:
                        return JSONResponse({"code": "PAGE_LIMIT"}, status_code=422)
                    return {"pages": pages}
        except TimeoutError:
            return JSONResponse({"code": "PAGECHECK_TIMEOUT"}, status_code=422)
        except Exception:
            return JSONResponse({"code": "PAGECHECK_UNAVAILABLE"}, status_code=503)
        finally:
            state["active"] = 0
            slot.release()

    return worker


app = create_worker()
