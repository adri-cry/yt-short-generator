import os

from dotenv import load_dotenv

load_dotenv()

MUAPI_API_KEY = os.getenv("MUAPI_API_KEY", "").strip()
MUAPI_BASE_URL = os.getenv("MUAPI_BASE_URL", "https://api.muapi.ai/api/v1").rstrip("/")

POLL_INTERVAL_SECONDS = float(os.getenv("MUAPI_POLL_INTERVAL", "5"))
POLL_TIMEOUT_SECONDS = float(os.getenv("MUAPI_POLL_TIMEOUT", "600"))

# Local-mode (--mode local) settings — only consulted when running offline.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or None
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "base")
LOCAL_WHISPER_DEVICE = os.getenv("LOCAL_WHISPER_DEVICE", "auto")  # auto / cpu / cuda
LOCAL_OUTPUT_DIR = os.getenv("LOCAL_OUTPUT_DIR", "output")
YT_COOKIES_FROM_BROWSER = os.getenv("YT_COOKIES_FROM_BROWSER", "").strip() or None
YT_COOKIE_FILE = os.getenv("YT_COOKIE_FILE", "").strip() or None


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# Subtitle settings (word-level karaoke). Only used in --mode local for now.
SUBTITLES_ENABLED = _bool_env("SUBTITLES_ENABLED", True)
SUBTITLE_FONT = os.getenv("SUBTITLE_FONT", "Arial Black")
SUBTITLE_FONT_SIZE_RATIO = float(os.getenv("SUBTITLE_FONT_SIZE_RATIO", "0.055"))
# ASS colours are &HAABBGGRR&. Defaults: white text, yellow karaoke sweep, black outline.
SUBTITLE_PRIMARY_COLOR = os.getenv("SUBTITLE_PRIMARY_COLOR", "&H00FFFFFF")
SUBTITLE_HIGHLIGHT_COLOR = os.getenv("SUBTITLE_HIGHLIGHT_COLOR", "&H0000FFFF")
SUBTITLE_OUTLINE_COLOR = os.getenv("SUBTITLE_OUTLINE_COLOR", "&H00000000")
SUBTITLE_OUTLINE_WIDTH = float(os.getenv("SUBTITLE_OUTLINE_WIDTH", "3"))
SUBTITLE_MARGIN_V_RATIO = float(os.getenv("SUBTITLE_MARGIN_V_RATIO", "0.12"))
SUBTITLE_WORDS_PER_CHUNK = int(os.getenv("SUBTITLE_WORDS_PER_CHUNK", "3"))
SUBTITLE_MAX_CHUNK_SECONDS = float(os.getenv("SUBTITLE_MAX_CHUNK_SECONDS", "1.4"))
SUBTITLE_UPPERCASE = _bool_env("SUBTITLE_UPPERCASE", True)
SUBTITLE_BOLD = _bool_env("SUBTITLE_BOLD", True)


def get_subtitle_style() -> dict:
    """Return the current subtitle style as a dict (used by the subtitles module)."""
    return {
        "font": SUBTITLE_FONT,
        "font_size_ratio": SUBTITLE_FONT_SIZE_RATIO,
        "primary_color": SUBTITLE_PRIMARY_COLOR,
        "highlight_color": SUBTITLE_HIGHLIGHT_COLOR,
        "outline_color": SUBTITLE_OUTLINE_COLOR,
        "outline_width": SUBTITLE_OUTLINE_WIDTH,
        "margin_v_ratio": SUBTITLE_MARGIN_V_RATIO,
        "words_per_chunk": SUBTITLE_WORDS_PER_CHUNK,
        "max_chunk_seconds": SUBTITLE_MAX_CHUNK_SECONDS,
        "uppercase": SUBTITLE_UPPERCASE,
        "bold": SUBTITLE_BOLD,
    }


def require_api_key() -> str:
    if not MUAPI_API_KEY:
        raise RuntimeError(
            "MUAPI_API_KEY is not set. Add it to your .env file or export it as an env var."
        )
    return MUAPI_API_KEY


def require_openai_key() -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Local mode needs an OpenAI key for highlight ranking. "
            "Add it to your .env or export it, or switch back to --mode api."
        )
    return OPENAI_API_KEY
