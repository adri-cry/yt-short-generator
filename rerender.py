"""Re-render top highlights from a cached source video.

Useful when YouTube blocks a fresh download but you already have the mp4
locally. Re-transcribes to get word-level timestamps, runs the highlight LLM
against the fresh transcript, then crops the top N clips.

Usage:
    python rerender.py [--source PATH] [--num-clips 3]
"""
import argparse
import json
import sys

for _s in (sys.stdout, sys.stderr):
    rc = getattr(_s, "reconfigure", None)
    if rc:
        try:
            rc(encoding="utf-8", errors="replace")
        except Exception:
            pass

from shorts_generator.config import get_subtitle_style, SUBTITLES_ENABLED
from shorts_generator.highlights import get_highlights
from shorts_generator.local.clipper import crop_highlights_local
from shorts_generator.local.llm import call_openai_llm
from shorts_generator.local.transcriber import transcribe_local


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="output/source_bgr6D9YuZfQ.mp4")
    p.add_argument("--num-clips", type=int, default=3)
    p.add_argument("--aspect-ratio", default="9:16")
    p.add_argument("--language", default=None)
    p.add_argument(
        "--subtitles",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    p.add_argument(
        "--transcript-cache",
        default="output/transcript_cache.json",
        help="Cache transcript to this path so we don't re-transcribe every run.",
    )
    p.add_argument(
        "--fresh-transcript",
        action="store_true",
        help="Ignore the transcript cache and re-transcribe.",
    )
    args = p.parse_args()

    subs_enabled = SUBTITLES_ENABLED if args.subtitles is None else args.subtitles

    transcript = None
    if args.transcript_cache and not args.fresh_transcript:
        try:
            with open(args.transcript_cache, encoding="utf-8") as f:
                transcript = json.load(f)
            print(f"[rerender] loaded cached transcript from {args.transcript_cache}", flush=True)
        except FileNotFoundError:
            transcript = None

    if transcript is None:
        print("[rerender] transcribing (this is the slow step)...", flush=True)
        transcript = transcribe_local(args.source, language=args.language)
        if args.transcript_cache:
            with open(args.transcript_cache, "w", encoding="utf-8") as f:
                json.dump(transcript, f)
            print(f"[rerender] cached transcript -> {args.transcript_cache}", flush=True)

    if not transcript.get("segments"):
        print("no segments transcribed", file=sys.stderr)
        return 1

    print("[rerender] ranking highlights...", flush=True)
    hl_result = get_highlights(transcript, num_clips=args.num_clips, llm_fn=call_openai_llm)
    all_highlights = hl_result.get("highlights") or []
    if not all_highlights:
        print("no highlights returned", file=sys.stderr)
        return 1

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[: args.num_clips]
    print(f"[rerender] cropping top {len(top)} of {len(all_highlights)} candidates", flush=True)

    shorts = crop_highlights_local(
        args.source,
        top,
        aspect_ratio=args.aspect_ratio,
        segments=transcript["segments"],
        subtitles_enabled=subs_enabled,
        subtitle_style=get_subtitle_style() if subs_enabled else None,
    )

    print("\n" + "=" * 72)
    for i, s in enumerate(shorts, 1):
        print(f"#{i}  score={s.get('score')}  {s.get('start_time'):.1f}s -> {s.get('end_time'):.1f}s")
        print(f"     title: {s.get('title')}")
        print(f"     clip:  {s.get('clip_url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
