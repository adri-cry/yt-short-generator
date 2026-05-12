"""CLI entry point.

Usage:
    python main.py "https://www.youtube.com/watch?v=..." \
        --num-clips 3 --aspect-ratio 9:16
"""
import argparse
import json
import sys

# Force UTF-8 on stdout/stderr so Unicode arrows etc. don't blow up on the
# default Windows cp1252 console.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from shorts_generator import generate_shorts


def main() -> int:
    parser = argparse.ArgumentParser(description="AI YouTube Shorts Generator")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--mode",
        choices=["api", "local"],
        default="local",
        help="local (default, yt-dlp + faster-whisper + OpenAI/9-router + ffmpeg) or api (MuAPI cloud).",
    )
    parser.add_argument("--num-clips", type=int, default=3, help="How many shorts to render (default: 3)")
    parser.add_argument("--aspect-ratio", default="9:16", help="Output aspect ratio (default: 9:16)")
    parser.add_argument("--format", default="720", help="Source download resolution: 360 / 480 / 720 / 1080 (default: 720)")
    parser.add_argument("--language", default=None, help="Force Whisper language code, e.g. 'en' (default: auto-detect)")
    parser.add_argument(
        "--subtitles",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Burn word-level karaoke captions into each short (default: SUBTITLES_ENABLED env, ON). Local mode only.",
    )
    parser.add_argument(
        "--min-duration",
        type=int,
        default=45,
        help="Minimum clip duration in seconds (default: 45). Clips shorter than this are dropped.",
    )
    parser.add_argument(
        "--max-duration",
        type=int,
        default=90,
        help="Maximum clip duration in seconds (default: 90). Longer clips are trimmed to this length.",
    )
    parser.add_argument(
        "--whisper-model",
        default=None,
        help="faster-whisper model: tiny / base / small / medium / large-v3. "
             "Bigger = much better accuracy, especially for non-English audio. "
             "Defaults to LOCAL_WHISPER_MODEL env (base).",
    )
    parser.add_argument(
        "--initial-prompt",
        default=None,
        help="Whisper bias prompt — comma-separated names, jargon, brands, "
             "or a sample sentence to steer spellings (e.g. 'Luna Maya, Raffi Ahmad, Gojek, Tokopedia').",
    )
    parser.add_argument("--output-json", default=None, help="Write the full result JSON to this path")
    args = parser.parse_args()

    try:
        result = generate_shorts(
            youtube_url=args.url,
            num_clips=args.num_clips,
            aspect_ratio=args.aspect_ratio,
            download_format=args.format,
            language=args.language,
            mode=args.mode,
            subtitles=args.subtitles,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            whisper_model=args.whisper_model,
            initial_prompt=args.initial_prompt,
        )
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        return 1

    print("\n" + "=" * 72)
    print(f"Mode:          {result.get('mode', args.mode)}")
    print(f"Source video:  {result['source_video_url']}")
    print(f"Highlights:    {len(result['highlights'])} candidates → kept top {len(result['shorts'])}")
    print("=" * 72)
    for i, s in enumerate(result["shorts"], 1):
        print(f"\n#{i}  score={s.get('score')}  {s.get('start_time'):.1f}s → {s.get('end_time'):.1f}s")
        print(f"     title:  {s.get('title')}")
        print(f"     hook:   {s.get('hook_sentence')}")
        if s.get("clip_url"):
            print(f"     clip:   {s['clip_url']}")
        else:
            print(f"     clip:   FAILED ({s.get('error')})")

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nFull JSON written to {args.output_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
