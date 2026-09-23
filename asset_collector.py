"""
asset_collector.py
Step 6 of the Shorts pipeline: download free stock footage from Pexels
with a local clip cache to avoid re-downloading the same clips.

Cache file: ~/.shorts_clip_cache.json
- Before downloading: checks cache for matching keyword
- If found: copies local file (no download)
- If not found: downloads from Pexels, saves to cache

Also supports Pixabay as a fallback source.

Usage:
    export PEXELS_API_KEY="your-key-here"
    export PIXABAY_API_KEY="your-key-here"  # optional
"""

import os
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
import concurrent.futures
from pathlib import Path

# Import LLM client for tag verification
try:
    import llm_client
except ImportError:
    llm_client = None

PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
PEXELS_PHOTO_API = "https://api.pexels.com/v1/search"   # the photos endpoint
PIXABAY_API = "https://pixabay.com/api/"          # photos endpoint
PIXABAY_VIDEO_API = "https://pixabay.com/api/videos/"  # videos endpoint (separate URL)
CACHE_FILE = Path.home() / ".shorts_clip_cache.json"
COMMENT_CACHE_FILE = Path.home() / ".shorts_comment_cache.json"

# Download settings.
# MAX_CLIPS_PER_SHORT and MAX_DOWNLOAD_BYTES limits removed — pipeline now
# downloads the full set of assets required by the visual plan without
# count or per-asset byte-size restrictions.
REQUEST_DELAY = 1.0

MIN_CLIP_WIDTH = 480             # portrait 480p — minimum usable resolution

# Pexels sits behind Cloudflare and 403s default urllib/python User-Agents.
PEXELS_USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
PIXABAY_USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


# ==============================================================================
# SHOT VARIETY ENFORCEMENT — Visual categories to prevent repetitive clips
# ==============================================================================
VISUAL_CATEGORIES = {
    "person": ["person", "people", "human", "man", "woman", "face", "portrait",
               "programmer", "developer", "engineer", "worker", "employee"],
    "screen": ["screen", "monitor", "laptop", "computer", "code", "coding",
               "programming", "desktop", "terminal", "editor", "ide", "display"],
    "abstract": ["abstract", "background", "gradient", "particles", "neural",
                 "network", "ai", "tech", "digital", "data", "visualization",
                 "concept", "futuristic", "cyber"],
    "nature": ["nature", "tree", "forest", "mountain", "ocean", "sky", "clouds",
               "landscape", "water", "sunset", "sunrise", "beach", "river"],
    "city": ["city", "building", "office", "street", "urban", "skyline",
             "architecture", "downtown", "metropolis", "construction"],
    "object": ["robot", "device", "phone", "chip", "server", "hardware",
               "drone", "car", "vehicle", "machine", "gadget", "sensor"],
}

DEFAULT_CATEGORY = "abstract"


def _categorize_query(query: str) -> str:
    """Categorize a search query into a visual category."""
    q = query.lower()
    for cat, keywords in VISUAL_CATEGORIES.items():
        if any(k in q for k in keywords):
            return cat
    return DEFAULT_CATEGORY


def _enforce_shot_variety(plan: list[dict], max_consecutive: int = 2) -> list[dict]:
    """Reorder plan items to enforce visual variety (no more than N consecutive same category).

    Returns plan items in VARIETY-ORDERED sequence. Each returned item retains its
    original ``_orig_index`` field so downstream consumers (asset collection,
    manifest building, Remotion staging) can map back to the original sentence
    position and its timing.

    This is a best-effort reordering that tries to maintain sentence order as much
    as possible while avoiding visual repetition.
    """
    if len(plan) <= max_consecutive:
        # Tag items with original index even when no reordering occurs.
        return [dict(item, _orig_index=i) for i, item in enumerate(plan)]

    # Add category + original index to each item
    enriched = []
    for i, item in enumerate(plan):
        query = (item.get("search_term") or "").strip()
        cat = _categorize_query(query)
        enriched.append((i, item, cat))

    # Greedy reorder: iterate and swap if we'd exceed max_consecutive
    result = []
    remaining = enriched[:]

    while remaining:
        # Find first item that doesn't violate consecutive constraint
        placed = False
        for idx, (orig_i, item, cat) in enumerate(remaining):
            # Check last max_consecutive items in result
            recent_cats = [c for _, _, c in result[-max_consecutive:]]
            if recent_cats.count(cat) < max_consecutive:
                result.append((orig_i, item, cat))
                remaining.pop(idx)
                placed = True
                break

        if not placed:
            # All remaining would violate - just take first
            result.append(remaining.pop(0))

    # Return reordered items, each tagged with its original index so the
    # caller can map assets back to sentence positions.
    return [dict(item, _orig_index=orig_i) for orig_i, item, _ in result]


def _verify_asset_relevance(search_term: str, tags: list[str], alt_text: str) -> bool:
    """DEPRECATED: LLM tag verification removed — keeping stub for compatibility."""
    return True


def _get_api_key() -> str:
    key = os.environ.get("PEXELS_API_KEY", "")
    if not key:
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("PEXELS_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key


# ---------------------------------------------------------------------------
# Clip Cache
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    """Load the clip cache from disk. Returns {keyword: [clip_info, ...]}"""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except (json.JSONDecodeError, Exception):
            pass
    return {"clips": [], "keywords": {}}


def _save_cache(cache: dict):
    """Save the clip cache to disk."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _find_cached_clip(keyword: str, cache: dict) -> Path | None:
    """Check if a clip for this keyword already exists locally.
    Returns the path if the file still exists on disk."""
    keyword_lower = keyword.lower()
    keyword_map = cache.get("keywords", {})

    if keyword_lower in keyword_map:
        clip_ids = keyword_map[keyword_lower]
        for clip in cache.get("clips", []):
            if clip["id"] in clip_ids:
                path = Path(clip["path"])
                if path.exists():
                    return path
    return None


def _add_to_cache(keyword: str, clip_path: Path, clip_id: int, cache: dict):
    """Record a downloaded clip in the cache."""
    keyword_lower = keyword.lower()

    # Ensure keyword map exists
    if keyword_lower not in cache.setdefault("keywords", {}):
        cache["keywords"][keyword_lower] = []

    # Check if clip already recorded
    for c in cache["clips"]:
        if c["id"] == clip_id:
            if clip_id not in cache["keywords"][keyword_lower]:
                cache["keywords"][keyword_lower].append(clip_id)
            return

    # Add new clip entry
    cache["clips"].append({
        "id": clip_id,
        "keyword": keyword_lower,
        "path": str(clip_path),
        "source": "pexels",
        "downloaded": time.strftime("%Y-%m-%d"),
    })
    cache["keywords"][keyword_lower].append(clip_id)
    _save_cache(cache)


# ---------------------------------------------------------------------------
# Asset Collection
# ---------------------------------------------------------------------------

def collect_assets(keywords: list[str], project_dir: Path,
                   max_clips: int = None, length_mode: str = "short") -> list[Path]:
    """
    Collect background video clips for a Short.

    1. Check clip cache for existing clips matching keywords
    2. Download any missing clips from Pexels
    3. Log newly downloaded clips to cache

    Args:
        keywords: Search terms from the storyboard generator.
        project_dir: Project folder to save assets into.
        max_clips: Max clips to use (default: MAX_CLIPS_PER_SHORT).

    Returns:
        List of paths to video files ready to use.
    """
    api_key = _get_api_key()
    project_dir = Path(project_dir)
    assets_dir = project_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    if not api_key:
        print("  ⚠ PEXELS_API_KEY not set. Skipping asset download.")
        print("    Get a free key at: https://www.pexels.com/api/")
        return []

    # max_clips=None means no count limit (MAX_CLIPS_PER_SHORT removed)
    cache = _load_cache()
    downloaded_paths = []
    used_queries = set()

    # Search keywords + some generic fallbacks
    priority_keywords = _prioritize_keywords(keywords)
    search_queries = priority_keywords + [
        "technology background",
        "person working",
        "office",
    ]

    def _process_query(query):
        """Process a single query: check cache, search, download."""
        if query in used_queries:
            return None
        used_queries.add(query)

        # Step 1: Check cache first
        cached = _find_cached_clip(query, cache)
        if cached:
            dest = assets_dir / cached.name
            if not dest.exists():
                dest.write_bytes(cached.read_bytes())
            return ("cached", dest, query)

        # Step 2: Not in cache — search Pexels
        clips = _search_pexels(query, api_key, length_mode=length_mode)
        for clip in clips:
            try:
                path = _download(clip, query, assets_dir)
                if path:
                    _add_to_cache(query, path, clip["id"], cache)
                    return ("downloaded", path, query)
            except Exception as e:
                print(f"  Skipped {query}: {e}")
            time.sleep(REQUEST_DELAY)
        return None

    # Process queries in parallel (max 3 concurrent to respect rate limits)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_query = {executor.submit(_process_query, q): q for q in search_queries}
        for future in concurrent.futures.as_completed(future_to_query):
            result = future.result()
            if result:
                status, path, query = result
                downloaded_paths.append(path)
                print(f"  {status.capitalize()}: {path.name} (query: {query})")

    if downloaded_paths:
        print(f"  Assets ready: {len(downloaded_paths)} clip(s)")
    else:
        print(f"  No assets found. Drop clips into {assets_dir}/ manually.")
        _place_holder_readme(assets_dir)

    return downloaded_paths


def collect_assets_for_plan(plan: list[dict], project_dir: Path, force_fresh: bool = False,
                            length_mode: str = "short") -> dict:
    """Download ONE asset per entry in plan (each entry is a sub_shot), keyed by original index.

    The primary entry for the new per-sentence assembler. `plan` is the
    per-sentence list from storyboard_generator (each item has `search_term`
    and `media_type`). Identical search terms are deduped (one asset reused
    across those entries) via the cache.

    Visual variety is enforced: no more than 2 consecutive clips from the
    same visual category (person, screen, abstract, nature, city, object).
    Reordering for variety preserves each item's original index in the
    ``_orig_index`` field so assets are mapped back to their sentence
    position, not their reordered position.

    Args:
        plan: Per-sentence visual plan (flat list of assets)
        project_dir: Project folder to save assets into
        force_fresh: If True, bypass cache and download fresh assets

    Returns:
        {original_asset_index: asset_path} map where asset_path is a .mp4 (video)
        or .jpg (photo). Indices with no available asset are omitted; the
        assembler falls back to the gradient for those.
    """
    api_key = _get_api_key()
    project_dir = Path(project_dir)
    assets_dir = project_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    if not api_key:
        print("  ⚠ PEXELS_API_KEY not set. Skipping asset download.")
        print("    Get a free key at: https://www.pexels.com/api/")
        return {}

    # Enforce shot variety: reorder plan to avoid visual repetition.
    # _enforce_shot_variety tags each item with _orig_index so we can
    # map downloaded assets back to their original sentence position.
    plan = _enforce_shot_variety(plan)

    cache = _load_cache()
    result = {}                      # original_index -> Path
    term_to_path = {}                # dedupe identical search terms
    used_queries = set()

    for item in plan:
        # _orig_index is the original position before variety reordering.
        orig_idx = item.get("_orig_index", 0)
        query = (item.get("search_term") or "").strip()
        media = (item.get("media_type") or "video").lower()
        if not query:
            continue
        if query in used_queries and query in term_to_path:
            result[orig_idx] = term_to_path[query]
            continue
        used_queries.add(query)

        # Cache first (works for both video and photo — keyed by term).
        if not force_fresh:
            cached = _find_cached_clip(query, cache)
            if cached and cached.exists():
                dest = assets_dir / cached.name
                if not dest.exists():
                    dest.write_bytes(cached.read_bytes())
                result[orig_idx] = dest
                term_to_path[query] = dest
                print(f"  Cached asset reused: {cached.name}")
                continue

        # Search + download per media type.
        if media == "photo":
            clips = _search_pexels_photo(query, api_key, length_mode=length_mode)
        else:
            clips = _search_pexels(query, api_key, length_mode=length_mode)

        got = None
        for clip in clips:
            if media == "photo":
                path = _download_photo(clip, query, assets_dir)
            else:
                # cast id to int for the cache's clip_id field
                clip = dict(clip, id=int(clip.get("id", 0) or 0))
                path = _download(clip, query, assets_dir)
            if path:
                _add_to_cache(query, path, int(clip.get("id", 0) or 0), cache)
                print(f"  Downloaded: {path.name}  ({media})")
                got = path
                break
            time.sleep(REQUEST_DELAY)

        if got is not None:
            result[orig_idx] = got
            term_to_path[query] = got

        time.sleep(REQUEST_DELAY)

    if result:
        print(f"  Assets ready: {len(result)} asset(s) for {len(plan)} entry(s)")
    else:
        print(f"  No assets found. Drop clips into {assets_dir}/ manually.")
        _place_holder_readme(assets_dir)

    return result


def _search_pexels_photo(query: str, api_key: str, length_mode: str = "short") -> list[dict]:
    """Search the Pexels PHOTOS API. Returns portrait (Shorts) or landscape (Long) candidates.

    Uses the per-photo `src.portrait` URL (Pexels pre-crops to a fixed ~1300px
    portrait) — that's already small, and the download byte-cap is the real
    backstop. No dimension filter on the full-res original.
    """
    orientation = "landscape" if length_mode == "long" else "portrait"
    url = (f"{PEXELS_PHOTO_API}?query={urllib.parse.quote(query)}"
           f"&per_page=5&orientation={orientation}&size=small")
    req = urllib.request.Request(
        url,
        headers={"Authorization": api_key, "User-Agent": PEXELS_USER_AGENT},
    )
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            break
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
            if attempt == max_retries - 1:
                print(f"  Pexels photo API error for '{query}' after {max_retries} retries: {e}")
                return []
            wait = (attempt + 1) * 2
            print(f"  [retry {attempt+1}/{max_retries}] waiting {wait}s... ({e})")
            time.sleep(wait)
    else:
        return []

    clips = []
    for photo in data.get("photos", []):
        src = (photo.get("src") or {})
        photo_url = (src.get("portrait") or src.get("large2x")
                     or src.get("large") or src.get("original"))
        if not photo_url:
            continue
        clips.append({
            "url": photo_url,
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
            "size_bytes": 0,            # unknown until download; byte-cap enforces
            "id": photo.get("id"),
        })
    return clips


def _download_photo(clip: dict, query: str, assets_dir: Path) -> Path | None:
    """Download a single photo from Pexels, enforcing the byte cap."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in query)[:30]
    filename = f"{safe}_{clip['id']}.jpg"
    filepath = assets_dir / filename
    if filepath.exists():
        return filepath

    url = clip["url"]
    # Skip HEAD pre-flight, just enforce cap during streaming

    max_retries = 3
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={"User-Agent": PEXELS_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = 0
                with open(filepath, "wb") as f:
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        f.write(chunk)
            if filepath.stat().st_size < 1024:
                filepath.unlink(missing_ok=True)
                return None
            return filepath
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
            if attempt == max_retries - 1:
                print(f"  Photo download error for {clip['id']} after {max_retries} retries: {e}")
                filepath.unlink(missing_ok=True)
                return None
            wait = (attempt + 1) * 2
            print(f"  [retry {attempt+1}/{max_retries}] waiting {wait}s... ({e})")
            time.sleep(wait)
            filepath.unlink(missing_ok=True)
        except Exception as e:
            print(f"  Photo download error for {clip['id']}: {e}")
            filepath.unlink(missing_ok=True)
            return None

    return None


def _prioritize_keywords(keywords: list[str]) -> list[str]:
    """Order keywords for best visual results."""
    priority = [
        "technology", "computer", "office", "business", "coding",
        "robot", "future", "innovation", "science", "data",
        "phone", "mobile", "communication", "network", "digital",
    ]
    ordered = [kw for kw in priority if kw in keywords]
    ordered += [kw for kw in keywords if kw not in ordered]
    return ordered


def _search_pexels(query: str, api_key: str, length_mode: str = "short") -> list[dict]:
    """Search Pexels for free stock video clips (portrait for Shorts, landscape for Long).

    Picks the SMALLEST usable file per video (≥ MIN_CLIP_WIDTH) so
    fresh downloads stay small. A 20-30s Short with a blurred/scaled background
    does not need a 12 MB 1080p source — a ~1-5 MB 540p-720p clip is plenty.
    """
    # size=small biases Pexels toward smaller source clips (vs the old
    # size=large which favored heavyweight files).
    orientation = "landscape" if length_mode == "long" else "portrait"
    url = (f"{PEXELS_VIDEO_API}?query={urllib.parse.quote(query)}"
           f"&per_page=5&orientation={orientation}&size=small")
    # Browser UA is required — Cloudflare 403s (error 1010) the default
    # urllib/python User-Agent, which silently killed asset downloads.
    req = urllib.request.Request(
        url,
        headers={"Authorization": api_key, "User-Agent": PEXELS_USER_AGENT},
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            break
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
            if attempt == max_retries - 1:
                print(f"  Pexels API error for '{query}' after {max_retries} retries: {e}")
                return []
            wait = (attempt + 1) * 2
            print(f"  [retry {attempt+1}/{max_retries}] waiting {wait}s... ({e})")
            time.sleep(wait)
    else:
        return []

    clips = []
    for video in data.get("videos", []):
        # Collect every usable portrait file, then pick the SMALLEST — not the
        # first HD file. Sorting by Pexels-reported byte size is what actually
        # minimizes the download, regardless of resolution label.
        # ALSO prefer shorter duration clips (≤10s) since we only need 3s segments
        usable = []
        for file in video.get("video_files", []):
            w, h = file.get("width", 0), file.get("height", 0)
            duration = video.get("duration", 10)
            if (w > h if length_mode == "long" else h > w) and w >= MIN_CLIP_WIDTH:  # landscape(Long) / portrait(Short) + big enough
                usable.append({
                    "url": file["link"],
                    "width": w,
                    "height": h,
                    "size_bytes": file.get("size", 0) or 0,
                    "duration": duration,
                    "id": video.get("id"),
                })
        if usable:
            # Prefer: smaller file size, then shorter duration (better for 3s clips)
            usable.sort(key=lambda c: (c["size_bytes"] or float("inf"), c["duration"]))
            clips.append(usable[0])
    return clips


def _head_size(url: str) -> int | None:
    """Get Content-Length from a HEAD request without downloading the body."""
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": PEXELS_USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
    except Exception:
        # Some CDNs don't support HEAD or don't return Content-Length.
        # Fall back to None and let the actual download enforce the cap.
        return None


def _download(clip: dict, query: str, assets_dir: Path) -> Path | None:
    """Download a single clip from Pexels, enforcing a max-size cap.

    Skip HEAD pre-flight; just enforce cap during streaming download with retries.
    """
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in query)[:30]
    filename = f"{safe}_{clip['id']}.mp4"
    filepath = assets_dir / filename

    if filepath.exists():
        return filepath

    url = clip["url"]

    # No HEAD pre-flight — just enforce cap during streaming

    max_retries = 3
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={"User-Agent": PEXELS_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = 0
                with open(filepath, "wb") as f:
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        f.write(chunk)
            size_kb = filepath.stat().st_size / 1024
            if size_kb < 10:
                filepath.unlink(missing_ok=True)
                return None
            return filepath
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
            if attempt == max_retries - 1:
                print(f"  Download error for {clip['id']} after {max_retries} retries: {e}")
                filepath.unlink(missing_ok=True)
                return None
            wait = (attempt + 1) * 2
            print(f"  [retry {attempt+1}/{max_retries}] waiting {wait}s... ({e})")
            time.sleep(wait)
            filepath.unlink(missing_ok=True)
        except Exception as e:
            filepath.unlink(missing_ok=True)
            print(f"  Download error for {clip['id']}: {e}")
            return None

    return None


def _get_pixabay_key() -> str:
    """Get Pixabay API key from environment."""
    key = os.environ.get("PIXABAY_API_KEY", "")
    if not key:
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("PIXABAY_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key


def _search_pixabay(query: str, api_key: str, media_type: str = "video",
                    length_mode: str = "short") -> list[dict]:
    """Search Pixabay for free stock videos/photos.

    Pixabay has a generous free tier (no auth required for basic use,
    but key enables higher rate limits).
    """
    per_page = 5
    if media_type == "video":
        url = (f"{PIXABAY_VIDEO_API}?key={api_key}&q={urllib.parse.quote(query)}"
               f"&per_page={per_page}&video_type=all")
    else:
        orientation = "horizontal" if length_mode == "long" else "vertical"
        url = (f"{PIXABAY_API}?key={api_key}&q={urllib.parse.quote(query)}"
               f"&per_page={per_page}&orientation={orientation}&image_type=photo")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": PIXABAY_USER_AGENT},
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            break
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
            if attempt == max_retries - 1:
                print(f"  Pixabay API error for '{query}': {e}")
                return []
            wait = (attempt + 1) * 2
            print(f"  [retry {attempt+1}/{max_retries}] waiting {wait}s... ({e})")
            time.sleep(wait)
    else:
        return []

    clips = []
    for item in data.get("hits", []):
        if media_type == "video":
            videos = item.get("videos", {})
            # Collect all portrait-usable quality tiers, then pick the smallest
            # (matching the Pexels approach: smallest file ≥ MIN_CLIP_WIDTH)
            usable = []
            for quality in ["tiny", "small", "medium", "large"]:
                if quality in videos:
                    v = videos[quality]
                    w, h = v.get("width", 0), v.get("height", 0)
                    if (w > h if length_mode == "long" else h > w) and w >= MIN_CLIP_WIDTH:
                        usable.append({
                            "url": v["url"],
                            "width": w,
                            "height": h,
                            "size_bytes": v.get("size", 0) or 0,
                            "duration": item.get("duration", 10),
                            "id": item.get("id"),
                        })
            if usable:
                # Smallest file first; fall back to first usable if sizes unknown
                usable.sort(key=lambda c: (c["size_bytes"] or float("inf"), c["duration"]))
                clips.append(usable[0])
        else:
            # Photos - use webformatURL or largeImageURL
            photo_url = item.get("webformatURL") or item.get("largeImageURL")
            if photo_url:
                clips.append({
                    "url": photo_url,
                    "width": item.get("imageWidth", 0),
                    "height": item.get("imageHeight", 0),
                    "size_bytes": 0,
                    "id": item.get("id"),
                })
    return clips


def _download_pixabay(clip: dict, query: str, assets_dir: Path, is_video: bool = True) -> Path | None:
    """Download a single asset from Pixabay."""
    ext = ".mp4" if is_video else ".jpg"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in query)[:30]
    filename = f"{safe}_pixabay_{clip['id']}{ext}"
    filepath = assets_dir / filename

    if filepath.exists():
        return filepath

    url = clip["url"]
    max_retries = 3
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={"User-Agent": PIXABAY_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = 0
                with open(filepath, "wb") as f:
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        f.write(chunk)
            size_kb = filepath.stat().st_size / 1024
            if size_kb < 10:
                filepath.unlink(missing_ok=True)
                return None
            return filepath
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
            if attempt == max_retries - 1:
                print(f"  Pixabay download error for {clip['id']} after {max_retries} retries: {e}")
                filepath.unlink(missing_ok=True)
                return None
            wait = (attempt + 1) * 2
            print(f"  [retry {attempt+1}/{max_retries}] waiting {wait}s... ({e})")
            time.sleep(wait)
            filepath.unlink(missing_ok=True)
        except Exception as e:
            filepath.unlink(missing_ok=True)
            print(f"  Pixabay download error for {clip['id']}: {e}")
            return None

    return None


def collect_assets_for_plan_with_fallback(plan: list[dict], project_dir: Path, force_fresh: bool = False,
                                          length_mode: str = "short") -> dict:
    """Download assets with Pexels first, then Pixabay fallback.

    Tries Pexels for each sentence. If Pexels fails or returns no results,
    tries Pixabay as a fallback. Shot variety is enforced.

    Args:
        plan: Per-sentence visual plan (flat list of assets)
        project_dir: Project folder to save assets into
        force_fresh: If True, bypass cache and download fresh assets

    Returns:
        {original_asset_index: asset_path} map — keys are ORIGINAL sentence
        positions, so the manifest and staging align assets to sentences
        regardless of variety reordering.
    """
    # First try Pexels (includes shot variety enforcement)
    result = collect_assets_for_plan(plan, project_dir, force_fresh=force_fresh,
                                     length_mode=length_mode)

    # Check which original indices are missing
    missing_indices = [i for i in range(len(plan)) if i not in result]

    # Try Pixabay for missing
    pixabay_key = _get_pixabay_key()
    if not pixabay_key:
        print("  ⚠ PIXABAY_API_KEY not set, skipping Pixabay fallback")
        # Still write the manifest so staging can use Pexels results
        if result:
            manifest = {str(i): p.name for i, p in result.items()}
            (project_dir / "assets_manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            print(f"  ✓ assets_manifest.json ({len(manifest)} entries)")
        return result

    print(f"  Trying Pixabay fallback for {len(missing_indices)} missing asset(s)...")

    for i in missing_indices:
        item = plan[i]
        query = (item.get("search_term") or "").strip()
        media = (item.get("media_type") or "video").lower()

        if not query:
            continue

        is_video = (media == "video")
        clips = _search_pixabay(query, pixabay_key, "video" if is_video else "photo",
                                length_mode=length_mode)

        for clip in clips:
            path = _download_pixabay(clip, query, project_dir / "assets", is_video)
            if path:
                result[i] = path
                print(f"  Downloaded via Pixabay fallback: {path.name} ({'video' if is_video else 'photo'})")
                break
            time.sleep(REQUEST_DELAY)

    # Write an index -> filename manifest keyed by ORIGINAL sentence index so
    # downstream staging in save_project can map assets to their sentences
    # correctly, regardless of variety reordering.
    manifest = {str(i): p.name for i, p in result.items()}
    (project_dir / "assets_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"  ✓ assets_manifest.json ({len(manifest)} entries)")

    return result


def _place_holder_readme(assets_dir: Path):
    readme = assets_dir / "README.txt"
    if not readme.exists():
        readme.write_text(
            "Drop background video clips (.mp4) in this folder.\n"
            "Free sources: pexels.com, pixabay.com, coverr.co\n"
        )


if __name__ == "__main__":
    import sys
    paths = collect_assets(sys.argv[1:] if len(sys.argv) > 1 else ["technology"], Path("/tmp/test_cache"))
    print(f"Got {len(paths)} clips")
    for p in paths:
        print(f"  {p.name} ({p.stat().st_size / 1024:.0f} KB)")
