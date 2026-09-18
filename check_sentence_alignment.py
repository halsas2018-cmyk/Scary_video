#!/usr/bin/env python3
"""
check_sentence_alignment.py
Efficiently checks and verifies that each sentence is mapped to the visual
during Remotion render using sentence timestamps made from timing.json
(derived from WhisperX), guaranteeing frame-accurate audiovisual alignment.

Usage:
    python3 check_sentence_alignment.py                     # Check current public staging
    python3 check_sentence_alignment.py path/to/project_dir # Check a specific project
    python3 check_sentence_alignment.py --all               # Check all projects in output/
"""

import sys
import json
import argparse
from pathlib import Path

FPS = 30
OVERLAP_FRAMES = 2

def check_alignment(project_dir: Path, verbose: bool = True) -> dict:
    project_dir = Path(project_dir)
    
    # 1. Locate required files
    timing_file = project_dir / "timing.json"
    props_file = project_dir / "remotion_props.json"
    timestamps_file = project_dir / "timestamps.json"
    asset_plan_file = project_dir / "asset_plan.json"

    # Fallback to public/ if checking root or public staging
    if not props_file.exists() and (project_dir / "public" / "remotion_props.json").exists():
        project_dir = project_dir / "public"
        timing_file = project_dir / "timing.json"
        props_file = project_dir / "remotion_props.json"
        timestamps_file = project_dir / "project_assets" / "timestamps.json"

    errors = []
    warnings = []

    if not props_file.exists():
        return {
            "project": str(project_dir),
            "status": "FAILED",
            "errors": [f"Missing remotion_props.json in {project_dir}"],
            "total_sentences": 0,
            "aligned_sentences": 0,
        }

    try:
        props = json.loads(props_file.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "project": str(project_dir),
            "status": "FAILED",
            "errors": [f"Could not parse remotion_props.json: {e}"],
            "total_sentences": 0,
            "aligned_sentences": 0,
        }

    shots = props.get("shots", [])
    words = props.get("words", [])
    timing = props.get("timing")

    # If timing not in props, check timing.json file
    if not timing and timing_file.exists():
        try:
            timing = json.loads(timing_file.read_text(encoding="utf-8"))
        except Exception:
            timing = []

    if not timing:
        errors.append("No timing.json (WhisperX sentence timestamps) found in props or directory.")
        timing = []

    if not shots:
        errors.append("No shots found in remotion_props.json.")

    num_shots = len(shots)
    num_sentences = len(timing)

    if num_shots != num_sentences and num_sentences > 0:
        errors.append(f"Count mismatch: {num_sentences} sentences in timing.json vs {num_shots} shots in remotion_props.json")

    # Simulate Remotion's calculateShotTimingRanges
    has_explicit_timing = all(
        s.get("start") is not None or s.get("start_seconds") is not None
        for s in shots
    ) if shots else False

    ranges = []
    if has_explicit_timing:
        for s in shots:
            start_sec = s.get("start") if s.get("start") is not None else s.get("start_seconds", 0.0)
            end_sec = s.get("end") if s.get("end") is not None else s.get("end_seconds", start_sec + s.get("duration_seconds", 3.0))
            ranges.append({"startSec": float(start_sec), "endSec": float(end_sec), "source": "explicit"})
    elif timing and len(timing) == len(shots):
        for idx, t in enumerate(timing):
            s = shots[idx]
            start_sec = float(t["start"])
            end_sec = float(t.get("end", start_sec + s.get("duration_seconds", 3.0)))
            ranges.append({"startSec": start_sec, "endSec": end_sec, "source": "timing.json"})
    elif words:
        warnings.append("Shots lack explicit timing and timing.json; falling back to word matching.")
        # Minimal word match fallback simulation
        cur = 0.0
        for s in shots:
            dur = s.get("duration_seconds", 3.0)
            ranges.append({"startSec": cur, "endSec": cur + dur, "source": "fallback_words"})
            cur += dur
    else:
        errors.append("No timing source available (no explicit timing, no timing.json, no words).")
        cur = 0.0
        for s in shots:
            dur = s.get("duration_seconds", 3.0)
            ranges.append({"startSec": cur, "endSec": cur + dur, "source": "fallback_cumulative"})
            cur += dur

    # Simulate Remotion nominal cut and end frames
    nominal_cut_frames = []
    for idx in range(len(shots)):
        if idx == 0:
            nominal_cut_frames.append(0)
        else:
            nominal_cut_frames.append(round(ranges[idx]["startSec"] * FPS))

    for i in range(1, len(nominal_cut_frames)):
        if nominal_cut_frames[i] <= nominal_cut_frames[i - 1]:
            nominal_cut_frames[i] = nominal_cut_frames[i - 1] + 1

    last_word_end = words[-1]["end"] if words else (ranges[-1]["endSec"] if ranges else 0)
    composition_duration = max(
        sum(max(30, round(s.get("duration_seconds", 3.0) * FPS)) for s in shots) if shots else 0,
        int(last_word_end * FPS) if last_word_end else 0,
        30
    )

    nominal_end_frames = []
    for idx in range(len(shots)):
        if idx < len(shots) - 1:
            nominal_end_frames.append(nominal_cut_frames[idx + 1])
        else:
            last_sentence_end_frame = int(ranges[idx]["endSec"] * FPS)
            nominal_end_frames.append(max(nominal_cut_frames[idx] + 30, composition_duration, last_sentence_end_frame))

    # Detailed alignment check per sentence
    sentence_reports = []
    aligned_count = 0
    max_sync_delta_ms = 0.0

    for idx in range(min(len(shots), len(timing))):
        shot = shots[idx]
        t = timing[idx]
        t_start = float(t["start"])
        t_end = float(t["end"])
        
        remotion_cut_frame = nominal_cut_frames[idx]
        expected_start_frame = 0 if idx == 0 else round(t_start * FPS)
        
        # Audio speech start vs Visual cut frame
        frame_diff = abs(remotion_cut_frame - expected_start_frame)
        time_diff_ms = (frame_diff / FPS) * 1000.0
        max_sync_delta_ms = max(max_sync_delta_ms, time_diff_ms)

        asset_path = shot.get("asset_path") or shot.get("visual") or "[Gradient Fallback]"
        sentence_text = shot.get("sentence") or f"Sentence {idx+1}"
        short_sentence = (sentence_text[:36] + "...") if len(sentence_text) > 36 else sentence_text

        is_aligned = (frame_diff <= 1) and (ranges[idx]["source"] in ("explicit", "timing.json"))
        if is_aligned:
            aligned_count += 1

        sentence_reports.append({
            "index": idx + 1,
            "sentence": short_sentence,
            "asset": Path(asset_path).name if "/" in asset_path else asset_path[:20],
            "audio_window": f"{t_start:.2f}s - {t_end:.2f}s",
            "cut_frame": remotion_cut_frame,
            "expected_frame": expected_start_frame,
            "delta_ms": time_diff_ms,
            "aligned": is_aligned,
            "source": ranges[idx]["source"],
        })

    # Timeline gap check (ensure zero black gaps across the entire duration)
    sequenced = []
    for idx in range(len(shots)):
        nominal_start = nominal_cut_frames[idx]
        nominal_end = nominal_end_frames[idx]
        start_f = 0 if idx == 0 else max(0, nominal_start - OVERLAP_FRAMES)
        dur_f = max(30, nominal_end - start_f)
        sequenced.append({"start": start_f, "end": start_f + dur_f})

    gap_found = False
    for f in range(composition_duration):
        active = [s for s in sequenced if s["start"] <= f < s["end"]]
        if len(active) == 0:
            errors.append(f"Black gap detected at frame {f} ({f/FPS:.2f}s)")
            gap_found = True
            break

    all_passed = (len(errors) == 0) and (aligned_count == len(timing)) and (len(timing) > 0)

    if verbose:
        print(f"\n================================================================================")
        print(f"🎬 Remotion Visual-to-Sentence Alignment Check: {project_dir.name}")
        print(f"================================================================================")
        print(f"Timing Source: {'timing.json (WhisperX)' if timing else 'None'}")
        print(f"Shots Count:   {num_shots} | Sentences Count: {num_sentences}")
        print(f"Duration:      {composition_duration} frames (~{composition_duration/FPS:.2f}s at {FPS}fps)")
        print(f"--------------------------------------------------------------------------------")
        print(f"{'#':<3} {'Sentence Snippet':<38} {'Visual Asset':<20} {'Audio Time':<15} {'CutFrame':<9} {'Delta':<8} {'Status'}")
        print(f"--------------------------------------------------------------------------------")
        for r in sentence_reports:
            status_icon = "✓ OK" if r["aligned"] else "✗ MISMATCH"
            print(f"{r['index']:<3} {r['sentence']:<38} {r['asset']:<20} {r['audio_window']:<15} {r['cut_frame']:<9} {r['delta_ms']:>5.1f}ms  {status_icon}")
        print(f"--------------------------------------------------------------------------------")
        if all_passed:
            print(f"✅ PERFECT ALIGNMENT: All {aligned_count}/{num_sentences} sentences mapped to visuals accurately.")
            print(f"   Max Sync Delta: {max_sync_delta_ms:.1f}ms (≤ 1 frame / 33.3ms)")
            print(f"   Continuity: 100% covered, 0 black gaps across all {composition_duration} frames.")
        else:
            print(f"❌ ALIGNMENT ISSUES FOUND:")
            for err in errors:
                print(f"   - {err}")
            for warn in warnings:
                print(f"   - Warning: {warn}")

    return {
        "project": str(project_dir),
        "status": "PASSED" if all_passed else "FAILED",
        "total_sentences": num_sentences,
        "aligned_sentences": aligned_count,
        "max_sync_delta_ms": max_sync_delta_ms,
        "has_gaps": gap_found,
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description="Efficient check of Remotion visual-to-sentence mapping using timing.json")
    parser.add_argument("project", nargs="?", default="public", help="Path to project directory (defaults to public/)")
    parser.add_argument("--all", action="store_true", help="Check all projects found in output/")
    parser.add_argument("--quiet", action="store_true", help="Quiet output (summary only)")
    args = parser.parse_args()

    if args.all:
        output_dir = Path("output")
        project_dirs = sorted([
            p for p in output_dir.glob("*/*")
            if p.is_dir() and (p / "timing.json").exists()
        ])
        if not project_dirs:
            print("No project directories with timing.json found in output/.")
            sys.exit(1)

        print(f"Checking {len(project_dirs)} projects in output/...\n")
        all_passed = True
        for p in project_dirs:
            res = check_alignment(p, verbose=not args.quiet)
            if res["status"] != "PASSED":
                all_passed = False

        print("\n================================================================================")
        print(f"OVERALL RESULT: {'ALL PASSED ✅' if all_passed else 'SOME FAILED ❌'}")
        print("================================================================================")
        sys.exit(0 if all_passed else 1)
    else:
        target = Path(args.project)
        res = check_alignment(target, verbose=not args.quiet)
        sys.exit(0 if res["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
