"""
Prompt Segment Library Node
Save labeled prompt segments (clothing styles, hair, poses, etc.) to a persistent JSON library.
Retrieve them by category + label to inject into new prompts.
"""

import json
import os
import uuid
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SEGMENTS_FILE = os.path.join(DATA_DIR, "segments.json")

CATEGORIES = [
    "quality", "style", "character", "hair", "clothing",
    "action", "pose", "scene", "lighting", "misc"
]


def load_segments():
    if not os.path.exists(SEGMENTS_FILE):
        return []
    with open(SEGMENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("segments", [])


def save_segments(segments):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEGMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"segments": segments}, f, indent=2, ensure_ascii=False)


def get_labels_for_category(category):
    segments = load_segments()
    labels = [s["label"] for s in segments if s["category"] == category]
    return labels if labels else ["(none saved)"]


class SegmentSaver:
    """
    Save a prompt string as a named segment under a category.
    Duplicate labels in the same category are overwritten.
    """

    CATEGORY = "CharacterSuite"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "save_segment"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_text": ("STRING", {"multiline": True, "default": ""}),
                "category": (CATEGORIES, {"default": "clothing"}),
                "label": ("STRING", {"default": "e.g. school uniform casual"}),
            }
        }

    def save_segment(self, prompt_text, category, label):
        if not prompt_text.strip() or not label.strip():
            return ("⚠️ Empty prompt or label — nothing saved.",)

        segments = load_segments()

        # Overwrite if same category+label exists
        existing = next(
            (i for i, s in enumerate(segments)
             if s["category"] == category and s["label"].lower() == label.lower()),
            None
        )

        entry = {
            "id": str(uuid.uuid4())[:8],
            "category": category,
            "label": label.strip(),
            "content": prompt_text.strip(),
            "created": int(time.time()),
        }

        if existing is not None:
            segments[existing] = entry
            status = f"✓ Updated '{label}' in [{category}]"
        else:
            segments.append(entry)
            status = f"✓ Saved '{label}' to [{category}] ({len(segments)} total)"

        save_segments(segments)
        return (status,)


class SegmentLoader:
    """
    Load a saved segment by category and label, output its prompt content.
    Supports loading up to 4 segments and concatenating them.
    """

    CATEGORY = "CharacterSuite"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("combined_prompt", "load_log")
    FUNCTION = "load_segments_node"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "category_1": (["(skip)"] + CATEGORIES, {"default": "clothing"}),
                "label_1": ("STRING", {"default": ""}),
                "category_2": (["(skip)"] + CATEGORIES, {"default": "(skip)"}),
                "label_2": ("STRING", {"default": ""}),
                "category_3": (["(skip)"] + CATEGORIES, {"default": "(skip)"}),
                "label_3": ("STRING", {"default": ""}),
                "category_4": (["(skip)"] + CATEGORIES, {"default": "(skip)"}),
                "label_4": ("STRING", {"default": ""}),
                "separator": ("STRING", {"default": ", "}),
            }
        }

    def load_segments_node(self, category_1, label_1, category_2, label_2,
                           category_3, label_3, category_4, label_4, separator):
        segments = load_segments()
        pairs = [
            (category_1, label_1),
            (category_2, label_2),
            (category_3, label_3),
            (category_4, label_4),
        ]

        results = []
        log_lines = []

        for cat, lbl in pairs:
            if cat == "(skip)" or not lbl.strip():
                continue
            match = next(
                (s for s in segments
                 if s["category"] == cat and s["label"].lower() == lbl.strip().lower()),
                None
            )
            if match:
                results.append(match["content"])
                log_lines.append(f"[✓] {cat}/{lbl} → {len(match['content'].split(','))} tags")
            else:
                log_lines.append(f"[✗] Not found: {cat}/{lbl}")

        combined = separator.join(results)
        log = "\n".join(log_lines) if log_lines else "Nothing loaded."
        return (combined, log)


class SegmentBrowser:
    """
    Lists all saved segments for a given category.
    Output is a formatted text block suitable for display in a Show Text node.
    """

    CATEGORY = "CharacterSuite"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("segment_list",)
    FUNCTION = "browse"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "category": (["(all)"] + CATEGORIES, {"default": "(all)"}),
            }
        }

    def browse(self, category):
        segments = load_segments()
        if category != "(all)":
            segments = [s for s in segments if s["category"] == category]

        if not segments:
            return (f"No segments saved for category: {category}",)

        lines = []
        current_cat = None
        for s in sorted(segments, key=lambda x: (x["category"], x["label"])):
            if s["category"] != current_cat:
                current_cat = s["category"]
                lines.append(f"\n[{current_cat.upper()}]")
            preview = s["content"][:60] + ("…" if len(s["content"]) > 60 else "")
            lines.append(f"  • {s['label']}: {preview}")

        return ("\n".join(lines).strip(),)


NODE_CLASS_MAPPINGS = {
    "SegmentSaver": SegmentSaver,
    "SegmentLoader": SegmentLoader,
    "SegmentBrowser": SegmentBrowser,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SegmentSaver": "💾 Save Prompt Segment",
    "SegmentLoader": "📂 Load Prompt Segments",
    "SegmentBrowser": "🔍 Browse Segments",
}
