# YouTube Shorts AI Agent — Complete Run Command Reference

This document lists **every possible way to run the pipeline** with explanations, examples, and tips.

---

## Quick Reference Table

| Flag | Purpose | Default |
|------|---------|---------|
| `--count N` | Number of Shorts to produce (1–10) | 3 |
| `--outdir DIR` | Output directory | `output` |
| `--no-video` | Scripts + voice only (skip asset download & video assembly) | off |
| `--quick` | Shortcut: 1 script only, no video | off |
| `--model KEY` | LLM model to use | `groq-gpt-oss-120b` |
| `--rank-model KEY` | LLM for the editorial rerank ONLY (default: same as `--model`) | off |
| `--auto` | Non-interactive: pick top-N automatically (cron-friendly) | off |
| `--no-dedupe` | Allow regenerating stories already done today | off |
| `--no-llm-rank` | Skip the LLM rerank; heuristic score order only | off |
| `--compare-modelS LIST` | Run the SAME story across comma-separated model keys | off |
| `--with-hook-text` | Burn headline as on-screen text on gradient fallback videos | off |
| `--branding` | Branding elements (placeholder for future intro/outro) | off |

---

## Available Models (`--model`)

Run `python3 llm_client.py --list` to see the current registry. As of this writing:

| Key | Provider | Model ID | Notes |
|-----|----------|----------|-------|
| `groq-gpt-oss-120b` | Groq | `openai/gpt-oss-120b` | **Default** — strongest reasoning on Groq |
| `groq-gpt-oss-20b` | Groq | `openai/gpt-oss-20b` | Fast, cheap sibling of the default |
| `nvidia-llama33` | NVIDIA | `meta/llama-3.3-70b-instruct` | Fast, general purpose |
| `nvidia-gpt-oss-120b` | NVIDIA | `openai/gpt-oss-120b` | Open-weight, strong reasoning |
| `nvidia-llama-3-1-70b` | NVIDIA | `meta/llama-3.1-70b-instruct` | Solid general purpose |
| `nvidia-nemotron-ultra` | NVIDIA | `nvidia/nemotron-3-ultra-550b-a55b` | Biggest reasoning model |

Dead keys removed after live smoke tests — don't re-add without verifying:
`groq-llama33`, `groq-deepseek`, `groq-llama4`, `groq-kimi-k2`,
`groq-qwen3-27b`, `nvidia-nemotron-super`.

**Groq TPM note:** the LLM editorial rerank sends ~8.5k tokens worst case
(~3.4k input + 5120 max output), over Groq free tier's 8000 TPM cap. Use
`--rank-model nvidia-nemotron-ultra` so ranking rides NVIDIA's separate rate
limits while scripts stay on Groq (details in §5 below).

---

## Common Run Commands

### 1. First-time / Quick Test (no video)
```bash
python3 run_pipeline.py --quick
```
- Produces **1 script only** (no voice, no video)
- Takes ~30–60 seconds
- Great for verifying API keys and prompt quality

### 2. Single Full Video (end-to-end)
```bash
python3 run_pipeline.py --count 1
```
- 1 complete Short: script → voice → assets → `draft_video.mp4`
- Takes ~5–10 minutes (depends on Pexels download speed)
- Output in `output/MM_DD_short_vids/MM_DD_NN_<model>_<slug>/`

### 3. Multiple Videos (batch)
```bash
python3 run_pipeline.py --count 5
```
- 5 complete Shorts
- Interactive story picker (unless `--auto`)

### 4. Scripts Only (no video assembly)
```bash
python3 run_pipeline.py --count 3 --no-video
```
- Generates scripts, research, voice narration — **no** asset download or video assembly
- Much faster, useful for reviewing scripts before committing to video render

### 5. Use a Different Model / Rank Model
```bash
# Fast/cheap Groq sibling
python3 run_pipeline.py --model groq-gpt-oss-20b --count 1

# OpenAI GPT-OSS 120B on NVIDIA
python3 run_pipeline.py --model nvidia-gpt-oss-120b --count 1

# NVIDIA Nemotron Ultra 550B (biggest reasoning model)
python3 run_pipeline.py --model nvidia-nemotron-ultra --count 1

# Meta Llama 3.3 70B on NVIDIA
python3 run_pipeline.py --model nvidia-llama33 --count 1

# Meta Llama 3.1 70B on NVIDIA
python3 run_pipeline.py --model nvidia-llama-3-1-70b --count 1
```

#### Decouple the editorial rerank with `--rank-model`

The LLM rerank sends ~8.5k tokens worst case (~3.4k input + 5120 max output),
which Groq free tier's 8000 TPM cap REJECTS outright. Route ONLY the ranking
to NVIDIA (separate rate limits) while scripts stay on Groq:

```bash
python3 run_pipeline.py --rank-model nvidia-nemotron-ultra --count 1
```

- Banner shows both models (`Model:` + `Rank:` lines); scripts still generate
  on Groq; needs `NVIDIA_API_KEY` in `.env`
- Without it, bare `python3 run_pipeline.py --count 1` still works end-to-end —
  the rerank falls back to heuristic order with a `[llm-rank] fell back` line
- Skip the LLM rerank entirely with `--no-llm-rank`

### 6. Non-Interactive / Cron-Friendly
```bash
python3 run_pipeline.py --auto --count 5
```
- **No prompts** — automatically takes top-N stories
- Perfect for cron jobs, CI/CD, scheduled runs
- Nobody sees the picker in `--auto` mode, so pass `--rank-model nvidia-nemotron-ultra`
  to keep LLM ranking alive (otherwise the Groq TPM wall silently degrades it to heuristic)
- Combine with `--no-video` for script-only cron:
```bash
python3 run_pipeline.py --auto --count 10 --no-video
```

### 7. Override Daily Deduplication
```bash
python3 run_pipeline.py --no-dedupe --count 3
```
- By default, stories already generated **today** are filtered out (logged in `output/MM_DD_short_vids/_generated_log.json`)
- Use this to re-generate a story you weren't happy with

### 8. Custom Output Directory
```bash
python3 run_pipeline.py --count 3 --outdir my_shorts
```
- Output goes to `my_shorts/` instead of `output/`

### 9. Combine Flags
```bash
# 5 videos, Groq scripts + NVIDIA ranking, non-interactive, custom folder
python3 run_pipeline.py --rank-model nvidia-nemotron-ultra --count 5 --auto --outdir batch_001

# 1 video, GPT-OSS 120B on NVIDIA, no dedupe (re-run today's story)
python3 run_pipeline.py --model nvidia-gpt-oss-120b --count 1 --no-dedupe

# 10 scripts only for review, auto-pick, custom dir
python3 run_pipeline.py --count 10 --no-video --auto --outdir script_review
```

---

## Story Selection (Interactive Mode)

When you run **without `--auto`** and have a TTY, you'll see:

```
┌─ Story Selection
│  Enter numbers (e.g. 1,3,5), 'top3', 'all', or press Enter for top-N:
└─
   1. [ 87.3] (YouTube CNBC) Broadcom closes $70B debt deal to feed AI chip demand
        └─ $70B financing for the AI buildout — concrete number, broad appeal
   2. [ 84.1] (Hacker News) Show HN: I built a local-first alternative to Notion
        └─ Dev-tool launch with 400 HN points — strong discussion hook
   3. [ 79.8] (YouTube Bloomberg Tech) OpenAI's Greg Brockman on the road to GPT-5
        └─ Named insider on the biggest AI story of the week
Pick stories to generate:
```

With LLM ranking the list is **best-first with an editor reason** under each
candidate (plus `↻ same event as #N` on duplicate-group members); when the
rerank falls back to heuristic order the same stories appear **grouped by
category** (`── AI ──` headers). Either way the displayed numbers map exactly
to what you type.

**Valid inputs:**
| Input | Meaning |
|-------|---------|
| (empty / Enter) | Take top-N (where N = `--count`) |
| `1,3,5` | Pick stories 1, 3, and 5 |
| `all` | Generate ALL fetched candidates |
| `top3` | Top 3 (also `top5`, `top10`, etc.) |

**Tip:** If the picker feels "not smooth," check:
- Are you in a real TTY? (Some terminals/IDEs don't allocate one)
- Use `--auto` to bypass entirely for automation
- The prompt accepts comma-separated indices — no spaces needed (`1,3,5` not `1, 3, 5`)

---

## Understanding the Output Structure

Each Short gets its own folder under the daily output dir:

```
output/MM_DD_short_vids/MM_DD_NN_<model>_<slug>/
├── script.txt              # Narration script (6–9 sentences, 110–150 words)
├── research_notes.json     # Fetch quality + headline options
├── metadata.txt            # Title, source, link, score, fetch block (JSON)
├── narration.mp3           # Edge-TTS voiceover (en-US-AndrewNeural, +20% rate)
├── headline.txt            # On-screen hook headline
├── storyboard.md           # Per-sentence visual plan
├── captions.srt            # Timed subtitles (from REAL audio duration)
├── asset_plan.json         # Keywords + per-sentence Pexels search terms
├── timing.json             # Sentence start/end times (from ffprobe)
├── thumbnail_notes.txt     # Thumbnail design suggestions
├── edit_plan.json          # Full editing instructions for DaVinci/CapCut
├── youtube_meta.json       # YouTube title (≤60 chars), description (≤200 + tags)
├── assets/                 # Per-sentence clips (video or photo)
│   ├── 0.mp4
│   ├── 1.jpg
│   └── ...
└── draft_video.mp4         # Assembled 1080×1920 Short (no burned captions)
```

**Key files to review:**
- `script.txt` — Read the narration; tweak if needed before video
- `youtube_meta.json` — Ready-to-copy title + description + hashtags
- `draft_video.mp4` — The assembled draft (open in any player)
- `asset_plan.json` — See what search terms were used per sentence

---

## Cache Behavior (Pexels Clips)

The pipeline caches downloaded clips at `~/.shorts_clip_cache.json`:
- **Video clips** and **photos** are cached by search term
- If you re-run with similar topics, clips are **reused** (saves bandwidth)
- Cache is global across all runs/projects
- To force fresh downloads, delete the cache file:
```bash
rm ~/.shorts_clip_cache.json
```

**Note:** During asset download, you'll see messages like:
```
  ─ Downloading 7 per-sentence asset(s) from Pexels...
  [cache hit] "AI chip" -> /home/user/.cache/shorts_clips/ai_chip_abc123.mp4
  [downloaded] "neural network" -> assets/1.mp4 (2.3 MB)
```
This is normal — cache hits are fast, downloads take a few seconds each.

---

## Prerequisites Checklist

Before running, ensure:

1. **`.env` file exists** in project root with:
   ```
   GROQ_API_KEY="gsk-..."       # REQUIRED for script generation
   PEXELS_API_KEY="qkn-..."     # REQUIRED for video/photo assets
   NVIDIA_API_KEY="nvapi-..."   # OPTIONAL — NVIDIA models + --rank-model rerank
   ```

2. **System tools installed:**
   ```bash
   # Ubuntu/Debian
   sudo apt install ffmpeg curl
   
   # macOS
   brew install ffmpeg curl
   ```

3. **Python deps:**
   ```bash
   pip install -r requirements.txt
   # (requests, edge-tts, Pillow, trafilatura, readability-lxml,
   #  youtube-transcript-api)
   ```
   On Debian/Ubuntu, pip refuses with "externally-managed-environment"
   (PEP 668) — add the override flag:
   ```bash
   python3 -m pip install --break-system-packages -r requirements.txt
   ```

4. **Run the prerequisites check:**
   ```bash
   python3 run_pipeline.py --quick  # Will warn if keys missing
   ```

---

## Troubleshooting Common Issues

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `GROQ_API_KEY is not set` | Missing/invalid key in `.env` | Add valid key from console.groq.com |
| `PEXELS_API_KEY is not set` | Missing Pexels key | Add key from pexels.com/api |
| `curl returned 28` / timeout | LLM call took too long | Model may be slow; try `groq-gpt-oss-20b` or an NVIDIA model |
| `[llm-rank] fell back to heuristic order` | Groq free-tier 8000 TPM cap rejects the ~8.5k-token rerank request | Run with `--rank-model nvidia-nemotron-ultra` (see §Available Models) |
| `HTTP 403` from Pexels | Missing browser User-Agent | Fixed in code — update `asset_collector.py` |
| `No stories found` | Network / feed issue | Check internet; RSS feeds may be down |
| `draft_video.mp4` is 1080×1920 but no video track | Pexels download failed | Check `PEXELS_API_KEY`; delete cache and retry |
| Story picker doesn't appear | Not in a TTY (e.g., IDE terminal) | Use `--auto` or run in real terminal |

---

## Advanced: Running Individual Modules for Debugging

Each module has a `__main__` block for standalone testing:

```bash
# 1. News fetcher — see top stories with scores
python3 news_fetcher.py

# 2. LLM ranker — ONE editorial rerank call over the live pool
python3 llm_ranker.py --model nvidia-nemotron-ultra
# (bare invocation defaults to Groq and hits the known 8k TPM wall)

# 3. Article fetcher — fetch full article + comments for a URL
python3 article_fetcher.py "https://news.ycombinator.com/item?id=12345"
# Or with no args: demos on current top HN story
# YouTube watch URLs pull the transcript instead of scraping the page

# 4. LLM client — list models, smoke-test, or benchmark the registry
python3 llm_client.py --list
python3 llm_client.py --model groq-gpt-oss-120b
python3 llm_client.py --bench

# 5. Script generator — full combined call on a URL
python3 script_generator.py "https://example.com/article"

# 6. Voice generator — test TTS
python3 voice_generator.py --script "Hello world" --output /tmp/test.mp3

# 7. Storyboard generator — reads stdin, writes test_output/
python3 storyboard_generator.py

# 8. Asset collector — legacy (flat keywords) or per-sentence plan
python3 asset_collector.py "technology" /tmp/test_cache
# Or build a plan and call collect_assets_for_plan()

# 9. Video assembler — needs a project with narration + assets
python3 video_assembler.py output/01_test_project

# 10. Full quick test (1 script, no video)
python3 run_pipeline.py --quick

# 11. Full video test (1 complete Short)
python3 run_pipeline.py --count 1
```

---

## Environment Variables Summary

| Variable | Required? | Where to Get |
|----------|-----------|--------------|
| `GROQ_API_KEY` | **Yes** (default pipeline: scripts + tag verification) | https://console.groq.com |
| `NVIDIA_API_KEY` | Only for NVIDIA models / `--rank-model` rerank | https://build.nvidia.com |
| `PEXELS_API_KEY` | **Yes** (for video/photos) | https://pexels.com/api |

All three can be in `.env` file (auto-loaded) or exported in shell.

---

## Model Selection Guide

| Use Case | Recommended Model |
|----------|-------------------|
| **Scripts (default)** | `groq-gpt-oss-120b` — strongest writer on Groq |
| **Fast/cheap scripts** | `groq-gpt-oss-20b` |
| **Editorial rerank** | `nvidia-nemotron-ultra` via `--rank-model` (dodges Groq's 8k TPM wall) |
| **Maximum reasoning capacity** | `nvidia-nemotron-ultra` (550B MoE) |
| **General purpose on NVIDIA** | `nvidia-llama33` or `nvidia-llama-3-1-70b` |
| **Testing / experimentation** | `python3 llm_client.py --bench` times every registered model |

---

## Cron Example (Daily Automated Run)

```bash
# /etc/cron.d/shorts-pipeline (or crontab -e)
# Runs at 6 AM daily: generates 3 Shorts non-interactively
0 6 * * * cd /path/to/video_maker && /usr/bin/python3 run_pipeline.py --auto --count 3 --rank-model nvidia-nemotron-ultra >> /var/log/shorts_pipeline.log 2>&1
```

(`--rank-model` needs `NVIDIA_API_KEY` in `.env`; without it the rerank
silently degrades to heuristic order in non-interactive runs.)

**Tip:** Use `--no-video` for a lighter cron that only produces scripts:
```bash
0 6 * * * cd /path/to/video_maker && /usr/bin/python3 run_pipeline.py --auto --count 10 --no-video --rank-model nvidia-nemotron-ultra
```

---

## Need Help?

Run any command with `--help`:
```bash
python3 run_pipeline.py --help
python3 llm_client.py --help
python3 script_generator.py --help
```

Or check the main docs: `CLAUDE.md` (project architecture) and `pipeline_upgrade_spec.md` (upgrade history).
