"""Generate structured stories for the scary-stories video pipeline.

Story Input/Output Contract:
----------------------------
Input:
- genre (required, str): Exactly one of "scary", "mystery", "moral", "motivational".
- premise (optional, str | None): Story premise, theme, or prompt hook.
- model_key (optional, str): Model key configured in llm_client.
- length_mode (optional, str): "short" (default, ~170-400 words) or "long"
  (~1,000-2,000 words with deeper narrative structure).

Output:
- JSON-compatible dict exactly containing:
  {
      "title": str,
      "genre": str,
      "sentences": list[str]
  }
- "sentences" contains the authoritative narration sentence-by-sentence in spoken order.
  It must NOT contain visual directions, timestamps, sound effects, narration labels,
  or other metadata.
- Sentence count and sentence word count are flexible and must NOT be artificially
  enforced, because these exact sentences are passed unchanged to TTS and later
  matched against WhisperX word timestamps.
"""

import json
import re

import llm_client


DEFAULT_MAX_TOKENS = 6096
DEFAULT_MAX_TOKENS_LONG = 15288

ALLOWED_GENRES = ("scary", "mystery", "moral", "motivational")
ALLOWED_LENGTH_MODES = ("short", "long")
REQUIRED_STORY_KEYS = {"title", "genre", "sentences"}

METADATA_PATTERNS = [
    (re.compile(r"^\s*(?:narrator|voiceover|voice\s*over|v\.o\.|speaker(?:\s*\d+)?|host)\s*:\s*", re.IGNORECASE), "narration label"),
    (re.compile(r"(?i)\b(?:sfx|sound effect|bgm)\s*:", re.IGNORECASE), "sound effect label"),
    (re.compile(r"\[\s*(?:sfx|sound effect?|sound|music|audio|bgm)\b[^\]]*\]", re.IGNORECASE), "bracketed sound effect"),
    (re.compile(r"\(\s*(?:sfx|sound effect?|sound|music|audio|bgm)\b[^\)]*\)", re.IGNORECASE), "parenthetical sound effect"),
    (re.compile(r"(?i)\b(?:visual|camera|shot|scene)\s*:", re.IGNORECASE), "visual direction label"),
    (re.compile(r"\[\s*(?:camera|visual|shot|scene|cut to|fade to|fade in|close[- ]up|wide shot|zoom)\b[^\]]*\]", re.IGNORECASE), "bracketed visual direction"),
    (re.compile(r"\(\s*(?:camera|visual|shot|scene|cut to|fade to|fade in|close[- ]up|wide shot|zoom)\b[^\)]*\)", re.IGNORECASE), "parenthetical visual direction"),
    (re.compile(r"^\s*\[.*\]\s*$"), "bracketed direction"),
    (re.compile(r"\[\s*\d{1,2}:\d{2}(?::\d{2})?\s*\]"), "bracketed timestamp"),
    (re.compile(r"\(\s*\d{1,2}:\d{2}(?::\d{2})?\s*\)"), "parenthetical timestamp"),
    (re.compile(r"(?i)\btimestamp\s*:\s*\d"), "timestamp label"),
    (re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s*[:-]"), "leading timestamp"),
]


def find_sentence_metadata_artifacts(sentence: str) -> list[str]:
    """Identify forbidden visual directions, timestamps, sound effects, or labels in a sentence."""
    artifacts = []
    for pattern, desc in METADATA_PATTERNS:
        if pattern.search(sentence):
            artifacts.append(desc)
    return artifacts


def _clean_sentence(s: str) -> str:
    """Strip accidental narrator/speaker labels while preserving spoken narration."""
    s = s.strip()
    s = re.sub(
        r"^\s*(?:narrator|voiceover|voice\s*over|v\.o\.|speaker(?:\s*\d+)?|host)\s*:\s*",
        "",
        s,
        flags=re.IGNORECASE,
    ).strip()
    return s


def validate_story_contract(story: dict) -> None:
    """Enforce the strict story contract on a story dictionary.

    Contract specification:
    - Must be a JSON-compatible dict.
    - Exact keys: {"title", "genre", "sentences"} (no extra keys, no missing keys).
    - title: non-empty str.
    - genre: str, strictly one of "scary", "mystery", "moral", "motivational".
    - sentences: non-empty list of non-empty str in spoken narration order.
    - No visual directions, timestamps, sound effects, labels, or other metadata in sentences.
    - Sentence count and word count per sentence are flexible and must NOT be artificially
      enforced, because these exact sentences are passed unchanged to TTS and later
      matched against WhisperX word timestamps.

    Raises:
        TypeError: If top-level or field types are invalid.
        ValueError: If keys, values, genres, sentence contents, or serialization violate the contract.
    """
    if not isinstance(story, dict):
        raise TypeError(f"Story must be a dict, got {type(story).__name__}")

    try:
        json.dumps(story)
    except (TypeError, OverflowError) as exc:
        raise ValueError(f"Story dict must be JSON-compatible: {exc}") from exc

    story_keys = set(story.keys())
    if story_keys != REQUIRED_STORY_KEYS:
        extra = story_keys - REQUIRED_STORY_KEYS
        missing = REQUIRED_STORY_KEYS - story_keys
        reasons = []
        if missing:
            reasons.append(f"missing required keys: {sorted(missing)}")
        if extra:
            reasons.append(f"unexpected extra keys: {sorted(extra)}")
        raise ValueError(
            f"Story dict keys do not match contract ({'; '.join(reasons)}). "
            f"Expected exactly: {sorted(REQUIRED_STORY_KEYS)}"
        )

    title = story["title"]
    if not isinstance(title, str):
        raise TypeError(f"Story title must be a str, got {type(title).__name__}")
    if not title.strip():
        raise ValueError("Story title must be a non-empty string.")

    genre = story["genre"]
    if not isinstance(genre, str):
        raise TypeError(f"Story genre must be a str, got {type(genre).__name__}")
    if genre.strip().lower() not in ALLOWED_GENRES:
        raise ValueError(
            f"Invalid genre {genre!r}. Must be one of: {', '.join(ALLOWED_GENRES)}"
        )

    sentences = story["sentences"]
    if not isinstance(sentences, list):
        raise TypeError(
            f"Story sentences must be a list of strings, got {type(sentences).__name__}"
        )
    if not sentences:
        raise ValueError("Story sentences list must be non-empty.")

    for i, s in enumerate(sentences):
        if not isinstance(s, str):
            raise TypeError(
                f"Sentence {i + 1} must be a str, got {type(s).__name__}"
            )
        if not s.strip():
            raise ValueError(f"Sentence {i + 1} is empty or whitespace-only.")

        artifacts = find_sentence_metadata_artifacts(s)
        if artifacts:
            raise ValueError(
                f"Sentence {i + 1} contains forbidden non-narration metadata "
                f"({', '.join(artifacts)}): {s!r}"
            )


STORY_SYSTEM_PROMPT = """You write original, engaging, and coherent short-form stories for narrated vertical-video Shorts.

Your stories must grab attention in the first sentence, escalate naturally, and deliver a satisfying payoff. Aim for approximately 170-400 words across 15-30 natural sentences — giving the narrative enough sentence-level beats for varied visuals and pacing. Treat both word count and sentence count as flexible guidelines, never hard constraints.

STORY QUALITY REQUIREMENTS:
- **Strong hook**: The first sentence should make the viewer stop scrolling.
- **Natural escalation**: Build tension, stakes, or emotional weight scene by scene.
- **Concrete details**: Use specific nouns, sensory language, and grounded imagery rather than vague abstractions.
- **Varied pacing**: Mix longer flowing sentences with punchy, impactful ones for rhythm.
- **Genre-appropriate tone**: Match the requested genre's conventions and emotional palette.
- **Satisfying payoff**: Every story needs an ending that resolves the central conflict or reveals something meaningful.
- **Originality**: Avoid clichés, recycled plots, stock horror tropes, and generic motivational language. Surprise the viewer.

SENTENCE GUIDELINES:
- 10-15 words per sentence is a natural baseline, but let length follow the story's needs.
- Do NOT force a sentence to meet a word-count target.
- Do NOT use a fixed number of sentences.
- Do NOT artificially split or combine sentences just to satisfy a count.
- Write in natural, conversational narration that sounds good when spoken aloud.

Do NOT include visual directions, camera directions, sound effects, timestamps,
stage directions, emojis, hashtags, narration labels, or any metadata in sentences.

Return ONLY valid JSON with this exact structure:
{
  "title": "short compelling title",
  "genre": "scary|mystery|moral|motivational",
  "sentences": [
    "Complete sentence one.",
    "Complete sentence two."
  ]
}

The sentences array must contain the actual narration in the exact order it
should be spoken. Preserve the sentence boundaries naturally because another
system will later match each sentence to its real WhisperX timing.
"""


STORY_SYSTEM_PROMPT_LONG = """You write original, engaging, and coherent long-form stories for narrated video content.

Your stories sustain attention over a longer arc, unfold across multiple beats,
and deliver a payoff that feels earned rather than sudden. You must produce at
least 1,000 words across 60-150 natural sentences — enough length for layered
character development, sustained tension, and a narrative that can breathe. It
is better to exceed this floor than to fall short. Do not be sparing with detail;
long-form narration rewards expansive, descriptive prose.

LONG-FORM NARRATIVE STRUCTURE:
- **Three to four acts with clear turning points**: Open with a strong hook,
  introduce the ordinary world, disrupt it with the inciting incident, escalate
  through rising complications across several scenes, reach a climax or revelation,
  then resolve with a payoff that recontextualizes what came before. Let each act
  feel like its own natural paragraph of narration with internal momentum.
- **Character depth**: Let characters have clear motivations, flaws, and an arc
  of change. The narrator's perspective should evolve as understanding deepens.
  Include at least one moment of quiet character reflection or world-building
  detail that reveals something about them beyond the plot.
- **Scene-rich escalation**: Do not skip between beats too quickly. Within each
  rising complication, set the scene with concrete sensory detail — what is seen,
  heard, smelled, touched — so the listener can inhabit the moment rather than
  being told a summary. Each scene should have at least 5-8 sentences of detailed
  buildup before the next plot beat, and some scenes should be longer, more
  atmospheric passages where tension is allowed to simmer. Lean into description
  rather than rushing toward resolution.
- **Atmospheric pacing**: Alternate between quieter, descriptive scenes and more
  urgent, plot-driven scenes. Let tension ebb and flow rather than climbing
  relentlessly. Some sentences should linger to build mood; others should snap.
  The overall rhythm should feel expansive — this is the time to let a moment
  breathe, not to skim across it.
- **Thematic resonance**: Let the ending reflect back on the story's central
  theme or question, ideally with an unexpected but inevitable twist or
  revelation.
- **Genre-appropriate tone**: Match the requested genre's conventions and
  emotional palette, whether creeping dread (scary), investigative unraveling
  (mystery), reflective journey (moral), or aspirational arc (motivational).
- **Originality**: Avoid clichés, recycled plots, stock horror tropes, and
  generic language. Surprise the listener.

SENTENCE GUIDELINES:
- 10-25 words per sentence is a natural baseline, but let length follow the
  story's needs. Longer, flowing descriptive sentences are appropriate for
  atmospheric moments; shorter ones for tension.
- Do NOT force a sentence to meet a word-count target.
- Do NOT use a fixed number of sentences.
- Do NOT artificially split or combine sentences just to satisfy a count.
- Write in natural, conversational narration that sounds good when spoken aloud.
- Each sentence should be a complete thought that another system will match
  against its real WhisperX timing.

Do NOT include visual directions, camera directions, sound effects, timestamps,
stage directions, emojis, hashtags, narration labels, or any metadata in sentences.

Return ONLY valid JSON with this exact structure:
{
  "title": "short compelling title",
  "genre": "scary|mystery|moral|motivational",
  "sentences": [
    "Complete sentence one.",
    "Complete sentence two."
  ]
}

The sentences array must contain the actual narration in the exact order it
should be spoken. Preserve the sentence boundaries naturally because another
system will later match each sentence to its real WhisperX timing.
"""


def _clean_json_text(raw: str) -> str:
    """Remove accidental Markdown fences around an otherwise valid JSON response."""
    text = raw.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    return text.strip()


def _validate_story(parsed: dict) -> list[str]:
    """Return validation errors without imposing artificial story-length limits."""
    errors = []

    if not isinstance(parsed, dict):
        return ["Response is not a JSON object."]

    title = parsed.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("Missing or invalid title.")

    genre = parsed.get("genre")
    if not isinstance(genre, str) or genre.strip().lower() not in ALLOWED_GENRES:
        errors.append(
            f"Invalid genre '{genre}'. Expected one of: "
            + ", ".join(ALLOWED_GENRES)
        )

    sentences = parsed.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        errors.append("sentences must be a non-empty array.")
    else:
        for i, sentence in enumerate(sentences):
            if not isinstance(sentence, str) or not sentence.strip():
                errors.append(f"Sentence {i + 1} is empty or invalid.")
            else:
                artifacts = find_sentence_metadata_artifacts(sentence)
                if artifacts:
                    errors.append(
                        f"Sentence {i + 1} contains forbidden metadata ({', '.join(artifacts)})."
                    )

    return errors


def generate_story(
    genre: str,
    premise: str | None = None,
    model_key: str = llm_client.DEFAULT_MODEL_KEY,
    length_mode: str = "short",
) -> dict:
    """Generate one structured story enforcing the story input/output contract.

    Contract:
    - Input:
        - genre (required, str): One of "scary", "mystery", "moral", "motivational".
        - premise (optional, str | None): Story premise or hook.
        - model_key (optional, str): LLM model identifier.
        - length_mode (optional, str): "short" (default, ~170-400 words, 15-30
          sentences for Shorts) or "long" (~1,000-2,000 words, 60-150 sentences
          with deeper narrative structure for 6-10 min long-form video).
    - Output:
        - JSON-compatible dict exactly containing:
            {
                "title": str,
                "genre": str,
                "sentences": list[str]
            }
        - "sentences" contains the authoritative narration sentence-by-sentence in spoken order,
          with no visual directions, timestamps, sound effects, labels, or other metadata.
        - Sentence count and word counts are flexible and NOT artificially enforced,
          because these exact sentences are passed unchanged to TTS and later matched
          against WhisperX word timestamps.

    Raises:
        ValueError: If genre or arguments violate the contract, or generated story fails validation.
        TypeError: If input argument types are invalid.
        RuntimeError: If LLM generation or parsing fails.
    """
    if not isinstance(genre, str) or genre.strip().lower() not in ALLOWED_GENRES:
        raise ValueError(
            f"genre is required and must be one of {ALLOWED_GENRES!r}, got {genre!r}"
        )
    genre = genre.strip().lower()

    if premise is not None and not isinstance(premise, str):
        raise TypeError(f"premise must be a str or None, got {type(premise).__name__}")

    if model_key is not None and not isinstance(model_key, str):
        raise TypeError(f"model_key must be a str, got {type(model_key).__name__}")
    model_key = model_key or llm_client.DEFAULT_MODEL_KEY

    if not isinstance(length_mode, str) or length_mode.strip().lower() not in ALLOWED_LENGTH_MODES:
        raise ValueError(
            f"length_mode must be one of {ALLOWED_LENGTH_MODES!r}, got {length_mode!r}"
        )
    length_mode = length_mode.strip().lower()

    system_prompt = STORY_SYSTEM_PROMPT_LONG if length_mode == "long" else STORY_SYSTEM_PROMPT
    max_tokens = DEFAULT_MAX_TOKENS_LONG if length_mode == "long" else DEFAULT_MAX_TOKENS

    premise_text = (
        premise.strip()
        if premise and premise.strip()
        else "Create an original story with an unexpected but satisfying ending."
    )

    user_prompt = (
        f"Genre: {genre}\n\n"
        f"Premise: {premise_text}\n\n"
        "Write the complete story now and return only the requested JSON."
    )

    temperature = 0.8 if length_mode == "short" else 0.5

    raw = llm_client.call_llm(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model_key=model_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    try:
        parsed = json.loads(_clean_json_text(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Story generator returned invalid JSON: {exc}") from exc

    if isinstance(parsed, dict) and isinstance(parsed.get("sentences"), list):
        parsed["sentences"] = [
            _clean_sentence(s) if isinstance(s, str) else s
            for s in parsed["sentences"]
        ]

    errors = _validate_story(parsed)
    if errors:
        raise RuntimeError("Invalid generated story: " + " ".join(errors))

    story = {
        "title": parsed["title"].strip(),
        "genre": parsed["genre"].strip().lower(),
        "sentences": [s.strip() for s in parsed["sentences"]],
    }

    # Strict contract enforcement before returning
    validate_story_contract(story)

    return story


if __name__ == "__main__":
    print("=== SHORT (default) ===")
    story = generate_story(
        genre="scary",
        premise="A man keeps hearing three knocks on his door at exactly 3:00 AM.",
    )
    print(json.dumps(story, indent=2, ensure_ascii=False))

    print("\n=== LONG ===")
    story = generate_story(
        genre="scary",
        premise="A man keeps hearing three knocks on his door at exactly 3:00 AM.",
        length_mode="long",
    )
    print(json.dumps(story, indent=2, ensure_ascii=False))
