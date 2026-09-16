"""
storyboard_generator.py
Steps 5-6 of the Shorts pipeline: Groq-driven visual storyboard + asset plan.

For each sentence of the script, Groq produces:
  - a plain-English visual description (for the storyboard)
  - a concrete Pexels search term (relatable, non-jargon, searches well)
  - a media_type hint: "video" (default) or "photo" (still with motion fallback)

Generates:
  - storyboard.md          — shot-by-shot visual plan (real per-sentence visuals)
  - captions.srt           — subtitle reference file (timed from real narration
                             when sentence_timings is provided; else estimated)
  - asset_plan.json        — per-sentence [{sentence, search_term, media_type, visual}]
  - timing.json            — per-sentence (start, end) timings used (written so the
                             video assembler reads the SAME timings and stays in sync)
  - thumbnail_notes.txt    — thumbnail design notes

Falls back to keyword-based defaults if Groq is unavailable, so a Groq hiccup
can never hard-fail the pipeline.
"""

import re
import json
from pathlib import Path

try:
    import llm_client
    def _call_groq(messages, model_key=None, temperature=0.4):
        key = model_key or llm_client.DEFAULT_MODEL_KEY
        return llm_client.call_llm(messages, model_key=key, temperature=temperature, max_tokens=2048)
except Exception:  # pragma: no cover - import-only safety net
    _call_groq = None



VISUAL_PLAN_SYSTEM_PROMPT = """You plan the VISUALS for a faceless YouTube Short.
You are given a narration script already split into sentences, plus the title
and the story's genre (scary, mystery, moral, or motivational).

For EACH sentence, decide one concrete stock-footage visual that matches what is
actually being said at that moment — so the on-screen clip aligns with the words.
Match the genre's mood: scary visuals should be dark and unsettling, mystery
should feel investigative and tense, moral should be thoughtful and reflective,
motivational should be uplifting and triumphant.

Audience is the GENERAL PUBLIC (non-tech). The clips are free stock from Pexels,
so think in terms of real-world, searchable footage: people, objects, places,
everyday situations. NOT tech jargon, NOT abstract renders.

For each sentence return a JSON object with:
  "sentence":     the sentence text, copied verbatim from the input,
  "visual":       one-line plain-English description of the on-screen visual,
                  tied to THAT sentence's meaning,
  "search_term":  a concrete 2-4 word Pexels search term for that visual
                  (relatable, low-jargon, e.g. "city traffic night",
                  "person phone surprised", "money coins falling",
                  "office desk typing"). Choose terms that actually return good
                  stock footage,
  "media_type":   "video" if a stock video clearly fits, otherwise "photo"
                  (a striking still — a landmark, a face, a specific object).

ALSO produce a SHORT "headline" for the on-screen hook text: a punchy 3-6 word
phrase a non-tech person would click on, tied to the most surprising/relatable
thing in the script. NOT the raw news title. Plain words, no jargon, no emoji.

Return ONLY a JSON object (no fences, no preamble) shaped as:
  {"head": [{"sentence":...,"visual":...,"search_term":...,"media_type":...}, ...],
   "headline": "<the punchy on-screen hook text>"}
The "head" array length MUST equal the number of sentences you received.
"""


def generate_visual_plan(sentences: list[str], title: str, model_key: str = None, genre: str = None) -> tuple:
    """Ask LLM for a per-sentence visual plan + a punchy on-screen headline.

    Returns (plan, headline):
      - plan: list of dicts (len == len(sentences)), each with
        sentence/visual/search_term/media_type. Keyword-fallback on failure.
      - headline: a short punchy on-screen hook phrase ("" if unavailable).
    """
    if not sentences:
        return [], ""

    if _call_groq is None:
        return _fallback_visual_plan(sentences, title, genre=genre), _fallback_headline(title, genre=genre)

    user_prompt = (
        f"Title: {title}\n"
        + (f"Genre: {genre}\n" if genre else "")
        + "\nSentences (one visual per sentence, in order):\n"
        + "\n".join(f"{i+1}. {s}" for i, s in enumerate(sentences))
    )
    try:
        raw = _call_groq(
            [
                {"role": "system", "content": VISUAL_PLAN_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model_key=model_key,
            temperature=0.4,
        )
    except Exception as e:
        print(f"  [storyboard] LLM visual-plan failed ({e}); using keyword fallback.")
        return _fallback_visual_plan(sentences, title), _fallback_headline(title)

    plan_raw, headline = _parse_plan_object(raw)
    plan = plan_raw
    if not plan or len(plan) != len(sentences):
        print(f"  [storyboard] Groq returned {len(plan) if plan else 0} visuals "
              f"for {len(sentences)} sentences; using keyword fallback.")
        return _fallback_visual_plan(sentences, title, genre=genre), (headline or _fallback_headline(title, genre=genre))

    # Normalize + pin each entry to its sentence so ordering never drifts.
    norm = []
    for i, s in enumerate(sentences):
        entry = plan[i] if i < len(plan) else {}
        norm.append({
            "sentence": s,
            "visual": str(entry.get("visual") or "").strip() or s,
            "search_term": str(entry.get("search_term") or "").strip()
            or _term_from_sentence(s),
            "media_type": "photo" if str(entry.get("media_type", "")).lower()
            == "photo" else "video",
        })
    h = (str(headline or "")).strip() or _fallback_headline(title)
    return norm, h


def _parse_plan_object(raw: str) -> tuple:
    """Parse the wrapped {head:[...], headline:"..."} object."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(),
                         flags=re.MULTILINE).strip()
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError:
            return None, ""
    # tolerate Groq returning a bare array (old shape)
    if isinstance(obj, list):
        return obj, ""
    if isinstance(obj, dict):
        return obj.get("head") or obj.get("segments") or [], obj.get("headline") or ""
    return None, ""


def _fallback_headline(title: str, genre: str = None) -> str:
    """A best-effort headline when Groq is unavailable — trimmed from the title."""
    genre_headlines = {
        "scary": "Wait... what was that?",
        "mystery": "What happened here?",
        "moral": "The choice that changed everything",
        "motivational": "You were born for this",
    }
    if genre and genre.lower() in genre_headlines:
        return genre_headlines[genre.lower()]
    t = (title or "").strip()
    if not t:
        return "Wait... what?"
    # first 6 words
    words = re.findall(r"[A-Za-z0-9'%]+", t)
    return (" ".join(words[:6])).strip() or t


def _fallback_visual_plan(sentences: list[str], title: str, genre: str = None) -> list[dict]:
    """Keyword-based per-sentence plan when Groq is unavailable.

    Genre-aware: picks search terms and visual descriptions that match the
    story's genre when the RELATABLE_TERMS list doesn't yield a match.
    """
    genre_terms = GENRE_SEARCH_TERMS.get((genre or "").lower(), [])
    return [
        {
            "sentence": s,
            "visual": _fallback_visual_desc(s, genre) if genre else f"Relatable scene for: {s}",
            "search_term": _term_from_sentence(s, title, genre_terms=genre_terms),
            "media_type": "video",
        }
        for s in sentences
    ]


def _fallback_visual_desc(sentence: str, genre: str = None) -> str:
    """Pick a genre-flavored visual description string for fallback mode."""
    genre_visuals = {
        "scary": "Dark, ominous scene",
        "mystery": "Mysterious, investigative scene",
        "moral": "Thoughtful, reflective scene",
        "motivational": "Uplifting, inspiring scene",
    }
    prefix = genre_visuals.get((genre or "").lower(), "Relatable scene")
    return f"{prefix} for: {sentence}"


GREYHOUND_GENRE_TERMS = {
    "scary": ["dark", "shadow", "night", "fog", "ghost", "eerie", "creepy",
              "abandoned", "graveyard", "blood", "haunted", "darkness", "ominous"],
    "mystery": ["investigation", "detective", "clues", "mystery", "suspense",
                "crime", "investigator", "magnifying", "noir", "dark"],
    "moral": ["lesson", "choice", "consequence", "ethics", "decision",
              "regret", "reflection", "wisdom", "karma", "judgment"],
    "motivational": ["success", "achievement", "winner", "goal", "overcome",
                     "victory", "triumph", "growth", "inspiration", "winner"],
}


def _term_from_sentence(sentence: str, title: str = "", genre_terms: list = None) -> str:
    """Derive a 2-4 word Pexels search term from a sentence's words.

    If genre_terms are provided, they are checked first so genre-specific
    imagery is preferred over generic relatable terms.
    """
    combined = (title + " " + sentence).lower()
    RELATABLE_TERMS = [
        "money", "phone", "work", "job", "writing", "email", "photo", "video",
        "music", "game", "shopping", "travel", "food", "health", "school",
        "car", "house", "robot", "future", "city", "night", "coffee", "office",
        "computer", "laptop", "typing", "reading", "people", "business",
    ]
    # Prefer genre-specific terms first so imagery matches the story's mood.
    found = []
    if genre_terms:
        found = [t for t in genre_terms if t in combined]
    if not found:
        found = [t for t in RELATABLE_TERMS if t in combined]
    if found:
        return " ".join(found[:3])
    # fall back to the first few non-stopwords of the sentence itself
    words = [w for w in re.findall(r"[a-z]+", sentence.lower())
             if w not in ("the", "a", "an", "and", "of", "to", "in", "is",
                          "it", "that", "this", "you", "your", "for", "on",
                          "with", "as", "are", "be", "but", "or", "so", "now")]
    return " ".join(words[:3]) or "technology"


def generate_storyboard(script: str, title: str, project_dir: Path,
                        sentence_timings: list[tuple] = None,
                        plan: list[dict] = None,
                        headline: str = None,
                        sentences: list[str] = None,
                        model_key: str = None,
                        genre: str = None) -> dict:
    """Parse a script into visual shots and write all plan files.

    Args:
        script: narration text.
        title: story title.
        project_dir: where to write outputs.
        sentence_timings: optional list of (start, end) floats timed from the
            REAL narration audio, one per sentence. When provided, captions and
            shot durations use these (no drift). When None, durations are
            estimated from word counts (legacy behaviour).
        plan: optional per-sentence plan already produced (each item: sentence/sub_shots).
            When provided, the storyboard uses it directly.
            When None, calls generate_visual_plan().
        headline: optional chosen on-screen headline.
            Falls back to generate_visual_plan()/_fallback_headline when None.
        sentences: optional list of pre-split sentences (e.g. from story_generator).
            When provided, the script is NOT split again, preventing drift.
        model_key: optional LLM model key for generate_visual_plan.
        genre: optional story genre ("scary", "mystery", "moral", "motivational")
            for genre-aware fallback plan and search terms.
    """
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    if sentences is None:
        sentences = _split_into_sentences(script)
    if not script and sentences:
        script = " ".join(sentences)

    # Per-sentence visual plan + on-screen headline.
    if plan is not None:
        # The new format has sub_shots per sentence. We need to expand this into
        # a flat list of visual entries for the asset collector, while keeping
        # track of sentence boundaries for the assembler.
        norm = []
        sentence_to_asset_indices = []  # tracks which asset indices belong to each sentence
        for i, s in enumerate(sentences):
            entry = plan[i] if i < len(plan) else {}
            sub_shots = entry.get("sub_shots", [])
            if not sub_shots:
                # fallback: at least one sub_shot per sentence
                sub_shots = [{
                    "search_term": _term_from_sentence(s),
                    "media_type": "video",
                    "visual_description": s
                }]

            asset_start_idx = len(norm)
            for ss in sub_shots:
                term = str(ss.get("search_term") or "").strip() or _term_from_sentence(s)
                norm.append({
                    "sentence": s,
                    "visual": str(ss.get("visual_description") or "").strip() or term,
                    "search_term": term,
                    "media_type": "photo" if str(ss.get("media_type", "")).lower() == "photo" else "video",
                })
            asset_end_idx = len(norm)
            sentence_to_asset_indices.append((asset_start_idx, asset_end_idx))

        plan = norm
        headline = (str(headline or "")).strip() or _fallback_headline(title)
        print(f"  Using pre-computed visual plan ({len(plan)} assets across {len(sentences)} sentences) — no extra Groq call")
    else:
        print(f"  Planning visuals + headline for {len(sentences)} sentence(s)...")
        plan, headline = generate_visual_plan(sentences, title, model_key=model_key, genre=genre)
        # For legacy format, each sentence = 1 asset
        sentence_to_asset_indices = [(i, i+1) for i in range(len(sentences))]

    # Resolve per-sentence timings: prefer real narration timings; else estimate.
    timings = _resolve_timings(sentences, sentence_timings)

    # Distribute sentence durations across sub_shots for each asset in plan.
    # Each sentence's duration should be split among its sub_shots.
    plan = _distribute_subshot_durations(plan, timings, sentence_to_asset_indices)

    # Build shot list from the real plan + timings.
    shots = _build_shot_list(sentences, title, plan, timings, sentence_to_asset_indices)

    # Write storyboard
    storyboard_path = project_dir / "storyboard.md"
    storyboard_path.write_text(
        _format_storyboard_md(shots, title, script), encoding="utf-8"
    )

    # Write captions (reference file — NOT burned into the video anymore).
    captions_path = project_dir / "captions.srt"
    captions_path.write_text(
        _generate_srt(sentences, timings), encoding="utf-8"
    )

    # Write the real per-sentence asset plan + the timings (read by assembler).
    keywords = _dedupe_preserve([p["search_term"] for p in plan if p["search_term"]])
    asset_plan = {
        "per_sentence": plan,
        "headline": headline,
        "keywords_for_stock_search": keywords,
        "free_stock_sources": [
            "https://pexels.com (free, no API key for manual download)",
            "https://pixabay.com (free, no API key)",
            "https://coverr.co (free stock video)",
            "https://mixkit.co (free stock video)",
        ],
        "suggested_bgm_mood": _suggest_bgm_mood(title, script),
        "sentence_to_asset_indices": sentence_to_asset_indices,
    }
    (project_dir / "asset_plan.json").write_text(
        json.dumps(asset_plan, indent=2), encoding="utf-8"
    )
    (project_dir / "timing.json").write_text(
        json.dumps([{"start": round(a, 3), "end": round(b, 3)}
                    for a, b in timings], indent=2), encoding="utf-8"
    )

    # On-screen hook headline (written to a file; NOT burned into the video —
    # the user adds on-screen text themselves).
    (project_dir / "headline.txt").write_text(
        (headline or "").strip() + "\n", encoding="utf-8"
    )

    # Write thumbnail notes
    (project_dir / "thumbnail_notes.txt").write_text(
        _format_thumbnail_notes(title, keywords, script), encoding="utf-8"
    )

    return {
        "shots": shots,
        "keywords": keywords,
        "asset_plan": plan,
        "headline": headline,
        "timings": timings,
        "files_written": [
            str(storyboard_path),
            str(captions_path),
            str(project_dir / "asset_plan.json"),
            str(project_dir / "timing.json"),
            str(project_dir / "headline.txt"),
            str(project_dir / "thumbnail_notes.txt"),
        ],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_into_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _resolve_timings(sentences: list[str],
                     sentence_timings: list[tuple] = None) -> list[tuple]:
    """Return one (start, end) per sentence.

    If real narration timings are provided (and match the sentence count), use
    them directly. Otherwise estimate from word counts (18-45s total), as the
    legacy code did.
    """
    if sentence_timings and len(sentence_timings) == len(sentences):
        return [(float(a), float(b)) for a, b in sentence_timings]

    total_words = sum(len(s.split()) for s in sentences)
    total_duration = max(18, min(total_words / 3.2, 45))
    timings = []
    cur = 0.0
    for i, s in enumerate(sentences):
        wc = len(s.split())
        if total_words > 0:
            weight = 0.8 if i == 0 else (1.2 if i == len(sentences) - 1 else 1.0)
            dur = max(1.8, (wc / total_words) * total_duration)
        else:
            dur = 2.0
        # apply the legacy hook/closing weight only in estimate mode
        if sentence_timings is None and total_words > 0:
            dur = max(1.8, (wc / total_words) * total_duration * weight)
        timings.append((cur, cur + dur))
        cur += dur
    return timings


def _distribute_subshot_durations(plan: list[dict], timings: list[tuple],
                                    sentence_to_asset_indices: list[tuple]) -> list[dict]:
    """Distribute sentence durations across sub_shots for each asset in plan.

    Each sentence has a start/end time. We split the duration evenly across
    all sub_shots (assets) for that sentence. The result is a new plan with
    duration_seconds added to each entry.
    """
    if not timings or not sentence_to_asset_indices:
        # Fallback: no timing info, keep original plan
        return plan

    result = []
    for i, entry in enumerate(plan):
        new_entry = dict(entry)  # copy the entry

        # Find which sentence this asset belongs to
        for sent_idx, (asset_start, asset_end) in enumerate(sentence_to_asset_indices):
            if asset_start <= i < asset_end:
                # Calculate how many assets are in this sentence
                sent_duration = timings[sent_idx][1] - timings[sent_idx][0]
                n_assets_in_sentence = asset_end - asset_start
                position_in_sent = i - asset_start

                # Distribute duration evenly (sub_shots share the sentence duration)
                # For longer sentences, this may mean each sub_shot gets less than max duration
                # The video assembler will handle looping if needed
                if n_assets_in_sentence > 0:
                    # Each sub_shot gets an equal portion
                    shot_duration = sent_duration / n_assets_in_sentence
                else:
                    shot_duration = sent_duration

                new_entry["duration_seconds"] = round(shot_duration, 3)
                break
        else:
            # Asset not in any sentence - use a default
            new_entry["duration_seconds"] = 2.0

        result.append(new_entry)

    return result


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen, out = set(), []
    for it in items:
        k = it.lower()
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


def _build_shot_list(sentences: list[str], title: str,
                     plan: list[dict], timings: list[tuple],
                     sentence_to_asset_indices: list[tuple] = None) -> list[dict]:
    shots = []
    n = len(sentences)

    # If sentence_to_asset_indices not provided (legacy format), each sentence = 1 asset
    if sentence_to_asset_indices is None:
        sentence_to_asset_indices = [(i, i+1) for i in range(len(sentences))]

    for i, (sentence, (start, end)) in enumerate(zip(sentences, timings)):
        asset_start, asset_end = sentence_to_asset_indices[i]
        assets_for_sentence = plan[asset_start:asset_end]

        # Use the first asset's visual for the shot description
        visual = assets_for_sentence[0].get("visual", sentence) if assets_for_sentence else sentence

        # Transition/zoom choices: punchy hook in, gentle motion in body,
        # slow close out. These are editorial hints, not the asset itself.
        if i == 0:
            transition = "fade in (0.3s)"
            zoom = "fast zoom in (110%)"
        elif i == n - 1:
            transition = "fade out (0.8s)"
            zoom = "slow zoom out (95%)"
        else:
            transition = "cross dissolve (0.3s)"
            zoom = "slow zoom in (105%)"

        shots.append({
            "shot": i + 1,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration_seconds": round(end - start, 3),
            "text": sentence,
            "search_term": assets_for_sentence[0].get("search_term", "") if assets_for_sentence else "",
            "media_type": assets_for_sentence[0].get("media_type", "video") if assets_for_sentence else "video",
            "is_hook": i == 0,
            "is_closing": i == n - 1,
            "visual_suggestion": visual,
            "transition": transition,
            "zoom_effect": zoom,
            # Store the sub_asset info for the assembler
            "sub_assets": assets_for_sentence,
        })
    return shots


def _format_storyboard_md(shots: list[dict], title: str, script: str) -> str:
    lines = [f"# Storyboard: {title}", "", "## Full Script", "", script, "",
             "---", "", "## Shot List", "",
             "| Shot | Start | Dur | Visual | Search Term | Type | Transition | Zoom |",
             "|------|-------|-----|--------|-------------|------|------------|------|"]
    for s in shots:
        hook_mark = "⭐ HOOK" if s["is_hook"] else ("📺 Close" if s["is_closing"] else "")
        lines.append(
            f"| {s['shot']} | {s['start']:.1f}s | {s['duration_seconds']:.1f}s | "
            f"{s['visual_suggestion'][:50]}... | {s['search_term']} | "
            f"{s['media_type']} | {s['transition']} | {s['zoom_effect']} |"
        )
    lines += ["", "---", ""]
    for s in shots:
        lines.append(f"### Shot {s['shot']} ({s['start']:.1f}–{s['end']:.1f}s, "
                     f"{s['duration_seconds']:.1f}s)")
        lines.append(f"- **Narration:** {s['text']}")
        lines.append(f"- **Visual:** {s['visual_suggestion']}")
        lines.append(f"- **Pexels search:** `{s['search_term']}` ({s['media_type']})")
        lines.append(f"- **Transition:** {s['transition']}")
        lines.append(f"- **Zoom:** {s['zoom_effect']}")
        if s["is_hook"]:
            lines.append("- **⚠ CRITICAL: hook shot — make it fast and punchy.**")
        lines.append("")
    return "\n".join(lines)


def _generate_srt(sentences: list[str], timings: list[tuple]) -> str:
    """Generate an SRT reference file from real (or estimated) timings."""
    lines = []
    for i, (sentence, (start, end)) in enumerate(zip(sentences, timings)):
        lines.append(str(i + 1))
        lines.append(f"{_fmt(start)} --> {_fmt(end)}")
        lines.append(sentence)
        lines.append("")
    return "\n".join(lines)


def _fmt(secs: float) -> str:
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    ms = int((secs - int(secs)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _suggest_bgm_mood(title: str, script: str) -> str:
    combined = (title + " " + script).lower()
    upbeat = sum(1 for w in ["launch", "new", "free", "fast", "save",
                            "money", "easy", "simple"] if w in combined)
    serious = sum(1 for w in ["danger", "risk", "scam", "problem",
                             "warning", "threat", "steal"] if w in combined)
    if serious > upbeat:
        return "Documentary/informative — subtle ambient, low volume"
    elif upbeat > 1:
        return "Upbeat/optimistic — light electronic or lo-fi"
    else:
        return "Neutral/curious — calm piano or ambient"


def _format_thumbnail_notes(title: str, keywords: list[str], script: str) -> str:
    numbers = re.findall(r'\d[\d,]*[kKmMbB%$]?', script)
    number_text = numbers[0] if numbers else "???"
    return "\n".join([
        "# Thumbnail Notes", "",
        "## Goal", "Make a NON-TECH person curious enough to click.", "",
        "## Text Overlay (3-5 words, bold, high contrast)",
        f"Suggestion: \"Free?\" or \"{number_text}\" or \"Wait...\"",
        "- White text with thick black stroke",
        "- Bottom third of the image", "",
        "## Visual",
        "- ONE focal point — no clutter",
        "- Surprised/shocked expression if using a person",
        "- Bold colors (red/yellow accent on dark bg)", "",
        "## Keywords for thumbnail",
        ", ".join(keywords[:5]), "",
        "## DO NOT",
        "- Don't use misleading imagery",
        "- Don't put more than 5 words of text",
        "- Don't make it look like a tech blog", "",
        "## Thumbnail A/B Test Ideas",
        f"1. Text \"{number_text}\" with shocked face",
        "2. Text \"Free?\" with minimalist tech background",
        "3. Question format with curiosity gap",
    ])


if __name__ == "__main__":
    import sys
    script = sys.stdin.read() if not sys.stdin.isatty() else \
        "Imagine getting 3 hours of work done in 30 seconds for free. A tool that " \
        "writes your emails and plans your trips. You can try it right now."
    result = generate_storyboard(script, "Test Video", Path("test_output"))
    print(json.dumps({k: v for k, v in result.items()
                      if k != "files_written"}, indent=2))
