"""
Character Suite — Backend API Routes
Registered into ComfyUI's PromptServer to serve the web panel requests.
Handles character CRUD and segment CRUD via /character_suite/* endpoints.
"""

import json
import os
import uuid
import time
from aiohttp import web

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CHARACTERS_FILE = os.path.join(DATA_DIR, "characters.json")
SEGMENTS_FILE = os.path.join(DATA_DIR, "segments.json")


# ── File helpers ──────────────────────────────────────────────────────────────

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Character routes ──────────────────────────────────────────────────────────

async def route_list_characters(request):
    data = load_json(CHARACTERS_FILE, {"characters": []})
    return web.json_response(data)


async def route_save_character(request):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise web.HTTPBadRequest(text="name is required")

    data = load_json(CHARACTERS_FILE, {"characters": []})
    chars = data["characters"]

    existing = next((i for i, c in enumerate(chars) if c["name"].lower() == name.lower()), None)
    entry = {
        "name": name,
        "positive": body.get("positive", "").strip(),
        "negative": body.get("negative", "").strip(),
        "tags": body.get("tags", []),
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

    data = load_json(CHARACTERS_FILE, {"characters": []})
    before = len(data["characters"])
    data["characters"] = [c for c in data["characters"] if c["name"].lower() != name.lower()]

    if len(data["characters"]) == before:
        raise web.HTTPNotFound(text=f"Character '{name}' not found")

    save_json(CHARACTERS_FILE, data)
    return web.json_response({"status": "deleted", "name": name})


# ── Segment routes ────────────────────────────────────────────────────────────

async def route_list_segments(request):
    category = request.rel_url.query.get("category", None)
    data = load_json(SEGMENTS_FILE, {"segments": []})
    segs = data["segments"]
    if category and category != "(all)":
        segs = [s for s in segs if s["category"] == category]
    return web.json_response({"segments": segs})


async def route_save_segment(request):
    body = await request.json()
    category = body.get("category", "").strip()
    label = body.get("label", "").strip()
    content = body.get("content", "").strip()

    if not all([category, label, content]):
        raise web.HTTPBadRequest(text="category, label, and content are required")

    data = load_json(SEGMENTS_FILE, {"segments": []})
    segs = data["segments"]

    existing = next(
        (i for i, s in enumerate(segs)
         if s["category"] == category and s["label"].lower() == label.lower()),
        None
    )
    entry = {
        "id": str(uuid.uuid4())[:8],
        "category": category,
        "label": label,
        "content": content,
        "created": int(time.time()),
    }
    if existing is not None:
        segs[existing] = entry
    else:
        segs.append(entry)

    save_json(SEGMENTS_FILE, {"segments": segs})
    return web.json_response({"status": "ok", "label": label})


async def route_delete_segment(request):
    body = await request.json()
    seg_id = body.get("id", "").strip()
    if not seg_id:
        raise web.HTTPBadRequest(text="id is required")

    data = load_json(SEGMENTS_FILE, {"segments": []})
    before = len(data["segments"])
    data["segments"] = [s for s in data["segments"] if s["id"] != seg_id]

    if len(data["segments"]) == before:
        raise web.HTTPNotFound(text=f"Segment '{seg_id}' not found")

    save_json(SEGMENTS_FILE, data)
    return web.json_response({"status": "deleted", "id": seg_id})


# ── Registration ──────────────────────────────────────────────────────────────

def register_routes(server):
    server.app.router.add_get("/character_suite/characters",         route_list_characters)
    server.app.router.add_post("/character_suite/character/save",    route_save_character)
    server.app.router.add_post("/character_suite/character/delete",  route_delete_character)
    server.app.router.add_get("/character_suite/segments",           route_list_segments)
    server.app.router.add_post("/character_suite/segment/save",      route_save_segment)
    server.app.router.add_post("/character_suite/segment/delete",    route_delete_segment)
