# RUN_COMMANDS.md — Scary Stories YouTube Shorts Pipeline

Working commands for generating, verifying, and rendering scary story YouTube Shorts (9:16, 1080×1920).

---

## 1. Primary Story Generation Commands

### Standard Generation (Story + Voice + WhisperX + Assets Staging)
Generates a complete scary story, synthesizes high-speed Edge-TTS voiceover, derives sentence timestamps with WhisperX, downloads matching stock assets from Pexels/Pixabay, and stages everything into `public/project_assets/` and `public/remotion_props.json`:
```bash
# 1 Scary Story (Default genre: scary, default model: gemini-31-flash-lite)
python3 run_pipeline.py --count 1

# Batch of 3 stories
python3 run_pipeline.py --count 3
```

### With a Custom Premise / Prompt Hook
Guide the story premise or eerie concept:
```bash
python3 run_pipeline.py --premise "The basement mirror that reflects someone standing behind you"
```

### Full End-to-End Render (Including Remotion MP4 Output)
Automatically stages assets and renders `draft_video.mp4` with Remotion:
```bash
python3 run_pipeline.py --count 1 --render
```

### Quick Tests & Script Review (No Asset Downloads)
```bash
# Fastest test: 1 script only, no audio or asset download (~5 seconds)
python3 run_pipeline.py --quick

# Script + Edge-TTS narration audio only (no stock video downloads)
python3 run_pipeline.py --count 1 --no-video
```

### Other Supported Genres
While the primary focus is scary stories, the pipeline supports four structured genres (`scary`, `mystery`, `moral`, `motivational`):
```bash
python3 run_pipeline.py --genre mystery --premise "The payphone that rings at 3:14 AM"
python3 run_pipeline.py --genre moral --count 1
python3 run_pipeline.py --genre motivational --count 1
```

### Custom Model Selection
```bash
# Use Groq GPT-OSS 120B
python3 run_pipeline.py --model groq-gpt-oss-120b --count 1

# Use NVIDIA Nemotron Ultra 550B
python3 run_pipeline.py --model nvidia-nemotron-ultra --count 1
```

---

## 2. Visual-to-Sentence Alignment Verification

Check that each spoken sentence from WhisperX (`timing.json`) is accurately mapped to its visual with zero drift and zero black gaps:

```bash
# Verify currently staged story (reads public/remotion_props.json & timing.json)
python3 check_sentence_alignment.py

# Verify all generated projects in output/
python3 check_sentence_alignment.py --all

# Verify a specific story folder
python3 check_sentence_alignment.py output/17_09_short_vids/09_17_01_scary_gemini_31_flash_lite_the_last_echo
```

---

## 3. Remotion Studio & Manual Rendering

### Preview in Browser (Remotion Studio)
Launch the interactive web UI to inspect the staged story, audio, captions, and visual cuts:
```bash
npm start
# Opens http://localhost:3000
```

### Manual Render to MP4
Render the currently staged story into an MP4 video file:
```bash
# Full video render
npx remotion render ShortsComposition out/scary_story.mp4

# Test render first 60 frames (2 seconds)
npx remotion render ShortsComposition out/test_preview.mp4 --frames=0-59
```

---

## 4. Testing & Verification

```bash
# Run Vitest test suite (timeline calculation, timing.json alignment, zero black gaps)
npx vitest run
```

---

## 5. Standalone Module Debugging

Test individual components in isolation:

```bash
# Test story generation only
python3 -c "from story_generator import generate_story; print(generate_story('scary'))"

# Test Edge-TTS narration
python3 voice_generator.py --script "The silence in the hallway was heavier than before." --output /tmp/test_narration.mp3

# Test WhisperX word timestamps extraction
python3 extract_word_timestamps.py public/narration.mp3 --output /tmp/test_timestamps.json

# Test Remotion assembler on an existing project folder
python3 remotion_assembler.py output/17_09_short_vids/09_17_01_scary_gemini_31_flash_lite_the_last_echo
```
