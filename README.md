# yt-short-generator

Turn any long-form YouTube video into ranked, vertical shorts — all offline on your own machine. A YouTube URL goes in; viral-worthy 9:16 clips with burned-in word-by-word karaoke captions come out.

Built because the existing SaaS options (Opus Clip, Klap, Vidyo.ai, SubMagic, …) charge monthly subscriptions, cap your minutes, and watermark free-tier output. This runs locally with `yt-dlp` + `faster-whisper` + `ffmpeg` + OpenCV, plus any OpenAI-compatible LLM endpoint you point it at.

> Status: local mode is the main pipeline and what I actually use day-to-day. A legacy API mode that delegates each step to MuAPI is still present in the code for reference, but it's not the path I ship against.

## What you get

- **YouTube URL in, vertical mp4s out.** Hand it any URL, get back N viral-ready 9:16 shorts saved to `output/`.
- **Web UI.** Optional FastAPI dashboard — submit jobs from the browser, watch live logs, preview the rendered shorts inline, download with one click.
- **Word-level karaoke captions.** 2-3 words pop in at a time, active word swept in yellow — the same CapCut/Opus Clip look. Fully configurable via env vars (font, size, colour, position, chunking).
- **Stabilised face-aware pan.** Two-pass reframing: sample face detections, median-filter the series, linear-interpolate the gaps, exponential-smooth the trajectory, lock the Y axis. No jittery, seasick crops.
- **LLM highlight ranking.** Videos are scored through a virality framework — hooks, emotional peaks, opinion bombs, revelations, conflict, quotables, story peaks, practical value. Long videos (>30 min) are auto-chunked with overlap so cross-boundary clips aren't lost.
- **Works with any OpenAI-compatible LLM.** OpenAI direct, Azure, self-hosted router, 9router — just set `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`.
- **CLI + Python lib.** Run from the shell or `from shorts_generator import generate_shorts` in your own code.
- **Structured JSON output.** `--output-json` dumps the full transcript + every candidate highlight + final clip paths for downstream automation.

## Requirements

- **Python 3.10+** (tested on 3.11 and 3.14)
- **ffmpeg** on your PATH, ideally with `libass` support (the official Windows/macOS/Linux builds all ship it)
- An **OpenAI-compatible LLM key** — OpenAI, a local router, whatever you prefer
- CPU is fine for `faster-whisper` at the `base` model; CUDA if you want it faster or want to run `large-v3`

## Install

```bash
git clone https://github.com/adri-cry/yt-short-generator.git
cd yt-short-generator

# venv (strongly recommended)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-local.txt
# Optional — only if you want the web UI:
pip install -r requirements-webui.txt
```

Copy `.env.example` to `.env` and fill in your keys:

```ini
# LLM highlight ranking — any OpenAI-compatible endpoint
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1   # or your router
OPENAI_MODEL=gpt-4o-mini                    # or claude, etc.

# Whisper (fully local)
LOCAL_WHISPER_MODEL=base        # tiny / base / small / medium / large-v3
LOCAL_WHISPER_DEVICE=auto       # auto / cpu / cuda
LOCAL_OUTPUT_DIR=output
```

Subtitle styling env vars live alongside these — see `.env.example` for the full list.

## Usage

```bash
# Simplest run — local mode, 3 shorts with burned-in karaoke captions
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" --mode local
```

Rendered clips land in `./output/short_01.mp4`, `short_02.mp4`, …

### More options

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" \
    --mode local \
    --num-clips 5 \
    --aspect-ratio 9:16 \
    --format 720 \
    --language id \
    --no-subtitles \
    --output-json result.json
```

### CLI flags

| Flag | Default | Notes |
|------|---------|-------|
| `--mode` | `api` | `local` runs the full offline pipeline (the one this repo is built around) |
| `--num-clips` | `3` | How many shorts to render |
| `--aspect-ratio` | `9:16` | Any ratio; `9:16` for TikTok/Reels/Shorts, `1:1` for square |
| `--format` | `720` | Source download resolution: `360` / `480` / `720` / `1080` |
| `--language` | auto | Force Whisper language code, e.g. `en`, `id` |
| `--subtitles` / `--no-subtitles` | on | Burn word-level karaoke captions (local mode only) |
| `--whisper-model` | `base` (env) | faster-whisper model: `tiny` / `base` / `small` / `medium` / `large-v3`. Bigger = much better accuracy, especially for non-English |
| `--initial-prompt` | — | Glossary / bias prompt for Whisper — names, brands, jargon (e.g. `"Luna Maya, Raffi Ahmad, Gojek"`). Fixes most "wrong word" subtitles |
| `--min-duration` | `45` | Minimum clip length in seconds. Shorter candidates are dropped |
| `--max-duration` | `90` | Maximum clip length in seconds. Longer candidates are trimmed |
| `--output-json` | — | Dump the full run result to a JSON file |

### Python API

```python
from shorts_generator import generate_shorts

result = generate_shorts(
    "https://www.youtube.com/watch?v=...",
    num_clips=5,
    aspect_ratio="9:16",
    mode="local",
)

for short in result["shorts"]:
    print(short["score"], short["title"], short["clip_url"])
```

### Re-rendering without re-downloading

`rerender.py` reuses a source mp4 already on disk (handy if YouTube rate-limits you, or you want to tweak the subtitle style without paying the download cost again). It also caches the Whisper transcript so only the first run pays for transcription.

```bash
python rerender.py --source output/source_VIDEO_ID.mp4 --num-clips 3
```

### Batch processing

```bash
# one URL per line in urls.txt
xargs -a urls.txt -I{} python main.py "{}" --mode local
```

### Web UI

There's a lightweight FastAPI dashboard if you'd rather click than type.

```bash
pip install -r requirements-webui.txt
python -m webui
# → http://127.0.0.1:8000
```

> **Windows tip:** Make sure you're running Python from the project `.venv`, not whatever interpreter `python` resolves to first. The easiest way is to use the launcher:
>
> ```powershell
> # PowerShell
> .\run-webui.ps1
> ```
> ```cmd
> :: cmd
> run-webui.bat
> ```
>
> Both pass args through, so `./run-webui.ps1 --host 0.0.0.0 --port 8080` works. If you try to start it with a Python that doesn't have the local-mode deps installed, the server will print a warning at startup pointing you at the right interpreter.

What you get:

- URL submit form with the same knobs as the CLI (mode, num clips, aspect ratio, language, subtitles toggle, min/max clip duration)
- Live log stream (SSE) so you can watch the pipeline run in real time
- Inline video previews of the rendered shorts, with one-click download
- Recent-jobs list that survives page refreshes

Flags:

```bash
python -m webui --host 0.0.0.0 --port 8000 --reload
```

Jobs run serialised in-process (the pipeline mutates `sys.stdout`, so a single worker keeps things sane). The server doesn't persist anything to disk — restart and the job list starts clean, but the rendered mp4s stay in `output/`.

## How it works

1. **Download** — `yt-dlp` pulls the source at the requested resolution.
2. **Transcribe** — `faster-whisper` produces a word-timestamped transcript (CPU or CUDA).
3. **Classify** — a tiny LLM call categorises the content (podcast, interview, tutorial, vlog, …) and density so the main prompt can be tuned per style.
4. **Chunk** — videos longer than 30 min are split into 20-min chunks with overlap so cross-boundary clips aren't missed.
5. **Rank** — the LLM scans the transcript through the virality framework and emits ranked candidates with scores 0-100, a hook sentence, and a one-line reason.
6. **Dedupe** — overlapping candidates are collapsed by score.
7. **Select** — the top `--num-clips` candidates survive.
8. **Crop** — a two-pass face-aware pan produces a smooth 9:16 reframe.
9. **Burn in captions** — a word-level karaoke ASS track is generated from the Whisper word timestamps and burned into the clip in the same ffmpeg pass that muxes the audio back.

## Output

Console at the end of a run:

```
========================================================================
Mode:          local
Source video:  output\source_VIDEO_ID.mp4
Highlights:    13 candidates -> kept top 3
========================================================================

#1  score=96  629.8s -> 723.2s
     title:  Semua Pekerjaan Kerah Putih Akan Hilang Sebelum 2030
     hook:   ...
     clip:   output\short_01.mp4
```

`--output-json result.json`:

```json
{
  "mode": "local",
  "source_video_url": "output/source_VIDEO_ID.mp4",
  "transcript": { "duration": 1800.0, "segments": [ ... ] },
  "highlights": [ { "...": "..." } ],
  "shorts": [
    {
      "title": "...",
      "start_time": 124.3,
      "end_time": 187.6,
      "score": 92,
      "hook_sentence": "...",
      "virality_reason": "...",
      "clip_url": "output/short_01.mp4"
    }
  ],
  "subtitles": true
}
```

## Configuration

### Highlight selection

Edit `shorts_generator/highlights.py`:

- `VIRALITY_CRITERIA` — the ranked list of signals the LLM optimises for
- `HIGHLIGHT_SYSTEM_PROMPT` — duration sweet spot, hook rules, JSON schema
- `CHUNK_SIZE_SECONDS` (1200) — chunk length for long videos
- `LONG_VIDEO_THRESHOLD` (1800) — videos longer than this get chunked
- `CHUNK_OVERLAP_SECONDS` (60) — overlap between chunks

### Subtitles

All styling is env-configurable. Defaults match the "viral shorts" look — bold uppercase, white with thick black outline, yellow karaoke sweep, bottom-centre.

- `SUBTITLES_ENABLED` — master toggle (default `true`)
- `SUBTITLE_FONT` — font family (fontconfig fallback if missing)
- `SUBTITLE_FONT_SIZE_RATIO` — font size as a fraction of video height (default `0.055`)
- `SUBTITLE_PRIMARY_COLOR` / `SUBTITLE_HIGHLIGHT_COLOR` / `SUBTITLE_OUTLINE_COLOR` — ASS colours `&HAABBGGRR`
- `SUBTITLE_OUTLINE_WIDTH` — outline thickness
- `SUBTITLE_MARGIN_V_RATIO` — distance from bottom edge as a fraction of height
- `SUBTITLE_WORDS_PER_CHUNK` / `SUBTITLE_MAX_CHUNK_SECONDS` — chunking behaviour
- `SUBTITLE_UPPERCASE`, `SUBTITLE_BOLD` — text styling

### Camera stabilisation

If the pan feels off, tune `_build_pan_trajectory` in `shorts_generator/local/clipper.py`:

- `alpha` (0.08) — lower = more static, higher = more responsive
- `detect_every` (`fps / 6`) — lower = faster reaction to subject changes, costs CPU
- median filter `window` (5) — bump to 7 if spurious detections slip through

## Project layout

```
yt-short-generator/
├── main.py                       CLI entry point
├── rerender.py                   re-render from a cached local source
├── requirements.txt              core deps
├── requirements-local.txt        local-mode deps (yt-dlp, faster-whisper, cv2, openai)
├── requirements-webui.txt        web UI deps (fastapi, uvicorn)
├── .env.example
├── webui/                        optional FastAPI dashboard
│   ├── app.py                    routes: submit, list, SSE logs, clip serving
│   ├── jobs.py                   background job runner + log capture
│   ├── __main__.py               `python -m webui`
│   └── static/                   single-page HTML/CSS/JS
└── shorts_generator/
    ├── config.py                 env / settings (OpenAI + Whisper + subtitles)
    ├── highlights.py             LLM virality ranking (pluggable backend)
    ├── subtitles.py              word-level karaoke ASS generator + ffmpeg burn-in
    ├── pipeline.py               mode dispatcher (api <-> local)
    ├── muapi.py                  legacy: MuAPI client (API mode only)
    ├── downloader.py             legacy: API mode YouTube download
    ├── transcriber.py            legacy: API mode Whisper
    ├── clipper.py                legacy: API mode autocrop
    └── local/                    local-mode pipeline (the one you want)
        ├── downloader.py         yt-dlp download
        ├── transcriber.py        faster-whisper with word-level timestamps
        ├── llm.py                OpenAI-compatible chat-completions client
        └── clipper.py            ffmpeg cut + OpenCV vertical pan + subtitle burn-in
```

## Troubleshooting

**Whisper produced no segments.** The video may have no detectable speech or be in a language the base model struggles with. Pass `--language <iso>` to skip auto-detection, or bump `LOCAL_WHISPER_MODEL` to `small` / `medium` / `large-v3`.

**Subtitle text is wrong — transcribes words the speaker never said.** This is a Whisper accuracy problem, not a subtitle-rendering bug. Fixes, in order of impact:

1. **Use a bigger Whisper model.** `base` (the default) is *noticeably* weaker on non-English audio. Set `--whisper-model small` or `medium`. For Bahasa Indonesia / Japanese / Korean / Chinese or mixed-language podcasts, `medium` is the realistic minimum for clean captions.
2. **Lock the language.** If auto-detect keeps flipping mid-video, pass `--language id` (or whichever ISO code). Auto-detect uses the first ~30s only, which gets it wrong on intros.
3. **Seed the glossary.** Proper nouns, brand names, and technical terms are where small models hallucinate most. Pass them as `--initial-prompt`:
   ```bash
   python main.py "..." --mode local \
       --whisper-model medium \
       --language id \
       --initial-prompt "Luna Maya, Raffi Ahmad, Gojek, Tokopedia, Shopee"
   ```
4. **Higher source audio quality.** `--format 720` already pulls a decent track; if the upstream mic is bad, no Whisper model will save you.

Tradeoff: jumping from `base` → `medium` costs ~4-6× transcription time on CPU. `small` is the sweet spot for most use cases on laptops.

**`Sign in to confirm you're not a bot` on download.** YouTube rate-limits `yt-dlp` after enough hits from the same IP. Either pass cookies (see yt-dlp docs) or use `rerender.py` against a source you already have locally.

**`'charmap' codec can't encode character` on Windows.** The default Windows console is cp1252. The CLI forces UTF-8 itself now; if you still see this when scripting around the library, set `PYTHONIOENCODING=utf-8`.

**Clips look jittery.** Lower `alpha` in `_build_pan_trajectory` (e.g. `0.05`) or increase the median filter `window`.

**Font missing in the burned-in captions.** libass falls back via fontconfig, but override with `SUBTITLE_FONT` to a family you definitely have installed (e.g. `Arial`, `DejaVu Sans`).

## Credits

This started as a fork of [SamurAIGPT/AI-Youtube-Shorts-Generator](https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator) and has since been rewritten to focus on a self-hosted local pipeline, word-level karaoke captions, and a stabilised face-aware pan.

## License

MIT.
