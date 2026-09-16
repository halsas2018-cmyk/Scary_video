"""
voice_generator.py
Step 4 of the Shorts pipeline: generate narration audio from script text.

Uses Microsoft Edge TTS (free, no API key, runs locally).
Voice: en-US-AndrewNeural — warm, confident, authentic.

Usage:
    python voice_generator.py --script "Hello world" --output narration.mp3
    python voice_generator.py --file script.txt --output narration.mp3
"""

import argparse
import asyncio
import concurrent.futures
import edge_tts
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Default TTS settings — tuned for YouTube Shorts
# ---------------------------------------------------------------------------

VOICE = "en-US-AndrewNeural"
RATE = "+20%"       # faster-paced for Shorts retention
PITCH = "+0Hz"      # natural
VOLUME = "+0%"      # default

OUTPUT_DIR = Path("output")
TTS_TIMEOUT = 120.0  # seconds — increased for longer scripts (150 words @ +20% ≈ 40s audio)


async def _generate(text: str, output_path: str, voice: str = VOICE,
                    rate: str = RATE, pitch: str = PITCH, volume: str = VOLUME) -> Path:
    """Run edge-tts and write the audio file."""
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
    # Use a longer timeout for the actual save operation
    await asyncio.wait_for(communicate.save(output_path), timeout=TTS_TIMEOUT)
    # Verify the generated file has reasonable duration
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", output_path],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0 and result.stdout.strip():
        duration = float(result.stdout.strip())
        # For 110-150 words at +20% rate, expect 25-45s audio
        if duration < 15:
            raise RuntimeError(f"Generated audio too short ({duration:.1f}s) — likely truncated")
    return Path(output_path)


def generate_narration(text: str, output_path: str = None,
                       project_dir: Path = None) -> Path:
    """
    Generate a narration MP3 from text.

    Args:
        text: The script text to narrate.
        output_path: Direct output path (overrides project_dir).
        project_dir: If set, saves narration.mp3 inside this directory.

    Returns:
        Path to the generated MP3 file.
    """
    if output_path is None and project_dir is not None:
        project_dir = Path(project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(project_dir / "narration.mp3")
    elif output_path is None:
        output_path = "narration.mp3"

    # Clean text for better TTS delivery
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("Text is empty or whitespace only")

    # Ensure output directory exists
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    print(f"  Generating narration ({len(clean_text.split())} words)...")
    # Use asyncio.run() but handle case where event loop is already running
    try:
        result = asyncio.run(_generate(clean_text, output_path))
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            # Fallback: run in a new thread with its own event loop
            def run_in_new_loop(coro):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(coro)
                finally:
                    loop.close()

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_new_loop, _generate(clean_text, output_path))
                result = future.result(timeout=TTS_TIMEOUT)
        else:
            raise
    except asyncio.TimeoutError:
        raise RuntimeError(f"TTS generation timed out after {TTS_TIMEOUT}s — script may be too long")

    duration = _get_mp3_duration(output_path)
    # Sanity check: 110-150 words at +20% rate should be 25-45s
    expected_min = len(clean_text.split()) / 4.5  # ~4.5 wps at +20%
    if duration < expected_min * 0.6:
        print(f"  ⚠ WARNING: Narration duration ({duration:.1f}s) seems too short for {len(clean_text.split())} words (expected ~{expected_min:.0f}s)")
    print(f"  Narration saved: {output_path} ({duration:.1f}s)")
    return result


def _get_mp3_duration(filepath: str) -> float:
    """Estimate duration from file size / bitrate or return 0."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
             filepath],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return 0.0
        return float(result.stdout.strip()) if result.stdout.strip() else 0.0
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return 0.0


def main():
    parser = argparse.ArgumentParser(description="Generate narration audio")
    parser.add_argument("--script", type=str, help="Script text directly")
    parser.add_argument("--file", type=str, help="Path to script.txt file")
    parser.add_argument("--output", type=str, default="narration.mp3",
                        help="Output audio file path")
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.script:
        text = args.script
    else:
        print("Provide --script or --file")
        return

    path = generate_narration(text, output_path=args.output)
    print(f"Done: {path}")


if __name__ == "__main__":
    main()
