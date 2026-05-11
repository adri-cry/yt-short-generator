"""Local transcription via faster-whisper.

Reads a local media file and returns the same shape the highlight generator
expects: {duration, segments[start, end, text, words]}.

The subtitle pipeline needs accurate word-level timestamps and transcripts —
smaller models (`tiny`, `base`) frequently mis-hear non-English speech and
hallucinate words. For Bahasa Indonesia, Korean, Japanese, mixed-language or
noisy audio, use `small` or `medium`; large-v3 is the ceiling. Pass a
glossary of proper nouns / technical terms as `initial_prompt` to steer the
decoder toward the right spellings.
"""
from typing import Dict, Optional

from ..config import LOCAL_WHISPER_DEVICE, LOCAL_WHISPER_MODEL


def _resolve_device() -> str:
    if LOCAL_WHISPER_DEVICE != "auto":
        return LOCAL_WHISPER_DEVICE
    try:
        import torch  # type: ignore
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def transcribe_local(
    media_path: str,
    language: Optional[str] = None,
    model_name: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    beam_size: int = 5,
) -> Dict:
    """Run faster-whisper on a local file path.

    Args:
        media_path: local audio/video file.
        language: ISO-639-1 code (e.g. "en", "id"). Forces the recognition
            language; auto-detect otherwise.
        model_name: faster-whisper model id. Defaults to `LOCAL_WHISPER_MODEL`
            from config. `small` / `medium` dramatically improve non-English
            accuracy over `base`.
        initial_prompt: glossary-style hint for the decoder — names, jargon,
            spellings to bias toward.
        beam_size: decoding beam. Larger is marginally better, slower.
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    model_id = (model_name or LOCAL_WHISPER_MODEL).strip()
    device = _resolve_device()
    compute_type = "float16" if device == "cuda" else "int8"
    print(
        f"[transcribe/local] faster-whisper model={model_id} device={device} "
        f"lang={language or 'auto'} beam={beam_size}"
        + (f" prompt='{initial_prompt[:80]}...'" if initial_prompt else ""),
        flush=True,
    )

    model = WhisperModel(model_id, device=device, compute_type=compute_type)

    # temperature=0 (greedy) + VAD + no prev-text = most deterministic and
    # lowest-hallucination decode, at the cost of very slightly missing some
    # disfluency. That's the right trade-off for burn-in subtitles.
    segments_iter, info = model.transcribe(
        media_path,
        language=language,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
        temperature=0.0,
        word_timestamps=True,
        initial_prompt=initial_prompt or None,
    )

    segments = []
    for s in segments_iter:
        words = []
        for w in (getattr(s, "words", None) or []):
            w_text = (getattr(w, "word", None) or "").strip()
            if not w_text:
                continue
            w_start = getattr(w, "start", None)
            w_end = getattr(w, "end", None)
            if w_start is None or w_end is None:
                continue
            words.append({
                "start": float(w_start),
                "end": float(w_end),
                "word": w_text,
            })
        segments.append({
            "start": float(s.start),
            "end": float(s.end),
            "text": (s.text or "").strip(),
            "words": words,
        })

    duration = float(getattr(info, "duration", 0.0)) or (segments[-1]["end"] if segments else 0.0)
    detected = getattr(info, "language", None)
    lang_prob = getattr(info, "language_probability", None)
    lang_note = (
        f" detected={detected} (p={lang_prob:.2f})"
        if detected and lang_prob is not None
        else ""
    )
    print(
        f"[transcribe/local] {len(segments)} segments, {duration:.0f}s of audio{lang_note}",
        flush=True,
    )
    return {"duration": duration, "segments": segments}
