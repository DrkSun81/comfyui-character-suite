/**
 * Character Suite — Character Manager Web Extension
 * Adds a sidebar panel to ComfyUI for managing character prompt entries.
 * Communicates with the backend via /character_suite/* API routes.
 */

import { app } from "../../scripts/app.js";

const API_BASE = "/character_suite";

// ── Helpers ──────────────────────────────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store", // this is live CRUD data; a cached GET here re-shows pre-edit content after a save
    ...options,
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  return res.json();
}

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  Object.assign(e, attrs);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on") && typeof v === "function") {
      e.addEventListener(k.slice(2).toLowerCase(), v);
      delete e[k];
    }
  }
  children.flat().forEach(c =>
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c)
  );
  return e;
}

// ── Styles ────────────────────────────────────────────────────────────────────

const STYLE = `
  #cs-panel {
    padding: 10px;
    font-family: var(--font-main, sans-serif);
    font-size: 13px;
    color: var(--fg-color, #eee);
    display: flex;
    flex-direction: column;
    gap: 10px;
    height: 100%;
    box-sizing: border-box;
  }
  #cs-panel h2 {
    margin: 0 0 4px;
    font-size: 15px;
    color: var(--p-primary-color, #c084fc);
  }
  #cs-search {
    width: 100%;
    padding: 5px 8px;
    border-radius: 6px;
    border: 1px solid var(--border-color, #444);
    background: var(--comfy-input-bg, #1e1e2e);
    color: inherit;
    box-sizing: border-box;
  }
  #cs-list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .cs-card {
    background: var(--comfy-menu-bg, #252535);
    border: 1px solid var(--border-color, #444);
    border-radius: 8px;
    padding: 8px 10px;
    cursor: pointer;
    transition: border-color 0.15s;
  }
  .cs-card:hover { border-color: var(--p-primary-color, #c084fc); }
  .cs-card.active { border-color: #a78bfa; background: #2d2b4e; }
  .cs-card-name { font-weight: bold; margin-bottom: 3px; }
  .cs-card-preview { font-size: 11px; color: #aaa; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .cs-card-tags { font-size: 10px; color: #7c6fcd; margin-top: 3px; }
  #cs-editor {
    border-top: 1px solid var(--border-color, #444);
    padding-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  #cs-editor label { font-size: 11px; color: #aaa; margin-bottom: 2px; display: block; }
  #cs-editor input, #cs-editor textarea {
    width: 100%;
    padding: 5px 8px;
    border-radius: 6px;
    border: 1px solid var(--border-color, #444);
    background: var(--comfy-input-bg, #1e1e2e);
    color: inherit;
    resize: vertical;
    font-size: 12px;
    box-sizing: border-box;
  }
  #cs-editor textarea { min-height: 60px; }
  .cs-btn-row { display: flex; gap: 6px; flex-wrap: wrap; }
  .cs-btn {
    padding: 5px 12px;
    border-radius: 6px;
    border: none;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
  }
  .cs-btn-save   { background: #6d28d9; color: #fff; }
  .cs-btn-save:hover { background: #7c3aed; }
  .cs-btn-new    { background: #065f46; color: #fff; }
  .cs-btn-new:hover { background: #047857; }
  .cs-btn-delete { background: #7f1d1d; color: #fff; }
  .cs-btn-delete:hover { background: #991b1b; }
  .cs-btn-copy   { background: #1e3a5f; color: #fff; }
  .cs-btn-copy:hover { background: #1e40af; }
  #cs-status { font-size: 11px; color: #6ee7b7; min-height: 16px; }
`;

// ── State ─────────────────────────────────────────────────────────────────────

let characters = [];
let activeIdx = null;

// ── Build UI ──────────────────────────────────────────────────────────────────

function buildPanel() {
  const style = document.createElement("style");
  style.textContent = STYLE;
  document.head.appendChild(style);

  // Fields
  const searchInput = el("input", { id: "cs-search", placeholder: "🔍 Search characters…", type: "text" });
  const list = el("div", { id: "cs-list" });

  const nameInput    = el("input",    { placeholder: "Character name (e.g. Avery)" });
  const posTextarea  = el("textarea", { placeholder: "Positive prompt tags…", rows: 4 });
  const negTextarea  = el("textarea", { placeholder: "Negative prompt tags…", rows: 3 });
  const tagsInput    = el("input",    { placeholder: "Tags (comma separated, e.g. oc, female)" });
  const statusEl     = el("div",      { id: "cs-status" });

  function setStatus(msg, color = "#6ee7b7") {
    statusEl.textContent = msg;
    statusEl.style.color = color;
    setTimeout(() => { statusEl.textContent = ""; }, 3000);
  }

  function renderList(filter = "") {
    list.innerHTML = "";
    const filtered = characters.filter(c =>
      c.name.toLowerCase().includes(filter.toLowerCase()) ||
      (c.tags || []).join(" ").toLowerCase().includes(filter.toLowerCase())
    );
    if (!filtered.length) {
      list.appendChild(el("div", { style: "color:#666;font-size:12px;padding:8px" }, "No characters found."));
      return;
    }
    filtered.forEach((char, i) => {
      const realIdx = characters.indexOf(char);
      const card = el("div", { className: "cs-card" + (realIdx === activeIdx ? " active" : "") });
      card.appendChild(el("div", { className: "cs-card-name" }, `🎭 ${char.name}`));
      card.appendChild(el("div", { className: "cs-card-preview" }, char.positive?.slice(0, 80) || "—"));
      if (char.tags?.length) {
        card.appendChild(el("div", { className: "cs-card-tags" }, char.tags.join(" · ")));
      }
      card.addEventListener("click", () => selectCharacter(realIdx));
      list.appendChild(card);
    });
  }

  function selectCharacter(idx) {
    activeIdx = idx;
    const c = characters[idx];
    nameInput.value   = c.name || "";
    posTextarea.value = c.positive || "";
    negTextarea.value = c.negative || "";
    tagsInput.value   = (c.tags || []).join(", ");
    renderList(searchInput.value);
  }

  function clearEditor() {
    activeIdx = null;
    nameInput.value = posTextarea.value = negTextarea.value = tagsInput.value = "";
    renderList(searchInput.value);
  }

  // Buttons
  const btnNew = el("button", { className: "cs-btn cs-btn-new" }, "＋ New");
  btnNew.addEventListener("click", clearEditor);

  const btnSave = el("button", { className: "cs-btn cs-btn-save" }, "💾 Save");
  btnSave.addEventListener("click", async () => {
    const name = nameInput.value.trim();
    if (!name) { setStatus("⚠️ Name required", "#f87171"); return; }
    const entry = {
      name,
      positive: posTextarea.value.trim(),
      negative: negTextarea.value.trim(),
      tags: tagsInput.value.split(",").map(t => t.trim()).filter(Boolean),
    };
    try {
      await apiFetch("/character/save", { method: "POST", body: JSON.stringify(entry) });
      await loadCharacters();
      // Re-select by name
      const newIdx = characters.findIndex(c => c.name === name);
      if (newIdx >= 0) selectCharacter(newIdx);
      setStatus(`✓ Saved "${name}"`);
    } catch (e) { setStatus(`✗ ${e.message}`, "#f87171"); }
  });

  const btnDelete = el("button", { className: "cs-btn cs-btn-delete" }, "🗑 Delete");
  btnDelete.addEventListener("click", async () => {
    if (activeIdx === null) { setStatus("Select a character first", "#f87171"); return; }
    const name = characters[activeIdx].name;
    if (!confirm(`Delete "${name}"?`)) return;
    try {
      await apiFetch("/character/delete", { method: "POST", body: JSON.stringify({ name }) });
      await loadCharacters();
      clearEditor();
      setStatus(`✓ Deleted "${name}"`);
    } catch (e) { setStatus(`✗ ${e.message}`, "#f87171"); }
  });

  const btnCopyPos = el("button", { className: "cs-btn cs-btn-copy" }, "📋 Copy Positive");
  btnCopyPos.addEventListener("click", () => {
    navigator.clipboard.writeText(posTextarea.value);
    setStatus("Copied positive prompt!");
  });

  searchInput.addEventListener("input", () => renderList(searchInput.value));

  // Editor section
  const editor = el("div", { id: "cs-editor" },
    el("label", {}, "Character Name"),
    nameInput,
    el("label", {}, "Positive Prompt"),
    posTextarea,
    el("label", {}, "Negative Prompt"),
    negTextarea,
    el("label", {}, "Tags"),
    tagsInput,
    el("div", { className: "cs-btn-row" }, btnSave, btnNew, btnDelete, btnCopyPos),
    statusEl,
  );

  const panel = el("div", { id: "cs-panel" },
    el("h2", {}, "🎭 Character Manager"),
    searchInput,
    list,
    editor,
  );

  return panel;
}

// ── Load from backend ─────────────────────────────────────────────────────────

async function loadCharacters() {
  try {
    const data = await apiFetch("/characters");
    characters = data.characters || [];
  } catch (e) {
    console.warn("[CharacterSuite] Could not load characters:", e);
    characters = [];
  }
}

// ── Register extension ────────────────────────────────────────────────────────

app.registerExtension({
  name: "CharacterSuite.CharacterManager",

  async setup() {
    await loadCharacters();
    const panel = buildPanel();

    if (app.extensionManager?.registerSidebarTab) {
      // ComfyUI 1.x+ extensionManager sidebar API
      app.extensionManager.registerSidebarTab({
        id: "character-suite",
        icon: "pi pi-user",
        title: "Characters",
        tooltip: "Character Suite — Manage character prompt entries",
        type: "custom",
        render: (container) => {
          container.appendChild(panel);
        },
      });
    } else if (app.ui?.sidebar?.addTab) {
      // Legacy sidebar API (older ComfyUI builds)
      app.ui.sidebar.addTab({
        id: "character-suite",
        icon: "🎭",
        title: "Characters",
        tooltip: "Character Suite — Manage character prompt entries",
        type: "custom",
        render: (container) => {
          container.appendChild(panel);
        },
      });
    } else {
      // Fallback: floating toggle button
      panel.style.cssText = `
        position: fixed; top: 60px; right: 10px; width: 320px; max-height: 85vh;
        background: #1a1a2e; border: 1px solid #6d28d9; border-radius: 10px;
        overflow-y: auto; z-index: 9999; box-shadow: 0 4px 24px rgba(0,0,0,0.6);
        display: none;
      `;
      document.body.appendChild(panel);

      const toggle = document.createElement("button");
      toggle.textContent = "🎭 Characters";
      toggle.style.cssText = `
        position: fixed; top: 14px; right: 10px; z-index: 10000;
        padding: 5px 12px; background: #6d28d9; color: #fff;
        border: none; border-radius: 6px; cursor: pointer; font-size: 13px;
      `;
      toggle.addEventListener("click", () => {
        panel.style.display = panel.style.display === "none" ? "block" : "none";
      });
      document.body.appendChild(toggle);
    }
  },
});
