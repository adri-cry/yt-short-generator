"""FastAPI web UI for yt-short-generator.

Routes:
  GET  /                    single-page UI
  POST /api/jobs            submit a new job
  GET  /api/jobs            list recent jobs
  GET  /api/jobs/{id}       job detail (status + result + log snapshot)
  GET  /api/jobs/{id}/logs  SSE stream of log lines
  GET  /clips/{path}        serve rendered mp4s from LOCAL_OUTPUT_DIR
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from shorts_generator.config import LOCAL_OUTPUT_DIR, LOCAL_WHISPER_MODEL, SUBTITLES_ENABLED
from shorts_generator.highlights import DEFAULT_MAX_DURATION, DEFAULT_MIN_DURATION

from .jobs import runner


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"


class JobSubmit(BaseModel):
    youtube_url: str = Field(..., min_length=5)
    mode: str = Field(default="local", pattern="^(api|local)$")
    num_clips: int = Field(default=3, ge=1, le=20)
    aspect_ratio: str = Field(default="9:16")
    download_format: str = Field(default="720")
    language: Optional[str] = None
    subtitles: Optional[bool] = None
    min_duration: int = Field(default=DEFAULT_MIN_DURATION, ge=5, le=300)
    max_duration: int = Field(default=DEFAULT_MAX_DURATION, ge=5, le=300)
    whisper_model: Optional[str] = None
    initial_prompt: Optional[str] = None


app = FastAPI(title="yt-short-generator web UI")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/defaults")
def defaults() -> dict:
    return {
        "mode": "local",
        "num_clips": 3,
        "aspect_ratio": "9:16",
        "download_format": "720",
        "subtitles": SUBTITLES_ENABLED,
        "output_dir": LOCAL_OUTPUT_DIR,
        "min_duration": DEFAULT_MIN_DURATION,
        "max_duration": DEFAULT_MAX_DURATION,
        "whisper_model": LOCAL_WHISPER_MODEL,
        "whisper_model_options": ["tiny", "base", "small", "medium", "large-v3"],
    }


@app.post("/api/jobs")
def submit_job(body: JobSubmit) -> dict:
    if body.max_duration < body.min_duration:
        raise HTTPException(
            status_code=400,
            detail=f"max_duration ({body.max_duration}) must be >= min_duration ({body.min_duration})",
        )
    params = {
        "youtube_url": body.youtube_url,
        "num_clips": body.num_clips,
        "aspect_ratio": body.aspect_ratio,
        "download_format": body.download_format,
        "language": body.language or None,
        "mode": body.mode,
        "subtitles": body.subtitles,
        "min_duration": body.min_duration,
        "max_duration": body.max_duration,
        "whisper_model": (body.whisper_model or "").strip() or None,
        "initial_prompt": (body.initial_prompt or "").strip() or None,
    }
    job = runner.submit(params)
    return job.snapshot()


@app.get("/api/jobs")
def list_jobs(limit: int = 50) -> dict:
    return {"jobs": runner.list(limit=limit)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = runner.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    snap = job.snapshot()
    # Include the most recent log tail so refreshes restore context.
    snap["logs"] = list(job.logs)[-200:]
    return snap


@app.get("/api/jobs/{job_id}/logs")
async def stream_logs(job_id: str, request: Request) -> StreamingResponse:
    job = runner.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_generator():
        last_index = 0
        # On (re)connect, flush everything we already have.
        snapshot = list(job.logs)
        for line in snapshot:
            yield f"data: {json.dumps({'line': line})}\n\n"
        last_index = len(snapshot)

        while True:
            if await request.is_disconnected():
                return

            # Move the wait off the event loop so we don't block FastAPI.
            await asyncio.get_event_loop().run_in_executor(
                None, job.wait_for_new_logs, last_index, 1.0
            )

            logs_now = list(job.logs)
            if len(logs_now) > last_index:
                for line in logs_now[last_index:]:
                    yield f"data: {json.dumps({'line': line})}\n\n"
                last_index = len(logs_now)

            if job.status in ("succeeded", "failed") and last_index >= len(job.logs):
                payload = {"event": "done", "status": job.status, "error": job.error, "result": job.result}
                yield f"data: {json.dumps(payload)}\n\n"
                return

            # SSE heartbeat so intermediaries don't drop the connection.
            yield ": keep-alive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/clips/{rel_path:path}")
def serve_clip(rel_path: str) -> FileResponse:
    """Serve a file from the output directory.

    We resolve relative to the output dir and refuse anything that escapes it,
    so this is safe even though the path comes from a URL.
    """
    base = Path(LOCAL_OUTPUT_DIR).resolve()
    target = (base / rel_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(str(target))
