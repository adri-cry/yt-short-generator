"""End-to-end orchestrator.

Two modes:
  * mode="api"   (default) — MuAPI does download / transcribe / LLM / autocrop.
                              Fast, no local deps, pay-per-call.
  * mode="local"            — yt-dlp + faster-whisper + OpenAI + ffmpeg/opencv.
                              Self-hosted, OPENAI_API_KEY required for the LLM.
                              Supports word-level karaoke subtitles.
"""
from typing import Dict, List, Optional

from .clipper import crop_highlights
from .config import SUBTITLES_ENABLED, get_subtitle_style
from .downloader import download_youtube
from .highlights import (
    DEFAULT_MAX_DURATION,
    DEFAULT_MIN_DURATION,
    call_muapi_llm,
    get_highlights,
)
from .transcriber import transcribe


def _run_local(
    youtube_url: str,
    num_clips: int,
    aspect_ratio: str,
    download_format: str,
    language: Optional[str],
    subtitles: bool,
    min_duration: int,
    max_duration: int,
) -> Dict:
    from .local.clipper import crop_highlights_local
    from .local.downloader import download_youtube_local
    from .local.llm import call_openai_llm
    from .local.transcriber import transcribe_local

    source_path = download_youtube_local(youtube_url, fmt=download_format)

    transcript = transcribe_local(source_path, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    highlights_result = get_highlights(
        transcript,
        num_clips=num_clips,
        llm_fn=call_openai_llm,
        min_duration=min_duration,
        max_duration=max_duration,
    )
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline/local] cropping {len(top)} of {len(all_highlights)} candidates", flush=True)

    shorts = crop_highlights_local(
        source_path,
        top,
        aspect_ratio=aspect_ratio,
        segments=transcript["segments"],
        subtitles_enabled=subtitles,
        subtitle_style=get_subtitle_style() if subtitles else None,
    )

    return {
        "mode": "local",
        "source_video_url": source_path,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
        "subtitles": subtitles,
        "clip_duration_range": [min_duration, max_duration],
    }


def _run_api(
    youtube_url: str,
    num_clips: int,
    aspect_ratio: str,
    download_format: str,
    language: Optional[str],
    subtitles: bool,
    min_duration: int,
    max_duration: int,
) -> Dict:
    if subtitles:
        print(
            "[pipeline] note: --subtitles is currently only implemented for --mode local; "
            "API-mode clips will be rendered without burn-in.",
            flush=True,
        )

    source_url = download_youtube(youtube_url, fmt=download_format)

    transcript = transcribe(source_url, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    highlights_result = get_highlights(
        transcript,
        num_clips=num_clips,
        llm_fn=call_muapi_llm,
        min_duration=min_duration,
        max_duration=max_duration,
    )
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline] cropping {len(top)} of {len(all_highlights)} candidates", flush=True)

    shorts = crop_highlights(source_url, top, aspect_ratio=aspect_ratio)

    return {
        "mode": "api",
        "source_video_url": source_url,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
        "subtitles": False,
        "clip_duration_range": [min_duration, max_duration],
    }


def generate_shorts(
    youtube_url: str,
    num_clips: int = 3,
    aspect_ratio: str = "9:16",
    download_format: str = "720",
    language: Optional[str] = None,
    mode: str = "api",
    subtitles: Optional[bool] = None,
    min_duration: int = DEFAULT_MIN_DURATION,
    max_duration: int = DEFAULT_MAX_DURATION,
) -> Dict:
    """Run the full pipeline and return a structured result.

    Args:
        youtube_url: source URL.
        num_clips: how many shorts to render.
        aspect_ratio: e.g. "9:16", "1:1".
        download_format: source resolution ("360" / "480" / "720" / "1080").
        language: ISO-639-1 to force Whisper language detection.
        mode: "api" (default, MuAPI) or "local" (yt-dlp + faster-whisper +
            OpenAI + ffmpeg).
        subtitles: burn word-level karaoke captions into each short.
            Defaults to the SUBTITLES_ENABLED env var (True by default).
            Only effective in --mode local for now.
        min_duration / max_duration: preferred clip length in seconds.
            Defaults to 45-90s. Both a prompt hint and a hard post-filter.

    Returns:
        {
          "mode": "api" | "local",
          "source_video_url": str,   # hosted URL (api) or local path (local)
          "transcript": {...},
          "highlights": [...],       # all candidates ranked
          "shorts": [...],           # top `num_clips` with clip_url / local path
          "subtitles": bool,         # whether subtitles were burned in
          "clip_duration_range": [min, max],
        }
    """
    mode = (mode or "api").lower()
    subs = SUBTITLES_ENABLED if subtitles is None else bool(subtitles)

    min_d = int(min_duration)
    max_d = int(max_duration)
    if max_d < min_d:
        raise ValueError(f"max_duration ({max_d}) must be >= min_duration ({min_d})")

    if mode == "local":
        return _run_local(
            youtube_url, num_clips, aspect_ratio, download_format, language, subs, min_d, max_d
        )
    if mode == "api":
        return _run_api(
            youtube_url, num_clips, aspect_ratio, download_format, language, subs, min_d, max_d
        )
    raise ValueError(f"Unknown mode: {mode!r}. Use 'api' or 'local'.")
