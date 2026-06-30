/**
 * CharacterSuite — LoRA Stacker Widget
 * Adds an interactive tag-chip panel to the CS_LoraStacker node.
 *
 * Two sources of trigger words feed the UI:
 *   1. Per-slot, pre-execution: as soon as a LoRA is picked in a lora_N
 *      dropdown, its cached tags (or an on-demand fetch) render inline right
 *      under that slot's row.
 *   2. Aggregate, post-execution: after the node runs, the backend pushes
 *      the full set of tags it actually applied via
 *      /character_suite/lora_tags?node_id=X, shown in the bottom panel.
 *
 * Both sources share one `selectedSet` of active trigger words (synced via
 * a chip registry) so toggling a tag anywhere — inline, aggregate, or by
 * hand-editing the textarea — stays consistent everywhere it's rendered.
 */

import { app } from "../../scripts/app.js";

const NODE_TYPE  = "CS_LoraStacker";
const POLL_MS    = 1200;   // re-fetch tags after execution settles
const MAX_LORAS  = 10;     // keep in sync with nodes/lora_stacker.py MAX_LORAS

// ─── colour palette (DrkSun81 theme compatible) ───────────────────────────────
const STYLE = `
.cs-lora-tag-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 6px 4px 2px;
  font-family: monospace;
}
.cs-inline-slot-panel {
  padding: 2px 4px 4px 18px;
  font-family: monospace;
}
.cs-lora-tag-group {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.cs-lora-tag-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cs-lora-tag-group-label {
  font-size: 10px;
  color: #9b8fa0;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding-left: 2px;
  flex: 1;
}
.cs-lora-tag-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.cs-tag-chip {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 10px;
  background: #2a1a2e;
  border: 1px solid #5a2a3a;
  color: #e8d5e8;
  font-size: 11px;
  cursor: pointer;
  user-select: none;
  transition: background 0.12s, border-color 0.12s;
  white-space: nowrap;
}
.cs-tag-chip:hover {
  background: #8b0000;
  border-color: #cc2244;
  color: #fff;
}
.cs-tag-chip.cs-tag-active {
  background: #6b0000;
  border-color: #ff4466;
  color: #fff;
}
.cs-selected-box {
  width: 100%;
  min-height: 36px;
  background: #150a18;
  border: 1px solid #5a2a3a;
  border-radius: 4px;
  color: #e8d5e8;
  font-size: 11px;
  padding: 4px 6px;
  box-sizing: border-box;
  resize: vertical;
  font-family: monospace;
}
.cs-tag-actions {
  display: flex;
  gap: 6px;
  margin-top: 2px;
  flex-wrap: wrap;
}
.cs-tag-btn {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #2a1a2e;
  border: 1px solid #5a2a3a;
  color: #c0a0c8;
  cursor: pointer;
}
.cs-tag-btn:hover {
  background: #3a0a1e;
  border-color: #8b0000;
  color: #fff;
}
.cs-select-all-btn {
  font-size: 9px;
  padding: 1px 6px;
  flex: none;
}
.cs-add-all-global-btn {
  align-self: flex-start;
  border-color: #8b0000;
  color: #e8d5e8;
}
.cs-no-tags {
  font-size: 11px;
  color: #6a5a70;
  font-style: italic;
  padding: 2px 4px;
}
.cs-inline-loading {
  font-size: 10px;
  color: #9b8fa0;
  font-style: italic;
  padding: 2px 4px;
}
.cs-inline-failed {
  font-size: 10px;
  color: #ff6a6a;
  padding: 2px 4px;
  cursor: pointer;
  text-decoration: underline dotted;
}
.cs-inline-failed:hover {
  color: #ff9a9a;
}
`;

function injectStyle() {
  if (document.getElementById("cs-lora-stacker-style")) return;
  const el = document.createElement("style");
  el.id = "cs-lora-stacker-style";
  el.textContent = STYLE;
  document.head.appendChild(el);
}

// ─── backend calls ──────────────────────────────────────────────────────────────

// Aggregate tags pushed by the most recent execution (server-side, keyed by node id)
async function fetchExecutionTags(nodeId) {
  try {
    // no-store: this is polled repeatedly against the same URL after every
    // execution — a cached GET here would keep showing tags from the first run.
    const r = await fetch(`/character_suite/lora_tags?node_id=${nodeId}`, { cache: "no-store" });
    if (!r.ok) return {};
    return await r.json();
  } catch {
    return {};
  }
}

// Instant, no-network cache lookup for a single LoRA (pre-execution)
async function fetchCachedEntry(loraName) {
  try {
    const r = await fetch(`/character_suite/lora_tags/by_name?lora_name=${encodeURIComponent(loraName)}`, { cache: "no-store" });
    if (!r.ok) return { tags: [], status: "unknown" };
    return await r.json();
  } catch {
    return { tags: [], status: "unknown" };
  }
}

// On-demand CivitAI fetch (or force refresh) for a single LoRA
async function fetchAndCacheEntry(loraName, force = false) {
  try {
    const r = await fetch("/character_suite/lora_tags/fetch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ lora_name: loraName, force }),
    });
    if (!r.ok) return { tags: [], status: "failed" };
    const data = await r.json();
    return { tags: data.tags || [], status: data.status || "unknown" };
  } catch {
    return { tags: [], status: "failed" };
  }
}

// ─── shared selection state (selectedSet + cross-panel chip sync) ──────────────

// ComfyUI's widget configure/undo-redo machinery can hand a DOM widget's
// setValue() something other than a string (e.g. undefined, or a stray
// non-string default) — never assume `.split` is safe without this guard.
function parseTagList(v) {
  if (typeof v !== "string") return [];
  return v.split(",").map(s => s.trim()).filter(Boolean);
}

function createTagState(tagsWidget, selBox) {
  const state = {
    selectedSet: new Set(parseTagList(tagsWidget.value)),
    chipRegistry: new Map(),  // tag -> Set<chipElement>
    slotData: {},             // slot index -> { loraName, tags, status } | null
    tagsWidget,
    selBox,
  };
  state.onChanged = () => {
    const val = [...state.selectedSet].join(", ");
    tagsWidget.value = val;
    selBox.value = val;
  };
  return state;
}

function registerChip(state, tag, el) {
  if (!state.chipRegistry.has(tag)) state.chipRegistry.set(tag, new Set());
  state.chipRegistry.get(tag).add(el);
}

function syncChipState(state, tag) {
  const els = state.chipRegistry.get(tag);
  if (!els) return;
  for (const el of [...els]) {
    if (!document.contains(el)) {
      els.delete(el);
      continue;
    }
    el.classList.toggle("cs-tag-active", state.selectedSet.has(tag));
  }
}

function syncAllChipStates(state) {
  for (const tag of state.chipRegistry.keys()) syncChipState(state, tag);
}

function toggleTag(state, tag) {
  if (state.selectedSet.has(tag)) state.selectedSet.delete(tag);
  else state.selectedSet.add(tag);
  state.onChanged();
  syncChipState(state, tag);
}

// Idempotent: adding tags already in selectedSet is a no-op for those tags.
function addAllTags(state, tags) {
  for (const tag of tags) state.selectedSet.add(tag);
  state.onChanged();
  syncAllChipStates(state);
}

// ─── chip group builder (shared by inline per-slot + aggregate panels) ─────────

function buildChipGroup(loraName, tags, state, opts = {}) {
  const group = document.createElement("div");
  group.className = "cs-lora-tag-group";

  const header = document.createElement("div");
  header.className = "cs-lora-tag-group-header";

  const label = document.createElement("div");
  label.className = "cs-lora-tag-group-label";
  label.textContent = opts.label ?? loraName.replace(/^.*[\\/]/, "").replace(/\.[^.]+$/, "");
  header.appendChild(label);

  if (tags.length) {
    const selAllBtn = document.createElement("button");
    selAllBtn.className = "cs-tag-btn cs-select-all-btn";
    selAllBtn.textContent = "+ All";
    selAllBtn.title = `Add all ${tags.length} trigger word(s) from this LoRA`;
    selAllBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      addAllTags(state, tags);
    });
    header.appendChild(selAllBtn);
  }
  group.appendChild(header);

  if (!tags.length) {
    const msg = document.createElement("div");
    msg.className = "cs-no-tags";
    msg.textContent = "no trigger words found";
    group.appendChild(msg);
    return group;
  }

  const chips = document.createElement("div");
  chips.className = "cs-lora-tag-chips";
  for (const tag of tags) {
    const chip = document.createElement("span");
    chip.className = "cs-tag-chip" + (state.selectedSet.has(tag) ? " cs-tag-active" : "");
    chip.textContent = tag;
    chip.title = "Click to toggle in trigger prompt";
    chip.addEventListener("click", () => toggleTag(state, tag));
    registerChip(state, tag, chip);
    chips.appendChild(chip);
  }
  group.appendChild(chips);
  return group;
}

// ─── aggregate (post-execution) panel ──────────────────────────────────────────

function buildAggregatePanel(container, executionTags, state) {
  container.innerHTML = "";

  // Merge what the last execution actually applied with whatever per-slot
  // tags are already known client-side, so the panel is useful even before
  // the node has ever run. Execution data wins on conflicts (it's what
  // actually got loaded).
  const merged = {};
  for (const slot of Object.values(state.slotData)) {
    if (slot && slot.tags?.length) merged[slot.loraName] = slot.tags;
  }
  for (const [name, tags] of Object.entries(executionTags || {})) {
    if (Array.isArray(tags) && tags.length) merged[name] = tags;
  }

  if (Object.keys(merged).length === 0) {
    const msg = document.createElement("div");
    msg.className = "cs-no-tags";
    msg.textContent = "Select a LoRA above, or run the node, to load trigger words.";
    container.appendChild(msg);
    return;
  }

  const globalBtn = document.createElement("button");
  globalBtn.className = "cs-tag-btn cs-add-all-global-btn";
  globalBtn.textContent = "★ Add All From Every Loaded LoRA";
  globalBtn.addEventListener("click", () => {
    const all = [];
    for (const tags of Object.values(merged)) all.push(...tags);
    addAllTags(state, all);  // Set-backed selectedSet dedupes automatically
  });
  container.appendChild(globalBtn);

  for (const [loraName, tags] of Object.entries(merged)) {
    container.appendChild(buildChipGroup(loraName, tags, state));
  }
}

// ─── per-slot inline panel (pre-execution, fires on dropdown selection) ────────

function renderSlotPanel(container, slotIndex, state, loraName, entry) {
  container.innerHTML = "";

  if (entry.status === "failed") {
    const msg = document.createElement("div");
    msg.className = "cs-inline-failed";
    msg.textContent = "⚠ fetch failed — click to retry";
    msg.addEventListener("click", () => refreshSlotPanel(container, slotIndex, state, { force: true }));
    container.appendChild(msg);
    return;
  }

  container.appendChild(buildChipGroup(loraName, entry.tags || [], state));
}

async function refreshSlotPanel(container, slotIndex, state, opts = {}) {
  const node = state.node;
  const loraWidget = node.widgets?.find(w => w.name === `lora_${slotIndex}`);
  const loraName = loraWidget?.value;

  if (!loraName || loraName === "None") {
    container.innerHTML = "";
    state.slotData[slotIndex] = null;
    updateSlotCollapse(node, slotIndex);
    return;
  }

  updateSlotCollapse(node, slotIndex);

  let entry = await fetchCachedEntry(loraName);
  if (entry.status === "unknown" || opts.force) {
    container.innerHTML = "";
    const loading = document.createElement("div");
    loading.className = "cs-inline-loading";
    loading.textContent = opts.force ? "retrying…" : "fetching trigger words…";
    container.appendChild(loading);
    entry = await fetchAndCacheEntry(loraName, !!opts.force);
  }

  // The user may have changed the dropdown again while this was in flight.
  if (node.widgets?.find(w => w.name === `lora_${slotIndex}`)?.value !== loraName) return;

  state.slotData[slotIndex] = { loraName, tags: entry.tags || [], status: entry.status };
  renderSlotPanel(container, slotIndex, state, loraName, entry);
}

// ─── widget collapse (hide strength/bypass/force_fetch rows when lora_N == None) ─

function setWidgetCollapsed(widget, collapsed) {
  if (!widget) return;
  if (collapsed) {
    if (!widget._csOrigComputeSize) widget._csOrigComputeSize = widget.computeSize;
    widget.computeSize = () => [0, -4];
  } else if (widget._csOrigComputeSize) {
    widget.computeSize = widget._csOrigComputeSize;
  }
}

function updateSlotCollapse(node, slotIndex) {
  const loraWidget = node.widgets?.find(w => w.name === `lora_${slotIndex}`);
  const collapsed = !loraWidget || loraWidget.value === "None";
  for (const name of [
    `strength_model_${slotIndex}`,
    `strength_clip_${slotIndex}`,
    `bypass_${slotIndex}`,
    `force_fetch_${slotIndex}`,
  ]) {
    setWidgetCollapsed(node.widgets?.find(w => w.name === name), collapsed);
  }
  setWidgetCollapsed(node._csInlineWidgets?.[slotIndex], collapsed);
  node.setSize(node.computeSize());
  node.graph?.setDirtyCanvas(true, true);
}

// ─── widget ordering ────────────────────────────────────────────────────────────

function moveWidgetAfter(node, widget, afterName) {
  const idx = node.widgets.indexOf(widget);
  if (idx === -1) return;
  node.widgets.splice(idx, 1);
  const afterIdx = node.widgets.findIndex(w => w.name === afterName);
  node.widgets.splice(afterIdx + 1, 0, widget);
}

function hookSlotCombo(node, slotIndex, state, container) {
  const widget = node.widgets?.find(w => w.name === `lora_${slotIndex}`);
  if (!widget) return;
  const origCallback = widget.callback?.bind(widget);
  widget.callback = function (value, ...rest) {
    const ret = origCallback ? origCallback(value, ...rest) : undefined;
    refreshSlotPanel(container, slotIndex, state);
    return ret;
  };
}

// ─── register extension ───────────────────────────────────────────────────────
app.registerExtension({
  name: "CharacterSuite.LoraStacker",

  async nodeCreated(node) {
    if (node.comfyClass !== NODE_TYPE) return;

    injectStyle();

    // Find or create the hidden selected_tags widget
    let tagsWidget = node.widgets?.find(w => w.name === "selected_tags");
    if (!tagsWidget) {
      // Shouldn't normally happen, but create a fallback STRING widget
      tagsWidget = {
        name: "selected_tags",
        value: "",
        type: "text",
        callback: () => {},
      };
    }
    tagsWidget.computeSize = () => [0, -4];  // hide the default widget row

    // Selected tags textarea
    const selBox = document.createElement("textarea");
    selBox.className = "cs-selected-box";
    selBox.placeholder = "Click tags above to add trigger words…";
    selBox.value = tagsWidget.value || "";

    const state = createTagState(tagsWidget, selBox);
    state.node = node;

    selBox.addEventListener("input", () => {
      tagsWidget.value = selBox.value;
      // Re-sync selectedSet from manual edits, then re-sync every rendered
      // chip (inline + aggregate) so a hand-deleted tag deactivates instead
      // of waiting for the next full panel rebuild.
      state.selectedSet.clear();
      parseTagList(selBox.value).forEach(t => state.selectedSet.add(t));
      syncAllChipStates(state);
    });

    // ── DOM container for the aggregate (post-execution) panel ──────────────
    const panel = document.createElement("div");
    panel.className = "cs-lora-tag-panel";

    const chipsArea = document.createElement("div");
    panel.appendChild(chipsArea);

    const actions = document.createElement("div");
    actions.className = "cs-tag-actions";

    const clearBtn = document.createElement("button");
    clearBtn.className = "cs-tag-btn";
    clearBtn.textContent = "✕ Clear";
    clearBtn.addEventListener("click", () => {
      state.selectedSet.clear();
      tagsWidget.value = "";
      selBox.value = "";
      syncAllChipStates(state);
    });

    const copyBtn = document.createElement("button");
    copyBtn.className = "cs-tag-btn";
    copyBtn.textContent = "⎘ Copy";
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(selBox.value).catch(() => {});
    });

    const refreshBtn = document.createElement("button");
    refreshBtn.className = "cs-tag-btn";
    refreshBtn.textContent = "↻ Refresh";
    refreshBtn.title = "Re-pull the tags applied by the last execution";
    refreshBtn.addEventListener("click", async () => {
      const data = await fetchExecutionTags(node.id);
      buildAggregatePanel(chipsArea, data, state);
    });

    actions.appendChild(clearBtn);
    actions.appendChild(copyBtn);
    actions.appendChild(refreshBtn);

    panel.appendChild(selBox);
    panel.appendChild(actions);

    // ── attach aggregate DOM panel to node ───────────────────────────────────
    node.addDOMWidget("cs_lora_tag_ui", "div", panel, {
      getValue() { return tagsWidget.value; },
      setValue(v) {
        const str = typeof v === "string" ? v : "";
        tagsWidget.value = str;
        selBox.value = str;
        state.selectedSet.clear();
        parseTagList(str).forEach(t => state.selectedSet.add(t));
        syncAllChipStates(state);
      },
      serialize: false,
    });

    // ── per-slot inline panels, positioned right under each lora_N combo ────
    // Deferred via setTimeout: when a workflow is loaded, ComfyUI applies the
    // saved widgets_values to node.widgets *positionally*, after nodeCreated
    // fires, with no special handling for widgets inserted in between. If we
    // insert these DOM widgets immediately (interspersed among the real
    // lora_N/strength/bypass widgets), every value after the first inserted
    // widget gets read from the wrong array slot and the whole node desyncs.
    // A macrotask delay runs after that synchronous configure pass finishes
    // (for both a freshly-dragged node, where there's nothing to configure,
    // and a loaded one), so by the time we insert, real values are already set.
    setTimeout(() => {
      node._csInlineWidgets = {};
      for (let i = 1; i <= MAX_LORAS; i++) {
        const container = document.createElement("div");
        container.className = "cs-inline-slot-panel";
        const inlineWidget = node.addDOMWidget(`cs_lora_inline_${i}`, "div", container, { serialize: false });
        moveWidgetAfter(node, inlineWidget, `lora_${i}`);
        node._csInlineWidgets[i] = inlineWidget;

        hookSlotCombo(node, i, state, container);
        updateSlotCollapse(node, i);
        // Populate immediately in case a workflow was reloaded with LoRAs
        // already selected — don't wait for the user to reselect.
        refreshSlotPanel(container, i, state);
      }
    }, 0);

    // ── poll for the aggregate panel after execution settles ────────────────
    node._csTagPoll = null;
    function schedulePoll() {
      clearTimeout(node._csTagPoll);
      node._csTagPoll = setTimeout(async () => {
        const data = await fetchExecutionTags(node.id);
        buildAggregatePanel(chipsArea, data, state);
      }, POLL_MS);
    }

    const origOnExecuted = node.onExecuted?.bind(node);
    node.onExecuted = function (output) {
      origOnExecuted?.(output);
      schedulePoll();
    };

    // Initial load (in case tags were cached from a previous session)
    schedulePoll();
  },
});
