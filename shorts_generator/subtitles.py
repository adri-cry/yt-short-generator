"""Word-level karaoke subtitles for local-mode shorts.

Given word-timestamped Whisper segments, this module builds an ASS subtitle
file that pops 2-3 words at a time with the active word highlighted (karaoke
sweep), then burns it into a video via ffmpeg/libass.

Designed to be called per highlight clip: we extract the words that fall
inside the clip's [start, end] window, rebase their timestamps to zero, and
render.
"""
import os
import subprocess
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# Word collection / chunking                                                  #
# --------------------------------------------------------------------------- #


def collect_words_in_range(
    segments: List[Dict],
    clip_start: float,
    clip_end: float,
) -> List[Dict]:
    """Return word dicts whose timing overlaps [clip_start, clip_end], rebased
    so the clip starts at t=0. Drops segments without word-level data."""
    out: List[Dict] = []
    for seg in segments or []:
        for w in seg.get("words") or []:
            try:
                ws = float(w["start"])
                we = float(w["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if we <= clip_start or ws >= clip_end:
                continue
            ws = max(ws, clip_start)
            we = min(we, clip_end)
            if we <= ws:
                continue
            text = (w.get("word") or "").strip()
            if not text:
                continue
            out.append({
                "start": ws - clip_start,
                "end": we - clip_start,
                "word": text,
            })
    out.sort(key=lambda x: x["start"])
    return out


def _chunk_words(
    words: List[Dict],
    words_per_chunk: int,
    max_chunk_seconds: float,
) -> List[List[Dict]]:
    """Group words into karaoke lines of up to N words and max duration."""
    chunks: List[List[Dict]] = []
    cur: List[Dict] = []
    for w in words:
        if not cur:
            cur = [w]
            continue
        chunk_start = cur[0]["start"]
        if (
            len(cur) >= words_per_chunk
            or (w["end"] - chunk_start) > max_chunk_seconds
        ):
            chunks.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------- #
# ASS generation                                                              #
# --------------------------------------------------------------------------- #


def _format_ass_time(seconds: float) -> str:
    """ASS time format: H:MM:SS.cs (centiseconds)."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape_ass_text(text: str) -> str:
    """Neutralise characters that ASS treats specially inside dialogue."""
    return (
        text.replace("\\", "\\\\")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def build_karaoke_ass(
    words: List[Dict],
    video_w: int,
    video_h: int,
    style: Dict,
) -> Optional[str]:
    """Render a full ASS file (header + events) for the given word list.

    Returns None if `words` is empty — caller should skip burn-in in that case.
    """
    if not words:
        return None

    font = style.get("font", "Arial Black")
    font_size = max(14, int(video_h * float(style.get("font_size_ratio", 0.055))))
    primary = style.get("primary_color", "&H00FFFFFF")
    secondary = style.get("highlight_color", "&H0000FFFF")
    outline = style.get("outline_color", "&H00000000")
    outline_w = float(style.get("outline_width", 3))
    margin_v = max(10, int(video_h * float(style.get("margin_v_ratio", 0.12))))
    bold = "-1" if style.get("bold", True) else "0"
    uppercase = bool(style.get("uppercase", True))
    words_per_chunk = max(1, int(style.get("words_per_chunk", 3)))
    max_chunk_seconds = float(style.get("max_chunk_seconds", 1.4))

    # ASS style line. MarginL/R 40 gives some horizontal breathing room.
    style_line = (
        f"Style: Default,{font},{font_size},{primary},{secondary},"
        f"{outline},&H64000000,{bold},0,0,0,100,100,0,0,1,{outline_w},0,2,40,40,{margin_v},1"
    )

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_w}",
        f"PlayResY: {video_h}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style_line,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: List[str] = []
    for chunk in _chunk_words(words, words_per_chunk, max_chunk_seconds):
        start = chunk[0]["start"]
        end = chunk[-1]["end"]
        if end <= start:
            continue

        # Build karaoke text. \kf<centiseconds> makes the word "sweep" filling
        # in the primary colour while inactive words stay in secondary.
        parts: List[str] = []
        for w in chunk:
            dur_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
            word_text = w["word"]
            if uppercase:
                word_text = word_text.upper()
            parts.append(f"{{\\kf{dur_cs}}}{_escape_ass_text(word_text)}")
        text = " ".join(parts)

        events.append(
            f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},"
            f"Default,,0,0,0,,{text}"
        )

    if not events:
        return None

    return "\n".join(header + events) + "\n"


# --------------------------------------------------------------------------- #
# ffmpeg burn-in                                                              #
# --------------------------------------------------------------------------- #


def _escape_ffmpeg_filter_path(path: str) -> str:
    """libass/ffmpeg parses the filter string, so Windows drive colons and
    backslashes need escaping. Forward slashes are accepted everywhere."""
    p = path.replace("\\", "/")
    # Escape the drive-letter colon: C:/foo -> C\:/foo
    if len(p) >= 2 and p[1] == ":":
        p = p[0] + r"\:" + p[2:]
    # Single quotes inside the filter string must be escaped.
    p = p.replace("'", r"\'")
    return p


def burn_subtitles_to_video(
    in_silent_video: str,
    audio_source: str,
    ass_path: str,
    out_path: str,
) -> str:
    """Single ffmpeg pass: apply ASS burn-in on the silent reframed video and
    mux audio from the cut clip back in. Returns `out_path`."""
    escaped = _escape_ffmpeg_filter_path(ass_path)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", in_silent_video,
        "-i", audio_source,
        "-filter_complex", f"[0:v]ass='{escaped}'[v]",
        "-map", "[v]",
        "-map", "1:a:0?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def write_ass_file(ass_content: str, out_path: str) -> str:
    """Write ASS content as UTF-8 (libass expects it)."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(ass_content)
    return out_path
