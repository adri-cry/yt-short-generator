"""Local clipping: ffmpeg subclip + OpenCV face-aware vertical crop.

Three stages per highlight:
  1. Cut the source video to [start, end] with ffmpeg (re-encoded, audio kept).
  2. Reframe the cut to the target aspect ratio. For 9:16 we slide a vertical
     window horizontally across the frame to keep faces centred (Haar
     cascade — same approach as the original repo, no external models).
  3. Mux audio back in, optionally burning in word-level karaoke subtitles
     generated from the Whisper transcript.
"""
import os
import subprocess
from typing import Dict, List, Optional

from ..config import LOCAL_OUTPUT_DIR, get_subtitle_style
from ..subtitles import (
    build_karaoke_ass,
    burn_subtitles_to_video,
    collect_words_in_range,
    write_ass_file,
)


def _ratio(aspect_ratio: str) -> float:
    """Parse '9:16' → 9/16, '1:1' → 1.0."""
    try:
        w, h = aspect_ratio.split(":")
        return float(w) / float(h)
    except (ValueError, ZeroDivisionError):
        return 9.0 / 16.0


def _cut_subclip(source_path: str, start: float, end: float, out_path: str) -> str:
    """ffmpeg -ss start -to end → re-encoded mp4 with audio."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", source_path,
        "-ss", f"{start:.3f}",
        "-to", f"{end:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def _mux_audio_only(silent_path: str, audio_source: str, out_path: str) -> str:
    """Copy the silent reframed video and mux audio back on top. No re-encode."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", silent_path,
        "-i", audio_source,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-map", "0:v:0", "-map", "1:a:0?",
        "-shortest",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def _build_pan_trajectory(
    in_path: str,
    src_w: int,
    src_h: int,
    fps: float,
    crop_w: int,
    crop_h: int,
) -> List[int]:
    """Pass 1: scan the video, sample face detections, build a heavily smoothed
    horizontal-pan trajectory. Returns one cx value per frame.

    Strategy:
      * Detect only every ~1/6 second (fast + less noise).
      * Keep detections in the plausible face-size range relative to frame.
      * Median-filter the detection series to drop single-frame outliers.
      * Forward/backward fill missing samples.
      * Exponential smoothing (alpha≈0.08) for silky motion.
      * Y is locked to the vertical centre — for 16:9 → 9:16 cropping Y never
        needs to move, and keeping it fixed avoids bobbing.
    """
    import cv2  # type: ignore

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_cascade = cv2.CascadeClassifier(cascade_path)

    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open {in_path}")

    # Detection sampling interval — ~6 samples per second regardless of fps.
    detect_every = max(1, int(round(fps / 6.0)))
    default_cx = src_w // 2

    # Valid face size range (relative to frame) — kills tiny/huge false positives.
    min_face = max(60, src_h // 10)
    max_face = int(src_h * 0.9)

    sampled_frames: List[int] = []
    sampled_cx: List[int] = []
    frame_idx = 0
    total_frames = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        total_frames += 1
        if frame_idx % detect_every == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=6,
                minSize=(min_face, min_face),
                maxSize=(max_face, max_face),
            )
            if len(faces) > 0:
                # Pick the largest face — usually the speaker.
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                cx = x + w // 2
                sampled_frames.append(frame_idx)
                sampled_cx.append(cx)
        frame_idx += 1
    cap.release()

    if total_frames == 0:
        return []

    # No detections at all → stay centred.
    if not sampled_cx:
        return [default_cx] * total_frames

    # Median filter on the sparse series (window=5) to drop spurious jumps.
    def _median_filter(vals: List[int], window: int = 5) -> List[int]:
        out = []
        half = window // 2
        for i in range(len(vals)):
            lo = max(0, i - half)
            hi = min(len(vals), i + half + 1)
            chunk = sorted(vals[lo:hi])
            out.append(chunk[len(chunk) // 2])
        return out

    filtered_cx = _median_filter(sampled_cx, window=5)

    # Dense per-frame series: forward-fill from last known sample.
    dense = [default_cx] * total_frames
    # Prefix (before first sample) = first sample value.
    first_f = sampled_frames[0]
    first_v = filtered_cx[0]
    for i in range(min(first_f, total_frames)):
        dense[i] = first_v
    # Between/after samples: linear interpolation for smoother motion than hold.
    for s_idx in range(len(sampled_frames)):
        f0 = sampled_frames[s_idx]
        v0 = filtered_cx[s_idx]
        f1 = sampled_frames[s_idx + 1] if s_idx + 1 < len(sampled_frames) else total_frames
        v1 = filtered_cx[s_idx + 1] if s_idx + 1 < len(sampled_frames) else v0
        span = max(1, f1 - f0)
        for i in range(f0, min(f1, total_frames)):
            t = (i - f0) / span
            dense[i] = int(round(v0 + (v1 - v0) * t))

    # Exponential smoothing — small alpha = very smooth, slight lag but no jitter.
    alpha = 0.08
    smoothed: List[int] = [0] * total_frames
    smoothed[0] = dense[0]
    for i in range(1, total_frames):
        smoothed[i] = int(round(alpha * dense[i] + (1 - alpha) * smoothed[i - 1]))

    # Clamp so the crop window stays inside the frame.
    half_w = crop_w // 2
    lo = half_w
    hi = src_w - (crop_w - half_w)
    if lo > hi:
        lo = hi = src_w // 2
    smoothed = [max(lo, min(hi, cx)) for cx in smoothed]
    return smoothed


def _reframe_vertical(
    in_path: str,
    out_path: str,
    aspect_ratio: str,
    subtitle_words: Optional[List[Dict]] = None,
    subtitle_style: Optional[Dict] = None,
) -> str:
    """Crop the cut clip to the target aspect ratio with a stabilised,
    face-aware horizontal pan.

    The reframe is done in two passes:
      1. Sample face detections across the whole clip and build a smoothed
         per-frame X trajectory (median filter + linear interp + EMA).
      2. Re-read the clip and write the cropped frames using that trajectory.

    If `subtitle_words` is provided the final mux pass also burns a word-level
    karaoke ASS track onto the video; otherwise the video stream is copied to
    avoid an unnecessary re-encode.
    """
    try:
        import cv2  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "opencv-python is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    target_ratio = _ratio(aspect_ratio)
    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open {in_path}")

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()

    # Compute the largest crop that fits inside the frame at the target ratio.
    if target_ratio < src_w / src_h:
        crop_h = src_h
        crop_w = int(crop_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(crop_w / target_ratio)
    crop_w = max(2, crop_w - (crop_w % 2))
    crop_h = max(2, crop_h - (crop_h % 2))

    print(
        f"[clip/local] reframe {src_w}x{src_h} -> {crop_w}x{crop_h} @ {fps:.1f}fps",
        flush=True,
    )

    # Pass 1: smoothed pan trajectory.
    pan_cx = _build_pan_trajectory(in_path, src_w, src_h, fps, crop_w, crop_h)
    cy = src_h // 2
    half_h = crop_h // 2
    y0 = max(0, min(src_h - crop_h, cy - half_h))

    # Pass 2: write frames with the smoothed crop.
    cap = cv2.VideoCapture(in_path)
    silent_path = out_path + ".silent.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(silent_path, fourcc, fps, (crop_w, crop_h))

    frame_idx = 0
    fallback_cx = src_w // 2
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        cx = pan_cx[frame_idx] if frame_idx < len(pan_cx) else fallback_cx
        x0 = max(0, min(src_w - crop_w, cx - crop_w // 2))
        cropped = frame[y0:y0 + crop_h, x0:x0 + crop_w]
        writer.write(cropped)
        frame_idx += 1

    cap.release()
    writer.release()

    ass_path: Optional[str] = None
    try:
        ass_content = None
        if subtitle_words:
            ass_content = build_karaoke_ass(
                subtitle_words,
                video_w=crop_w,
                video_h=crop_h,
                style=subtitle_style or get_subtitle_style(),
            )

        if ass_content:
            ass_path = out_path + ".ass"
            write_ass_file(ass_content, ass_path)
            burn_subtitles_to_video(silent_path, in_path, ass_path, out_path)
        else:
            _mux_audio_only(silent_path, in_path, out_path)
    finally:
        if os.path.exists(silent_path):
            os.remove(silent_path)
        if ass_path and os.path.exists(ass_path):
            os.remove(ass_path)

    return out_path


def crop_clip_local(
    source_path: str,
    start_time: float,
    end_time: float,
    aspect_ratio: str,
    out_path: str,
    subtitle_words: Optional[List[Dict]] = None,
    subtitle_style: Optional[Dict] = None,
) -> str:
    """Cut + reframe one highlight, returning the local mp4 path."""
    cut_path = out_path + ".cut.mp4"
    try:
        _cut_subclip(source_path, start_time, end_time, cut_path)
        _reframe_vertical(
            cut_path,
            out_path,
            aspect_ratio,
            subtitle_words=subtitle_words,
            subtitle_style=subtitle_style,
        )
    finally:
        if os.path.exists(cut_path):
            os.remove(cut_path)
    return out_path


def crop_highlights_local(
    source_path: str,
    highlights: List[Dict],
    aspect_ratio: str = "9:16",
    out_dir: Optional[str] = None,
    segments: Optional[List[Dict]] = None,
    subtitles_enabled: bool = True,
    subtitle_style: Optional[Dict] = None,
) -> List[Dict]:
    """Render every highlight to an mp4.

    When `subtitles_enabled` is True and `segments` contain word-level
    timestamps, a word-by-word karaoke subtitle track is burned into each clip.
    """
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    style = subtitle_style or (get_subtitle_style() if subtitles_enabled else None)

    results: List[Dict] = []
    for i, h in enumerate(highlights, 1):
        out_path = os.path.join(out_dir, f"short_{i:02d}.mp4")
        print(f"[clip/local] {i}/{len(highlights)}: {h.get('title', '(untitled)')}", flush=True)

        words: Optional[List[Dict]] = None
        if subtitles_enabled and segments:
            words = collect_words_in_range(
                segments,
                float(h["start_time"]),
                float(h["end_time"]),
            )
            if not words:
                print(
                    f"[clip/local] {i}: no word-level timestamps in range — skipping subtitles",
                    flush=True,
                )

        try:
            crop_clip_local(
                source_path,
                float(h["start_time"]),
                float(h["end_time"]),
                aspect_ratio,
                out_path,
                subtitle_words=words,
                subtitle_style=style,
            )
            results.append({**h, "clip_url": out_path})
        except Exception as e:
            print(f"[clip/local] {i} failed: {e}", flush=True)
            results.append({**h, "clip_url": None, "error": str(e)})
    return results
