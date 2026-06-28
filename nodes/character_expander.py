"""
Character Expander Node
Finds {CharacterName} tokens in prompt text and expands them to stored character base prompts.
Multiple characters supported. Expansion merges with surrounding text.
"""

import re
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CHARACTERS_FILE = os.path.join(DATA_DIR, "characters.json")


def load_characters():
    if not os.path.exists(CHARACTERS_FILE):
        return {}
    with open(CHARACTERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {c["name"].lower(): c for c in data.get("characters", [])}


class CharacterExpander:
    """
    Expands {CharacterName} tokens in a prompt string using stored character data.
    Positive and negative prompts are handled separately.
    Multiple {Name} tokens are supported in one prompt.
    """

    CATEGORY = "CharacterSuite"
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive", "negative", "expansion_log")
    FUNCTION = "expand"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive_text": ("STRING", {
                    "multiline": True,
                    "default": "masterpiece, best quality, {Avery}, standing in a field"
                }),
                "negative_text": ("STRING", {
                    "multiline": True,
                    "default": "worst quality, low quality"
                }),
                "merge_mode": (["append", "prepend"], {"default": "append"}),
            }
        }

    def expand(self, positive_text, negative_text, merge_mode):
        characters = load_characters()
        log_lines = []

        def replace_token(text, field, neg_accumulator):
            """Replace all {Name} tokens in text with the character's field value."""
            pattern = re.compile(r"\{(\w[\w\s]*?)\}")
            found = pattern.findall(text)

            for name in found:
                key = name.strip().lower()
                if key in characters:
                    char = characters[key]
                    replacement = char.get(field, "")
                    text = text.replace("{" + name + "}", replacement, 1)
                    # Accumulate negative from each matched character
                    char_neg = char.get("negative", "").strip()
                    if char_neg and char_neg not in neg_accumulator:
                        neg_accumulator.append(char_neg)
                    log_lines.append(f"[✓] Expanded '{name}' → {len(replacement.split(','))} tags")
                else:
                    log_lines.append(f"[✗] No character found for '{name}'")

            return text

        neg_additions = []

        # Expand positive — also collects each character's negative
        expanded_positive = replace_token(positive_text, "positive", neg_additions)

        # Expand any {Name} tokens in negative_text too
        expanded_negative = replace_token(negative_text, "negative", [])

        # Merge accumulated character negatives into the negative prompt
        if neg_additions:
            joined = ", ".join(neg_additions)
            if merge_mode == "append":
                expanded_negative = (expanded_negative.rstrip(", ") + ", " + joined).lstrip(", ")
            else:
                expanded_negative = (joined + ", " + expanded_negative.lstrip(", ")).rstrip(", ")

        log = "\n".join(log_lines) if log_lines else "No {Character} tokens found."
        return (expanded_positive, expanded_negative, log)


NODE_CLASS_MAPPINGS = {
    "CharacterExpander": CharacterExpander,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CharacterExpander": "🎭 Character Expander",
}
