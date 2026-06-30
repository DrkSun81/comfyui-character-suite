"""
ComfyUI Character Suite
=======================
A node suite for managing character prompts, expanding {Name} wildcards,
categorizing prompt tags, building a searchable segment library, and stacking
LoRAs with interactive CivitAI trigger-word picker.

Nodes:
🎭 Character Expander   — expands {Name} tokens to stored base prompts
🗂️ Prompt Categorizer   — splits prompt into quality/style/clothing/hair/etc buckets
💾 Save Prompt Segment  — saves a labeled prompt fragment to the library
📂 Load Prompt Segments — loads up to 4 segments by category+label
🔍 Browse Segments      — lists all saved segments (use with Show Text node)
🔨 Prompt Builder       — merges character prompts + segments into final output
🔗 LoRA Stacker         — up to 10 LoRAs in one node with CivitAI tag picker

Web Panel:
🎭 Character Manager — sidebar UI to create/edit/delete characters
"""

import os
import sys

# Ensure nodes subpackage is importable
sys.path.insert(0, os.path.dirname(__file__))

from .nodes.character_expander import NODE_CLASS_MAPPINGS as CM_EXPANDER, NODE_DISPLAY_NAME_MAPPINGS as DN_EXPANDER
from .nodes.prompt_categorizer import NODE_CLASS_MAPPINGS as CM_CATEG,   NODE_DISPLAY_NAME_MAPPINGS as DN_CATEG
from .nodes.segment_library    import NODE_CLASS_MAPPINGS as CM_SEGS,    NODE_DISPLAY_NAME_MAPPINGS as DN_SEGS
from .nodes.prompt_builder     import NODE_CLASS_MAPPINGS as CM_BUILDER,  NODE_DISPLAY_NAME_MAPPINGS as DN_BUILDER
from .nodes.lora_stacker       import NODE_CLASS_MAPPINGS as CM_LORA,    NODE_DISPLAY_NAME_MAPPINGS as DN_LORA

NODE_CLASS_MAPPINGS = {
    **CM_EXPANDER,
    **CM_CATEG,
    **CM_SEGS,
    **CM_BUILDER,
    **CM_LORA,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    **DN_EXPANDER,
    **DN_CATEG,
    **DN_SEGS,
    **DN_BUILDER,
    **DN_LORA,
}

WEB_DIRECTORY = os.path.join(os.path.dirname(__file__), "web")

# Register backend API routes for the web panel + lora tag endpoints
try:
    from server import PromptServer
    from .api_routes import register_routes
    register_routes(PromptServer.instance)
    print("[CharacterSuite] OK: API routes registered")
except Exception as e:
    print(f"[CharacterSuite] WARNING: Could not register API routes: {e}")

print(f"[CharacterSuite] OK: Loaded {len(NODE_CLASS_MAPPINGS)} nodes")

# Warm the LoRA trigger-word cache in the background so the library is ready
# to browse without waiting for each LoRA to be selected/run for the first
# time. Runs on a daemon thread with its own startup delay + rate limiting,
# so it never blocks ComfyUI boot or node registration.
try:
    from .nodes.lora_stacker import start_background_scan
    start_background_scan()
except Exception as e:
    print(f"[CharacterSuite] WARNING: could not start LoRA tag startup scan: {e}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
