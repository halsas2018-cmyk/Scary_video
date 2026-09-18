# CLAUDE.md — Scary Stories YouTube Shorts Pipeline

Automated pipeline for generating high-retention scary stories (along with mystery, moral, and motivational tales) into ready-to-edit 9:16 YouTube Shorts (1080×1920).

Connects story generation, high-speed Edge-TTS voiceover, WhisperX sentence-boundary timing, genre-aligned stock footage collection (Pexels/Pixabay), and Remotion video rendering.

---

## 1. Quick Start & Environment

- **Runtime:** Python 3.13+ (always run scripts with `python3`, never bare `python`).
- **Dependencies:** `python3 -m pip install --break-system-packages -r requirements.txt`
- **System Tools:** `ffmpeg`, `ffprobe`, `curl`, `node` (v18+).
- **Environment (`.env`):**
  ```env
  GEMINI_API_KEY="..."        # Default: Gemini 3.1 Flash Lite (story generation)
  GROQ_API_KEY="gsk-..."      # Optional: Groq LLM alternative models
  PEXELS_API_KEY="qkn-..."    # Stock footage/photo downloads
  PIXABAY_API_KEY="..."       # Stock fallback downloads
  NVIDIA_API_KEY="nvapi-..."  # Optional: NVIDIA NIM alternative models
  ```

### Common Working Commands
```bash
# 1. Generate 1 scary story (stages assets for Remotion, default: gemini-31-flash-lite)
python3 run_pipeline.py --count 1

# 2. Custom scary premise / prompt
python3 run_pipeline.py --premise "The basement mirror that reflects someone standing behind you"

# 3. Quick script + voice only (no asset download)
python3 run_pipeline.py --quick

# 4. Full end-to-end video render with Remotion
python3 run_pipeline.py --count 1 --render

# 5. Check visual-to-sentence alignment (< 20ms verification)
python3 check_sentence_alignment.py          # current staging
python3 check_sentence_alignment.py --all    # all generated stories

# 6. Preview in Remotion Studio or run tests
npm start          # Remotion Studio
npx vitest run     # Timeline and alignment unit tests
```

---

## 2. Pipeline Architecture & Flow

```
run_pipeline.py (Orchestrator)
  ├─ 1. story_generator.generate_story() → LLM produces structured narration (default: scary)
  ├─ 2. Global deduplication check (_is_duplicate against output/_global_dedup.json)
  ├─ 3. voice_generator.generate_narration() → narration.mp3 (Edge-TTS)
  ├─ 4. extract_word_timestamps.py → timestamps.json (WhisperX word timestamps)
  ├─ 5. Sentence timing alignment (_sentence_timings_from_word_timestamps) → timing.json
  ├─ 6. storyboard_generator.generate_storyboard() → genre-aware visual plan, search terms, captions.srt
  ├─ 7. asset_collector.collect_assets_for_plan_with_fallback() → Pexels / Pixabay downloads with variety ordering
  ├─ 8. remotion_assembler.py → stages project_assets/, writes remotion_props.json with timing.json bounds
  ├─ 9. Remotion Render (ShortsComposition) → draft_video.mp4 with frame-accurate cuts & dark cinematic treatment
  └─ 10. check_sentence_alignment.py → validates 1:1 sentence-to-visual mapping & zero black gaps
```

---

## 3. Core Modules & Contracts

- **`run_pipeline.py`**: Orchestrates story generation, voice synthesis, WhisperX word timestamps, sentence timing alignment, visual planning, asset collection, and Remotion staging/render.
- **`story_generator.py`**: Generates structured stories enforcing the pipeline story contract:
  - **Genre**: Defaults to `"scary"` (supports `"mystery"`, `"moral"`, `"motivational"`).
  - **Contract**: JSON dictionary with `"title"`, `"genre"`, and `"sentences"` (authoritative spoken narration in sequential order, free of camera directions or meta-text).
- **`voice_generator.py`**: High-speed Microsoft Edge TTS narration (`en-US-AndrewNeural`, +20% rate).
- **`extract_word_timestamps.py`**: Runs WhisperX alignment on `narration.mp3` to extract word-level timestamps (`timestamps.json`).
- **`storyboard_generator.py`**: Formats visual plan and search terms tailored to the story mood (dark/eerie for scary), writing `timing.json`, `asset_plan.json`, and `storyboard.md`.
- **`asset_collector.py`**: Downloads stock videos/photos with variety reordering (`_orig_index` preserves sentence order in `assets_manifest.json`).
- **`remotion_assembler.py`**: Stages audio and media to `public/project_assets/`, populates `remotion_props.json` with `timing.json` sentence bounds, and executes Remotion render.
- **`check_sentence_alignment.py`**: Fast verification tool ensuring 100% frame synchronization between WhisperX speech timestamps and Remotion visual cuts.
- **`src/ShortsComposition.tsx`**: Remotion composition applying sentence-based visual cuts, dark cinematic grading (vignette, film grain, subtle desaturation), and synchronized TikTok captions.

---

## 4. Key Gotchas & Troubleshooting

1. **API Keys:** Check `GEMINI_API_KEY` (or `GROQ_API_KEY`) and `PEXELS_API_KEY` in `.env`.
2. **Execution:** Always use `python3`, never bare `python`.
3. **Alignment Verification:** Always run `python3 check_sentence_alignment.py` to confirm visual cuts match narration speech.
4. **Remotion Rendering:** Use `--render` flag on `run_pipeline.py` to produce final MP4; without `--render`, it stages assets for Studio inspection.

## 5. Sentence Timing Alignment (Two-Phase)

WhisperX word-level timestamps are matched to sentences in two phases:

**Phase 1 — Greedy word-by-word alignment** (`_sentence_timings_from_word_timestamps`).
- Walks the WhisperX word list left-to-right.
- Matches each WhisperX token to the expected sentence word (case-insensitive, punctuation stripped).
- Handles two WhisperX failure modes:
  - **Prefix match**: WhisperX merges adjacent words into one token (e.g. `"city morgue"` → `"citymort"`). The matcher consumes as many sentence words as fit within the merged token.
  - **Future-sentence-word match**: WhisperX drops an intermediate word. The matcher looks ahead within the same sentence and skips dropped words, advancing to the matched future word.
  - **Skipped WX word**: Noise/OOV tokens are skipped with no match failure.
- Accepts partial matches: if at least one real WhisperX timestamp was captured for a sentence, that sentence is timed from real data.
- If Phase 1 aligns every sentence successfully, the result is returned immediately — sentence start/end always come from actual WhisperX `start`/`end` fields.

**Phase 2 — Time-window refinement** (`_refine_timings_with_word_timestamps`).
- Activates when Phase 1 cannot align all sentences (too many dropped/merged tokens).
- Computes a word-count-proxy time window per sentence (proportional to word counts within the real audio duration).
- Snaps each window's boundaries to actual WhisperX timestamps: `start` = earliest WX `start` falling in the window; `end` = latest WX `end` falling in the window.
- If zero WhisperX words fall in a window, the proxy estimate is used (never an invented value).
- The last sentence's end is always snapped to the final WhisperX word's `end` timestamp.
- **Key invariant**: timings never come purely from the proxy when real WhisperX data is available — the proxy only seeds the window.

## 6. Asset Plan & Shot Variety Reordering

`_enforce_shot_variety()` in `asset_collector.py` reorders the per-sentence asset plan to avoid consecutive clips from the same visual category (person, screen, abstract, nature, city, object).

**Bug fixed**: The original implementation discarded each item's original index when reordering. The `result` dict from `collect_assets_for_plan()` was then keyed by reordered position, not original sentence position. `assets_manifest.json` inherited these reordered keys, so `save_project()` in `run_pipeline.py` matched `shots[idx]` (original order from `asset_plan.json`) against `manifest[str(idx)]` (reordered order from manifest) — pairing assets with the wrong sentences.

**Fix**: `_enforce_shot_variety()` now tags each item with `_orig_index` (the original position before reordering). `collect_assets_for_plan()` and `collect_assets_for_plan_with_fallback()` key their result dict and manifest by `_orig_index` instead of enumerated position. This ensures `assets_manifest.json` is always keyed by original sentence index, and `save_project()` correctly pairs each sentence's `search_term`/`visual` with its downloaded asset, regardless of variety reordering.

**Genre-aware visual planning**: `storyboard_generator.py` now accepts a `genre` parameter threaded from `story["genre"]` in `save_project()`. The genre is included in the LLM planner prompt, so search terms and visual descriptions match the story's mood (dark/eerie for scary, investigative for mystery, reflective for moral, uplifting for motivational). The keyword fallback `_term_from_sentence()` checks genre-specific terms first via the `GREYHOUND_GENRE_TERMS` dictionary before falling back to `RELATABLE_TERMS`.

## 7. Cinematic Treatment (Remotion Composition Level)

`ShortsComposition.tsx` now applies a subtle global dark cinematic treatment at the composition level, without modifying narration, captions, timing, asset selection, or storyboard logic:

- **CSS filter wrapper**: All media layers (video/photos/fallback gradients) are wrapped in an `<AbsoluteFill>` with `filter: brightness(0.85) contrast(1.1) saturate(0.85) sepia(0.15)`, providing gentle darkening, contrast boost, slight desaturation, and a warm tone.
- **Soft vignette overlay**: An absolutely-positioned `<AbsoluteFill>` with `radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.4) 90%)` draws focus to the center with subtle edge darkening.
- **Film grain / noise overlay**: An `<AbsoluteFill>` with an SVG fractal-noise data URI background at `opacity: 0.12` and `mixBlendMode: "overlay"` adds subtle texture without competing with content.
- **Text readability preserved**: The TikTok captions layer is kept outside the CSS filter wrapper and given `zIndex: 10`, so narration audio, ambient audio, and captions are completely unaffected by the cinematic treatment.
- **Validated**: Confirmed via a 30-frame render (`npx remotion render ShortsComposition --frames=0-29`) that exits cleanly with exit code 0.

Note: `@remotion/effects` (brightness, contrast, saturation, vignette, noise, whiteNoise) is installed and available, but its `effects` prop only works on canvas-based components (`Img`→`CanvasImage`, `<HtmlInCanvas>`). `OffthreadVideo` does not support the `effects` prop, so CSS filters on a wrapper container were used instead for a uniform treatment across both video and photo assets.

## 8. Composition Duration Fix

**`ShortsCompositionMetadata` in `ShortsComposition.tsx`**: The composition duration was previously computed by summing each shot's `duration_seconds` (e.g. 59.8s), which ignored the inter-sentence pauses/gaps present in WhisperX timings. This caused the rendered video to cut off ~8 seconds of narration (68.5s audio vs. 60s render).

**Fix**: After computing the sum of shot durations, the metadata function now checks the `words` array (actual WhisperX word timestamps) and extends `durationInFrames` to `ceil(lastWordEnd * fps)` if that is larger. This uses the real last WhisperX word's `end` timestamp — not a hardcoded offset — to guarantee the composition always covers the full narration timeline.

**Validated**: `npx remotion compositions` now reports `ShortsComposition 30 1080x1920 2046 (68.20 sec)`, matching the narration duration (68.472s) and last WhisperX word end (68.196s). A 30-frame render exits cleanly with code 0.

## 9. Persistent Global Story Deduplication

The old dedup system had two bugs: `_fingerprint()` only hashed the story title (so the same story with a different title was never detected), and the dedup log was daily-scoped (`output/<daily>/_generated_log.json`) so it didn't survive across dates.

**Fix** in `run_pipeline.py`:

- **`_fingerprint(story, premise=None)`**: Now generates a SHA-256 hash from normalized genre + ordered sentences (each lowercased, whitespace-collapsed) + premise when provided. The title is deliberately excluded so identical story content with different titles is still detected as a duplicate.
- **Persistent global dedup store** (`output/_global_dedup.json`): A JSON list of fingerprint strings stored at the project root, surviving across all dates and runs. Functions `_load_global_dedup()`, `_save_global_dedup()`, `_is_duplicate()`, and `_add_global_fingerprint()` manage it.
- **Dedup check with retry**: After `generate_story()` succeeds, `_is_duplicate()` is called. If the story is a duplicate, the pipeline regenerates up to 3 times. If all retries produce duplicates, the story is skipped.
- **Daily log preserved**: The existing daily `_generated_log.json` is kept for date-based history; it now uses the same content-based fingerprint as its key.

**Validated**: Tested that the same story content with a different title produces an identical fingerprint (detected as duplicate), while genuinely different stories produce distinct fingerprints (accepted). Premise is included in the fingerprint. The global dedup file persists to disk.

## 10. Sentence-to-Visual Mapping (`timing.json`)

- **Alignment**: WhisperX sentence boundaries from `timing.json` are attached directly as `start`/`end` on each shot in `remotion_props.json` and staged to `public/timing.json`.
- **Remotion**: `ShortsComposition.tsx` prioritizes explicit shot timings and `props.timing`, cutting visuals exactly on sentence boundaries (0.0ms drift) with inter-sentence pause bridging.
- **Verification**: Run `python3 check_sentence_alignment.py` (or `--all`) to verify 1:1 visual mapping, frame sync (≤1 frame delta), and zero black gaps in <20ms.

