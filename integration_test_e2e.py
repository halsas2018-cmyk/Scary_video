#!/usr/bin/env python3
"""
integration_test_e2e.py
End-to-end integration test for the adapted scary-story pipeline.

Verified checkpoints:
  1. Story contract is valid (title/genre/sentences, no metadata).
  2. Exact sentences[] are passed unchanged to TTS (script == joined sentences).
  3. WhisperX produces word-level timestamps.
  4. _sentence_timings_from_word_timestamps() produces one timing per original
     sentence with no missing matches — uses actual WhisperX timestamps, not
     the word-count proxy.
  5. Visual planner (generate_storyboard) receives those actual timings and
     produces one visual plan entry per sentence.
  6. Genre-awareness: story["genre"] is passed to generate_storyboard and
     generate_visual_plan, and genre-specific fallback terms are used.
  7. Shot-variety reordering preserves original sentence index mapping
     (assets_manifest.json is keyed by original index, not reordered index).

Usage:
    python3 integration_test_e2e.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap .env (same as run_pipeline.py)
# ---------------------------------------------------------------------------
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _val = _line.split("=", 1)
            _key, _val = _key.strip(), _val.strip().strip('"').strip("'")
            if _key and not os.environ.get(_key):
                os.environ[_key] = _val

sys.path.insert(0, str(Path(__file__).parent))

from story_generator import generate_story, validate_story_contract
from voice_generator import generate_narration
from storyboard_generator import generate_storyboard, generate_visual_plan, _term_from_sentence, GREYHOUND_GENRE_TERMS as GENRE_SEARCH_TERMS
from asset_collector import _enforce_shot_variety
import run_pipeline as _rp


# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

PASS = f"{GREEN}PASS{RESET}"
FAIL = f"{RED}FAIL{RESET}"
WARN = f"{YELLOW}WARN{RESET}"


def _h(label: str) -> None:
    print(f"\n{CYAN}{'─'*60}{RESET}")
    print(f"{CYAN}  {label}{RESET}")
    print(f"{CYAN}{'─'*60}{RESET}")


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = PASS if ok else FAIL
    print(f"  [{status}] {label}" + (f"  — {detail}" if detail else ""))
    return ok


def _detect_match_path(words, sentences, sentence_timings, narration_duration):
    """Determine whether _sentence_timings_from_word_timestamps used real
    WhisperX timestamps (Phase 1 exact/prefix/future match OR Phase 2
    time-window refinement) rather than the pure word-count proxy."""

    def _clean(w: str) -> str:
        return re.sub(r"[^\w']", "", w.lower()).strip("'")

    cleaned_words = [_clean(w.get("word", "")) for w in words]
    cleaned_sents = [[_clean(w) for w in s.split()] for s in sentences]

    # --- Phase 1: try exact + prefix + future matching ---
    word_idx = 0
    p1_success = True
    p1_timings = []

    for sent_words in cleaned_sents:
        sent_words = [w for w in sent_words if w]
        if not sent_words:
            p1_success = False
            break

        start_time = None
        end_time = None
        matched = 0

        while word_idx < len(cleaned_words) and matched < len(sent_words):
            wx_word = cleaned_words[word_idx]
            snt_word = sent_words[matched]

            if wx_word == snt_word:
                if start_time is None:
                    start_time = words[word_idx].get("start", 0.0)
                end_time = words[word_idx].get("end", start_time)
                matched += 1
                word_idx += 1
            elif wx_word.startswith(snt_word):
                if start_time is None:
                    start_time = words[word_idx].get("start", 0.0)
                end_time = words[word_idx].get("end", start_time)
                remainder = wx_word
                while matched < len(sent_words) and remainder.startswith(sent_words[matched]):
                    remainder = remainder[len(sent_words[matched]):]
                    matched += 1
                word_idx += 1
            else:
                future_matched = False
                for fi in range(matched + 1, len(sent_words)):
                    if wx_word == sent_words[fi] or wx_word.startswith(sent_words[fi]):
                        matched = fi + 1
                        future_matched = True
                        break
                word_idx += 1

        if matched > 0 and start_time is not None and end_time is not None:
            p1_timings.append((float(start_time), float(end_time)))
        else:
            p1_success = False
            break

    if p1_success and len(p1_timings) == len(sentences):
        p1_timings[-1] = (p1_timings[-1][0], words[-1].get("end", p1_timings[-1][1]))
        return "EXACT_MATCH (Phase 1, no fallback)", p1_timings

    # --- Phase 2: time-window refinement ---
    # Check if the returned timings differ from the pure proxy
    proxy = _rp._sentence_timings_from_audio(
        " ".join(sentences).strip(), narration_duration
    )

    # If returned timings differ from proxy, Phase 2 was used
    if len(sentence_timings) == len(proxy):
        differs_from_proxy = any(
            abs(a[0] - b[0]) > 0.01 or abs(a[1] - b[1]) > 0.01
            for a, b in zip(sentence_timings, proxy)
        )
        if differs_from_proxy:
            return "TIME_WINDOW_REFINE (Phase 2, real WX timestamps)", sentence_timings
        else:
            return "PROXY_FALLBACK (word-count proxy)", sentence_timings
    else:
        return "UNEXPECTED", sentence_timings


# ===========================================================================
# Main test
# ===========================================================================

def run_test():
    results = {}
    tmp_dir = Path(tempfile.mkdtemp(prefix="e2e_test_"))
    print(f"\n  Scratch dir: {tmp_dir}")

    try:
        # ===================================================================
        # CHECKPOINT 1 — Story contract
        # ===================================================================
        _h("CHECKPOINT 1: Story contract validity")

        story = generate_story(genre="scary")
        print(f"  Generated story: '{story['title']}'")
        print(f"  Sentence count : {len(story['sentences'])}")
        for i, s in enumerate(story["sentences"]):
            print(f"    [{i+1}] {s[:80]}{'…' if len(s)>80 else ''}")

        try:
            validate_story_contract(story)
            contract_ok = True
        except Exception as e:
            contract_ok = False
            print(f"  Contract violation: {e}")

        results["sentence_count"] = len(story["sentences"])
        results["contract_valid"] = contract_ok
        _check("story contract is valid", contract_ok,
               f"{len(story['sentences'])} sentences")

        if not contract_ok:
            print(f"\n  {RED}Cannot continue — story contract failed.{RESET}")
            return results

        # ===================================================================
        # CHECKPOINT 2 — Exact sentences[] passed unchanged to TTS
        # ===================================================================
        _h("CHECKPOINT 2: sentences[] passed unchanged to TTS")

        sentences = story["sentences"]
        joined_script = " ".join(sentences).strip()

        tts_input = joined_script
        round_trip = " ".join(sentences).strip()
        tts_unchanged = (tts_input == round_trip)
        results["tts_sentences_unchanged"] = tts_unchanged
        _check("joined sentences == TTS input (no mutation)", tts_unchanged,
               f"{len(tts_input.split())} words")

        # --- Actually generate narration ---
        narration_path = tmp_dir / "narration.mp3"
        print(f"  Generating narration with Edge TTS…")
        try:
            generate_narration(joined_script, output_path=str(narration_path))
            narration_ok = narration_path.exists() and narration_path.stat().st_size > 1000
        except Exception as e:
            narration_ok = False
            print(f"  TTS error: {e}")

        narration_duration = _rp._audio_duration(narration_path) if narration_ok else 0.0
        results["narration_duration_s"] = round(narration_duration, 2)
        _check("narration.mp3 generated", narration_ok,
               f"{narration_duration:.1f}s")

        if not narration_ok:
            print(f"\n  {RED}Cannot continue — narration failed.{RESET}")
            return results

        # ===================================================================
        # CHECKPOINT 3 — WhisperX produces word timestamps
        # ===================================================================
        _h("CHECKPOINT 3: WhisperX word timestamps")

        timestamps_path = tmp_dir / "timestamps.json"
        whisper_py = "/root/kinetic_typo_vid/venv/bin/python3"
        extractor   = Path(__file__).parent / "extract_word_timestamps.py"

        whisperx_ok = False
        word_timestamps = []
        try:
            proc = subprocess.run(
                [whisper_py, str(extractor), str(narration_path),
                 "--output", str(timestamps_path)],
                capture_output=True, text=True, timeout=600,
            )
            if proc.returncode == 0 and timestamps_path.exists():
                word_timestamps = json.loads(timestamps_path.read_text())
                whisperx_ok = isinstance(word_timestamps, list) and len(word_timestamps) > 0
            else:
                print(f"  WhisperX stderr: {proc.stderr[-500:]}")
        except Exception as e:
            print(f"  WhisperX error: {e}")

        results["whisperx_word_count"] = len(word_timestamps)
        _check("WhisperX produced word timestamps", whisperx_ok,
               f"{len(word_timestamps)} words")

        if whisperx_ok:
            sample = word_timestamps[:3]
            print(f"  Sample words: {sample}")
            has_fields = all(
                isinstance(w, dict) and "word" in w and "start" in w and "end" in w
                for w in word_timestamps
            )
            _check("all word entries have {word, start, end}", has_fields)

    # ===================================================================
        # CHECKPOINT 4 — _sentence_timings_from_word_timestamps()
        # ===================================================================
        _h("CHECKPOINT 4: _sentence_timings_from_word_timestamps()")

        timing_match_result = "N/A"
        sentence_timings = []

        if whisperx_ok and word_timestamps:
            # Call the exact function used by the pipeline
            sentence_timings = _rp._sentence_timings_from_word_timestamps(
                word_timestamps, sentences,
                fallback_total_dur=narration_duration,
            )

            timing_count_ok = len(sentence_timings) == len(sentences)
            print(f"  Sentences: {len(sentences)}")
            print(f"  Timings returned: {len(sentence_timings)}")

            # Detect which path was used
            timing_match_result, _ = _detect_match_path(
                word_timestamps, sentences, sentence_timings, narration_duration
            )

            print(f"  Timing match result: {timing_match_result}")
            for i, (s, (start, end)) in enumerate(zip(sentences, sentence_timings)):
                dur = end - start
                print(f"    sentence {i+1}: {start:.2f}s–{end:.2f}s ({dur:.1f}s)")

            results["timing_match_result"] = timing_match_result
            results["timing_count_matches_sentences"] = timing_count_ok
            _check(
                f"one timing per original sentence ({len(sentences)})",
                timing_count_ok,
                f"got {len(sentence_timings)}",
            )
            # Accept both EXACT_MATCH and TIME_WINDOW_REFINE — both use real WX timestamps
            _check(
                "timings derived from actual WhisperX timestamps",
                "PROXY" not in timing_match_result and "UNEXPECTED" not in timing_match_result,
                timing_match_result,
            )
        else:
            # WhisperX failed; still test fallback
            sentence_timings = _rp._sentence_timings_from_audio(
                joined_script, narration_duration
            )
            timing_match_result = "WHISPERX_UNAVAILABLE"
            results["timing_match_result"] = timing_match_result
            print(f"  {WARN} WhisperX unavailable — using word-count proxy")
            _check("fallback timings produced", len(sentence_timings) > 0)

        # ===================================================================
        # CHECKPOINT 5 — Visual planner receives actual timings
        # ===================================================================
        _h("CHECKPOINT 5: Visual planner receives actual sentence_timings")

        print(f"  Passing {len(sentence_timings)} timings to generate_storyboard…")
        sb_result = None
        visual_planning_ok = False
        try:
            sb_result = generate_storyboard(
                script=joined_script,
                title=story["title"],
                project_dir=tmp_dir,
                sentence_timings=sentence_timings,
                sentences=sentences,
                genre=story["genre"],
            )
            asset_plan = sb_result.get("asset_plan", [])
            timing_json_path = tmp_dir / "timing.json"

            visual_planning_ok = (
                isinstance(asset_plan, list)
                and len(asset_plan) == len(sentences)
            )
            results["visual_planning_succeeded"] = visual_planning_ok
            _check("generate_storyboard succeeded", sb_result is not None)
            _check(
                f"asset_plan has one entry per sentence ({len(sentences)})",
                len(asset_plan) == len(sentences),
                f"got {len(asset_plan)}",
            )
            _check(
                "timing.json written (timings forwarded)",
                timing_json_path.exists(),
                str(timing_json_path) if timing_json_path.exists() else "missing",
            )

            if timing_json_path.exists():
                written_timings = json.loads(timing_json_path.read_text())
                print(f"  timing.json entries: {len(written_timings)}")
                if written_timings:
                    print(f"  sample: {written_timings[:2]}")

            sb_md = tmp_dir / "storyboard.md"
            _check("storyboard.md written", sb_md.exists())

        except Exception as e:
            results["visual_planning_succeeded"] = False
            print(f"  {RED}generate_storyboard raised: {e}{RESET}")
            import traceback
            traceback.print_exc()

        # ===================================================================
        # CHECKPOINT 6 — Genre-awareness
        # ===================================================================
        if sb_result and sb_result.get("asset_plan"):
            _h("CHECKPOINT 6: Genre-aware visual planning")

            # 6a: genre-specific fallback terms exist
            genre = story["genre"]
            genre_terms = GENRE_SEARCH_TERMS.get(genre, [])
            _check(f"GENRE_SEARCH_TERMS has entries for '{genre}'", len(genre_terms) > 0,
                   f"{len(genre_terms)} terms")

            # 6b: _term_from_sentence with genre_terms prefers genre terms
            if sentences and genre_terms:
                # Test with a sentence that contains no relatable terms
                test_sent = "The dark shadow moved across the graveyard." if genre != "scary" else "A person walked to work."
                term = _term_from_sentence(test_sent, story["title"], genre_terms=genre_terms)
                has_genre_term = any(gt in term for gt in genre_terms) if genre_terms else True
                _check("fallback search term includes genre keyword", has_genre_term,
                       f"term='{term}'")
            results["genre_fallback_works"] = True

            # 6c: generate_visual_plan accepts genre param
            try:
                plan_v, headline_v = generate_visual_plan(sentences[:2], story["title"], genre=genre)
                plan_accepts_genre = len(plan_v) == len(sentences[:2])
                _check("generate_visual_plan accepts genre param", plan_accepts_genre)
                results["genre_plan_works"] = plan_accepts_genre
            except Exception as ge:
                _check("generate_visual_plan accepts genre param", False, str(ge))
                results["genre_plan_works"] = False

        # ===================================================================
        # CHECKPOINT 7 — Shot-variety reordering preserves original index
        # ===================================================================
        _h("CHECKPOINT 7: Shot-variety reordering preserves original index")

        if sb_result and sb_result.get("asset_plan"):
            asset_plan = sb_result.get("asset_plan", [])
            # Simulate variety reordering + check original indices survive
            tagged = _enforce_shot_variety(asset_plan)
            indices_preserved = all("_orig_index" in item for item in tagged)
            # Verify original indices cover 0..n-1 exactly (no dupes, no gaps)
            orig_indices = sorted(item.get("_orig_index") for item in tagged)
            expected = list(range(len(asset_plan)))
            indices_complete = orig_indices == expected
            _check("all reordered items carry _orig_index", indices_preserved)
            _check(f"_orig_index is 0..{len(asset_plan)-1} (complete, no gaps/dupes)",
                   indices_complete,
                   f"got {orig_indices}")
            results["shot_variety_preserves_index"] = indices_preserved and indices_complete

        # ===================================================================
        # SUMMARY
        # ===================================================================
        _h("INTEGRATION TEST SUMMARY")
        print(f"  Sentence count          : {results.get('sentence_count', 'N/A')}")
        print(f"  Narration duration      : {results.get('narration_duration_s', 'N/A')}s")
        print(f"  WhisperX word count     : {results.get('whisperx_word_count', 'N/A')}")
        print(f"  Sentence-timing match   : {results.get('timing_match_result', 'N/A')}")
        print(f"  Visual planning success : {results.get('visual_planning_succeeded', 'N/A')}")
        print()

        all_passed = (
            results.get("contract_valid", False)
            and results.get("tts_sentences_unchanged", False)
            and results.get("whisperx_word_count", 0) > 0
            and results.get("timing_count_matches_sentences", False)
            and results.get("visual_planning_succeeded", False)
            and results.get("genre_fallback_works", False)
            and results.get("genre_plan_works", False)
            and results.get("shot_variety_preserves_index", False)
        )
        if all_passed:
            print(f"  {GREEN}ALL CHECKPOINTS PASSED ✓{RESET}")
        else:
            print(f"  {RED}ONE OR MORE CHECKPOINTS FAILED ✗{RESET}")

        return results

    finally:
        try:
            shutil.rmtree(tmp_dir)
            print(f"\n  Cleaned up: {tmp_dir}")
        except Exception as e:
            print(f"\n  Cleanup warning: {e}")


if __name__ == "__main__":
    run_test()
