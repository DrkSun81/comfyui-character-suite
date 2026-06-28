# ComfyUI Character Suite

A node suite for prompt engineering with persistent character and segment libraries.

---

## Installation

```bash
cd ComfyUI/custom_nodes/
git clone https://github.com/yourname/comfyui-character-suite
# or extract the zip directly into custom_nodes/
```

Restart ComfyUI. No pip dependencies required.

> **Windows note:** Requires Python 3.9+ (tested on 3.11). The embedded Python included with the standalone ComfyUI build is fully supported.

---

## Example Workflow

An example workflow is included at `examples/character_suite_example.json`.

Drag it into ComfyUI to load a fully wired setup covering all nodes:
- `{Avery}` expansion through CharacterExpander
- Segment injection via SegmentLoader → Prompt Builder (CharacterSuite)
- CLIP encoding → KSampler → SaveImage
- PromptCategorizer wired off the final positive prompt
- SegmentSaver ready to capture the built prompt for reuse

> **Before running:** update the checkpoint in the **CheckpointLoaderSimple** node to one you have installed. The default (`illustrious/absoluteTerritory_v3.safetensors`) is set as a placeholder.

---

## Nodes

All nodes appear under the **CharacterSuite** category in the Add Node menu.

---

### 🎭 Character Expander
**Class name:** `CharacterExpander`

Finds `{Name}` tokens in your prompt and replaces them with that character's stored tags. The character's negative prompt is automatically collected and merged into the negative output.

**Inputs:**
| Name | Type | Description |
|------|------|-------------|
| `positive_text` | STRING | Your prompt, e.g. `{Avery}, wearing armor, in a dungeon` |
| `negative_text` | STRING | Your base negative prompt |
| `merge_mode` | COMBO | `append` (default) or `prepend` — where character tags land |

**Outputs:** `positive`, `negative`, `expansion_log`

**Example:**
```
Input positive:  {Avery}, wearing armor, in a dungeon
Output positive: 1girl, silver hair, heterochromia, red left eye, blue right eye,
                 athletic build, confident expression, wearing armor, in a dungeon
```

Supports multiple characters in one prompt: `{Avery} and {Kira}`

---

### 🗂️ Prompt Categorizer
**Class name:** `PromptCategorizer`

Splits a flat comma-separated prompt into labeled buckets using keyword heuristics.

**Inputs:**
| Name | Type | Description |
|------|------|-------------|
| `prompt` | STRING | Any prompt string to analyze |
| `use_llm` | BOOLEAN | Send unclassified tags to a local LLM (default off) |
| `llm_api_url` | STRING | LM Studio / Ollama endpoint (optional) |

**Outputs:** `categorized_text` (formatted summary) + one STRING output per category:

| Output | Examples |
|--------|----------|
| `quality` | masterpiece, best quality, highres |
| `style` | anime, cel shading, watercolor |
| `character` | 1girl, heterochromia, confident expression |
| `hair` | long silver hair, twintails |
| `clothing` | school uniform, thighhighs |
| `action` | running, holding sword |
| `pose` | cowboy shot, from above |
| `scene` | forest, sunset, rain |
| `lighting` | rim light, dramatic lighting |
| `misc` | everything else |

Wire any individual output directly into other nodes.

---

### 💾 Save Prompt Segment
**Class name:** `SegmentSaver`

Saves any prompt string as a named entry in the persistent segment library.

**Inputs:**
| Name | Type | Description |
|------|------|-------------|
| `prompt_text` | STRING | The prompt content to save (linkable) |
| `category` | COMBO | One of: quality, style, character, hair, clothing, action, pose, scene, lighting, misc |
| `label` | STRING | Your name for this segment, e.g. `plate armor fantasy` |

**Output:** `status` — confirmation string shown in a Show Text node.

Saving with an existing category + label combination overwrites the previous entry.

---

### 📂 Load Prompt Segments
**Class name:** `SegmentLoader`

Loads up to 4 saved segments by category + label and concatenates them.

**Inputs:** Four `category` / `label` pairs (set category to `(skip)` to leave a slot unused), plus a `separator` string (default `, `).

**Outputs:** `combined_prompt` (all loaded segments joined), `load_log` (what was found/missed).

Wire `combined_prompt` into **Prompt Builder (CharacterSuite)** `segment_a`, or directly into a CLIP encoder.

---

### 🔍 Browse Segments
**Class name:** `SegmentBrowser`

Lists all saved segments. Wire output into a **Show Text** node to view your full library.

**Input:** `category` — `(all)` to show everything, or pick a specific category to filter.

**Output:** `segment_list` — formatted text block.

---

### 🔨 Prompt Builder (CharacterSuite)
**Class name:** `CS_PromptBuilder`

> **Note:** The internal registry key is `CS_PromptBuilder` (not `PromptBuilder`) to avoid conflicts with other installed node packs. In the Add Node menu it appears as **Prompt Builder (CharacterSuite)**.

Merges a character-expanded prompt with loaded segment strings into final positive and negative outputs.

**Required inputs:**
| Name | Type | Description |
|------|------|-------------|
| `base_positive` | STRING | Positive prompt from CharacterExpander |
| `base_negative` | STRING | Negative prompt from CharacterExpander |
| `insert_mode` | COMBO | `append`, `prepend`, or `after_quality` |
| `use_break` | BOOLEAN | Insert `BREAK` between sections instead of `, ` |

**Optional inputs:** `segment_a`, `segment_b`, `segment_c` (from SegmentLoader or any STRING), `extra_negative`

**Outputs:** `final_positive`, `final_negative`

**Insert modes:**
- `append` — segments go after your base prompt
- `prepend` — segments go before
- `after_quality` — inserts after the last quality tag (masterpiece, best quality…)

---

## Web Panel — Character Manager

A **Characters** sidebar tab is added to ComfyUI automatically (look for the person icon in the left sidebar panel). On older ComfyUI builds without the extensionManager API a floating **🎭 Characters** button appears in the top-right corner instead.

Features:
- **Search** characters by name or tag
- **Create / edit / delete** characters with positive + negative prompts
- **Copy** positive prompt to clipboard
- **Tags** for filtering and organization

Characters are stored in `data/characters.json` inside the node folder.

---

## Data Files

```
data/
  characters.json   # character name → positive/negative/tags
  segments.json     # id, category, label, content, created
```

These are plain JSON — safe to edit manually or back up.

---

## Typical Workflow

```
[CharacterExpander]
  positive_text: "{Avery}, wearing armor, in a dungeon"
  negative_text: "worst quality, low quality, blurry"
        |
        ├─ positive ──→ [Prompt Builder (CharacterSuite)] ──→ final_positive ──→ [CLIPTextEncode] ──→ [KSampler]
        └─ negative ──→ [Prompt Builder (CharacterSuite)] ──→ final_negative ──→ [CLIPTextEncode] ──┘

[SegmentLoader]
  category_1: clothing  label_1: plate armor fantasy
        |
        └─ combined_prompt ──→ [Prompt Builder (CharacterSuite)] segment_a

[PromptCategorizer] ← wire final_positive in to analyze the built prompt
[SegmentSaver]      ← wire final_positive in to save a refined look for reuse
[SegmentBrowser]    ← standalone, wire segment_list to a Show Text node
```

---

## LLM Categorization

Set `use_llm = True` in the Prompt Categorizer node and provide your local API URL:

- **LM Studio**: `http://localhost:1234/v1/chat/completions`
- **Ollama**: `http://localhost:11434/v1/chat/completions`

Heuristics run first; only unmatched tags are sent to the LLM. Any instruct model works, 7B+ recommended for best results.

---

## Compatibility

| Component | Requirement |
|-----------|-------------|
| ComfyUI | Any recent version |
| Python | 3.9+ (3.11 recommended, tested) |
| Frontend | Sidebar tab requires ComfyUI frontend 1.x (`extensionManager` API); older builds get a floating panel fallback |
| OS | Windows, Linux, macOS |
| Dependencies | None (stdlib only) |
