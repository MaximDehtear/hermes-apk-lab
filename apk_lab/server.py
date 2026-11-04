from __future__ import annotations

import contextlib
import http.cookies
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

from .core import PROJECT, atomic_json, authorize, config, event, get_job, inside, issue_token, job_dir, lock, now, public_job, read_json, root
from .pipeline import accept_input


def runtime():
    p = root() / ".runtime"
    p.mkdir(mode=0o700, exist_ok=True)
    return p


def identity(pid):
    try:
        # Field 22 is starttime; comm may contain spaces, so split after its closing ')'.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {"pid": pid, "start": fields[19], "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(item):
    return bool(item and identity(item.get("pid")) == item)


def terminate(item):
    if alive(item):
        os.kill(item["pid"], signal.SIGTERM)
        return True
    return False


def server_status():
    data = read_json(runtime() / "server.json", {})
    return data | {"running": alive(data.get("process"))}


def start_server(exposure=None, port=None):
    cfg = config()
    exposure = exposure or cfg["exposure"]
    if exposure not in {"direct", "lan", "local"}:
        raise ValueError("Use exposure=direct (0.0.0.0) or local; tunnels are not supported")
    configured_url = validate_base_url(cfg.get("public_base_url", ""))
    port = port if port is not None else cfg["port"]
    with lock(runtime() / "lifecycle.lock"):
        current = server_status()
        if current["running"]:
            if current.get("exposure") != exposure or (port and current.get("port") != port):
                raise ValueError("Server is already running with different settings; stop it first")
            if current.get("configured_public_url", "") != configured_url:
                raise ValueError("Public address changed; stop and reopen the server")
            return current
        bind = "127.0.0.1" if exposure == "local" else "0.0.0.0"
        env = dict(os.environ, PYTHONPATH=str(PROJECT))
        command = [sys.executable, "-m", "apk_lab.cli", "serve", "--bind", bind,
                   "--port", str(port), "--exposure", exposure]
        proc = None
        # Separate transient unit survives the launching shell and gateway restart.
        unit = "hermes-apk-lab-transfer-" + hashlib.sha256(str(root()).encode()).hexdigest()[:12]
        use_systemd = False
        if shutil.which("systemd-run") and shutil.which("systemctl"):
            try:
                use_systemd = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, timeout=5).returncode == 0
            except subprocess.SubprocessError:
                pass
        if use_systemd:
            systemd_command = ["systemd-run", "--user", "--quiet", "--collect", "--unit", unit,
                               "--property", "Type=exec", "--property", "KillMode=control-group",
                               "--property", "WorkingDirectory="+str(PROJECT),
                               "--property", "StandardOutput=append:"+str(runtime()/"server.log"),
                               "--property", "StandardError=append:"+str(runtime()/"server.log"),
                               "--setenv=PYTHONPATH="+str(PROJECT), "--setenv=APK_LAB_WORKSPACE="+config()["workspace"],
                               "--setenv=PATH="+os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")]
            if os.environ.get("APK_LAB_CONFIG"):
                systemd_command.append("--setenv=APK_LAB_CONFIG="+os.environ["APK_LAB_CONFIG"])
            launched = subprocess.run(systemd_command + command, capture_output=True, timeout=10)
            if launched.returncode:
                raise ValueError("Cannot start transfer service: " + launched.stderr.decode(errors="replace")[-1500:])
        else:
            with (runtime() / "server.log").open("ab") as log:
                proc = subprocess.Popen(command, cwd=PROJECT, env=env, stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=log, start_new_session=True)
        launched_at = now()
        for _ in range(100):
            data = server_status()
            if data["running"] and data.get("started_at", 0) >= launched_at - 2:
                return data
            if proc and proc.poll() is not None:
                raise ValueError("Server failed; read " + str(runtime() / "server.log"))
            time.sleep(0.2)
        if proc:
            terminate(identity(proc.pid))
        else:
            subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True, timeout=10)
        raise ValueError("Server startup timed out")


def stop_server():
    with lock(runtime() / "lifecycle.lock"):
        data = server_status()
        changed = terminate(data.get("process"))
        for _ in range(40):
            if not alive(data.get("process")):
                break
            time.sleep(0.1)
        return {"stopped": changed, "status": server_status(), "jobs_preserved": True}


def link(job_id, exposure=None, port=None):
    status = start_server(exposure, port)
    token = issue_token(job_id)
    return {"job_id": job_id, "url": status["public_url"] + "/#job=" + job_id + "&token=" + token,
            "bind": status["bind"], "public_address_configured": bool(status.get("configured_public_url")),
            "internet_reachability_verified": False,
            "port": status["port"], "expires_in_seconds": config()["lifetime_seconds"],
            "idle_shutdown_seconds": config()["idle_seconds"]}


class LabServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address):
        super().__init__(address, Handler)
        self.last_activity = now()
        self.started = now()
        self.active = 0
        self.activity_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass  # No URLs, cookies, access tokens or uploaded names in HTTP logs.

    def setup(self):
        super().setup()
        self.connection.settimeout(90)

    def headers_out(self, code, size, kind="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def json(self, code, data, extra=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.headers_out(code, len(body), extra=extra)
        self.wfile.write(body)

    def body(self, maximum=65536):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Chunked transfer encoding is unsupported; send Content-Length")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 <= size <= maximum:
            raise ValueError("Request exceeds size limit")
        data = self.rfile.read(size)
        if len(data) != size:
            raise ValueError("Incomplete request body")
        return data

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def dispatch(self, method):
        with self.server.activity_lock:
            self.server.active += 1
        try:
            self.route(method)
        except (ValueError, KeyError, zipfile.BadZipFile) as e:
            self.close_connection = True
            self.json(400, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception as e:
            self.close_connection = True
            print("HTTP handler error:", type(e).__name__, str(e), flush=True)
            self.json(500, {"error": "Internal error; inspect server.log"})
        finally:
            with self.server.activity_lock:
                self.server.active -= 1

    def route(self, method):
        path = urlsplit(self.path).path
        if method == "GET" and path == "/":
            data = (PROJECT / "apk_lab" / "web.html").read_bytes()
            self.headers_out(200, len(data), "text/html; charset=utf-8")
            self.wfile.write(data)
            return
        if method == "GET" and path == "/health":
            return self.json(200, {"ok": True})
        match = re.fullmatch(r"/api/([a-f0-9]{16})/(auth|status|upload|chunk|complete|download/[a-f0-9]{24}|preview/[a-f0-9]{24})", path)
        if not match:
            return self.json(404, {"error": "Not found"})
        job_id, action = match.groups()
        bearer = self.headers.get("Authorization", "")
        cookie = http.cookies.SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        token = bearer[7:] if bearer.startswith("Bearer ") else (cookie.get("apk_lab_" + job_id).value if cookie.get("apk_lab_" + job_id) else "")
        if not authorize(job_id, token):
            self.close_connection = True
            return self.json(403, {"error": "Access expired or invalid. Ask Hermes for a new link."})
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", "") and origin != "https://" + self.headers.get("Host", ""):
            self.close_connection = True
            return self.json(403, {"error": "Cross-origin request rejected"})
        # Polling is deliberately not activity: an idle open tab must not keep the server alive.
        if action != "status":
            self.server.last_activity = now()
        if action == "auth" and method == "POST":
            self.body()
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            return self.json(200, {"ok": True}, {"Set-Cookie": f"apk_lab_{job_id}={token}; Path=/api/{job_id}/; HttpOnly; SameSite=Strict{secure}"})
        if action == "status" and method == "GET":
            return self.json(200, public_job(get_job(job_id)))
        if action.startswith("download/") and method == "GET":
            return self.download(job_id, action.split("/")[1])
        if action.startswith("preview/") and method == "GET":
            return self.download(job_id, action.split("/")[1], preview=True)
        if action == "upload" and method == "POST":
            data = json.loads(self.body())
            with lock(job_dir(job_id) / ".upload.lock"):
                if get_job(job_id)["input"]:
                    raise ValueError("Input already received")
                name, size = str(data["name"]), int(data["size"])
                if not 0 < size <= config()["max_upload_bytes"]:
                    raise ValueError("File exceeds upload limit")
                if Path(name).suffix.lower() not in {".apk", ".apks", ".xapk", ".apkm", ".zip"}:
                    raise ValueError("Select an APK or APK set")
                meta_path = job_dir(job_id) / "input" / "upload.json"
                part = job_dir(job_id) / "input" / "upload.part"
                meta = read_json(meta_path, {})
                fingerprint = str(data.get("fingerprint", ""))
                if meta and (meta["name"], meta["size"], meta.get("fingerprint")) != (name, size, fingerprint):
                    raise ValueError("Another file is partly uploaded; create a new job to replace it")
                if not meta:
                    meta = {"name": name, "size": size, "id": secrets.token_hex(16), "fingerprint": fingerprint}
                    atomic_json(meta_path, meta)
                return self.json(200, meta | {"offset": part.stat().st_size if part.exists() else 0, "chunk_bytes": config()["chunk_bytes"]})
        if action == "chunk" and method == "PUT":
            # Bound memory to one chunk per request, independent of total APK size.
            with lock(job_dir(job_id) / ".upload.lock"):
                if get_job(job_id)["input"]:
                    raise ValueError("Input already received")
                meta = read_json(job_dir(job_id) / "input" / "upload.json", {})
                if not secrets.compare_digest(meta.get("id", ""), self.headers.get("X-Upload-ID", "missing")):
                    raise ValueError("Invalid upload id")
                part = job_dir(job_id) / "input" / "upload.part"
                offset = part.stat().st_size if part.exists() else 0
                length = int(self.headers.get("Content-Length", "0"))
                if int(self.headers.get("X-Upload-Offset", "-1")) != offset:
                    raise ValueError("Offset mismatch; reconnect to resume")
                if length <= 0 or offset + length > meta["size"]:
                    raise ValueError("Invalid chunk size")
                if shutil.disk_usage(part.parent).free < length + 128 * 1024**2:
                    raise ValueError("Insufficient free disk space")
                block = self.body(config()["chunk_bytes"])
                with part.open("ab") as f:
                    f.write(block)
                    f.flush()
                    os.fsync(f.fileno())
                return self.json(200, {"offset": offset + len(block)})
        if action == "complete" and method == "POST":
            data = json.loads(self.body())
            with lock(job_dir(job_id) / ".upload.lock"):
                existing = get_job(job_id)
                if existing["input"]:
                    return self.json(200, public_job(existing))
                meta = read_json(job_dir(job_id) / "input" / "upload.json", {})
                part = job_dir(job_id) / "input" / "upload.part"
                if meta.get("id") != data.get("id") or not part.exists() or part.stat().st_size != meta.get("size"):
                    raise ValueError("Upload is incomplete")
                return self.json(200, public_job(accept_input(job_id, part, meta["name"])))
        self.close_connection = True
        self.json(405, {"error": "Method not allowed"})

    def download(self, job_id, artifact_id, preview=False):
        job = get_job(job_id)
        item = next((a for a in job["artifacts"] if a["id"] == artifact_id), None)
        if not item:
            return self.json(404, {"error": "Unknown artifact"})
        path = inside(item["path"], job_dir(job_id) / "artifacts")
        if preview and path.suffix != ".png":
            return self.json(400, {"error": "Only screenshots support inline preview"})
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        extra = {"Accept-Ranges": "bytes", "Content-Disposition": "attachment; filename*=UTF-8''" + quote(item["name"])}
        if self.headers.get("Range"):
            m = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers["Range"])
            if not m:
                return self.json(416, {"error": "Unsupported range"})
            start, end = int(m[1]), int(m[2]) if m[2] else size - 1
            if not 0 <= start <= end < size:
                return self.json(416, {"error": "Invalid range"})
            code = 206
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        if preview:
            extra["Content-Disposition"] = "inline"
        self.headers_out(code, end - start + 1, "image/png" if preview else "application/octet-stream", extra)
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining:
                block = f.read(min(1024**2, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)
                self.server.last_activity = now()
        event(job_id, "download", artifact_id=artifact_id, bytes_sent=end - start + 1 - remaining)


def validate_base_url(value):
    if not value:
        return ""
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"} or parsed.hostname in {"0.0.0.0", "::"}):
        raise ValueError("public_base_url must be an http(s) origin with a real host, e.g. http://your-host:9099")
    parsed.port  # Reject invalid ports before starting a detached service.
    return value.rstrip("/")


def serve(bind, port, exposure):
    server = LabServer((bind, port))
    port = server.server_address[1]
    public_url = f"http://127.0.0.1:{port}"
    if exposure != "local":
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                # Route lookup only: UDP connect sends no packet or discovery request.
                sock.connect(("192.0.2.1", 80))
                public_url = f"http://{sock.getsockname()[0]}:{port}"
            except OSError:
                public_url = f"http://{socket.gethostname()}:{port}"
    configured_url = validate_base_url(config().get("public_base_url", ""))
    if configured_url and exposure != "local":
        public_url = configured_url
    state = {"process": identity(os.getpid()), "port": port, "bind": bind, "exposure": exposure,
             "public_url": public_url, "configured_public_url": configured_url, "started_at": now()}
    atomic_json(runtime() / "server.json", state)
    def stop(*_args):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def watch():
        while True:
            time.sleep(1)
            with server.activity_lock:
                expired = now() - server.last_activity > config()["idle_seconds"] or now() - server.started > config()["lifetime_seconds"]
                if expired and server.active == 0:
                    stop()
                    return
    threading.Thread(target=watch, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        atomic_json(runtime() / "server.json", state | {"stopped_at": now(), "process": None})
