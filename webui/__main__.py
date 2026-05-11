"""`python -m webui` — start the dev server."""
import argparse
import os
import sys

import uvicorn


def main() -> int:
    p = argparse.ArgumentParser(description="yt-short-generator web UI")
    p.add_argument("--host", default=os.getenv("WEBUI_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("WEBUI_PORT", "8000")))
    p.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    args = p.parse_args()

    print(f"[webui] starting on http://{args.host}:{args.port}", flush=True)
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
