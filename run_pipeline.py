"""
run_pipeline.py
Story Shorts Pipeline: generate story -> narration voice -> WhisperX word timestamps ->
sentence timing alignment -> storyboard / visual plan -> Pexels/Pixabay assets -> Remotion staging/render.

Story Input/Output Contract:
    Input:
        - genre (required, str): One of "scary", "mystery", "moral", "motivational".
        - premise (optional, str | None): Story prompt or premise.
        - model_key (optional, str): LLM model key.
    Output:
        - JSON-compatible dict exactly containing:
            {
                "title": str,
                "genre": str,
                "sentences": list[str]
            }
        - "sentences" contains the authoritative narration sentence-by-sentence in spoken order,
          with no visual directions, timestamps, sound effects, labels, or other metadata.
        - Sentence count and sentence word count are flexible and must not be artificially
          enforced, because these exact sentences are passed unchanged to TTS and later
          matched against WhisperX word timestamps.

The pipeline prepares all assets and props in the public/ directory.
Use --render flag to automatically render with Remotion after staging.
Without --render, use: npx remotion render ShortsComposition [output.mp4] --props=remotion_props.json

Requirements (set in .env file or export):
    GEMINI_API_KEY="AIza..."           # or GROQ_API_KEY / NVIDIA_API_KEY
    PEXELS_API_KEY="your-key"          # optional — get at pexels.com/api
    PIXABAY_API_KEY="your-key"         # optional — get at pixabay.com/api

Usage:
    python run_pipeline.py --genre scary --count 1
    python run_pipeline.py --genre mystery --premise "An antique mirror shows the room 10 seconds in the future"
    python run_pipeline.py --genre moral --count 2 --no-video
    python run_pipeline.py --genre scary --render --count 1

Flags:
    --count       Number of story videos to produce (default: 1, max: 10)
    --genre       Story genre: scary, mystery, moral, motivational (default: scary)
    --premise     Optional premise or prompt for the story
    --outdir      Output directory (default: output)
    --no-video    Skip asset download & staging (scripts + voice only)
    --quick       Minimal output — 1 script for quick review
    --model       LLM model key (default: gemini-31-flash-lite). See `python llm_client.py --list`
    --render      Render video with Remotion after staging assets (default: stage only)
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Auto-load .env file (so you don't need to 'export' every time)
# ---------------------------------------------------------------------------
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _val = _line.split("=", 1)
            _key, _val = _key.strip(), _val.strip().strip('"').strip("'")
            if _key and not os.environ.get(_key):
                os.environ[_key] = _val

# Import llm_client early so model keys can be validated in CLI
import llm_client

from story_generator import (
    generate_story,
    validate_story_contract,
    ALLOWED_GENRES,
)
from voice_generator import generate_narration
from storyboard_generator import generate_storyboard
from asset_collector import collect_assets, collect_assets_for_plan, collect_assets_for_plan_with_fallback
from remotion_assembler import assemble_video_remotion


def slugify(text: str, max_len: int = 50) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return slug[:max_len] or "untitle"


def _get_daily_outdir(base_outdir: Path) -> Path:
    """Get the daily output directory (e.g., output/09_08_short_vids)."""
    today = date.today()
    daily_dir_name = f"{today.day:02d}_{today.month:02d}_short_vids"
    daily_dir = base_outdir / daily_dir_name
    daily_dir.mkdir(parents=True, exist_ok=True)
    return daily_dir


# ---------------------------------------------------------------------------
# Daily dedupe log (output/09_08_short_vids/_generated_log.json)
# ---------------------------------------------------------------------------

def _get_dedupe_log_path(base_outdir: Path) -> Path:
    """Get the daily dedupe log path inside the daily output directory."""
    daily_dir = _get_daily_outdir(base_outdir)
    return daily_dir / "_generated_log.json"


def _load_dedupe_log(base_outdir: Path) -> list[dict]:
    """Load the daily dedupe log, return empty list on any error."""
    log_path = _get_dedupe_log_path(base_outdir)
    try:
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8")
            if content.strip():
                return json.loads(content)
    except Exception:
        pass
    return []


def _save_dedupe_log(base_outdir: Path, entries: list[dict]):
    """Save the dedupe log, trimming to last ~30 days."""
    log_path = _get_dedupe_log_path(base_outdir)
    try:
        today = date.today().isoformat()
        cutoff = date.fromisoformat(today)
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=30)
        filtered = [
            e for e in entries
            if e.get("date") and date.fromisoformat(e["date"]) >= cutoff
        ]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(filtered, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  [warn] Could not save dedupe log: {e}")


def _fingerprint(story: dict, premise: str = None) -> str:
    """Generate a content fingerprint from normalized story content.

    Normalizes genre, ordered sentences (each lowercased and whitespace-collapsed),
    and premise (when provided) into a stable JSON blob, then returns a SHA-256
    hash. The title is deliberately excluded so that the same story with a
    different title is still detected as a duplicate.
    """
    normalized = {
        "genre": story.get("genre", "").lower(),
        "sentences": [" ".join(s.lower().split()) for s in story.get("sentences", [])],
    }
    if premise is not None and premise.strip():
        normalized["premise"] = " ".join(premise.lower().split())
    content = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Persistent global deduplicate store (survives across dates and runs)
# ---------------------------------------------------------------------------

_GLOBAL_DEDUP_PATH = Path(__file__).parent / "output" / "_global_dedup.json"


def _load_global_dedup() -> set:
    """Load the global fingerprint set, returning empty set on any error."""
    try:
        if _GLOBAL_DEDUP_PATH.exists():
            content = _GLOBAL_DEDUP_PATH.read_text(encoding="utf-8")
            if content.strip():
                data = json.loads(content)
                if isinstance(data, list):
                    return set(data)
                if isinstance(data, dict):
                    return set(data.get("fingerprints", []))
    except Exception:
        pass
    return set()


def _save_global_dedup(fingerprints: set):
    """Persist the global fingerprint set."""
    try:
        _GLOBAL_DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        _GLOBAL_DEDUP_PATH.write_text(
            json.dumps(sorted(fingerprints), indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"  [warn] Could not save global dedup log: {e}")


def _is_duplicate(story: dict, premise: str = None) -> bool:
    """Return True if a story with identical content was already generated."""
    return _fingerprint(story, premise) in _load_global_dedup()


def _add_global_fingerprint(story: dict, premise: str = None):
    """Record a story's fingerprint in the persistent global dedup store."""
    fingerprints = _load_global_dedup()
    fingerprints.add(_fingerprint(story, premise))
    _save_global_dedup(fingerprints)


def _log_generated_story(base_outdir: Path, story: dict, model_key: str, project_slug: str):
    """Append a successful generation to the daily dedupe log."""
    log = _load_dedupe_log(base_outdir)
    today = date.today().isoformat()
    log.append({
        "date": today,
        "key": _fingerprint(story),
        "title": story.get("title", "")[:120],
        "genre": story.get("genre", ""),
        "model": model_key,
        "project": project_slug,
    })
    _save_dedupe_log(base_outdir, log)


def _audio_duration(path: Path) -> float:
    """Measure real narration duration via ffprobe (~robust forced-align
    proxy: we distribute this real duration across sentences by word weight)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def _sentence_timings_from_audio(script: str, total_duration: float) -> list[tuple]:
    """Distribute the REAL narration duration across sentences by word count.

    Returns a list of (start, end) floats, one per sentence. Word-rate weighting
    is a robust proxy for forced alignment — accurate enough that clips line up
    with the spoken words.
    """
    sentences = re.split(r'(?<=[.!?])\s+', script.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences or total_duration <= 0:
        return []
    word_counts = [len(s.split()) for s in sentences]
    total_words = sum(word_counts)
    if total_words <= 0:
        return [(0.0, total_duration)]
    timings, cur = [], 0.0
    for wc in word_counts:
        dur = total_duration * (wc / total_words)
        timings.append((cur, cur + dur))
        cur += dur
    if timings:
        s, _ = timings[-1]
        timings[-1] = (s, total_duration)
    return timings


def _sentence_timings_from_word_timestamps(words: list[dict],
                                            sentences: list[str],
                                            fallback_total_dur: float = None) -> list[tuple]:
    """Derive per-sentence (start, end) timings from WhisperX word-level timestamps.

    Two-phase strategy:

    Phase 1 — Greedy word-by-word alignment:
      Walks the WX word list and matches each word to the expected sentence word
      (case-insensitive, punctuation stripped).  Handles:
        - exact word match
        - prefix match when WhisperX merges adjacent tokens (e.g. "city morgue"
          -> "citymorgue")
        - future-sentence-word match when WhisperX drops an intermediate word
          (the WX token is matched against a later word in the same sentence,
          skipping the dropped ones)

    Phase 2 — Time-window refinement (robust fallback):
      If Phase 1 fails (WhisperX dropped too many words, merged beyond recovery,
      or produced a transcription variant), fall back to placing each sentence
      inside a time window derived from the word-count proxy, then snapping the
      window boundaries to actual WhisperX word timestamps that fall within.
      This never *invents* a timing — the start is always the earliest real
      WX ``start`` and the end is always the latest real WX ``end`` found in
      that window (or the proxy estimate when zero WX words fall in the window).

    Args:
        words: WhisperX output — list of {"word": str, "start": float, "end": float}.
        sentences: The script's sentences (already split, in order).
        fallback_total_dur: If provided, used to seed the proxy's total
            duration (typically the real narration duration from ffprobe).

    Returns:
        list of (start, end) floats, one per sentence.
    """
    if not sentences or not words:
        if fallback_total_dur:
            return _sentence_timings_from_audio(__sentences_joined(sentences), fallback_total_dur)
        return []

    # Normalize: strip punctuation/case for matching.
    def _clean(w: str) -> str:
        return re.sub(r"[^\w']", "", w.lower()).strip("'")

    cleaned_words = [_clean(w.get("word", "")) for w in words]
    cleaned_sents = [[_clean(w) for w in s.split()] for s in sentences]

    # ── Phase 1: greedy word-by-word alignment ──────────────────────────
    timings = []
    word_idx = 0
    success = True

    for sent_words in cleaned_sents:
        sent_words = [w for w in sent_words if w]
        if not sent_words:
            timings.append((0.0, 0.0))
            success = False
            break

        start_time = None
        end_time = None
        matched = 0

        while word_idx < len(cleaned_words) and matched < len(sent_words):
            wx_word = cleaned_words[word_idx]
            snt_word = sent_words[matched]

            if wx_word == snt_word:
                if start_time is None:
                    start_time = words[word_idx].get("start", 0.0)
                end_time = words[word_idx].get("end", start_time)
                matched += 1
                word_idx += 1
            elif wx_word.startswith(snt_word):
                # WhisperX sometimes merges adjacent words into one token
                # (e.g. "city morgue" -> "citymort").  Try to consume as many
                # sentence words as fit within this single WhisperX word.
                if start_time is None:
                    start_time = words[word_idx].get("start", 0.0)
                end_time = words[word_idx].get("end", start_time)
                remainder = wx_word
                while matched < len(sent_words) and remainder.startswith(sent_words[matched]):
                    remainder = remainder[len(sent_words[matched]):]
                    matched += 1
                word_idx += 1
            else:
                # No match with the current expected word.  Check if this WX
                # token matches a *future* sentence word — WhisperX may have
                # dropped the current word entirely.  If so, skip the dropped
                # sentence words and advance to the matched future word.
                future_matched = False
                for fi in range(matched + 1, len(sent_words)):
                    if wx_word == sent_words[fi] or wx_word.startswith(sent_words[fi]):
                        matched = fi + 1
                        future_matched = True
                        break
                # If no match at all, skip this WX word (noise / OOV token)
                word_idx += 1

        # Accept partial matches: as long as we found at least one real
        # WX timestamp for this sentence, we can time it.
        if matched > 0 and start_time is not None and end_time is not None:
            timings.append((float(start_time), float(end_time)))
        else:
            success = False
            break

    if success and len(timings) == len(sentences):
        timings[-1] = (timings[-1][0], words[-1].get("end", timings[-1][1]))
        return timings

    # ── Phase 2: time-window refinement ────────────────────────────────
    # WhisperX dropped/renamed enough words that Phase 1 couldn't align
    # every sentence.  Fall back to word-count proxy windows, then snap
    # each window's boundaries to the nearest actual WX word timestamps.
    # This still uses *real* WhisperX timestamps rather than inventing timings.
    return _refine_timings_with_word_timestamps(words, sentences, fallback_total_dur)


def _refine_timings_with_word_timestamps(
    words: list[dict],
    sentences: list[str],
    fallback_total_dur: float = None,
) -> list[tuple]:
    """Produce one (start, end) per sentence by snapping word-count-proxy
    time windows to actual WhisperX word timestamps.

    For each sentence, the proxy gives an approximate [start, end] window.
    We then scan the WX word list and pick:
      - start = earliest WX word ``start`` that falls inside the window
      - end   = latest  WX word ``end``  that falls inside the window
    If no WX word falls in the window, the proxy estimate is used for that
    sentence (never an invented value — the proxy is based on real audio
    duration).  Sentence start/end therefore always trace back to a real
    WX timestamp when any WX word is available.
    """
    def _clean(w: str) -> str:
        return re.sub(r"[^\w']", "", w.lower()).strip("'")

    total_dur = fallback_total_dur
    if total_dur is None and words:
        total_dur = words[-1].get("end", 0.0)
    if not total_dur or total_dur <= 0:
        total_dur = max(20, len(__sentences_joined(sentences).split()) / 3.2)

    approx = _sentence_timings_from_audio(__sentences_joined(sentences), total_dur)
    if not approx or len(approx) != len(sentences):
        return approx

    # Build parallel arrays for fast lookup.
    word_starts = [float(w.get("start", 0.0)) for w in words]
    word_ends   = [float(w.get("end",   0.0)) for w in words]
    word_nonempty = [_clean(w.get("word", "")) for w in words]  # for filtering noise

    refined = []
    for si, (sent_start, sent_end) in enumerate(approx):
        actual_start = None
        actual_end = None

        for wi in range(len(words)):
            if not word_nonempty[wi]:
                continue
            ws, we = word_starts[wi], word_ends[wi]
            if ws >= sent_start and actual_start is None:
                actual_start = ws
            if we <= sent_end:
                actual_end = we

        if actual_start is not None and actual_end is not None:
            refined.append((actual_start, actual_end))
        else:
            # No WX word in this window — fall back to proxy estimate.
            refined.append((float(sent_start), float(sent_end)))

    # Snap the last sentence's end to the final WX timestamp so the timing
    # covers the entire narration.
    if refined and words:
        last_end = float(words[-1].get("end", refined[-1][1]))
        refined[-1] = (refined[-1][0], last_end)

    return refined


def __sentences_joined(sentences: list[str]) -> str:
    """Join sentences with spaces."""
    return " ".join(sentences).strip()


def check_prerequisites(model_key: str = llm_client.DEFAULT_MODEL_KEY):
    """Check API key and critical dependencies before starting."""
    try:
        row = llm_client.resolve_model(model_key)
    except ValueError as e:
        print(f"ERROR: {e}")
        return False

    key_env = row.get("key_env", "")
    if not os.environ.get(key_env):
        print("=" * 60)
        provider = row.get("provider", "").upper()
        signup = {
            "groq": "https://console.groq.com",
            "nvidia": "https://build.nvidia.com",
            "gemini": "https://makersuite.google.com/app/apikey"
        }.get(row.get("provider", ""), "")
        print(f"WARNING: {key_env} is not set.")
        print(f"Story + visual-plan generation require this {provider} key.")
        print()
        if signup:
            print(f"Get a free key at: {signup}")
        print(f"Put it in .env:  {key_env}=\"<your-key>\"")
        print("=" * 60)
        print()
        return False
    return True


def save_project(story: dict, outdir: Path, index: int, no_video: bool = False,
                 model_key: str = llm_client.DEFAULT_MODEL_KEY, render: bool = False):
    """
    Save all project files for one Story Short.

    Story Contract:
        story must be a JSON-compatible dict strictly containing:
        - "title": str (non-empty)
        - "genre": str (one of "scary", "mystery", "moral", "motivational")
        - "sentences": list[str] (authoritative narration in spoken order,
          no visual directions, timestamps, sound effects, labels, or metadata;
          sentence count and word count per sentence are flexible).

    Flow:
        1. Validate story contract
        2. Join sentences for narration script
        3. Generate narration audio with Edge TTS
        4. Extract WhisperX word timestamps
        5. Derive sentence timings with _sentence_timings_from_word_timestamps (using original sentences)
        6. Generate storyboard / visual plan using the actual sentence timings
        7. Generate edit plan
        8. Collect Pexels assets with Pixabay fallback
        9. Stage assets to public/project_assets/ for Remotion
        10. Render with Remotion if render=True
    """
    validate_story_contract(story)

    title = story["title"]
    genre = story["genre"]
    sentences = story["sentences"]
    script = __sentences_joined(sentences)
    word_count = len(script.split())

    daily_dir = _get_daily_outdir(outdir)
    today = date.today()
    date_str = f"{today.month:02d}_{today.day:02d}"
    model_slug = slugify(model_key.replace(".", "-"))
    project_name = f"{date_str}_{index:02d}_{genre}_{model_slug}_{slugify(title)}"
    project_dir = daily_dir / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = project_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    print(f"\n  ┌─ {'='*50}")
    print(f"  │  Project: {project_name}")
    print(f"  │  Genre:   {genre.capitalize()}")
    print(f"  │  Title:   {title}")
    print(f"  └─ {'='*50}")

    # --- Script ---
    script_path = project_dir / "script.txt"
    script_path.write_text(script, encoding="utf-8")
    print(f"  ✓ script.txt ({word_count} words, {len(sentences)} sentences)")

    # --- Metadata ---
    metadata = {
        "title": title,
        "genre": genre,
        "word_count": word_count,
        "sentences": sentences,
        "model": model_key,
        "generated_at": datetime.now().isoformat(),
    }
    (project_dir / "metadata.txt").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(f"  ✓ metadata.txt")

    # --- YouTube metadata ---
    youtube_meta = {
        "youtube_title": title,
        "youtube_description": f"{title} — A {genre} story.\n\n#shorts #{genre} #story",
        "genre": genre,
        "sentences": sentences,
    }
    (project_dir / "youtube_meta.json").write_text(
        json.dumps(youtube_meta, indent=2), encoding="utf-8"
    )
    print(f"  ✓ youtube_meta.json")

    if no_video:
        return project_dir, 0

    # --- Voice generation ---
    narration_path = project_dir / "narration.mp3"
    print(f"  ─ Voice generation...")
    try:
        generate_narration(script, project_dir=project_dir)
        print(f"  ✓ narration.mp3")
    except Exception as e:
        print(f"  ✗ narration.mp3 FAILED: {e}")

    # --- WhisperX Timestamp Extraction ---
    timestamps = []
    if narration_path.exists():
        print(f"  ─ Extracting word timestamps with WhisperX...")
        try:
            whisper_py = "/root/kinetic_typo_vid/venv/bin/python3"
            extractor = Path(__file__).parent / "extract_word_timestamps.py"

            subprocess.run(
                [whisper_py, str(extractor), str(narration_path), "--output", str(project_dir / "timestamps.json")],
                check=True,
                capture_output=True,
                text=True
            )
            print(f"  ✓ timestamps.json (WhisperX)")
            timestamps_path = project_dir / "timestamps.json"
            if timestamps_path.exists():
                timestamps = json.loads(timestamps_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠ WhisperX timestamp extraction failed: {e}")
            (project_dir / "timestamps.json").write_text("[]", encoding="utf-8")
            timestamps = []

    # --- Sentence timings derivation from original sentences ---
    sentence_timings = []
    if timestamps:
        sentence_timings = _sentence_timings_from_word_timestamps(
            timestamps, sentences, fallback_total_dur=_audio_duration(narration_path)
        )
        print(f"  · timing {len(sentence_timings)} sentence(s) from WhisperX word timestamps")
    elif narration_path.exists():
        real_dur = _audio_duration(narration_path)
        if real_dur > 0:
            sentence_timings = _sentence_timings_from_audio(script, real_dur)
            print(f"  · narration is {real_dur:.1f}s; timing {len(sentence_timings)} "
                  f"sentence(s) from real audio (word-count proxy)")
        else:
            print(f"  · couldn't probe narration duration; timing will be estimated")

    # --- Storyboard + Captions + per-sentence Asset plan ---
    print(f"  ─ Generating storyboard & visual plan...")
    sb_result = None
    try:
        sb_result = generate_storyboard(
            script=script,
            title=title,
            project_dir=project_dir,
            sentence_timings=sentence_timings,
            sentences=sentences,
            model_key=model_key,
            genre=genre,
        )
        for f in sb_result["files_written"]:
            print(f"  ✓ {Path(f).name}")
    except Exception as e:
        print(f"  ✗ Storyboard FAILED: {e}")
        try:
            thumbnail_notes = _generate_thumbnail_notes(story)
            (project_dir / "thumbnail_notes.txt").write_text(
                thumbnail_notes, encoding="utf-8"
            )
            print(f"  ✓ thumbnail_notes.txt (fallback)")
        except Exception as te:
            print(f"  ✗ thumbnail_notes.txt FAILED: {te}")

    # --- Edit plan ---
    try:
        edit_plan = _generate_edit_plan(story, script, sb_result)
        (project_dir / "edit_plan.json").write_text(
            json.dumps(edit_plan, indent=2), encoding="utf-8"
        )
        print(f"  ✓ edit_plan.json")
    except Exception as e:
        print(f"  ✗ edit_plan.json FAILED: {e}")

    # --- Asset collection (Pexels free stock with Pixabay fallback) ---
    asset_plan = sb_result.get("asset_plan", []) if sb_result else []
    assets_downloaded = 0
    if asset_plan:
        print(f"  ─ Downloading {len(asset_plan)} per-sentence asset(s) from Pexels (Pixabay fallback)...")
        try:
            asset_result = collect_assets_for_plan_with_fallback(asset_plan, project_dir)
            assets_downloaded = len(asset_result)
        except Exception as e:
            print(f"  ✗ Asset download FAILED: {e}")
    else:
        keywords = sb_result.get("keywords", []) if sb_result else []
        if keywords:
            print(f"  ─ Downloading stock footage from Pexels (legacy)...")
            try:
                collect_assets(keywords, project_dir)
            except Exception as e:
                print(f"  ✗ Asset download FAILED: {e}")
        else:
            print(f"  ─ No keywords for asset search")

    # --- Stage assets to public directory for Remotion ---
    if narration_path.exists():
        print(f"  ─ Staging assets to public directory...")
        try:
            import shutil

            # Stage assets into Remotion public/project_assets/ folder
            public_assets_dir = Path(__file__).parent / "public" / "project_assets"
            if public_assets_dir.exists():
                shutil.rmtree(public_assets_dir)
            public_assets_dir.mkdir(parents=True, exist_ok=True)

            # Copy narration to public/
            shutil.copy(narration_path, public_assets_dir / "narration.mp3")
            print(f"  ✓ staged narration.mp3")

            # Copy timestamps to public/
            timestamps_path = project_dir / "timestamps.json"
            if timestamps_path.exists():
                shutil.copy(timestamps_path, public_assets_dir / "timestamps.json")
                print(f"  ✓ staged timestamps.json")

            # Copy timing.json (WhisperX-aligned sentence timestamps) to public/
            timing_path = project_dir / "timing.json"
            timing_list = []
            if timing_path.exists():
                shutil.copy(timing_path, public_assets_dir / "timing.json")
                try:
                    shutil.copy(timing_path, Path(__file__).parent / "public" / "timing.json")
                except Exception:
                    pass
                print(f"  ✓ staged timing.json")
                try:
                    timing_list = json.loads(timing_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            # Load asset plan
            asset_plan_path = project_dir / "asset_plan.json"
            shots = []
            if asset_plan_path.exists():
                try:
                    data = json.loads(asset_plan_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        shots = (
                            data.get("per_sentence")
                            or data.get("asset_plan")
                            or data.get("head", [])
                        )
                    elif isinstance(data, list):
                        shots = data
                except Exception:
                    pass

            if not shots:
                print(f"  ⚠ No shots loaded from asset_plan.json")

            # Copy downloaded assets into public/project_assets/ and prepare props
            assets_dir = project_dir / "assets"
            manifest_path = project_dir / "assets_manifest.json"
            manifest = {}
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            enriched_shots = []
            for idx, s in enumerate(shots):
                match_path = None

                # 1) Prefer the manifest (index -> filename) when available.
                staged_name = manifest.get(str(idx))
                if staged_name:
                    cand = assets_dir / staged_name
                    if cand.exists():
                        match_path = cand

                # 2) Fallback: sequential shot_{idx+1}.{ext} naming.
                if not match_path:
                    for ext in ["mp4", "jpg", "png", "webp"]:
                        p = assets_dir / f"shot_{idx+1}.{ext}"
                        if p.exists():
                            match_path = p
                            break

                # 3) Last resort: whatever sits at position idx (best-effort, unordered).
                if not match_path and assets_dir.exists():
                    files = sorted(
                        [f for f in assets_dir.iterdir()
                         if f.suffix.lower() in {".mp4", ".jpg", ".png", ".webp"}],
                        key=lambda f: f.name,
                    )
                    if idx < len(files):
                        match_path = files[idx]

                staged_rel_path = ""
                if match_path and match_path.exists():
                    dest_name = f"shot_{idx+1}{match_path.suffix}"
                    shutil.copy(match_path, public_assets_dir / dest_name)
                    staged_rel_path = f"project_assets/{dest_name}"
                    print(f"  ✓ staged {dest_name}")

                # Sentence timing from timing.json or shot
                shot_timing = timing_list[idx] if idx < len(timing_list) else {}
                start_sec = shot_timing.get("start", s.get("start"))
                end_sec = shot_timing.get("end", s.get("end"))
                if start_sec is not None and end_sec is not None:
                    dur_sec = round(float(end_sec) - float(start_sec), 3)
                else:
                    dur_sec = float(s.get("duration_seconds", 3.0))

                enriched_item = {
                    "sentence": s.get("sentence", ""),
                    "search_term": s.get("search_term", ""),
                    "media_type": s.get("media_type", "video"),
                    "visual": s.get("visual", ""),
                    "asset_path": staged_rel_path,
                    "duration_seconds": dur_sec,
                }
                if start_sec is not None:
                    enriched_item["start"] = float(start_sec)
                if end_sec is not None:
                    enriched_item["end"] = float(end_sec)

                enriched_shots.append(enriched_item)

            words = []
            if timestamps_path.exists():
                try:
                    words = json.loads(timestamps_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            props = {
                "shots": enriched_shots,
                "words": words,
                "timing": timing_list,
                "narrationSrc": "project_assets/narration.mp3",
            }

            # Write to project directory
            props_json_path = project_dir / "remotion_props.json"
            props_json_path.write_text(json.dumps(props, indent=2), encoding="utf-8")
            print(f"  ✓ generated remotion_props.json")

            # Also publish to public/ for Studio mode
            try:
                public_props_path = Path(__file__).parent / "public" / "remotion_props.json"
                public_props_path.write_text(json.dumps(props, indent=2), encoding="utf-8")
                print(f"  ✓ published remotion_props.json to public/")
            except Exception as e:
                print(f"  ⚠ Could not publish to public/: {e}")

            print(f"  ✓ Assets staged to public directory")
        except Exception as e:
            print(f"  ⚠ Asset staging FAILED: {e}")
    else:
        print(f"  ─ Skipping asset staging (no narration available)")

    # --- Render with Remotion if requested ---
    if render and not no_video and narration_path.exists():
        try:
            print(f"  ─ Rendering video with Remotion...")
            output_video = assemble_video_remotion(project_dir)
            print(f"  ✓ Rendered: {output_video.name}")
        except Exception as rend_err:
            print(f"  ⚠ Remotion render FAILED: {rend_err}")

    return project_dir, assets_downloaded


def _generate_thumbnail_notes(story: dict) -> str:
    """Generate thumbnail design notes from the story."""
    title = story["title"]
    genre = story["genre"]

    lines = [
        f"# Thumbnail Notes: {title} ({genre})",
        "",
        "## Key Visual Elements",
        f"- Theme: {genre.capitalize()} story",
        "- High contrast, mysterious or dramatic focal point",
        "",
        "## Text Overlay Suggestions",
        "- Bold, 3-5 words max",
        "- High contrast (white text with dark outline / yellow accent)",
        f'- Example: "{title[:30]}"',
        "",
        "## Color Palette",
        "- Background: Dark / cinematic atmosphere",
        "- Accent: Red, cold blue, or amber highlights",
        "",
        "## Composition",
        "- Dramatic subject (silhouette, shadowed figure, expressive face)",
        "- Clear, uncluttered focal point readable on mobile screens",
    ]
    return "\n".join(lines)


def _generate_edit_plan(story: dict, script: str, sb_result: dict) -> dict:
    """Generate editing instructions JSON."""
    shots = sb_result.get("shots", []) if sb_result else []
    word_count = len(script.split())
    estimated_duration = max(20, word_count / 2.8)

    return {
        "project_title": story["title"],
        "genre": story["genre"],
        "format": "YouTube Shorts (9:16, 1080x1920)",
        "estimated_duration_seconds": round(estimated_duration, 1),
        "narration_file": "narration.mp3",
        "voice": "en-US-AndrewNeural (+20% rate)",
        "scenes": [
            {
                "shot": s["shot"],
                "duration": s["duration_seconds"],
                "narration": s["text"],
                "visual": s["visual_suggestion"],
                "transition": s["transition"],
                "zoom": s["zoom_effect"],
                "caption_style": {
                    "font": "Arial Bold",
                    "size": 48,
                    "color": "#FFFFFF",
                    "background": "#80000000",
                    "position": "center bottom",
                }
            }
            for s in shots
        ],
        "bgm_recommendation": _suggest_bgm(script, story["title"], story["genre"]),
        "export_settings": {
            "resolution": "1080x1920",
            "fps": 30,
            "codec": "H.264",
            "bitrate": "8 Mbps",
            "audio_bitrate": "128 kbps AAC",
            "format": "MP4",
        },
    }


def _suggest_bgm(script: str, title: str, genre: str = "scary") -> dict:
    """Suggest background music based on genre and script content."""
    genre = (genre or "").lower()
    if genre == "scary":
        return {
            "mood": "dark / horror / suspenseful",
            "genre": "dark ambient, cinematic drone, eerie strings",
            "volume": "-22dB relative to narration",
            "free_sources": [
                "YouTube Audio Library (Dark / Cinematic)",
                "Pixabay Music (Horror / Ambient)",
            ],
        }
    elif genre == "mystery":
        return {
            "mood": "mysterious / investigative / tense",
            "genre": "subtle suspense, tension piano, mystery ambient",
            "volume": "-22dB relative to narration",
            "free_sources": [
                "YouTube Audio Library (Cinematic)",
                "Pixabay Music (Mystery / Cinematic)",
            ],
        }
    elif genre == "motivational":
        return {
            "mood": "inspirational / uplifting",
            "genre": "hopeful piano, orchestral build",
            "volume": "-20dB relative to narration",
            "free_sources": [
                "YouTube Audio Library (Inspirational)",
                "Pixabay Music (Inspiring / Cinematic)",
            ],
        }
    else:  # moral / reflective
        return {
            "mood": "thoughtful / emotive / reflective",
            "genre": "calm piano, emotional strings",
            "volume": "-22dB relative to narration",
            "free_sources": [
                "YouTube Audio Library (Cinematic / Ambient)",
                "Pixabay Music (Emotional / Acoustic)",
            ],
        }


def main():
    parser = argparse.ArgumentParser(
        description="YouTube Shorts AI Agent — Story Video Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  python run_pipeline.py --genre scary --count 1
  python run_pipeline.py --genre mystery --premise "The phone booth that only rings at midnight"
  python run_pipeline.py --genre moral --count 2 --no-video
  python run_pipeline.py --genre scary --render --count 1

Valid --model keys: {', '.join(sorted(llm_client.MODEL_REGISTRY.keys()))}
Default model: {llm_client.DEFAULT_MODEL_KEY}
        """,
    )
    parser.add_argument(
        "--count", type=int, default=1,
        help="Number of Shorts to produce (default: 1, max: 10)"
    )
    parser.add_argument(
        "--genre", type=str, default="scary",
        choices=["scary", "mystery", "moral", "motivational"],
        help="Story genre: scary, mystery, moral, motivational (default: scary)"
    )
    parser.add_argument(
        "--premise", type=str, default=None,
        help="Optional premise or prompt for the story"
    )
    parser.add_argument(
        "--outdir", type=str, default="output",
        help="Output directory (default: output)"
    )
    parser.add_argument(
        "--no-video", action="store_true",
        help="Skip voice generation and video assembly (scripts/metadata only)"
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Equivalent to --count 1 --no-video (quick script review)"
    )
    parser.add_argument(
        "--model", type=str, default=llm_client.DEFAULT_MODEL_KEY,
        help=f"LLM model key (default: {llm_client.DEFAULT_MODEL_KEY})"
    )
    parser.add_argument(
        "--compare-models", type=str, default=None,
        help="Comma-separated model keys to run the SAME story across"
    )
    parser.add_argument(
        "--render", action="store_true",
        help="Render video with Remotion after staging assets (default: stage only, use --render to actually render)"
    )
    parser.add_argument(
        "--auto", action="store_true",
        help="Auto mode (non-interactive, retained for compatibility)"
    )

    args = parser.parse_args()

    # Validate model key early
    try:
        llm_client.resolve_model(args.model)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Handle --compare-models
    compare_models = None
    if args.compare_models:
        compare_models = [m.strip() for m in args.compare_models.split(",")]
        for mk in compare_models:
            try:
                llm_client.resolve_model(mk)
            except ValueError as e:
                print(f"ERROR: Invalid model in --compare-models: {e}")
                sys.exit(1)

    # Handle --quick shortcut
    if args.quick:
        args.count = 1
        args.no_video = True

    # Clamp count
    args.count = max(1, min(args.count, 10))

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Check prerequisites
    if not args.no_video:
        check_prerequisites(args.model)

    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║   Story Shorts AI Agent — Story Pipeline             ║")
    print("╠══════════════════════════════════════════════════════╣")
    print(f"║  Target: {args.count} Story Short{'s' if args.count > 1 else ''}{' (scripts only)' if args.no_video else ''}      ║")
    print(f"║  Genre:  {args.genre:<46} ║")
    print(f"║  Model:  {args.model:<46} ║")
    print(f"║  Output: {str(outdir.resolve()):<46} ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    completed = 0
    failed = 0
    total_assets_downloaded = 0

    # Determine which models to run
    models_to_run = compare_models if compare_models else [args.model]
    _all_keys = llm_client.model_keys()
    fallback_models = ([k for k in _all_keys if k.startswith("groq-")]
                       + [k for k in _all_keys if not k.startswith("groq-")])

    for i in range(1, args.count + 1):
        print(f"┌─ Story [{i}/{args.count}] (Genre: {args.genre})")
        if args.premise:
            print(f"│  Premise: {args.premise[:80]}")

        for model_idx, model_key in enumerate(models_to_run):
            models_to_try = [model_key] + [m for m in fallback_models if m != model_key]
            story = None
            last_error = None
            for try_model in models_to_try:
                try:
                    print(f"│  Generating story with {try_model}...")
                    story = generate_story(
                        genre=args.genre,
                        premise=args.premise,
                        model_key=try_model,
                    )
                    if try_model != model_key:
                        print(f"│  ↻ Fell back to {try_model} after {model_key} failed")
                    break
                except Exception as e:
                    last_error = e
                    print(f"│  ⚠ Model {try_model} failed: {e}")
                    continue

            if story is None:
                print(f"│  ✗ FAILED (all models exhausted): {last_error}")
                failed += 1
                continue

            # Check global dedup — retry up to 3 times if the generated
            # story is a duplicate of content already produced.
            MAX_DEDUP_RETRIES = 3
            dedup_pass = 0
            while _is_duplicate(story, args.premise):
                dedup_pass += 1
                if dedup_pass > MAX_DEDUP_RETRIES:
                    print(f"│  ⚠ Skipping: generated story is a duplicate after {MAX_DEDUP_RETRIES} retries")
                    failed += 1
                    story = None
                    break
                print(f"│  ↻ Duplicate detected, regenerating (attempt {dedup_pass + 1}/{MAX_DEDUP_RETRIES + 1})...")
                try:
                    story = generate_story(
                        genre=args.genre,
                        premise=args.premise,
                        model_key=model_key,
                    )
                except Exception as e:
                    last_error = e
                    print(f"│  ⚠ Regeneration model {model_key} failed: {e}")
                    story = None
                    break

            if story is None:
                if dedup_pass > MAX_DEDUP_RETRIES:
                    continue
                print(f"│  ✗ FAILED (regeneration exhausted): {last_error}")
                failed += 1
                continue

            try:
                project_dir, assets_got = save_project(
                    story=story,
                    outdir=outdir,
                    index=i,
                    no_video=args.no_video,
                    model_key=model_key,
                    render=args.render,
                )

                _log_generated_story(outdir, story, model_key, project_dir.name)
                _add_global_fingerprint(story, args.premise)
                completed += 1
                total_assets_downloaded += assets_got

            except Exception as e:
                print(f"│  ✗ FAILED (model: {model_key}): {e}")
                import traceback
                traceback.print_exc()
                failed += 1
                continue

    # --- Summary ---
    print()
    daily_dir = _get_daily_outdir(outdir)
    print("╔══════════════════════════════════════════════════════╗")
    print(f"║  Done: {completed} successful, {failed} failed                   ║")
    print(f"║  Output: {str(daily_dir.resolve()):<46} ║")
    if not args.no_video and completed > 0:
        print("║                                                      ║")
        print("║  Each project folder contains:                        ║")
        print("║  ├── script.txt          Narration script             ║")
        print("║  ├── narration.mp3       Voiceover audio              ║")
        print("║  ├── timestamps.json     WhisperX word timestamps     ║")
        print("║  ├── storyboard.md       Visual shot plan             ║")
        print("║  ├── captions.srt        Timed subtitles              ║")
        print("║  ├── metadata.txt        Title, genre, sentence list  ║")
        print("║  ├── asset_plan.json     Per-sentence search plan     ║")
        print("║  ├── thumbnail_notes.txt Thumbnail suggestions        ║")
        print("║  ├── edit_plan.json      Full editing instructions    ║")
        print("║  ├── youtube_meta.json   YouTube title + description  ║")
        print("║  ├── remotion_props.json Remotion props               ║")
        print("║  └── assets/             Downloaded video clips       ║")
        print(f"║  Assets downloaded: {total_assets_downloaded} total              ║")
        render_status = "rendered" if args.render else "render skipped"
        print(f"║  ── Assets staged to public/ (Remotion {render_status}) ║")
    elif args.no_video and completed > 0:
        print("║  (--no-video: scripts only — no audio or video)       ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()


if __name__ == "__main__":
    main()
