#!/root/kinetic_typo_vid/venv/bin/python3
"""
extract_word_timestamps.py
Extract word-level timestamps from narration audio using WhisperX.

Usage:
    python extract_word_timestamps.py path/to/narration.mp3 --output path/to/word_timestamps.json
    python extract_word_timestamps.py path/to/narration.mp3 --output-dir path/to/output_dir
"""

import argparse
import json
import sys
from pathlib import Path

import whisperx
import torch


def extract_word_timestamps(audio_path: str, output_path: str = None, output_dir: str = None) -> list[dict]:
    """
    Run WhisperX transcription + alignment to get word-level timestamps.

    Args:
        audio_path: Path to input audio file (mp3, wav, etc.)
        output_path: Direct output JSON path (optional)
        output_dir: Directory to write word_timestamps.json (optional, used if output_path not given)

    Returns:
        List of word timestamp dicts: [{"word": str, "start": float, "end": float}, ...]
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Determine output path
    if output_path is None:
        if output_dir is None:
            output_dir = audio_path.parent
        output_path = Path(output_dir) / "word_timestamps.json"
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] Loading Whisper model (base, int8, CPU)...")
    model = whisperx.load_model("base", device="cpu", compute_type="int8")

    print(f"[2/5] Loading audio: {audio_path}")
    audio = whisperx.load_audio(str(audio_path))

    print(f"[3/5] Transcribing with word timestamps (batch_size=4)...")
    result = model.transcribe(audio, batch_size=4)

    print(f"[4/5] Aligning for word-level precision...")
    model_a, metadata = whisperx.load_align_model(
        language_code=result["language"], device="cpu"
    )
    result = whisperx.align(
        result["segments"], model_a, metadata, audio, device="cpu"
    )

    print(f"[5/5] Flattening segments to word list...")
    timestamps = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            word_text = w["word"].strip()
            if word_text:
                timestamps.append({
                    "word": word_text,
                    "start": round(w["start"], 3),
                    "end": round(w["end"], 3)
                })

    with open(output_path, "w") as f:
        json.dump(timestamps, f, indent=2)

    print(f"✅ Extracted {len(timestamps)} words → {output_path}")
    return timestamps


def main():
    parser = argparse.ArgumentParser(description="Extract word-level timestamps from audio using WhisperX")
    parser.add_argument("audio", type=str, help="Path to narration audio file (mp3, wav, etc.)")
    parser.add_argument("--output", type=str, help="Output JSON file path")
    parser.add_argument("--output-dir", type=str, help="Output directory (writes word_timestamps.json)")
    args = parser.parse_args()

    try:
        extract_word_timestamps(args.audio, output_path=args.output, output_dir=args.output_dir)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
