"""`python -m webui` — start the dev server."""
import argparse
import os
import sys

import uvicorn


def _warn_if_wrong_venv() -> None:
    """Spot the foot-gun where someone launches ``python -m webui`` with a
    global Python that doesn't have the local-mode deps installed."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        project_py = os.path.join(project_root, ".venv", "Scripts", "python.exe")
        has_project_venv = os.path.exists(project_py)
        interp = sys.executable
        hint = (
            f"[webui] WARNING: yt-dlp is not installed in this Python "
            f"({interp}).\n"
            f"        Local-mode jobs WILL fail until you install the deps."
        )
        if has_project_venv and os.path.normcase(interp) != os.path.normcase(project_py):
            hint += (
                f"\n        Detected a project venv at {project_py} — "
                f"relaunch with that interpreter (e.g. `./run-webui.ps1`).\n"
                f"        Or install the deps into the current one:\n"
                f"          \"{interp}\" -m pip install -r requirements.txt "
                f"-r requirements-local.txt -r requirements-webui.txt"
            )
        else:
            hint += (
                f"\n        Install the deps with:\n"
                f"          \"{interp}\" -m pip install -r requirements.txt "
                f"-r requirements-local.txt -r requirements-webui.txt"
            )
        print(hint, flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description="yt-short-generator web UI")
    p.add_argument("--host", default=os.getenv("WEBUI_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("WEBUI_PORT", "8000")))
    p.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    args = p.parse_args()

    _warn_if_wrong_venv()

    print(f"[webui] starting on http://{args.host}:{args.port}", flush=True)
    print(f"[webui] python: {sys.executable}", flush=True)
    uvicorn.run(
        "webui.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
