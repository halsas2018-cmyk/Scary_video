# CLAUDE.md — YouTube Shorts AI Agent

Project guide for the automated, zero-cost pipeline turning trending tech/AI/business news into ready-to-edit YouTube Shorts (9:16, 1080×1920).

Adapted the pipeline from news Shorts to structured scary, mystery, moral, and motivational stories by connecting story generation, WhisperX sentence timing, visual planning, stock asset collection, and Remotion staging in `run_pipeline.py`.

---

## 1. Quick Start & Environment

- **Runtime:** Python 3.13+ (always run scripts with `python3`, never bare `python`).
- **Dependencies:** `python3 -m pip install --break-system-packages -r requirements.txt` (`requests`, `edge-tts`, `Pillow`, `trafilatura`, `readability-lxml`, `youtube-transcript-api`).
- **System Tools:** `ffmpeg`, `ffprobe`, `curl`.
- **Environment (`.env`):**
  ```env
  GROQ_API_KEY="gsk-..."      # Script generation & Groq LLM calls
  PEXELS_API_KEY="qkn-..."    # Stock footage/photo downloads
  NVIDIA_API_KEY="nvapi-..."  # Optional: NVIDIA NIM alternative models
  ```

### Common Commands
```bash
python3 run_pipeline.py --count 3 --outdir output      # Full run (default 3 stories)
python3 run_pipeline.py --quick                       # 1 script only, no video
python3 run_pipeline.py --count 1 --no-video          # Scripts + voice only
python3 run_pipeline.py --auto --count 5              # Non-interactive (cron)
python3 run_pipeline.py --model nvidia-nemotron-ultra # Use NVIDIA NIM
python3 run_pipeline.py --rank-model nvidia-nemotron-ultra # Groq scripts + NVIDIA ranking
python3 llm_client.py --bench                         # Benchmark all models
```

---

## 2. Pipeline Architecture & Flow

```
run_pipeline.py (Orchestrator)
  ├─ 1. news_fetcher.rank_top_stories() → fetch RSS (blogs, CNBC, TechCrunch, Reddit, Google News) + HN + YouTube feeds, score & rank pool (40 candidates)
  ├─ 2. Daily dedupe (output/<daily>/_generated_log.json)
  ├─ 3. llm_ranker.rerank() → LLM editorial rerank (best-first shortlist + reasons + duplicates; falls back to heuristic on error)
  ├─ 4. Interactive Picker (unless --auto) → user selects stories
  └─ For each selected story:
       ├─ article_fetcher.fetch_article_content() → scrape article/transcripts + comments (HN/Reddit fallback to RSS summary)
       ├─ script_generator.generate_combined() → ONE LLM call: script (6-9 sentences, 110-150w), headline, youtube_title (≤60c), youtube_description (≤200c), shots[] plan
       ├─ voice_generator.generate_narration() → narration.mp3 (edge-tts +20% rate)
       ├─ storyboard_generator.generate_storyboard() → storyboard.md, captions.srt, asset_plan.json, timing.json
       ├─ asset_collector.collect_assets_for_plan() → Pexels assets (one per sentence, video/photo, LLM tag verification, 2-use limit, max 15MB)
       └─ video_assembler.assemble_video_simple() → draft_video.mp4 (ffmpeg, chronological clip-per-sentence, xfade 0.2s transitions, Ken-Burns zoompan on photos, 1000Hz sentence-boundary clicks, no burned captions)
```

---

## 3. Core Modules & Contracts

- **`run_pipeline.py`**: Orchestrates story generation, voice synthesis, WhisperX word timestamps, sentence timing alignment, visual planning, Pexels asset collection, and Remotion staging/render. Strictly enforces the story contract at entry to `save_project`.
- **`story_generator.py`**: Generates structured stories enforcing the pipeline story contract:
  - **Input Contract**:
    - `genre` (`str`, required): Exactly one of `"scary" | "mystery" | "moral" | "motivational"`.
    - `premise` (`str | None`, optional): Story prompt or premise hook.
    - `model_key` (`str`, optional): LLM model key.
  - **Output Contract**:
    - JSON-compatible dictionary exactly containing:
      - `"title": str` (non-empty story title)
      - `"genre": str` (one of `"scary"`, `"mystery"`, `"moral"`, `"motivational"`)
      - `"sentences": list[str]` (authoritative spoken narration in sequential order)
    - **Narration Purity**: No visual directions, camera directions, timestamps, sound effects, speaker labels, or other metadata.
    - **Flexible Sentence & Word Counts**: Sentence count and per-sentence word counts are flexible and not artificially constrained, because the exact sentences are passed unchanged to Edge TTS and subsequently matched against WhisperX word timestamps.
- **`llm_client.py`**: Provider-agnostic LLM transport for Groq and NVIDIA NIM (`call_llm` via curl, MODEL_REGISTRY, error guards, token/time scaling, `--bench`).
- **`news_fetcher.py`**: Discovers stories from RSS, HN, Google News, and YouTube channel feeds; computes recency + niche + engagement score.
- **`llm_ranker.py`**: Precision editorial reranker over candidate pool. Outputs best-first order with reasons.
- **`article_fetcher.py`**: Extracts article text (trafilatura → readability → stdlib) and top comments. Routes YouTube URLs to `youtube-transcript-api`.
- **`script_generator.py`**: Combined LLM call producing script, metadata, and per-sentence visual plan with strict validation.
- **`voice_generator.py`**: Generates high-speed Microsoft Edge TTS narration (`en-US-AndrewNeural`).
- **`storyboard_generator.py`**: Formats the combined LLM shot plan into SRT, timing files, and storyboard markdown without extra LLM calls. Genre-aware: `genre` parameter is passed through to `generate_visual_plan()` and embedded in the LLM planner prompt, plus genre-specific fallback search terms for scary/mystery/moral/motivational.
- **`asset_collector.py`**: Downloads Pexels/Pixabay videos/photos with caching and visual-variety reordering. `_enforce_shot_variety()` tags each plan item with `_orig_index` so reordering preserves the original sentence-position mapping — `assets_manifest.json` is always keyed by original asset index regardless of variety reordering.
- **`video_assembler.py`**: FFmpeg assembly pipeline enforcing hard max durations (3.0s video, 1.5s photo), xfade transitions, audio padding, and subtle transition clicks.

---

## 4. Key Gotchas & Troubleshooting

1. **API Keys:** Check `GROQ_API_KEY` and `PEXELS_API_KEY` in `.env`.
2. **Groq TPM Limits:** Full rerank can hit Groq's 8k TPM limit; use `--rank-model nvidia-nemotron-ultra` to offload ranking.
3. **Execution:** Always use `python3`, never `python`.
4. **Module Tests:** Each module has a `if __name__ == "__main__"` smoke test (e.g., `python3 llm_client.py --list`).

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
