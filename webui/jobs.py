"""Job runner.

Each submitted job runs in its own background thread. stdout/stderr from the
pipeline are captured and funnelled into an in-memory deque per job so the
SSE endpoint can stream them live to the browser. Jobs are kept in-memory
only — restarting the server starts from a clean slate.
"""
from __future__ import annotations

import io
import sys
import threading
import time
import traceback
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from shorts_generator import generate_shorts


JobStatus = str  # "pending" | "running" | "succeeded" | "failed"


@dataclass
class Job:
    id: str
    params: Dict
    status: JobStatus = "pending"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    logs: Deque[str] = field(default_factory=lambda: deque(maxlen=5000))
    _log_cond: threading.Condition = field(default_factory=threading.Condition)

    def append_log(self, line: str) -> None:
        with self._log_cond:
            self.logs.append(line)
            self._log_cond.notify_all()

    def wait_for_new_logs(self, last_index: int, timeout: float = 1.0) -> None:
        """Block until more logs are available or timeout."""
        with self._log_cond:
            if len(self.logs) > last_index or self.status in ("succeeded", "failed"):
                return
            self._log_cond.wait(timeout=timeout)

    def notify_finished(self) -> None:
        with self._log_cond:
            self._log_cond.notify_all()

    def snapshot(self) -> Dict:
        return {
            "id": self.id,
            "params": self.params,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "log_count": len(self.logs),
        }


class _StreamForwarder(io.TextIOBase):
    """Tee a text stream into a job's log buffer *and* the real stdout."""

    def __init__(self, job: Job, real: io.TextIOBase):
        self._job = job
        self._real = real
        self._buf = ""

    def write(self, data: str) -> int:
        if not data:
            return 0
        try:
            self._real.write(data)
            self._real.flush()
        except Exception:
            pass
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                self._job.append_log(line)
        return len(data)

    def flush(self) -> None:
        try:
            self._real.flush()
        except Exception:
            pass
        if self._buf:
            self._job.append_log(self._buf)
            self._buf = ""


@contextmanager
def _capture_streams(job: Job):
    """Route the running thread's prints through the job's log buffer.

    Note: this mutates process-wide sys.stdout/stderr, so we only support one
    job executing at a time (enforced by the runner's lock).
    """
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = _StreamForwarder(job, old_out)
    sys.stderr = _StreamForwarder(job, old_err)
    try:
        yield
    finally:
        try:
            sys.stdout.flush()  # type: ignore[attr-defined]
            sys.stderr.flush()  # type: ignore[attr-defined]
        except Exception:
            pass
        sys.stdout = old_out
        sys.stderr = old_err


class JobRunner:
    """Single-worker job queue. One job runs at a time; extras queue up."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._order: List[str] = []  # newest-first
        self._lock = threading.Lock()
        self._worker_lock = threading.Lock()

    # --- public API ------------------------------------------------------- #

    def submit(self, params: Dict) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, params=params)
        with self._lock:
            self._jobs[job_id] = job
            self._order.insert(0, job_id)
        threading.Thread(target=self._run, args=(job,), daemon=True, name=f"job-{job_id}").start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            snaps = [self._jobs[jid].snapshot() for jid in self._order[:limit] if jid in self._jobs]
        return snaps

    # --- worker ----------------------------------------------------------- #

    def _run(self, job: Job) -> None:
        # Serialise jobs — the pipeline mutates sys.stdout globally.
        with self._worker_lock:
            job.status = "running"
            job.started_at = time.time()
            job.append_log(f"[webui] job {job.id} starting: {job.params}")
            try:
                with _capture_streams(job):
                    result = generate_shorts(**job.params)
                # Strip the transcript from the JSON shown in the UI — it's huge
                # and already saved to disk if --output-json was requested.
                if isinstance(result, dict):
                    slim = dict(result)
                    if "transcript" in slim:
                        t = slim["transcript"]
                        slim["transcript"] = {
                            "duration": (t or {}).get("duration"),
                            "segment_count": len((t or {}).get("segments") or []),
                        }
                    job.result = slim
                else:
                    job.result = {"raw": str(result)}
                job.status = "succeeded"
                job.append_log(f"[webui] job {job.id} succeeded")
            except Exception as e:
                job.status = "failed"
                job.error = f"{type(e).__name__}: {e}"
                job.append_log(f"[webui] job {job.id} failed: {job.error}")
                job.append_log(traceback.format_exc())
            finally:
                job.finished_at = time.time()
                job.notify_finished()


runner = JobRunner()
