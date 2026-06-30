"""
ComfyUI Character Suite — LoRA Stacker
=======================================
Loads up to 10 LoRAs in a single node, fetches CivitAI trigger words per-LoRA
(cached to data/loras_tags.json), and exposes an interactive tag-picker via the
companion JS extension (web/lora_stacker.js).

Outputs: MODEL, CLIP, STRING (accumulated selected trigger words)
"""

import os
import threading
import time

import folder_paths
from comfy.sd import load_lora_for_models
from comfy.utils import load_torch_file

from . import civitai_client as cc

# ── constants ──────────────────────────────────────────────────────────────────

DATA_DIR     = cc.DATA_DIR
TAGS_FILE    = cc.TAGS_FILE
_tags_lock   = threading.Lock()

MAX_LORAS    = 10
NONE_CHOICE  = "None"

STARTUP_SCAN_DELAY_SECS = 5.0   # let ComfyUI finish booting before we start hammering CivitAI
STARTUP_SCAN_RATE_SECS  = 0.75  # delay between CivitAI calls during the scan
STARTUP_SCAN_BATCH_SIZE = 10    # write the cache file every N fetches, not every single one


# ── helpers (thin wrappers around civitai_client, adding folder_paths lookups) ──

def get_tags_for_lora(lora_name: str, force: bool = False) -> list[str]:
    """
    Return cached tags or fetch from CivitAI and cache them.

    A failed fetch (network error, timeout, non-200/404 response) never
    overwrites previously-cached tags and never gets cached as "no tags" —
    it's recorded as status="failed" with a timestamp so routine calls don't
    hammer CivitAI every single run, while still allowing a retry after the
    cooldown window or an explicit force_fetch.
    """
    with _tags_lock:
        db = cc.load_tags_db()
        entry = db.get(lora_name)

    if entry and not force and cc.entry_is_fresh(entry):
        return entry.get("tags", [])

    lora_path = folder_paths.get_full_path("loras", lora_name)
    if not lora_path or not os.path.exists(lora_path):
        return entry.get("tags", []) if entry else []

    print(f"[LoraStacker] Hashing {lora_name} ...")
    sha = cc.sha256_file(lora_path)
    print(f"[LoraStacker] Querying CivitAI for {sha[:12]}...")
    success, tags = cc.fetch_civitai_tags(sha)

    with _tags_lock:
        db = cc.load_tags_db()  # reload in case the startup scanner wrote meanwhile
        result_entry = cc.apply_fetch_result(db, lora_name, success, tags)
        cc.save_tags_db(db)

    if success:
        print(f"[LoraStacker] Got {len(tags)} tag(s) for {lora_name}")
    else:
        print(f"[LoraStacker] Fetch failed for {lora_name}, keeping prior cache "
              f"({len(result_entry['tags'])} tag(s))")

    return result_entry["tags"]


def get_cached_entry(lora_name: str) -> dict:
    """Return the cached entry (tags/status/timestamps) without ever fetching."""
    with _tags_lock:
        db = cc.load_tags_db()
    entry = db.get(lora_name)
    if not entry:
        return {"tags": [], "status": "unknown", "last_attempt": None, "last_success": None}
    return entry


# ── startup library scan (feature: keep the cache warm for the whole library) ──

def scan_library(rate_limit_secs: float = STARTUP_SCAN_RATE_SECS,
                  batch_size: int = STARTUP_SCAN_BATCH_SIZE):
    """
    Compare every LoRA on disk against the tag cache and fetch anything
    missing, or anything that previously failed and is past its retry
    cooldown. Meant to run on a background thread (see start_background_scan)
    so it never blocks ComfyUI startup or node registration.
    """
    try:
        all_loras = folder_paths.get_filename_list("loras")
    except Exception as e:
        print(f"[LoraStacker] startup scan: could not list loras: {e}")
        return

    with _tags_lock:
        db = cc.load_tags_db()

    pending = [name for name in all_loras if not cc.entry_is_fresh(db.get(name))]
    if not pending:
        print(f"[LoraStacker] startup scan: {len(all_loras)} lora(s), cache already up to date")
        return

    print(f"[LoraStacker] startup scan: {len(all_loras)} lora(s) total, {len(pending)} need a fetch")

    fetched = 0
    new_tagged = 0
    since_save = 0
    for name in pending:
        lora_path = folder_paths.get_full_path("loras", name)
        if not lora_path or not os.path.exists(lora_path):
            continue

        try:
            sha = cc.sha256_file(lora_path)
            success, tags = cc.fetch_civitai_tags(sha)
        except Exception as e:
            print(f"[LoraStacker] startup scan: error on {name}: {e}")
            success, tags = False, []

        entry = cc.apply_fetch_result(db, name, success, tags)
        fetched += 1
        since_save += 1
        if success and entry["tags"]:
            new_tagged += 1

        outcome = f"{len(tags)} tag(s)" if success else "failed"
        print(f"[LoraStacker] startup scan: {fetched}/{len(pending)} fetched ({outcome}) — {name}")

        if since_save >= batch_size:
            with _tags_lock:
                # merge with whatever else may have been saved concurrently
                latest = cc.load_tags_db()
                latest.update(db)
                cc.save_tags_db(latest)
                db = latest
            since_save = 0

        time.sleep(rate_limit_secs)

    with _tags_lock:
        latest = cc.load_tags_db()
        latest.update(db)
        cc.save_tags_db(latest)

    print(f"[LoraStacker] startup scan complete: {fetched} fetched, {new_tagged} newly tagged")


def start_background_scan(delay_secs: float = STARTUP_SCAN_DELAY_SECS):
    """Kick off scan_library() on a daemon thread after a short delay, so it
    doesn't compete with ComfyUI's own startup work. Safe to call multiple
    times / interrupt — re-running only refetches stale or missing entries."""

    def _run():
        time.sleep(delay_secs)
        try:
            scan_library()
        except Exception as e:
            print(f"[LoraStacker] startup scan crashed: {e}")

    t = threading.Thread(target=_run, name="LoraStackerStartupScan", daemon=True)
    t.start()
    return t


# ── node ───────────────────────────────────────────────────────────────────────

class LoraStacker:
    """
    Single-node LoRA stacker supporting up to 10 LoRAs.
    Trigger words are fetched from CivitAI if not cached, then surfaced to the
    companion JS widget so the user can click to add them to the prompt.
    """

    def __init__(self):
        # Cache loaded lora tensors to avoid re-reading for the same path
        self._lora_cache: dict[str, object] = {}

    @classmethod
    def INPUT_TYPES(cls):
        lora_list = [NONE_CHOICE] + sorted(
            folder_paths.get_filename_list("loras"), key=str.lower
        )
        inputs = {
            "required": {
                "model": ("MODEL",),
                "clip":  ("CLIP",),
            },
            "optional": {
                "opt_prompt": ("STRING", {"forceInput": True}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

        for i in range(1, MAX_LORAS + 1):
            inputs["optional"][f"lora_{i}"]           = (lora_list,   {"default": NONE_CHOICE})
            inputs["optional"][f"strength_model_{i}"] = ("FLOAT",      {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.05})
            inputs["optional"][f"strength_clip_{i}"]  = ("FLOAT",      {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.05})
            inputs["optional"][f"bypass_{i}"]         = ("BOOLEAN",    {"default": False})
            inputs["optional"][f"force_fetch_{i}"]    = ("BOOLEAN",    {"default": False})

        # The JS widget writes the user-selected tags back into this hidden widget
        inputs["optional"]["selected_tags"] = ("STRING", {"default": "", "multiline": False})

        return inputs

    RETURN_TYPES = ("MODEL", "CLIP", "STRING")
    RETURN_NAMES = ("model", "clip", "trigger_prompt")
    FUNCTION     = "apply_loras"
    CATEGORY     = "CharacterSuite"

    def apply_loras(self, model, clip, unique_id=None, opt_prompt=None, selected_tags="", **kwargs):
        current_model = model
        current_clip  = clip

        all_tags: dict[str, list[str]] = {}   # lora_name → tag list (for JS)

        for i in range(1, MAX_LORAS + 1):
            lora_name    = kwargs.get(f"lora_{i}", NONE_CHOICE)
            str_model    = kwargs.get(f"strength_model_{i}", 1.0)
            str_clip     = kwargs.get(f"strength_clip_{i}", 1.0)
            bypass       = kwargs.get(f"bypass_{i}", False)
            force_fetch  = kwargs.get(f"force_fetch_{i}", False)

            if not lora_name or lora_name == NONE_CHOICE:
                continue

            # Fetch / cache tags (non-blocking for the model load if already cached)
            tags = get_tags_for_lora(lora_name, force=force_fetch)
            all_tags[lora_name] = tags

            if bypass or (str_model == 0 and str_clip == 0):
                print(f"[LoraStacker] slot {i} bypassed: {lora_name}")
                continue

            lora_path = folder_paths.get_full_path("loras", lora_name)
            if not lora_path:
                print(f"[LoraStacker] WARNING: cannot find path for {lora_name}")
                continue

            # Load or reuse cached tensor
            if lora_path not in self._lora_cache:
                self._lora_cache[lora_path] = load_torch_file(lora_path, safe_load=True)
            lora_sd = self._lora_cache[lora_path]

            current_model, current_clip = load_lora_for_models(
                current_model, current_clip, lora_sd, str_model, str_clip
            )
            print(f"[LoraStacker] slot {i} applied: {lora_name} ({str_model}/{str_clip})")

        # Build output prompt from selected_tags + optional upstream prompt
        parts = []
        if opt_prompt:
            parts.append(opt_prompt.strip())
        if selected_tags and selected_tags.strip():
            parts.append(selected_tags.strip())

        trigger_prompt = ", ".join(p for p in parts if p)

        # Push all_tags to the JS side via a server-side event so the widget
        # can render clickable tag chips.  We store them keyed by node id.
        _push_tags_to_js(unique_id, all_tags)

        return (current_model, current_clip, trigger_prompt)


# ── push tags to frontend ──────────────────────────────────────────────────────

def _push_tags_to_js(node_id: str | None, all_tags: dict):
    """
    Store the latest tag data so the /character_suite/lora_tags endpoint
    can serve it to the JS widget on demand.
    """
    if node_id is None:
        return
    _TAG_STORE[str(node_id)] = all_tags


# Module-level store shared with api_routes
_TAG_STORE: dict[str, dict] = {}


# ── registration ───────────────────────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "CS_LoraStacker": LoraStacker,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CS_LoraStacker": "LoRA Stacker (CharacterSuite)",
}
