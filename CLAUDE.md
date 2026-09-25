# CLAUDE.md — Scary Stories Shorts Pipeline

Automated pipeline: LLM story generation → Edge-TTS voiceover → WhisperX word timestamps → sentence timing alignment → genre-aware stock footage collection → Remotion render (9:16 Shorts or 16:9 Long-form).

---

## Quick Start

```bash
python3 run_pipeline.py --count 1          # generate + stage assets
python3 run_pipeline.py --premise "..."      # custom premise
python3 run_pipeline.py --count 1 --render   # full end-to-end render
python3 check_sentence_alignment.py          # verify visual-to-speech sync
npx vitest run                          # unit tests
```

**Runtime:** Python 3.13+, Node 18+, ffmpeg, ffprobe. Always use `python3`.

**.env keys:** `GEMINI_API_KEY` (story), `GROQ_API_KEY` (optional alt), `PEXELS_API_KEY` (footage), `PIXABAY_API_KEY` (fallback).

---

## Pipeline Flow

```
run_pipeline.py
  ├─ story_generator.py     → JSON {title, genre, sentences[]}
  ├─ _is_duplicate()        → checks output/_global_dedup.json (content-based SHA-256)
  ├─ voice_generator.py     → narration.mp3 (Edge-TTS en-US-AndrewNeural, +20% rate)
  ├─ extract_word_timestamps.py → timestamps.json (WhisperX word-level)
  ├─ _sentence_timings_from_word_timestamps() → timing.json (two-phase: greedy + time-window refinement)
  ├─ storyboard_generator.py → timing.json, asset_plan.json, storyboard.md, captions.srt
  ├─ asset_collector.py     → Pexels/Pixabay downloads with _orig_index keying
  ├─ remotion_assembler.py  → stages public/project_assets/, writes remotion_props.json
  └─ ShortsComposition.tsx / LongFormComposition.tsx → draft_video.mp4 / output/remotion-render.mp4
```

---

## Core Module Contracts

| Module | Output | Key Fields |
|--------|--------|------------|
| `story_generator.py` | `story.json` | `title`, `genre` ("scary"\|\"mystery"\|"moral"\|"motivational"), `sentences`[] |
| `voice_generator.py` | `narration.mp3` | Edge-TTS, `en-US-AndrewNeural`, +20% rate |
| `extract_word_timestamps.py` | `timestamps.json` | `words:[{word,start,end}]` from WhisperX |
| `remotion_assembler.py` | `remotion_props.json` | `shots:[{sentence,search_term,media_type,visual,asset_path,start,end}]`, `words`, `timing`, `narrationSrc` |
| `storyboard_generator.py` | `asset_plan.json` | `per_sentence[]`, `sentence_to_asset_indices`[][] |

**Genre threading:** `story["genre"]` → `storyboard_generator` → `asset_plan` → `remotion_props`. Genre-specific search terms via `GREYHOUND_GENRE_TERMS`.

---

## Key Invariants & Gotchas

1. **`_orig_index` keying:** `asset_collector._enforce_shot_variety()` reorders shots by visual category. Each item is tagged with `_orig_index` (original sentence position) before reordering. `collect_assets_for_plan()` and the manifest are keyed by `_orig_index`, not reordered position — ensures correct sentence-to-asset pairing.

2. **Timing coverage:** `ShortsCompositionMetadata` extends `durationInFrames` to `ceil(lastWordEnd * fps)`. The last sentence's end always equals the last WhisperX word's end. Never cut off narration tail.

3. **Cinematic treatment:** CSS filter wrapper (`brightness(0.85) contrast(1.1) saturate(0.85) sepia(0.15)`) + vignette overlay + film grain. Captions kept outside filter at `zIndex: 10`. Long-form uses lighter filter (`brightness(0.92) contrast(1.05) saturate(0.88)`).

4. **Two-phase timing alignment:** Phase 1 (greedy word-by-word) handles WhisperX prefix merges and dropped words. Phase 2 (time-window refinement) only activates on alignment failure, snapping proxy windows to nearest real WhisperX timestamps. Timings always come from real WhisperX data when available.

5. **Global dedup:** `output/_global_dedup.json` persists across runs/dates. SHA-256 of normalized genre + ordered sentences (lowercased, whitespace-collapsed) + premise. Title excluded. Retry on duplicate up to 3×.

6. **Asset dimensions:** Video assets from Pexels/Pixabay are landscape (16:9). Photos are portrait (2:3). Remotion handles cropping via `objectFit: "cover"`.

---

## Remotion Compositions

| Composition | Dimensions | FPS | Notes |
|-------------|-----------|-----|-------|
| `ShortsComposition` | 1080×1920 | 30 | 9:16 vertical, dark cinematic filter |
| `LongFormComposition` | 1920×1080 | 30 | 16:9 landscape, lighter filter, ambient loop |

Both consume `public/remotion_props.json` with the same props contract.

---

## GitHub Actions

`.github/workflows/remotion-render.yml` — dispatches manually with a `composition` choice input (`ShortsComposition` default, or `LongFormComposition`). Renders `--props=public/remotion_props.json` to `output/remotion-render.mp4`, uploads as `remotion-video-${{ inputs.composition }}`.

---

## Verification

```bash
python3 check_sentence_alignment.py       # current staging
python3 check_sentence_alignment.py --all # all generated stories
# Expect: "PERFECT ALIGNMENT: All N/N sentences mapped", Max Sync Delta ≤ 1 frame, 0 black gaps
```
