"""Generate structured short stories for the scary-stories video pipeline.

Story Input/Output Contract:
----------------------------
Input:
- genre (required, str): Exactly one of "scary", "mystery", "moral", "motivational".
- premise (optional, str | None): Story premise, theme, or prompt hook.
- model_key (optional, str): Model key configured in llm_client.

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


DEFAULT_MAX_TOKENS = 4096

ALLOWED_GENRES = ("scary", "mystery", "moral", "motivational")
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


STORY_SYSTEM_PROMPT = """You write original short-form stories for faceless vertical videos.

The story will be narrated aloud, so natural pacing, clarity, suspense, and strong
sentence rhythm matter more than rigid formatting rules.

Write an engaging story suitable for a 60-90 second narrated Short. The story may
be scary, mysterious, unsettling, morally meaningful, or motivational depending
on the requested genre.

SENTENCE GUIDELINES:
- Aim roughly for 10-15 words per sentence when natural.
- Longer sentences are allowed when they improve the story, including around 20
  words or somewhat more.
- Do NOT force a sentence to meet a word-count target.
- Do NOT use a fixed number of sentences.
- Do NOT artificially split or combine sentences just to satisfy a count.
- Prioritize natural narration, pacing, suspense, clarity, and a satisfying ending.

The story must be original and self-contained.
Do not include visual directions, camera directions, sound effects, timestamps,
stage directions, emojis, hashtags, or narration labels.

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
) -> dict:
    """Generate one structured story enforcing the story input/output contract.

    Contract:
    - Input:
        - genre (required, str): One of "scary", "mystery", "moral", "motivational".
        - premise (optional, str | None): Story premise or hook.
        - model_key (optional, str): LLM model identifier.
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

    raw = llm_client.call_llm(
        messages=[
            {"role": "system", "content": STORY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        model_key=model_key,
        temperature=0.8,
        max_tokens=DEFAULT_MAX_TOKENS,
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
    story = generate_story(
        genre="scary",
        premise="A man keeps hearing three knocks on his door at exactly 3:00 AM.",
    )

    print(json.dumps(story, indent=2, ensure_ascii=False))
