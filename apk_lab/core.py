from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def now():
    return time.time()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as f:
            os.chmod(temp, 0o600)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def config():
    cfg = read_json(os.environ.get("APK_LAB_CONFIG", str(PROJECT / "config.local.json")), {})
    workspace = os.environ.get("APK_LAB_WORKSPACE", cfg.get("workspace", str(Path.home() / "hermes_workdir")))
    cfg["workspace"] = str(Path(workspace).expanduser().resolve())
    cfg.setdefault("port", 9099)
    cfg.setdefault("exposure", "direct")
    cfg.setdefault("public_base_url", "")
    cfg.setdefault("max_upload_bytes", 4 * 1024**3)
    cfg.setdefault("chunk_bytes", 8 * 1024**2)
    cfg.setdefault("idle_seconds", 1800)
    cfg.setdefault("lifetime_seconds", 14400)
    return cfg


def root():
    p = Path(config()["workspace"]) / "apk-lab"
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


@contextlib.contextmanager
def lock(path, blocking=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise ValueError("Another operation is already running for this job") from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def db():
    conn = sqlite3.connect(root() / "jobs.sqlite", timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    return conn


def job_dir(job_id):
    if not re.fullmatch(r"[a-f0-9]{16}", job_id):
        raise ValueError("Invalid job id")
    return root() / "projects" / job_id


def get_job(job_id):
    job_dir(job_id)
    with contextlib.closing(db()) as conn:
        row = conn.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise ValueError("Unknown job")
    return json.loads(row[0])


def list_jobs():
    with contextlib.closing(db()) as conn:
        data = [json.loads(r[0]) for r in conn.execute("SELECT data FROM jobs")]
    return sorted(data, key=lambda x: x["created_at"], reverse=True)


def update_job(job_id, **changes):
    # DB is authoritative; serialize writers and regenerate the human-readable snapshot.
    with lock(job_dir(job_id) / ".state.lock"):
        with contextlib.closing(db()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Unknown job")
            job = json.loads(row[0])
            job.update(changes)
            job["updated_at"] = now()
            conn.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(job), job_id))
            conn.commit()
        atomic_json(job_dir(job_id) / "state.json", job)
    return job


def event(job_id, kind, **details):
    with lock(job_dir(job_id) / ".events.lock"):
        with (job_dir(job_id) / "events.jsonl").open("a") as f:
            f.write(json.dumps({"time": now(), "kind": kind, **details}, ensure_ascii=False) + "\n")


def create_job(goal, delivery=None):
    if not goal.strip():
        raise ValueError("A concrete analysis goal is required")
    job_id = secrets.token_hex(8)
    p = job_dir(job_id)
    for name in ["input", "analysis", "evidence", "decoded", "patches", "builds", "tests", "logs", "artifacts"]:
        (p / name).mkdir(parents=True, mode=0o700)
    job = {"id": job_id, "goal": goal, "phase": "waiting_upload", "created_at": now(),
           "updated_at": now(), "directory": str(p), "input": None, "artifacts": [],
           "verification": {}, "blockers": [], "next_action": "Wait for upload, then inspect and analyze",
           "delivery": delivery, "revision": 0, "test_mode": None, "work_mode": None, "control_owner": None}
    with contextlib.closing(db()) as conn:
        conn.execute("INSERT INTO jobs VALUES (?, ?)", (job_id, json.dumps(job)))
        conn.commit()
    atomic_json(p / "state.json", job)
    atomic_json(p / "goal.json", {"goal": goal, "acceptance_criteria": [], "constraints": []})
    (p / "analysis" / "notes.md").write_text("# Investigation\n\nGoal: " + goal + "\n\n## Findings\n\n## Hypotheses\n\n## Unknowns\n")
    event(job_id, "created")
    return job


def issue_token(job_id):
    get_job(job_id)
    token = secrets.token_urlsafe(32)
    atomic_json(job_dir(job_id) / ".access.json", {
        "digest": hashlib.sha256(token.encode()).hexdigest(),
        "expires_at": now() + config()["lifetime_seconds"],
    })
    return token


def authorize(job_id, token):
    item = read_json(job_dir(job_id) / ".access.json", {})
    return bool(token and item.get("expires_at", 0) > now() and secrets.compare_digest(
        item.get("digest", ""), hashlib.sha256(token.encode()).hexdigest()))


def inside(path, parent):
    p, base = Path(path).resolve(), Path(parent).resolve()
    if not p.is_relative_to(base):
        raise ValueError("Path is outside the permitted directory")
    return p


def publish(job_id, source, label=None):
    p = job_dir(job_id)
    source = inside(source, p)
    if not source.is_file() or source.name.startswith(".") or source.suffix.lower() not in {
        ".apk", ".apks", ".zip", ".md", ".json", ".html", ".txt", ".pdf", ".patch", ".png"}:
        raise ValueError("Unsupported or missing artifact")
    if not any(source.is_relative_to(p / name) for name in ["builds", "analysis", "tests", "patches"]):
        raise ValueError("Only builds, analysis, tests and patches may be published")
    digest = sha256(source)
    # Distinct before/after captures remain separately visible even if their pixels match.
    artifact_id = hashlib.sha256((digest + ":" + str(source.relative_to(p))).encode()).hexdigest()[:24]
    dest = p / "artifacts" / (artifact_id + source.suffix)
    if not dest.exists():
        shutil.copyfile(source, dest)
        os.chmod(dest, 0o400)
    item = {"id": artifact_id, "name": source.name, "label": label or source.name,
            "path": str(dest), "sha256": digest, "size": dest.stat().st_size}
    with lock(p / ".publish.lock"):
        job = get_job(job_id)
        artifacts = [a for a in job["artifacts"] if a["id"] != artifact_id] + [item]
        update_job(job_id, artifacts=artifacts)
    event(job_id, "published", artifact=item)
    return item


def public_job(job):
    return {k: job[k] for k in ["id", "goal", "phase", "created_at", "updated_at", "next_action", "blockers"]} | {
        "input": {k: job["input"][k] for k in ["name", "sha256", "size"]} if job["input"] else None,
        "artifacts": [{k: a[k] for k in ["id", "name", "label", "sha256", "size"]} for a in job["artifacts"]],
    }
