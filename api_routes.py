"""
Character Suite — Backend API Routes
Registered into ComfyUI's PromptServer to serve the web panel requests.

Handles:
  • Character CRUD  — /character_suite/characters/*
  • Segment CRUD   — /character_suite/segments/*
  • LoRA tag store — /character_suite/lora_tags          (GET)
                     /character_suite/lora_tags/fetch    (POST, force CivitAI refresh)
"""

import json
import os
import uuid
import time

from aiohttp import web

DATA_DIR        = os.path.join(os.path.dirname(__file__), "data")
CHARACTERS_FILE = os.path.join(DATA_DIR, "characters.json")
SEGMENTS_FILE   = os.path.join(DATA_DIR, "segments.json")


# ── File helpers ───────────────────────────────────────────────────────────────

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def no_cache_json(data):
    """
    web.json_response sends no cache-control headers by default, which lets
    browsers heuristically cache a GET response — so a save can succeed but
    the very next list-refresh re-shows pre-edit data from cache. All of this
    suite's GET endpoints are live CRUD reads and must never be cached.
    """
    return web.json_response(data, headers={"Cache-Control": "no-store"})


# ── Character routes ───────────────────────────────────────────────────────────

async def route_list_characters(request):
    data = load_json(CHARACTERS_FILE, {"characters": []})
    return no_cache_json(data)


async def route_save_character(request):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise web.HTTPBadRequest(text="name is required")
    data  = load_json(CHARACTERS_FILE, {"characters": []})
    chars = data["characters"]
    existing = next((i for i, c in enumerate(chars) if c["name"].lower() == name.lower()), None)
    entry = {
        "name":     name,
        "positive": body.get("positive", "").strip(),
        "negative": body.get("negative", "").strip(),
        "tags":     body.get("tags", []),
    }
    if existing is not None:
        chars[existing] = entry
    else:
        chars.append(entry)
    save_json(CHARACTERS_FILE, {"characters": chars})
    return web.json_response({"status": "ok", "name": name})


async def route_delete_character(request):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise web.HTTPBadRequest(text="name is required")
    data   = load_json(CHARACTERS_FILE, {"characters": []})
    before = len(data["characters"])
    data["characters"] = [c for c in data["characters"] if c["name"].lower() != name.lower()]
    if len(data["characters"]) == before:
        raise web.HTTPNotFound(text=f"Character '{name}' not found")
    save_json(CHARACTERS_FILE, data)
    return web.json_response({"status": "deleted", "name": name})


# ── Segment routes ─────────────────────────────────────────────────────────────

async def route_list_segments(request):
    category = request.rel_url.query.get("category", None)
    data = load_json(SEGMENTS_FILE, {"segments": []})
    segs = data["segments"]
    if category and category != "(all)":
        segs = [s for s in segs if s["category"] == category]
    return no_cache_json({"segments": segs})


async def route_save_segment(request):
    body     = await request.json()
    category = body.get("category", "").strip()
    label    = body.get("label", "").strip()
    content  = body.get("content", "").strip()
    if not all([category, label, content]):
        raise web.HTTPBadRequest(text="category, label, and content are required")
    data = load_json(SEGMENTS_FILE, {"segments": []})
    segs = data["segments"]
    existing = next(
        (i for i, s in enumerate(segs)
         if s["category"] == category and s["label"].lower() == label.lower()),
        None,
    )
    entry = {
        "id":       str(uuid.uuid4())[:8],
        "category": category,
        "label":    label,
        "content":  content,
        "created":  int(time.time()),
    }
    if existing is not None:
        segs[existing] = entry
    else:
        segs.append(entry)
    save_json(SEGMENTS_FILE, {"segments": segs})
    return web.json_response({"status": "ok", "label": label})


async def route_delete_segment(request):
    body   = await request.json()
    seg_id = body.get("id", "").strip()
    if not seg_id:
        raise web.HTTPBadRequest(text="id is required")
    data   = load_json(SEGMENTS_FILE, {"segments": []})
    before = len(data["segments"])
    data["segments"] = [s for s in data["segments"] if s["id"] != seg_id]
    if len(data["segments"]) == before:
        raise web.HTTPNotFound(text=f"Segment '{seg_id}' not found")
    save_json(SEGMENTS_FILE, data)
    return web.json_response({"status": "deleted", "id": seg_id})


# ── LoRA tag routes ────────────────────────────────────────────────────────────

async def route_get_lora_tags(request):
    """
    GET /character_suite/lora_tags?node_id=<id>
    Returns the cached tag dict for the given node id (set by lora_stacker.py
    after each execution).  If node_id is omitted, return the full store.
    """
    # Import the live store from the lora_stacker module
    try:
        from .nodes.lora_stacker import _TAG_STORE
    except ImportError:
        return no_cache_json({})

    node_id = request.rel_url.query.get("node_id", None)
    if node_id:
        return no_cache_json(_TAG_STORE.get(str(node_id), {}))
    return no_cache_json(_TAG_STORE)


async def route_fetch_lora_tags(request):
    """
    POST /character_suite/lora_tags/fetch
    Body: { "lora_name": "subdir/file.safetensors", "force": true }
    Triggers an immediate CivitAI fetch (or returns cache).
    Returns { "lora_name": ..., "tags": [...], "status": "ok"|"no_triggers"|"failed" }
    """
    try:
        from .nodes.lora_stacker import get_tags_for_lora, get_cached_entry
    except ImportError:
        raise web.HTTPInternalServerError(text="lora_stacker not loaded")

    body      = await request.json()
    lora_name = body.get("lora_name", "").strip()
    force     = bool(body.get("force", False))

    if not lora_name:
        raise web.HTTPBadRequest(text="lora_name is required")

    tags   = get_tags_for_lora(lora_name, force=force)
    status = get_cached_entry(lora_name).get("status", "unknown")
    return web.json_response({"lora_name": lora_name, "tags": tags, "status": status})


async def route_get_lora_tags_by_name(request):
    """
    GET /character_suite/lora_tags/by_name?lora_name=<name>
    Instantly returns the cached entry (tags + status) for a single LoRA with
    NO network fetch — used to populate the per-slot panel as soon as a LoRA
    is selected in the dropdown, before the node has ever executed. If the
    LoRA has never been looked up, status is "unknown" and the caller should
    fall back to POST /character_suite/lora_tags/fetch to trigger one.
    """
    try:
        from .nodes.lora_stacker import get_cached_entry
    except ImportError:
        return no_cache_json({"tags": [], "status": "unknown"})

    lora_name = request.rel_url.query.get("lora_name", None)
    if not lora_name:
        raise web.HTTPBadRequest(text="lora_name is required")

    return no_cache_json(get_cached_entry(lora_name))


# ── Registration ───────────────────────────────────────────────────────────────

def register_routes(server):
    # Characters
    server.app.router.add_get( "/character_suite/characters",          route_list_characters)
    server.app.router.add_post("/character_suite/character/save",       route_save_character)
    server.app.router.add_post("/character_suite/character/delete",     route_delete_character)

    # Segments
    server.app.router.add_get( "/character_suite/segments",            route_list_segments)
    server.app.router.add_post("/character_suite/segment/save",        route_save_segment)
    server.app.router.add_post("/character_suite/segment/delete",      route_delete_segment)

    # LoRA tags
    server.app.router.add_get( "/character_suite/lora_tags",           route_get_lora_tags)
    server.app.router.add_get( "/character_suite/lora_tags/by_name",   route_get_lora_tags_by_name)
    server.app.router.add_post("/character_suite/lora_tags/fetch",     route_fetch_lora_tags)
