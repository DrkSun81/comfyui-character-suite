"""
Standalone sanity check for nodes/civitai_client.py.

Verifies hashing + the CivitAI fetch path against a real local .safetensors
file WITHOUT booting ComfyUI (no `comfy`/`folder_paths` imports involved —
civitai_client.py is deliberately free of those).

Usage:
    python tests/test_civitai_fetch.py [path/to/file.safetensors] [known_sha256]

With no arguments, it defaults to the slime-girl LoRA already in this repo's
data/loras_tags.json cache, whose known-good hash is read from the matching
.hash sidecar file CivitAI Helper / ComfyUI-Lora-Manager style tools write
next to the LoRA (F:/models/loras/illustrious/...safetensors.hash).
"""

import importlib.util
import json
import os
import sys
import tempfile

# Load civitai_client.py by file path rather than `from nodes import ...` —
# ComfyUI itself ships a top-level nodes.py that would shadow our nodes/
# package on sys.path, so a normal package import can silently resolve to
# the wrong module.
_CLIENT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes", "civitai_client.py")
_spec = importlib.util.spec_from_file_location("civitai_client", _CLIENT_PATH)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

DEFAULT_LORA = r"F:\models\loras\illustrious\dasiwa-ill-slimegirl-style-v2-1833-39.safetensors"
DEFAULT_HASH_SIDECAR = DEFAULT_LORA + ".hash"


def _known_hash_from_sidecar(sidecar_path: str) -> str | None:
    if not os.path.exists(sidecar_path):
        return None
    with open(sidecar_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("hashes", {}).get("SHA256", "").lower() or None


def test_hash(lora_path: str, known_hash: str | None) -> str:
    assert os.path.exists(lora_path), f"test file not found: {lora_path}"
    computed = cc.sha256_file(lora_path)
    print(f"[hash] {lora_path}")
    print(f"[hash] computed:  {computed}")
    if known_hash:
        print(f"[hash] known-good: {known_hash}")
        assert computed == known_hash.lower(), "sha256 mismatch — hashing logic is broken"
        print("[hash] OK: matches known-good hash")
    else:
        print("[hash] (no known-good hash available to compare against — skipping assert)")
    return computed


def test_fetch(sha: str):
    print(f"\n[fetch] querying CivitAI for {sha[:12]}... (backend="
          f"{'requests' if cc._HAS_REQUESTS else 'urllib'})")
    success, tags = cc.fetch_civitai_tags(sha)
    print(f"[fetch] success={success} tags={tags}")
    assert success, "fetch failed — see CivitAI error logs above"
    return tags


def test_cache_roundtrip(lora_name: str, tags: list[str]):
    print("\n[cache] exercising load/apply/save/load roundtrip in a temp dir")
    with tempfile.TemporaryDirectory() as tmp:
        orig_data_dir, orig_tags_file = cc.DATA_DIR, cc.TAGS_FILE
        cc.DATA_DIR = tmp
        cc.TAGS_FILE = os.path.join(tmp, "loras_tags.json")
        try:
            db = cc.load_tags_db()
            assert db == {}

            entry = cc.apply_fetch_result(db, lora_name, True, tags)
            assert entry["status"] == ("ok" if tags else "no_triggers")
            cc.save_tags_db(db)

            reloaded = cc.load_tags_db()
            assert reloaded[lora_name]["tags"] == tags
            assert cc.entry_is_fresh(reloaded[lora_name])
            print("[cache] OK: successful fetch persists and reads back as fresh")

            # A failed re-fetch must NOT clobber the previously cached tags.
            failed_entry = cc.apply_fetch_result(reloaded, lora_name, False, [])
            assert failed_entry["status"] == "failed"
            assert failed_entry["tags"] == tags, "failed fetch must preserve prior tags"
            # entry_is_fresh() means "skip re-fetching" — a *freshly* failed
            # entry is still within its retry cooldown, so it should read as
            # fresh (don't hammer CivitAI again immediately) while its status
            # stays "failed" so the UI can still show a failure indicator.
            assert cc.entry_is_fresh(failed_entry), \
                "freshly-failed entry should still be within retry cooldown"
            old_attempt_entry = {**failed_entry, "last_attempt": 0}  # far in the past
            assert not cc.entry_is_fresh(old_attempt_entry), \
                "a failed entry past the cooldown window should allow a retry"
            print("[cache] OK: failed fetch preserves prior tags; cooldown gates retries correctly")

            # Legacy flat-list format migrates cleanly.
            with open(cc.TAGS_FILE, "w", encoding="utf-8") as f:
                json.dump({lora_name: tags}, f)
            migrated = cc.load_tags_db()
            assert migrated[lora_name]["tags"] == tags
            assert migrated[lora_name]["status"] == ("ok" if tags else "no_triggers")
            print("[cache] OK: legacy flat-list cache entries migrate correctly")
        finally:
            cc.DATA_DIR, cc.TAGS_FILE = orig_data_dir, orig_tags_file


def main():
    lora_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LORA
    known_hash = sys.argv[2] if len(sys.argv) > 2 else _known_hash_from_sidecar(DEFAULT_HASH_SIDECAR)

    sha = test_hash(lora_path, known_hash)
    tags = test_fetch(sha)
    test_cache_roundtrip(os.path.basename(lora_path), tags)

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
