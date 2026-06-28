"""
Prompt Builder Node
Combines a base prompt (with optional {Character} tokens) + up to 3 injected segment strings
into final positive and negative outputs. Handles ordering and BREAK insertion.
"""


class PromptBuilder:
    """
    Merges character-expanded prompts with loaded segment strings.
    Outputs a clean final positive and negative ready for CLIP encoding.
    """

    CATEGORY = "CharacterSuite"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("final_positive", "final_negative")
    FUNCTION = "build"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_positive": ("STRING", {
                    "multiline": True,
                    "default": "masterpiece, best quality"
                }),
                "base_negative": ("STRING", {
                    "multiline": True,
                    "default": "worst quality, low quality, blurry"
                }),
                "insert_mode": (["append", "prepend", "after_quality"], {"default": "append"}),
                "use_break": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "segment_a": ("STRING", {"multiline": True, "default": ""}),
                "segment_b": ("STRING", {"multiline": True, "default": ""}),
                "segment_c": ("STRING", {"multiline": True, "default": ""}),
                "extra_negative": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    def build(self, base_positive, base_negative, insert_mode, use_break,
              segment_a="", segment_b="", segment_c="", extra_negative=""):

        segments = [s.strip() for s in [segment_a, segment_b, segment_c] if s.strip()]
        sep = " BREAK " if use_break else ", "

        if not segments:
            final_positive = base_positive.strip()
        else:
            combined_segments = ", ".join(segments)

            if insert_mode == "append":
                final_positive = base_positive.rstrip(", ") + sep + combined_segments

            elif insert_mode == "prepend":
                final_positive = combined_segments + sep + base_positive.lstrip(", ")

            elif insert_mode == "after_quality":
                # Heuristic: split after first comma-group that looks like quality tags
                quality_endings = {
                    "masterpiece", "best quality", "high quality", "ultra detailed",
                    "highres", "absurdres"
                }
                parts = [p.strip() for p in base_positive.split(",")]
                insert_idx = 0
                for i, part in enumerate(parts):
                    if part.lower() in quality_endings:
                        insert_idx = i + 1
                # Inject after last quality tag found (or at start if none)
                before = ", ".join(parts[:insert_idx])
                after = ", ".join(parts[insert_idx:])
                pieces = [p for p in [before, combined_segments, after] if p]
                final_positive = sep.join(pieces) if use_break else ", ".join(pieces)

        # Negative merge
        neg_parts = [base_negative.strip()]
        if extra_negative.strip():
            neg_parts.append(extra_negative.strip())
        final_negative = ", ".join(p for p in neg_parts if p)

        return (final_positive, final_negative)


NODE_CLASS_MAPPINGS = {
    "CS_PromptBuilder": PromptBuilder,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CS_PromptBuilder": "🔨 Prompt Builder (CharacterSuite)",
}
