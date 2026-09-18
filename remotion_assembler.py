"""
remotion_assembler.py
Replaces video_assembler.py: renders draft_video.mp4 using Remotion,
sequencing Pexels stock videos/photos per sentence and overlaying
Whisper word-level kinetic captions.
"""

import json
import shutil
import subprocess
from pathlib import Path

def assemble_video_remotion(project_dir: Path) -> Path:
    project_dir = Path(project_dir)
    narration_path = project_dir / "narration.mp3"
    timestamps_path = project_dir / "timestamps.json"
    asset_plan_path = project_dir / "asset_plan.json"
    output_video = project_dir / "draft_video.mp4"

    if not narration_path.exists():
        raise FileNotFoundError(f"Narration not found: {narration_path}")

    # Stage assets into Remotion public/ project_assets/ folder so Remotion's web server can load them reliably
    public_assets_dir = Path(__file__).parent / "public" / "project_assets"
    if public_assets_dir.exists():
        shutil.rmtree(public_assets_dir)
    public_assets_dir.mkdir(parents=True, exist_ok=True)

    # Copy narration to public/
    shutil.copy(narration_path, public_assets_dir / "narration.mp3")

    # Copy timestamps to public/
    if timestamps_path.exists():
        shutil.copy(timestamps_path, public_assets_dir / "timestamps.json")

    # Copy timing.json (WhisperX-aligned sentence timestamps) to public/
    timing_path = project_dir / "timing.json"
    if timing_path.exists():
        shutil.copy(timing_path, public_assets_dir / "timing.json")
        try:
            shutil.copy(timing_path, Path(__file__).parent / "public" / "timing.json")
        except Exception:
            pass

    timing_list = []
    if timing_path.exists():
        try:
            timing_list = json.loads(timing_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Load asset plan. Different writers have used different top-level keys
    # over time ("head", "asset_plan", "per_sentence"); accept any of them so
    # a missing/renamed key never silently yields an empty shot list (which
    # renders a black video with only audio).
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
        print("  ⚠ No shots loaded from asset_plan.json (composition will be black)")

    # Copy downloaded assets into public/project_assets/ and map relative paths.
    # Asset files are named after their search term (e.g. Python_programming_123.mp4),
    # NOT shot_{idx}.ext, so we prefer the index -> filename manifest written by
    # the asset collector. The shot_{idx+1}.{ext} / iterdir() lookups are kept only
    # as a best-effort fallback for manually-dropped assets.
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

    total_dur_sec = sum(s["duration_seconds"] for s in enriched_shots) or 30.0
    total_frames = max(30, int(total_dur_sec * 30))

    props_json_path = project_dir / "remotion_props.json"
    props_json_path.write_text(json.dumps(props, indent=2), encoding="utf-8")

    # Also copy to public/ for Studio mode
    public_props_path = Path(__file__).parent / "public" / "remotion_props.json"
    public_props_path.write_text(json.dumps(props, indent=2), encoding="utf-8")
    print(f"  ✓ Published remotion_props.json to public/")

    print(f"  ─ Rendering video with Remotion ({len(enriched_shots)} shots, ~{round(total_dur_sec, 1)}s, {total_frames} frames)...")
    # NOTE: we deliberately do NOT pass --frames here. The ShortsComposition
    # now exposes calculateMetadata (see ShortsComposition.tsx) which derives
    # the duration straight from the shots prop. Hardcoding --frames in Python
    # risks an off-by-one (int() truncation vs JS Math.round()) that makes the
    # requested range exceed the computed duration and aborts the render.
    cmd = [
        "npx", "remotion", "render",
        "ShortsComposition",
        str(output_video.absolute()),
        f"--props={str(props_json_path.absolute())}",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Remotion render error:\n{result.stderr}")
        raise RuntimeError(f"Remotion render failed with code {result.returncode}")

    print(f"  ✓ draft_video.mp4 (Remotion)")
    return output_video


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        assemble_video_remotion(Path(sys.argv[1]))
    else:
        print("Usage: python remotion_assembler.py path/to/project_dir")
