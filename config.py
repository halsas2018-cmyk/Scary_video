# config.py — Centralized configuration for the Shorts pipeline
# This file allows tuning without modifying core modules.

import os
import json

# ==============================================================================
# BANNED_FILLER — Words/phrases that make scripts sound "AI-generated" or lazy.
# The validator in script_generator.py rejects scripts containing these.
# Override via BANNED_FILLER_EXTRA env var (JSON list) to add more.
# ==============================================================================
BANNED_FILLER = [
    # Original filler phrases
    "imagine",
    "have you ever",
    "in today's world",
    "in the world of",
    "be a part of the conversation",
    "what do you think",
    "let me know",
    "drop a comment",
    "smash that",
    "before we begin",
    "without further ado",
    "in this video",
    "today we're going to",
    "make sure to",
    "don't forget to",
    "subscribe",
    "like and subscribe",
    "hit the bell",
    "welcome back",
    "guys",
    # ANTI-JARGON — Corporate/industry phrasing that sounds like a press release or LinkedIn post
    "leverage",
    "paradigm",
    "ecosystem",
    "furthermore",
    "in today's landscape",
    "stakeholders",
    "utilize",
    "facilitate",
    "optimize",
    "synergy",
    "holistic",
    "granular",
    "robust",
    "seamless",
    "cutting-edge",
    "game-changer",
    "disruptive",
    "revolutionary",
    "transformative",
    "best-in-class",
    "mission-critical",
    "value-add",
    "move the needle",
    "deep dive",
    "low-hanging fruit",
    "circle back",
    "touch base",
    "bandwidth",
    "align",
    "actionable",
    "deliverable",
]

# Allow env override
if os.environ.get("BANNED_FILLER_EXTRA"):
    try:
        extra = json.loads(os.environ["BANNED_FILLER_EXTRA"])
        if isinstance(extra, list):
            BANNED_FILLER.extend(extra)
    except Exception:
        pass


# ==============================================================================
# NICHE_KEYWORDS — Keywords used by news_fetcher to score story relevance.
# Add business/finance/AI terms here to influence story ranking.
# ==============================================================================
NICHE_KEYWORDS = {
    # AI / Tech
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "generative ai", "gpt", "claude", "gemini",
    "transformer", "neural network", "training", "inference", "fine-tuning",
    "rag", "retrieval augmented", "agent", "copilot", "code generation",
    "multimodal", "diffusion", "stable diffusion", "midjourney",
    "openai", "anthropic", "google deepmind", "meta ai", "nvidia",

    # Business / Finance
    "business", "finance", "market", "stock", "earnings",
    "startup", "funding", "venture capital", "series a", "series b", "ipo",
    "acquisition", "merger", "revenue", "profit", "growth",
    "crypto", "bitcoin", "ethereum", "blockchain", "web3",
    "economy", "inflation", "fed", "interest rate", "layoff",
    "hiring", "remote work", "productivity",

    # Hardware / Semiconductors
    "chip", "semiconductor", "gpu", "nvidia", "amd", "intel", "tsmc",
    "datacenter", "data center", "h100", "h200", "blackwell",
    "server", "cloud", "aws", "azure", "gcp",

    # Robotics / Physical AI
    "robot", "robotics", "autonomous", "self-driving", "tesla bot", "optimus",
}

# ==============================================================================
# REDDIT_USER_AGENTS — Pool of UAs to rotate for Reddit API requests
# Helps avoid 403 blocks in some environments.
# ==============================================================================
REDDIT_USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
]

# ==============================================================================
# COMMENT_CACHE — Cache settings for HN/Reddit comments
# ==============================================================================
COMMENT_CACHE_FILE = os.path.expanduser("~/.shorts_comment_cache.json")
COMMENT_CACHE_TTL_DAYS = 7  # How long to keep cached comments

# ==============================================================================
# ASSET_DEFAULTS — Default settings for asset collection
# ==============================================================================
ASSET_DEFAULTS = {
    "MIN_CLIP_WIDTH": 480,
    "MAX_DOWNLOAD_BYTES": 15 * 1024 * 1024,
    "REQUEST_DELAY": 1.0,
    "MAX_CLIPS_PER_SHORT": 12,
    "PEXELS_TIMEOUT": 30,
    "PIXABAY_TIMEOUT": 30,
    "MAX_RETRIES": 3,
}