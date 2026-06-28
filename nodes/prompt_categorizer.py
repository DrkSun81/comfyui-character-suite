"""
Prompt Categorizer Node
Splits a flat comma-separated prompt into labeled category buckets.
Default: keyword heuristics. Optional: LLM classification via local API.
"""

import json
import re
import os
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Heuristic keyword maps — extend these freely
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS = {
    "quality": {
        "masterpiece", "best quality", "high quality", "ultra detailed", "ultra-detailed",
        "highres", "absurdres", "8k", "4k", "hdr", "sharp focus", "detailed",
        "intricate", "professional", "award winning", "wallpaper", "official art",
        "worst quality", "low quality", "bad quality", "normal quality", "jpeg artifacts",
        "blurry", "lowres", "out of focus",
    },
    "style": {
        "anime", "manga", "illustration", "digital art", "concept art", "watercolor",
        "oil painting", "sketch", "lineart", "cel shading", "flat color", "painterly",
        "realistic", "semi-realistic", "chibi", "pixel art", "3d render", "cgi",
        "webtoon", "comic", "cartoon", "gothic", "cyberpunk", "fantasy", "sci-fi",
        "art nouveau", "art deco", "impressionist", "noir",
    },
    "character": {
        "1girl", "1boy", "2girls", "2boys", "multiple girls", "multiple boys",
        "male", "female", "woman", "man", "girl", "boy", "child", "adult",
        "elf", "demon", "angel", "catgirl", "foxgirl", "wolf", "anthro", "furry",
        "heterochromia", "ahoge", "twintails", "ponytail", "braid", "bangs",
        "blush", "smile", "expression", "face", "eyes", "lips", "freckles",
        "athletic", "muscular", "slim", "curvy", "petite", "tall", "short",
        "tan", "pale", "dark skin", "skin",
    },
    "hair": {
        "hair", "hairstyle", "short hair", "long hair", "medium hair", "very long hair",
        "straight hair", "wavy hair", "curly hair", "spiky hair", "fluffy hair",
        "white hair", "black hair", "brown hair", "blonde hair", "blue hair",
        "red hair", "green hair", "pink hair", "purple hair", "silver hair",
        "gray hair", "multicolored hair", "gradient hair", "streaked hair",
        "twin tails", "twin braids", "side ponytail", "drill hair", "hime cut",
        "undercut", "bob cut", "pixie cut",
    },
    "clothing": {
        "dress", "skirt", "pants", "jeans", "shorts", "shirt", "blouse", "top",
        "jacket", "coat", "hoodie", "sweater", "uniform", "suit", "tuxedo",
        "kimono", "yukata", "qipao", "armor", "bikini", "swimsuit", "lingerie",
        "underwear", "bra", "panties", "stockings", "thighhighs", "socks",
        "boots", "shoes", "heels", "sneakers", "gloves", "hat", "cap", "hood",
        "cloak", "cape", "scarf", "tie", "collar", "choker", "jewelry", "earrings",
        "necklace", "bracelet", "ring", "outfit", "costume", "attire", "clothing",
        "naked", "nude", "topless", "barefoot",
    },
    "action": {
        "running", "walking", "jumping", "sitting", "standing", "lying", "leaning",
        "holding", "reaching", "fighting", "casting", "flying", "floating",
        "eating", "drinking", "sleeping", "reading", "writing", "looking",
        "waving", "pointing", "hugging", "kissing", "dancing", "singing",
        "laughing", "crying", "thinking", "stretching", "crouching",
    },
    "pose": {
        "pose", "cowboy shot", "from above", "from below", "from behind", "from side",
        "full body", "upper body", "bust", "portrait", "close-up", "dutch angle",
        "dynamic pose", "action pose", "standing", "sitting", "lying down",
        "spread legs", "crossed legs", "hands on hips", "arms crossed",
        "looking at viewer", "looking away", "looking back", "pov",
        "profile", "side view", "three-quarter view",
    },
    "scene": {
        "indoors", "outdoors", "interior", "exterior", "background", "setting",
        "forest", "ocean", "beach", "mountain", "city", "street", "alley",
        "room", "bedroom", "kitchen", "classroom", "office", "library",
        "castle", "dungeon", "space", "sky", "clouds", "night", "day",
        "sunset", "sunrise", "rain", "snow", "fog", "fire", "water",
        "nature", "garden", "park", "stage", "arena", "battlefield",
    },
    "lighting": {
        "lighting", "light", "shadow", "rim light", "backlight", "sunlight",
        "moonlight", "neon", "glow", "ambient", "dramatic lighting",
        "soft light", "hard light", "bloom", "lens flare", "volumetric",
        "dark", "bright", "moody", "cinematic lighting",
    },
}

# Flatten keyword → category lookup
KEYWORD_TO_CATEGORY = {}
for cat, keywords in CATEGORY_KEYWORDS.items():
    for kw in keywords:
        KEYWORD_TO_CATEGORY[kw.lower()] = cat


def heuristic_categorize(tags: list[str]) -> dict:
    buckets = {cat: [] for cat in CATEGORY_KEYWORDS}
    buckets["misc"] = []

    for tag in tags:
        tag_clean = tag.strip().lower()
        matched = False
        # Try exact match first
        if tag_clean in KEYWORD_TO_CATEGORY:
            buckets[KEYWORD_TO_CATEGORY[tag_clean]].append(tag.strip())
            matched = True
        else:
            # Try substring match
            for kw, cat in KEYWORD_TO_CATEGORY.items():
                if kw in tag_clean or tag_clean in kw:
                    buckets[cat].append(tag.strip())
                    matched = True
                    break
        if not matched:
            buckets["misc"].append(tag.strip())

    return buckets


def llm_categorize(tags: list[str], api_url: str) -> dict:
    """
    Sends unclassified tags to a local LLM endpoint (OpenAI-compatible or raw).
    Returns a category dict. Falls back to heuristic on error.
    """
    prompt = (
        "Classify each of these anime/illustration prompt tags into one of these categories: "
        "quality, style, character, hair, clothing, action, pose, scene, lighting, misc.\n\n"
        "Tags: " + ", ".join(tags) + "\n\n"
        "Respond ONLY with valid JSON like: {\"quality\": [...], \"style\": [...], ...}\n"
        "Every tag must appear in exactly one category. No extra text."
    )

    payload = json.dumps({
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 2000,
    }).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            # Try OpenAI-compatible response shape
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                # Try raw content field
                content = result.get("content", "")
            parsed = json.loads(content)
            return parsed
    except Exception as e:
        print(f"[CharacterSuite] LLM categorize failed: {e} -- falling back to heuristics")
        return heuristic_categorize(tags)


def buckets_to_string(buckets: dict) -> str:
    lines = []
    for cat, tags in buckets.items():
        if tags:
            lines.append(f"[{cat.upper()}]\n{', '.join(tags)}")
    return "\n\n".join(lines)


class PromptCategorizer:
    """
    Splits a flat prompt into labeled category buckets.
    Outputs the categorized breakdown as a string, plus individual STRING outputs per category.
    """

    CATEGORY = "CharacterSuite"
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING",
                    "STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("categorized_text", "quality", "style", "character", "hair",
                    "clothing", "action", "pose", "scene", "lighting", "misc")
    FUNCTION = "categorize"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "masterpiece, best quality, 1girl, long silver hair, school uniform, standing, looking at viewer, classroom, soft lighting"
                }),
                "use_llm": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "llm_api_url": ("STRING", {
                    "default": "http://localhost:1234/v1/chat/completions",
                    "multiline": False
                }),
            }
        }

    def categorize(self, prompt, use_llm, llm_api_url="http://localhost:1234/v1/chat/completions"):
        tags = [t.strip() for t in prompt.split(",") if t.strip()]

        if use_llm:
            buckets = llm_categorize(tags, llm_api_url)
            # Ensure all expected keys exist
            for key in list(CATEGORY_KEYWORDS.keys()) + ["misc"]:
                buckets.setdefault(key, [])
        else:
            buckets = heuristic_categorize(tags)

        summary = buckets_to_string(buckets)

        def join(cat):
            return ", ".join(buckets.get(cat, []))

        return (
            summary,
            join("quality"),
            join("style"),
            join("character"),
            join("hair"),
            join("clothing"),
            join("action"),
            join("pose"),
            join("scene"),
            join("lighting"),
            join("misc"),
        )


NODE_CLASS_MAPPINGS = {
    "PromptCategorizer": PromptCategorizer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCategorizer": "🗂️ Prompt Categorizer",
}
