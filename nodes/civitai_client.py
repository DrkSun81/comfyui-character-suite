"""
ComfyUI Character Suite — CivitAI tag-cache client
===================================================
Pure-stdlib(+optional requests) helpers for hashing a LoRA file, querying
CivitAI for its trigger words, and maintaining the on-disk tag cache.

Deliberately has ZERO dependency on `comfy`/`folder_paths` so it can be
imported and exercised standalone (see tests/test_civitai_fetch.py) without
booting ComfyUI.
"""

import hashlib
import json
import os
import time

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    requests = None
    _HAS_REQUESTS = False

# ── constants ──────────────────────────────────────────────────────────────────

DATA_DIR    = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TAGS_FILE   = os.path.join(DATA_DIR, "loras_tags.json")

REQUEST_TIMEOUT          = 10     # seconds, per attempt
MAX_RETRIES               = 3
RETRY_BACKOFF_BASE_SECS   = 1.5   # attempt N waits N * this many seconds
FAILED_RETRY_COOLDOWN_SECS = 3 * 24 * 3600  # don't re-hit CivitAI for a lora
                                             # that's currently failing more
                                             # than once per 3 days, unless forced

USER_AGENT = "ComfyUI-CharacterSuite/1.0"


# ── hashing ────────────────────────────────────────────────────────────────────

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── HTTP ───────────────────────────────────────────────────────────────────────

def _http_get_json(url: str, timeout: int = REQUEST_TIMEOUT):
    """
    Single HTTP GET attempt. Returns (status_code_or_None, json_or_None, error_snippet_or_None).
    Prefers `requests` (handles redirects/gzip/connection pooling transparently,
    which is where the bare-urllib version was silently failing); falls back to
    stdlib urllib if `requests` isn't importable in this environment.
    """
    headers = {"User-Agent": USER_AGENT}

    if _HAS_REQUESTS:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                try:
                    return resp.status_code, resp.json(), None
                except ValueError as e:
                    return resp.status_code, None, f"invalid JSON body: {e}"
            return resp.status_code, None, resp.text[:300]
        except requests.RequestException as e:
            return None, None, str(e)

    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            body = resp.read()
            if status == 200:
                try:
                    return status, json.loads(body), None
                except ValueError as e:
                    return status, None, f"invalid JSON body: {e}"
            return status, None, body[:300].decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body_snip = e.read()[:300].decode("utf-8", "replace")
        return e.code, None, body_snip
    except Exception as e:
        return None, None, str(e)


def fetch_civitai_tags(sha: str) -> tuple[bool, list[str]]:
    """
    Query CivitAI's model-versions-by-hash endpoint for trained/trigger words.

    Returns (success, tags):
      - success=True,  tags=[...]   fetch reached CivitAI and parsed a response
                                     (an empty list means the model genuinely
                                     has no trainedWords, or the hash isn't on
                                     CivitAI at all — both are "we now know
                                     the answer" outcomes and are safe to cache)
      - success=False, tags=[]      network error / timeout / non-200, non-404
                                     response — transient, caller should NOT
                                     overwrite any previously cached tags
    """
    url = f"https://civitai.com/api/v1/model-versions/by-hash/{sha}"
    backend = "requests" if _HAS_REQUESTS else "urllib"

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        status, data, err = _http_get_json(url)

        if status == 200 and data is not None:
            tags = data.get("trainedWords", []) or []
            print(f"[LoraStacker] CivitAI fetch OK via {backend} (attempt {attempt}/{MAX_RETRIES}): "
                  f"{len(tags)} tag(s)")
            return True, tags

        if status == 404:
            # Definitive answer: this hash isn't a known CivitAI model version.
            print(f"[LoraStacker] CivitAI: hash {sha[:12]}... not found (404 via {backend})")
            return True, []

        last_error = f"status={status} body={err}"
        print(f"[LoraStacker] CivitAI fetch failed via {backend} (attempt {attempt}/{MAX_RETRIES}): "
              f"{last_error}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_BASE_SECS * attempt)

    print(f"[LoraStacker] CivitAI fetch giving up after {MAX_RETRIES} attempts: {last_error}")
    return False, []


# ── tag cache (JSON file) ────────────────────────────────────────────────────

def _normalize_entry(value):
    """Migrate legacy `{lora_name: [tag, ...]}` rows to the structured form."""
    if isinstance(value, list):
        return {
            "tags": value,
            "status": "ok" if value else "no_triggers",
            "last_attempt": None,
            "last_success": None,
        }
    return value


def load_tags_db() -> dict:
    if not os.path.exists(TAGS_FILE):
        return {}
    try:
        with open(TAGS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    return {name: _normalize_entry(v) for name, v in raw.items()}


def save_tags_db(db: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_path = TAGS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, TAGS_FILE)


def entry_is_fresh(entry: dict) -> bool:
    """True if `entry` answers the question without needing a re-fetch."""
    if not entry:
        return False
    status = entry.get("status")
    if status in ("ok", "no_triggers"):
        return True
    if status == "failed":
        last_attempt = entry.get("last_attempt") or 0
        return (time.time() - last_attempt) < FAILED_RETRY_COOLDOWN_SECS
    return False


def apply_fetch_result(db: dict, lora_name: str, success: bool, tags: list[str]) -> dict:
    """
    Merge a fetch outcome into `db` (in place) for `lora_name` and return the
    resulting entry. A failed fetch never clobbers previously-known tags —
    it only records the attempt/status so future cache-hits know to retry
    (after cooldown) instead of treating "failed" the same as "no triggers".
    """
    now = time.time()
    prev = db.get(lora_name, {})
    if success:
        entry = {
            "tags": tags,
            "status": "ok" if tags else "no_triggers",
            "last_attempt": now,
            "last_success": now,
        }
    else:
        entry = {
            "tags": prev.get("tags", []),
            "status": "failed",
            "last_attempt": now,
            "last_success": prev.get("last_success"),
        }
    db[lora_name] = entry
    return entry
