"""
video_assembler.py
Step 7 of the Shorts pipeline: assemble a draft Shorts video.

Creates 1080x1920 (9:16) portrait video with:
  - One asset PER SENTENCE, cut in order so the on-screen clip aligns with the
    words actually spoken at that moment. Timing comes from the real narration
    audio (timing.json). Video clips are trimmed/looped per sentence; photos
    are shown static with a slow Ken-Burns "3D" zoom+pan for motion.
  - Smooth xfade crossfades between segments (fade, wipe, slide, circle, etc.).
  - Narration audio (MP3) as the sound track.
  - NO burned-in captions — captions are kept as a separate captions.srt
    reference file for the user to add in their own editor.
  - Optional on-screen headline hook (first 3s) for retention.
  - Subtle color grading by story mood (serious/upbeat/neutral).
  - Render telemetry JSON for debugging/analysis.

Falls back to an enhanced gradient background if no per-sentence assets could be
downloaded (gradient path also adds no burned captions, for consistency).

Uses FFmpeg (free, local, no API).
"""

import json
import random
import subprocess
import os
from datetime import datetime
from pathlib import Path

OUTPUT_SIZE = (1080, 1920)
FONT_SIZE = 52     # kept for reference / future use (captions no longer burned)
MARGIN = 100

# ==============================================================================
# TARGET CLIP DURATIONS — Professional fast-paced feel
# Fixed max durations per media type. If sentence narration exceeds this,
# we use 2 clips for that sentence (cycling through assets) instead of stretching.
# ==============================================================================
TARGET_VIDEO_CLIP_DURATION = 3.0    # max seconds per video clip
TARGET_PHOTO_CLIP_DURATION = 1.5    # max seconds per photo
MIN_CLIP_DURATION = 0.5             # minimum to avoid flash frames

# Max times an asset can be used per video (video or photo)
MAX_ASSET_USES = 2

# ==============================================================================
# TRANSITION CONFIG
# ==============================================================================
XFADE_DURATION = 0.2             # crossfade duration in seconds
XFADE_TRANSITIONS = [
    "fade", "wipeleft", "wiperight", "slideup", "slidedown", "zoomin",
]

# ==============================================================================
# KEN-BURNS VARIETY
# ==============================================================================
KEN_BURNS_ZOOM_RANGE = (0.08, 0.18)   # 8-18% zoom
KEN_BURNS_PAN_RANGE = (-0.15, 0.15)   # pan offset as fraction of frame

# ==============================================================================
# COLOR GRADING PRESETS
# ==============================================================================
COLOR_GRADES = {
    "serious":   "eq=contrast=1.05:brightness=-0.02:saturation=0.9,colorbalance=bs=-0.05:bm=-0.02",
    "upbeat":    "eq=contrast=1.03:brightness=0.02:saturation=1.1,colorbalance=rs=0.03:rm=0.02",
    "neutral":   "eq=contrast=1.05:brightness=0.01:saturation=1.02",
}

# Gradient fallback enhancements
GRADIENT_GRAIN_THRESHOLD = 0.985
GRADIENT_GRAIN_STRENGTH = 20


def assemble_video_simple(project_dir: Path,
                          narration_path: Path = None,
                          output_path: str = None,
                          headline: str = None,
                          render_hook_text: bool = False) -> Path:
    """Assemble a draft Shorts video.

    Reads the per-sentence asset map (asset_plan.json + assets/) and the real
    per-sentence timings (timing.json), cuts one asset per sentence in order.
    Falls back to the gradient background if no usable assets exist.

    Args:
        project_dir: Project folder containing assets/, timing.json, etc.
        narration_path: Path to narration.mp3 (default: project_dir/narration.mp3)
        output_path: Output video path (default: project_dir/draft_video.mp4)
        headline: Optional headline text for on-screen hook (first 3s)
        render_hook_text: If True, burn headline as text overlay on gradient fallback
    """
    project_dir = Path(project_dir)
    narration = narration_path or (project_dir / "narration.mp3")

    if not narration.exists():
        raise FileNotFoundError(f"Narration not found: {narration}")

    output = output_path or str(project_dir / "draft_video.mp4")

    # Real narration duration (drives total length).
    duration = _get_audio_duration(narration)
    if duration <= 0:
        duration = 30

    # Per-sentence plan + timings.
    plan, timings, sentence_to_asset_indices = _load_plan_and_timings(project_dir)

    # Map asset index -> asset path (video .mp4 or photo .jpg).
    asset_map = _resolve_asset_map(project_dir, plan)

    if plan and timings and asset_map:
        return _assemble_chronological(project_dir, narration, output,
                                       duration, plan, timings, asset_map,
                                       sentence_to_asset_indices=sentence_to_asset_indices,
                                       headline=headline)

    # Legacy gradient fallback (also no burned captions).
    return _assemble_with_gradient(narration, output, duration, project_dir,
                                    headline=headline if render_hook_text else None)


# ---------------------------------------------------------------------------
# Plan / timing / asset resolution
# ---------------------------------------------------------------------------

def _load_plan_and_timings(project_dir: Path):
    """Load asset_plan.json (per-sentence list) and timing.json."""
    plan_path = project_dir / "asset_plan.json"
    timing_path = project_dir / "timing.json"
    plan, timings, sentence_to_asset_indices = [], [], []

    if plan_path.exists():
        try:
            data = json.loads(plan_path.read_text(encoding="utf-8"))
            plan = data.get("per_sentence", []) if isinstance(data, dict) else []
            sentence_to_asset_indices = data.get("sentence_to_asset_indices", [])
        except (json.JSONDecodeError, OSError):
            plan = []
            sentence_to_asset_indices = []

    if timing_path.exists():
        try:
            raw = json.loads(timing_path.read_text(encoding="utf-8"))
            timings = [(float(t["start"]), float(t["end"]))
                        for t in raw if "start" in t and "end" in t]
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            timings = []

    return plan, timings, sentence_to_asset_indices


def _resolve_asset_map(project_dir: Path, plan: list[dict]) -> dict:
    """Match each asset entry to an asset file in assets/, by index + search_term.

    Files are named '<safe_query>_<id>.<ext>' by asset_collector. We match on
    the search_term prefix, or fall back to positional order in assets/glob.
    Returns {asset_index: Path}.
    """
    assets_dir = project_dir / "assets"
    if not assets_dir.exists():
        return {}

    # Index all downloaded assets (video + photo) by their query-derived slug.
    all_assets = sorted(
        list(assets_dir.glob("*.mp4")) + list(assets_dir.glob("*.jpg"))
    )
    if not all_assets:
        return {}

    # Build slug -> asset path (longest-prefix match: a file's name is
    # '<slug>_<id>.ext', so its name starts with the slug).
    slug_assets = {}
    for a in all_assets:
        stem = a.stem            # e.g. 'city_traffic_night_9365198'
        # the id is the last '_<digits>' chunk; slug is everything before it
        m = stem.rsplit("_", 1)
        slug = m[0] if (m and m[1].isdigit()) else stem
        slug_assets.setdefault(slug, []).append(a)

    asset_map = {}
    used = set()
    for i, item in enumerate(plan):
        query = (item.get("search_term") or "").strip().lower()
        slug = _slug(query)
        candidates = slug_assets.get(slug, [])
        for c in candidates:
            if c not in used:
                asset_map[i] = c
                used.add(c)
                break

    # Any leftover entries: fill from unused assets positionally so nothing
    # is wasted, then finally drop entries with no asset (gradient segment).
    unused = [a for a in all_assets if a not in used]
    for i in range(len(plan)):
        if i in asset_map:
            continue
        if unused:
            asset_map[i] = unused.pop(0)
            used.add(asset_map[i])
    return asset_map


def _slug(query: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in query.lower()).strip("_")
    return safe[:30] or "asset"


# ---------------------------------------------------------------------------
# Chronological assembly (the real per-sentence path) with xfade transitions
# ---------------------------------------------------------------------------

def _assemble_chronological(project_dir: Path, narration: Path, output: str,
                            duration: float, plan: list[dict],
                            timings: list[tuple], asset_map: dict,
                            sentence_to_asset_indices: list[tuple] = None,
                            headline: str = None) -> Path:
    """Cut one asset per entry in order, with xfade crossfades + narration.

    Strategy (single ffmpeg invocation, filter_complex):
      - One input per asset (looped if it's a photo or a short video that must
        fill its sentence duration).
      - For each segment: scale+pad to 1080x1920; if photo, add a varied
        Ken-Burns zoompan for the segment's duration; trim to fixed max duration.
      - Concatenate segments with xfade filter chain for smooth transitions.
      - Apply color grading per story mood.
      - Mux narration as the audio track with apad so audio never clips.
      - Total video length == narration length (+ small buffer).
    """
    print(f"    Chronological assembly: {len(asset_map)} asset(s) with assets")

    narration_dur = duration
    n_assets = len(plan)

    # Determine story mood for color grading
    story_title = ""
    metadata_path = project_dir / "metadata.txt"
    if metadata_path.exists():
        try:
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            story_title = meta.get("title", "")
        except Exception:
            pass
    script_path = project_dir / "script.txt"
    script_text = ""
    if script_path.exists():
        script_text = script_path.read_text(encoding="utf-8")
    color_grade = _get_color_grade_filter(story_title, script_text)

    # ── Per-sentence build (clean design) ──────────────────────────────────
    # One ffmpeg input per UNIQUE asset actually used, then per sentence we
    # trim slices out of those (looped) inputs and concat them within the
    # sentence, and xfade-chain only between sentences.
    #
    # Each sentence's slice durations sum to its REAL narration duration, so
    # the whole video equals narration length by construction — no rescale /
    # extension pass that could "stick" or unevenly stretch a clip.

    # Calculate sentence durations from real timings.
    n_sentences = len(timings)
    sentence_durations = []
    for i in range(n_sentences):
        if i < len(timings):
            sentence_durations.append(
                max(MIN_CLIP_DURATION, float(timings[i][1]) - float(timings[i][0])))
        else:
            sentence_durations.append(2.0)  # fallback

    # If we don't have sentence_to_asset_indices, create a simple 1:1 mapping.
    if not sentence_to_asset_indices:
        sentence_to_asset_indices = [(i, i + 1) for i in range(min(n_sentences, len(plan)))]

    all_assets_list = list(asset_map.values())

    # Step 1: choose the ordered asset(s) for each sentence, honouring the
    # MAX_ASSET_USES limit (counted per sentence, not per sub-slice) and
    # preventing the SAME asset from being used back-to-back across sentence
    # boundaries. This is the only place allocation decisions happen, so the
    # math below is transparent.
    asset_sentence_uses = set()         # set of (asset_path, sent_idx)
    sentence_assets = []                # list (per sentence) of [asset_path, ...]

    def _usage(asset_path):
        return sum(1 for (p, _s) in asset_sentence_uses if p == asset_path)

    def _find_alternative(excluded, is_photo):
        for cand in all_assets_list:
            if _usage(cand) >= MAX_ASSET_USES:
                continue
            if cand in excluded:
                continue
            if (cand.suffix.lower() in (".jpg", ".jpeg", ".png")) != is_photo:
                continue
            return cand
        return None

    for sent_idx in range(min(n_sentences, len(sentence_to_asset_indices))):
        asset_start, asset_end = sentence_to_asset_indices[sent_idx]
        is_photo_sents = [
            asset_map[ai].suffix.lower() in (".jpg", ".jpeg", ".png")
            for ai in range(asset_start, asset_end)
            if ai in asset_map
        ]
        chosen = []
        excluded = set()
        # First pick: prevent carrying the SAME asset from the previous sentence.
        if sentence_assets:
            excluded.update(sentence_assets[-1])
        for slot in range(asset_end - asset_start):
            is_photo = is_photo_sents[slot] if slot < len(is_photo_sents) else False
            primary = None
            for ai in range(asset_start + slot, asset_end):
                if ai in asset_map and ai not in chosen and asset_map[ai] not in excluded:
                    primary = asset_map[ai]
                    break
            if primary is not None:
                chosen.append(primary)
                excluded.add(primary)
                continue
            # fallback: any unused alternative of matching type
            alt = _find_alternative(excluded, is_photo)
            if alt is None:
                # Instead of raising, log warning and use gradient fallback for this sentence
                print(f"    ⚠ All {'photo' if is_photo else 'video'} assets exhausted "
                      f"({MAX_ASSET_USES}-use limit). Using gradient fallback for sentence {sent_idx}.")
                chosen.append(None)  # Signal to use gradient
                continue
            chosen.append(alt)
            excluded.add(alt)
        for p in chosen:
            asset_sentence_uses.add((p, sent_idx))
        sentence_assets.append(chosen)

    # Step 2: assign ffmpeg input indices to each unique asset used.
    input_index_of = {}                 # asset_path_str -> ffmpeg input index
    next_input_idx = 1                 # input 0 is narration
    click_input_count_holder = {"n": 0}  # filled when we build clicks
    # (we add click inputs right after narration, so reserve room later)

    # Build per-sentence slices: list of (asset_path, slice_duration).
    # Distribute the sentence duration evenly across its chosen assets, each
    # capped at its target_dur; if one asset can't absorb its full share, the
    # remainder spills to the next.
    sentence_slices = []
    sentence_total_dur = []
    for sent_idx, assets in enumerate(sentence_assets):
        sent_dur = sentence_durations[sent_idx]
        shares = []
        remaining = sent_dur
        for asset_path in assets:
            ext = asset_path.suffix.lower()
            is_photo = ext in (".jpg", ".jpeg", ".png")
            target_dur = TARGET_PHOTO_CLIP_DURATION if is_photo else TARGET_VIDEO_CLIP_DURATION
            if remaining <= 0:
                break
            dur = min(target_dur, remaining)
            shares.append((asset_path, dur))
            remaining -= dur
        # If assets didn't cover the sentence (only happens if the sentence is
        # longer than the sum of the chosen assets' target durations), loop the
        # assets again.
        i = 0
        while remaining > 0 and assets:
            asset_path = assets[i % len(assets)]
            ext = asset_path.suffix.lower()
            is_photo = ext in (".jpg", ".jpeg", ".png")
            target_dur = TARGET_PHOTO_CLIP_DURATION if is_photo else TARGET_VIDEO_CLIP_DURATION
            dur = min(target_dur, remaining)
            shares.append((asset_path, dur))
            remaining -= dur
            i += 1
        sentence_slices.append(shares)
        sentence_total_dur.append(round(sum(s[1] for s in shares), 3))

    # Assign input indices (narration=0; click inputs come AFTER narration so
    # video inputs begin at 1 + n_clicks; we compute n_clicks already since it
    # only depends on number of sentences).
    n_clicks = max(0, len(sentence_assets) - 1)
    video_input_offset = 1 + n_clicks

    # Register inputs in first-appearance order to keep indices dense.
    flat_slices = [s for sl in sentence_slices for s in sl]
    for asset_path, _ in flat_slices:
        key = str(asset_path)
        if key not in input_index_of:
            input_index_of[key] = video_input_offset + len(input_index_of)

    # Step 3: build filter_complex.
    parts = []

    # --- audio: narration apad'd; clicks at sentence boundaries ---
    click_labels = []
    if n_clicks > 0:
        boundary = 0.0
        for i in range(len(sentence_total_dur)):
            if i == 0:
                boundary += sentence_total_dur[i]
                continue
            click_labels.append((boundary, f"[{1 + (i - 1)}:a]"))
            boundary += sentence_total_dur[i]
        amix_inputs = "[a0] " + " ".join(lbl for _, lbl in click_labels)
        parts.append(
            f"[0:a]apad[a0];{amix_inputs}amix=inputs={1 + len(click_labels)}"
            f":duration=first:dropout_transition=0[aout]")
    else:
        parts.append("[0:a]apad[aout]")

    # --- per-sentence streams: concat the slices, then grade+normalize ---
    sentence_labels = []
    # Track cumulative offset per asset for video reuse
    per_asset_counter = {}

    for sent_idx, shares in enumerate(sentence_slices):
        slice_labels = []
        for asset_path, dur in shares:
            # Handle None (gradient fallback)
            if asset_path is None:
                # Create a gradient segment for this slice
                slabel = f"s{sent_idx}_{len(slice_labels)}"
                # Generate a simple gradient color based on sentence index
                hue = (sent_idx * 60) % 360
                parts.append(
                    f"color=c=hsl({hue} 50% 20%):s=1080x1920:d={dur:.3f}:r=30,"
                    f"format=yuv420p,fps=30[{slabel}]"
                )
                slice_labels.append(slabel)
                continue
                
            key = str(asset_path)
            in_idx = input_index_of[key]
            in_label = f"[{in_idx}:v]"
            ext = asset_path.suffix.lower()
            is_photo = ext in (".jpg", ".jpeg", ".png")
            clip_id = _extract_clip_id(asset_path)

            if is_photo:
                kb = _ken_burns_params(clip_id, dur)
                frames = max(1, int(round(dur * 30)))
                preload = "scale=-2:2150:force_original_aspect_ratio=increase,crop=1080:1920"
                # For zoom-in: start at 1.0, zoom to 1.0+amount. For zoom-out: start at 1.0+amount, zoom to 1.0.
                if kb['zoom_in']:
                    z_expr = f"{kb['start_zoom']}+{kb['zoom_amount']}*on/{frames}"
                else:
                    z_expr = f"{kb['start_zoom']}-{kb['zoom_amount']}*on/{frames}"
                x_expr = f"iw/2-(iw/zoom/2)+{kb['pan_x']}*iw*sin(2*PI*on/{frames})"
                y_expr = f"ih/2-(ih/zoom/2)+{kb['pan_y']}*ih*cos(2*PI*on/{frames})"
                # d=frames (not 1) so zoompan produces 'frames' frames = dur seconds at 30fps
                zoom = (f"zoompan=z='{z_expr}':d={frames}:s=1080x1920:fps=30:"
                        f"x='{x_expr}':y='{y_expr}'")
                chain = (f"{in_label}{preload},setsar=1,{zoom},"
                         f"trim=duration={dur:.3f},setpts=PTS-STARTPTS")
            else:
                # Reusing one video input for multiple slices: jump to distinct
                # source offsets so repeat slices don't show identical frames.
                # Track cumulative offset per asset.
                asset_offset = per_asset_counter.get(key, 0.0)
                per_asset_counter[key] = asset_offset + dur
                start_off = asset_offset
                chain = (
                    f"{in_label}scale=1080:1920:force_original_aspect_ratio=decrease,"
                    f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                    f"trim=start={start_off:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS")
            chain += ",format=yuv420p,fps=30"
            slabel = f"s{sent_idx}_{len(slice_labels)}"
            parts.append(f"{chain}[{slabel}]")
            slice_labels.append(slabel)

        # concat slices within this sentence (hard cut — fine inside one thought)
        if len(slice_labels) == 1:
            joined = slice_labels[0]
        else:
            joined = f"sent{sent_idx}"
            parts.append("".join(f"[{l}]" for l in slice_labels)
                         + f"concat=n={len(slice_labels)}:v=1:a=0[{joined}]")

        # grade the whole sentence stream once
        graded = f"sent{sent_idx}_g"
        grade_chain = f"[{joined}]"
        if color_grade:
            grade_chain += color_grade + ","
        grade_chain += "format=yuv420p,fps=30"
        parts.append(f"{grade_chain}[{graded}]")
        sentence_labels.append(graded)

    # --- xfade chain ACROSS sentences only ---
    XFADE_DUR = 0.2
    SHORT_TRANSITIONS = ["fade", "wipeleft", "wiperight", "slideup", "slidedown", "zoomin"]
    if len(sentence_labels) == 1:
        parts.append(f"[{sentence_labels[0]}]copy[vout]")
    else:
        # Track the actual output duration of the xfade chain so far.
        # After each xfade, the combined stream is shorter by XFADE_DUR.
        output_dur = sentence_total_dur[0]
        prev = sentence_labels[0]
        for i in range(1, len(sentence_labels)):
            # The transition starts at (output_dur - XFADE_DUR)
            offset = max(0.0, output_dur - XFADE_DUR)
            trans = SHORT_TRANSITIONS[i % len(SHORT_TRANSITIONS)]
            out_label = f"xf{i}"
            parts.append(
                f"[{prev}][{sentence_labels[i]}]xfade=transition={trans}"
                f":duration={XFADE_DUR:.2f}:offset={offset:.3f}[{out_label}]")
            prev = out_label
            # Update output duration: add this sentence's duration minus the overlap
            output_dur += sentence_total_dur[i] - XFADE_DUR
        parts.append(f"[{prev}]copy[vout]")

    # --- assemble ffmpeg command ---
    cmd = ["ffmpeg", "-y", "-i", str(narration)]
    # click lavfi inputs (one per sentence boundary), with -itsoffset to place them
    for boundary, _lbl in click_labels:
        cmd += ["-itsoffset", f"{boundary:.3f}", "-f", "lavfi", "-i",
                f"sine=frequency=1000:duration=0.02:sample_rate=48000,"
                f"volume=0.15,afade=t=out:st=0.015:d=0.005,pan=stereo"]
    # one input per unique asset, in registration order
    for key, _ in sorted(input_index_of.items(), key=lambda kv: kv[1]):
        p = Path(key)
        ext = p.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png"):
            cmd += ["-loop", "1", "-i", key]
        else:
            cmd += ["-stream_loop", "-1", "-i", key]

    cmd += ["-filter_complex", ";".join(parts),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-t", f"{narration_dur + 0.5:.3f}",
            "-pix_fmt", "yuv420p",
            str(output)]

    print("    Running ffmpeg (this can take a while)...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        err = result.stderr or "(no stderr)"
        print("    --- ffmpeg stderr (full) ---")
        print(err)
        print("    --- end stderr ---")
        raise RuntimeError("Chronological assembly failed (see stderr above)")

    output_path = Path(output)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"    Video: {output_path} ({size_mb:.1f} MB)")

    # Build a segments-style report (compatible with _write_render_report).
    segments = []
    for sent_idx, shares in enumerate(sentence_slices):
        for sub_idx, (asset_path, dur) in enumerate(shares):
            ext = asset_path.suffix.lower()
            segments.append((sent_idx, sub_idx, asset_path,
                             "photo" if ext in (".jpg", ".jpeg", ".png") else "video",
                             dur, sub_idx))
    _write_render_report(project_dir, segments, asset_map, narration_dur,
                         output_path, cmd, result, color_grade, plan)

    return output_path


def _ken_burns_params(clip_id: int, dur: float) -> dict:
    """Generate deterministic but varied Ken-Burns parameters per clip."""
    # Deterministic seed from clip_id for reproducibility
    r = random.Random(clip_id)

    # ~30% zoom-out, ~70% zoom-in for more natural feel
    zoom_in = r.random() < 0.7
    zoom_amount = r.uniform(*KEN_BURNS_ZOOM_RANGE)  # 8-18% zoom
    start_zoom = 1.0 if zoom_in else 1.0 + zoom_amount
    end_zoom = 1.0 + zoom_amount if zoom_in else 1.0

    # Pan direction (normalized -1 to 1, scaled to fraction of frame)
    pan_x = r.uniform(*KEN_BURNS_PAN_RANGE)
    pan_y = r.uniform(*KEN_BURNS_PAN_RANGE)

    frames = max(1, int(round(dur * 30)))

    return {
        "start_zoom": start_zoom,
        "end_zoom": end_zoom,
        "zoom_amount": zoom_amount,
        "pan_x": pan_x,
        "pan_y": pan_y,
        "frames": frames,
        "zoom_in": zoom_in,
    }


def _extract_clip_id(path: Path) -> int:
    """Extract numeric clip ID from filename for deterministic Ken-Burns seed."""
    stem = path.stem
    m = stem.rsplit("_", 1)
    if m and m[1].isdigit():
        return int(m[1])
    # Fallback: deterministic hash (not Python's randomized hash)
    # Use a simple stable hash algorithm
    h = 0
    for ch in stem:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h % 1000000


def _get_color_grade_filter(story_title: str, script: str) -> str:
    """Return subtle color grading filter based on content mood."""
    combined = (story_title + " " + script).lower()

    serious = ["warning", "risk", "danger", "concern", "problem", "crash",
               "failure", "threat", "ban", "lawsuit", "hack", "breach",
               "investigation", "scandal", "crash", "down", "fall", "drop"]
    upbeat = ["launch", "breakthrough", "new", "release", "fast", "record",
              "growth", "announced", "partnership", "funding", "ipo",
              "surge", "rally", "gain", "rise", "soar", "breakthrough",
              "innovation", "milestone", "success", "win"]

    serious_score = sum(1 for w in serious if w in combined)
    upbeat_score = sum(1 for w in upbeat if w in combined)

    if serious_score > upbeat_score:
        return COLOR_GRADES["serious"]
    elif upbeat_score > 0:
        return COLOR_GRADES["upbeat"]
    else:
        return COLOR_GRADES["neutral"]


def _write_render_report(project_dir: Path, segments: list, asset_map: dict,
                         narration_dur: float, output_path: Path,
                         cmd: list, result: subprocess.CompletedProcess,
                         color_grade: str, plan: list[dict]):
    """Write detailed render report for debugging/analysis."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "output": str(output_path),
        "output_size_mb": round(output_path.stat().st_size / (1024*1024), 2),
        "narration_duration": round(narration_dur, 2),
        "segment_count": len(segments),
        "color_grade_applied": color_grade,
        "transition_type": "xfade chain (0.2s, varying types: fade/wipe/slide/zoomin)",
        "segments": [],
        "ffmpeg_cmd": " ".join(cmd),
        "ffmpeg_returncode": result.returncode,
        "warnings": [],
    }

    for seg_i, seg in enumerate(segments):
        # segments are now 6-tuples: (sent_idx, asset_idx, path, media, dur, sub_idx)
        sent_idx, asset_idx, path, media, dur, sub_idx = seg
        report["segments"].append({
            "sentence_index": sent_idx,
            "sub_clip_index": sub_idx,
            "asset": str(path),
            "asset_name": path.name,
            "media_type": media,
            "planned_duration": round(dur, 3),
            "asset_size_mb": round(path.stat().st_size / (1024*1024), 2) if path.exists() else 0,
            "ken_burns": media == "photo" or path.suffix.lower() in (".jpg", ".jpeg", ".png"),
        })

    # Warnings
    total_plan = len(plan) if plan else 0
    if total_plan > 0 and len(asset_map) < total_plan * 0.5:
        report["warnings"].append(f"Less than 50% sentences have assets ({len(asset_map)}/{total_plan}) — heavy gradient fallback")

    for seg in report["segments"]:
        if seg["asset_size_mb"] > 20:
            report["warnings"].append(f"Large asset: {seg['asset_name']} ({seg['asset_size_mb']:.1f} MB)")
        if seg["planned_duration"] < 0.5:
            report["warnings"].append(f"Very short segment: sentence {seg['sentence_index']} ({seg['planned_duration']:.2f}s)")

    # Quality metrics
    video_segments = [s for s in report["segments"] if s["media_type"] == "video"]
    photo_segments = [s for s in report["segments"] if s["media_type"] == "photo"]
    report["quality_metrics"] = {
        "total_segments": len(report["segments"]),
        "video_segments": len(video_segments),
        "photo_segments": len(photo_segments),
        "asset_coverage_pct": round(len(asset_map) / total_plan * 100, 1) if total_plan > 0 else 0,
        "avg_segment_duration": round(sum(s["planned_duration"] for s in report["segments"]) / len(report["segments"]), 2) if report["segments"] else 0,
        "total_asset_size_mb": round(sum(s["asset_size_mb"] for s in report["segments"]), 1),
        "ken_burns_segments": len([s for s in report["segments"] if s.get("ken_burns", False)]),
    }

    try:
        (project_dir / "render_report.json").write_text(json.dumps(report, indent=2))
        print(f"    ✓ render_report.json written")
    except Exception as e:
        print(f"    [warn] Could not write render_report.json: {e}")


# ---------------------------------------------------------------------------
# Enhanced Gradient fallback (no assets at all)
# ---------------------------------------------------------------------------

def _assemble_with_gradient(narration: Path, output: str, duration: float,
                            project_dir: Path, headline: str = None) -> Path:
    """Enhanced gradient fallback with subtle grain, vignette, optional headline."""
    bg = _get_or_create_gradient(project_dir)
    print(f"    Using enhanced gradient background (no per-sentence assets)")

    # Build filter chain with enhancements
    vf_parts = []

    # Subtle animated noise/grain (deterministic per frame via random seed)
    vf_parts.append(
        f"geq='if(gt(random(0),{GRADIENT_GRAIN_THRESHOLD}),"
        f"p(X,Y)+random(1)*{GRADIENT_GRAIN_STRENGTH}-{GRADIENT_GRAIN_STRENGTH//2},"
        f"p(X,Y))'"
    )

    # Subtle vignette for depth
    vf_parts.append("vignette=angle=PI/4:aspect=1080/1920")

    # Optional headline text overlay (first 3 seconds with fade in/out)
    if headline:
        safe_headline = _escape_drawtext(headline)
        # Try to find a system font
        font_file = _find_system_font()
        if font_file:
            vf_parts.append(
                f"drawtext=text='{safe_headline}':"
                f"fontfile={font_file}:"
                f"fontsize=64:fontcolor=white:borderw=3:bordercolor=black:"
                f"x=(w-text_w)/2:y=h*0.12:"
                f"enable='between(t,0,3)':"
                f"alpha='if(lt(t,0.5),t/0.5,if(gt(t,2.5),1-(t-2.5)/0.5,1))'"
            )
        else:
            print("    [warn] No system font found for headline overlay, skipping")

    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(bg),
        "-i", str(narration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration), "-shortest",
        "-pix_fmt", "yuv420p",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"Assembly failed: {result.stderr[-300:]}")

    output_path = Path(output)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"    Video: {output_path} ({size_mb:.1f} MB)")
    return output_path


def _escape_drawtext(text: str) -> str:
    """Escape text for FFmpeg drawtext filter."""
    # Escape special characters: ', :, %, \, [
    text = text.replace("\\", "\\\\")
    text = text.replace("'", r"\'")
    text = text.replace(":", r"\:")
    text = text.replace("%", r"\%")
    text = text.replace("[", r"\[")
    text = text.replace("]", r"\]")
    return text


def _find_system_font() -> str | None:
    """Find a suitable bold system font for drawtext."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Windows/Fonts/arialbd.ttf",
        "/Windows/Fonts/arial.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            return fp
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_video_clips(project_dir: Path) -> list[Path]:
    """(Legacy) list of video clips in assets/ — kept for __main__/smoke."""
    assets_dir = project_dir / "assets"
    if not assets_dir.exists():
        return []
    clips = []
    for ext in ("*.mp4", "*.mov", "*.webm"):
        clips.extend(sorted(assets_dir.glob(ext)))
    return clips


def _get_audio_duration(audio_path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _get_or_create_gradient(project_dir: Path) -> Path:
    bg_path = project_dir / "_bg_gradient.png"
    if not bg_path.exists():
        from PIL import Image, ImageDraw
        width, height = OUTPUT_SIZE
        img = Image.new("RGB", (width, height), (15, 15, 25))
        draw = ImageDraw.Draw(img)
        for y in range(height):
            t = y / height
            r = int(10 + 5 * (1 - t))
            g = int(10 + 8 * (1 - t))
            b = int(25 + 12 * (1 - t))
            draw.line([(0, y), (width, y)], fill=(r, g, b))
        img.save(bg_path)
    return bg_path


if __name__ == "__main__":
    import sys
    proj = sys.argv[1] if len(sys.argv) > 1 else "output/01_test"
    out = assemble_video_simple(Path(proj))
    print(f"Done: {out}")
