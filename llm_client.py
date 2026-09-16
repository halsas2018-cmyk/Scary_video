"""
llm_client.py — provider-agnostic LLM transport for the Shorts pipeline.

Owns the MODEL_REGISTRY (the single place to add/edit a model) and a single
`call_llm()` that routes to Groq or NVIDIA-hosted NIM, both of which speak the
OpenAI-style /v1/chat/completions shape. Keeps the curl + retry/backoff logic
that lived in script_generator._call_llm, but lets you choose the model at run
time via a model key (see MODEL_REGISTRY keys, surfaced through run_pipeline's
--model flag).

Why this exists (vs. editing script_generator in place): the project's
reasoning hook #7 ("Swap LLM provider → replace _call_llm") wants the wire
transport separable from the prompts/validator. script_generator keeps the
*prompts + validation*; this module keeps the *wire*. The storyboard's
standalone Groq fallback also reaches it via script_generator._call_llm, which
is now a thin wrapper (so existing imports keep working).

Both providers use the same chat/completions request/response shape, so one curl
path serves both — only the endpoint URL + key env var differ per model.

Keys:
  Groq   → GROQ_API_KEY   (console.groq.com,  free, 30 req/min)
  NVIDIA → NVIDIA_API_KEY (build.nvidia.com,  free hosted NIM tier)

NOTE on NVIDIA model IDs: the exact strings in the API `model` field are
publisher/name-version style (e.g. "nvidia/llama-3.1-nemotron-ultra-253b-v1").
They can change as NVIDIA updates the catalog, so each ID is a one-line edit
here in MODEL_REGISTRY — verify the current IDs at
https://build.nvidia.com/explore/discover when you add a row or if a row
errors with "model not found".
"""

import os
import re
import json
import time
import subprocess
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# Auto-load .env (so a pasted NVIDIA_API_KEY just works, same as GROQ_API_KEY)
# ---------------------------------------------------------------------------
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
            if _k and not os.environ.get(_k):
                os.environ[_k] = _v

# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _signup_url(provider: str) -> str:
    return {
        "groq": "https://console.groq.com",
        "nvidia": "https://build.nvidia.com",
        "gemini": "https://makersuite.google.com/app/apikey",
    }.get(provider, "")


# ---------------------------------------------------------------------------
# Model registry — one row per choosable model. Add/edit freely.
#   key         — the value passed to run_pipeline --model
#   provider    — "groq" | "nvidia" | "gemini"   (selects endpoint + key env)
#   model       — the string sent in the API `model` field
#   key_env     — env var that holds that provider's API key
#   notes       — short human label for --help / error messages
# ---------------------------------------------------------------------------
MODEL_REGISTRY = {
    # --- Groq (free, 30 req/min) ---
    "groq-gpt-oss-120b": {
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "key_env": "GROQ_API_KEY",
        "notes": "Groq GPT-OSS 120B — strongest reasoning on Groq",
    },
    "groq-gpt-oss-20b": {
        "provider": "groq",
        "model": "openai/gpt-oss-20b",
        "key_env": "GROQ_API_KEY",
        "notes": "Groq GPT-OSS 20B — fast, cheap sibling of the default",
    },
    # --- NVIDIA hosted NIM (free tier; needs NVIDIA_API_KEY from build.nvidia.com) ---
    "nvidia-llama33": {
        "provider": "nvidia",
        "model": "meta/llama-3.3-70b-instruct",
        "key_env": "NVIDIA_API_KEY",
        "notes": "Meta Llama 3.3 70B on NVIDIA — fast, general purpose",
    },
    "nvidia-gpt-oss-120b": {
        "provider": "nvidia",
        "model": "openai/gpt-oss-120b",
        "key_env": "NVIDIA_API_KEY",
        "notes": "OpenAI GPT-OSS 120B on NVIDIA — open-weight, strong reasoning",
    },
    "nvidia-llama-3-1-70b": {
        "provider": "nvidia",
        "model": "meta/llama-3.1-70b-instruct",
        "key_env": "NVIDIA_API_KEY",
        "notes": "Meta Llama 3.1 70B Instruct on NVIDIA — solid general purpose",
    },
    "nvidia-nemotron-ultra": {
        "provider": "nvidia",
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "key_env": "NVIDIA_API_KEY",
        "notes": "NVIDIA Nemotron 3 Ultra 550B — biggest reasoning model",
    },
    # --- Google Gemini 3.1 Flash Lite (free tier; needs GEMINI_API_KEY from makersuite.google.com) ---
    "gemini-31-flash-lite": {
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite",
        "key_env": "GEMINI_API_KEY",
        "notes": "Google Gemini 3.1 Flash Lite — fast, efficient, optimized for cost",
    },
    "gemini-15-flash": {
        "provider": "gemini",
        "model": "gemini-1.5-flash",
        "key_env": "GEMINI_API_KEY",
        "notes": "Google Gemini 1.5 Flash — legacy model version",
    },
}

DEFAULT_MODEL_KEY = "gemini-31-flash-lite"


def list_models() -> list[dict]:
    """Return registry rows (key added) for --help / error messages."""
    out = []
    for key, row in MODEL_REGISTRY.items():
        out.append({"key": key, **{k: row[k] for k in ("provider", "model", "notes")}})
    return out


def resolve_model(model_key: str) -> dict:
    """Return the registry row for `model_key` or raise a clear error."""
    if not model_key:
        model_key = DEFAULT_MODEL_KEY
    row = MODEL_REGISTRY.get(model_key)
    if row is None:
        valid = ", ".join(sorted(MODEL_REGISTRY))
        raise ValueError(
            f"Unknown model '{model_key}'. Valid --model keys: {valid}"
        )
    return {"key": model_key, **row}


def _endpoint(row: dict) -> str:
    """Return the endpoint URL for a model row (includes model name for Gemini)."""
    provider = row["provider"]
    if provider == "groq":
        return GROQ_URL
    if provider == "nvidia":
        return NVIDIA_URL
    if provider == "gemini":
        # Gemini uses a different URL format that includes the model name
        model = row["model"]
        return GEMINI_URL.format(model=model)
    raise ValueError(f"Unknown provider: {provider}")


def _key_for(row: dict) -> str:
    """Return the API key for a model row, or raise a helpful error."""
    env = row.get("key_env", "")
    val = os.environ.get(env, "")
    if not val:
        provider = row.get("provider", "")
        raise RuntimeError(
            f"{env} is not set — the chosen --model '{row['key']}' needs a "
            f"{provider.upper()} key. Get one at: {_signup_url(provider)}\n"
            f"Then add to .env:  {env}=\"<your-key>\""
        )
    return val


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------

def call_llm(messages: list[dict],
             model_key: str = DEFAULT_MODEL_KEY,
             temperature: float = 0.5,
             max_tokens: int = 1024) -> str:
    """Send a chat-completions request to the chosen provider's model.

    OpenAI-shaped request/response for both Groq and NVIDIA NIM, so one curl
    path serves both. Returns the assistant text content.

    curl --max-time scales with max_tokens (the combined script+headlines+shots
    call returns a sizeable JSON; under-tokened timing cut it off mid-JSON —
    see CLAUDE.md known issue #12). 3 retries with backoff.
    """
    row = resolve_model(model_key)
    api_key = _key_for(row)
    endpoint = _endpoint(row)
    model_id = row["model"]

    if row["provider"] == "gemini":
        system_messages = [m for m in messages if m.get("role") == "system"]
        conversation_messages = [m for m in messages if m.get("role") != "system"]

        contents = []
        for m in conversation_messages:
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": m.get("content", "")}],
            })

        gemini_payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system_messages:
            gemini_payload["systemInstruction"] = {
                "parts": [{"text": system_messages[0].get("content", "")}]
            }

        payload = json.dumps(gemini_payload)
    else:
        payload = json.dumps({
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })

    # Model-specific timeout multipliers (120B models need much more time)
    timeout_multiplier = 3.0 if any(s in model_id.lower() for s in ("120b", "550b")) else 1.0
    
    last_error = None
    rate_limit_waits = 0
    for attempt in range(1, 4):
        try:
            # Increased timeout: 0.3s per token * multiplier + 60s base
            curl_max_time = max(60, int(max_tokens * 0.3 * timeout_multiplier) + 60)
            result = subprocess.run(
                [
                    "curl", "-s", "--connect-timeout", "60",
                    "--max-time", str(curl_max_time),
                    "-X", "POST", endpoint,
                    "-H", "Content-Type: application/json",
                    "-H", (f"x-goog-api-key: {api_key}" if row["provider"] == "gemini" else f"Authorization: Bearer {api_key}"),
                    "-d", payload,
                ],
                capture_output=True,
                text=True,
                timeout=curl_max_time + 60,
            )
            if result.returncode != 0:
                # Include stdout in error for debugging (may contain API error JSON)
                stderr_preview = result.stderr[:500] if result.stderr else "(empty stderr)"
                stdout_preview = result.stdout[:500] if result.stdout else "(empty stdout)"
                raise ConnectionError(
                    f"curl returned {result.returncode}: stderr={stderr_preview} stdout={stdout_preview}"
                )
            resp_data = json.loads(result.stdout)
            if "error" in resp_data:
                # Surface provider/model so a wrong model id is obvious
                err = resp_data["error"]
                err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                # Rate limits are transient — Groq embeds "try again in Xs"
                # in the message. Wait that out and retry WITHOUT burning an
                # attempt (the fallback cascade shares one org TPM pool, so
                # the next Groq model would hit the same wall otherwise).
                m = re.search(r"try again in ([\d.]+)s", err_msg)
                if m and "rate limit" in err_msg.lower():
                    if rate_limit_waits >= 3:
                        raise RuntimeError(
                            f"{row['provider']} API error for model "
                            f"'{model_id}': {err_msg}"
                        )
                    rate_limit_waits += 1
                    wait = float(m.group(1)) + 2.0
                    print(f"  [rate limit] waiting {wait:.0f}s before retry...")
                    time.sleep(wait)
                    continue
                raise RuntimeError(
                    f"{row['provider']} API error for model '{model_id}': {err_msg}"
                )
            if row["provider"] == "gemini":
                candidates = resp_data.get("candidates", [])
                if not candidates:
                    raise RuntimeError(f"Gemini returned no candidates: {resp_data}")
                parts = candidates[0].get("content", {}).get("parts", [])
                content = "".join(
                    part.get("text", "")
                    for part in parts
                    if isinstance(part, dict)
                )
                choice = {
                    "message": {"content": content},
                    "finish_reason": candidates[0].get("finishReason"),
                }
            else:
                choice = resp_data["choices"][0]
                content = choice["message"]["content"]
            if content is None or not content.strip():
                raise RuntimeError(f"LLM returned empty content for model '{model_id}'")
            if choice.get("finish_reason") == "length":
                # Token budget exhausted mid-output (GPT-OSS reasoning draws on
                # the same budget). Raise so the retry loop re-rolls instead of
                # handing downstream a truncated JSON payload.
                raise RuntimeError(
                    f"model '{model_id}' stopped at the token limit "
                    f"(finish_reason=length) — output truncated"
                )
            # Some models (e.g. Qwen via Groq) leak ...</think> reasoning
            # into content — strip it so downstream JSON parsing sees clean text.
            content = re.sub(r".*?</think>", "", content, flags=re.DOTALL)
            open_tag = "<" + "think" + ">"
            if open_tag in content:  # truncated mid-reasoning: drop the stub too
                content = content.split(open_tag)[0]
            content = content.strip()
            if not content:
                # Model spent its whole token budget on hidden reasoning and
                # never answered (Qwen does this on longer prompts). Raise so
                # the retry loop gets another roll of the dice.
                raise RuntimeError(
                    f"model '{model_id}' returned only hidden reasoning, no "
                    f"answer — needs more max_tokens or a different model"
                )
            return content
        except (ConnectionError, json.JSONDecodeError,
                subprocess.TimeoutExpired, KeyError, RuntimeError) as e:
            last_error = e
            # Don't retry a hard API error (wrong model id, bad key) — it'll
            # just fail N times. Connection/parse/timeout errors can be flaky.
            if isinstance(e, RuntimeError) and "API error" in str(e):
                raise
            if attempt < 3:
                wait = attempt * 5  # longer backoff: 5s, 10s
                print(f"  [retry {attempt}/3] waiting {wait}s... ({e})")
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"LLM call ({model_key}) failed after 3 attempts: {last_error}"
            ) from last_error
    # unreachable
    raise RuntimeError(f"LLM call ({model_key}) failed: {last_error}")


def model_keys() -> list[str]:
    """Sorted list of valid --model keys (for error messages)."""
    return sorted(MODEL_REGISTRY)


def available_models() -> list[str]:
    """Return model keys whose API keys are present in environment."""
    avail = []
    for key, row in MODEL_REGISTRY.items():
        if os.environ.get(row.get("key_env", "")):
            avail.append(key)
    return avail


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="List / smoke-test choosable LLM models.")
    ap.add_argument("--list", action="store_true", help="just print the registry")
    ap.add_argument("--model", default=None, help="model key to smoke-test (needs the key)")
    ap.add_argument("--prompt", default="Say hi in 3 words.")
    ap.add_argument("--bench", action="store_true",
                    help="run every registered model on a story prompt, timed")
    args = ap.parse_args()
    if args.list or (not args.model and not args.bench):
        rows = list_models()
        print(f"{'--model key':<28} {'provider':<8} model")
        print("-" * 70)
        for r in rows:
            print(f"{r['key']:<28} {r['provider']:<8} {r['model']}")
            print(f"{'':28}          — {r['notes']}")
        print(f"\nDefault: {DEFAULT_MODEL_KEY}")
        print("\nSmoke test with: python llm_client.py --model groq-gpt-oss-120b")
        raise SystemExit(0)

    if args.bench:
        story_prompt = ("Write a simple short story of about 150 words "
                        "about a stray cat that finds a home.")
        print(f"Benchmarking all {len(MODEL_REGISTRY)} models")
        print(f"Prompt: {story_prompt}")
        results = []  # (key, seconds-or-None, response)
        for key in model_keys():
            print(f"\n{'=' * 70}\n--- {key} ---")
            t0 = time.perf_counter()
            try:
                txt = call_llm([{"role": "user", "content": story_prompt}],
                               model_key=key)
                elapsed = time.perf_counter() - t0
                results.append((key, elapsed, txt))
                print(f"time: {elapsed:.1f}s\n")
                print(txt)
            except Exception as e:
                elapsed = time.perf_counter() - t0
                results.append((key, None, ""))
                print(f"FAILED after {elapsed:.1f}s: {e}")
        print(f"\n{'=' * 70}\nRANKING (working models, fastest first)")
        for k, t in sorted(((k, t) for k, t, _ in results if t is not None),
                           key=lambda x: x[1]):
            print(f"{t:6.1f}s  {k}")
        failed = [k for k, t, _ in results if t is None]
        if failed:
            print("failed: " + ", ".join(failed))
        raise SystemExit(0)

    txt = call_llm([{"role": "user", "content": args.prompt}], model_key=args.model)
    print(f"[{args.model}] -> {txt}")
