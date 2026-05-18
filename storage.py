# ─────────────────────────────────────────────
#  FOUNDRY — STORAGE
#  Simple JSON file persistence
#  (drop-in replacement for chrome.storage)
# ─────────────────────────────────────────────

import json
import logging
import os
import threading

log = logging.getLogger(__name__)

STORAGE_FILE = "foundry_data.json"


class Storage:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = self._load()

    def get(self, key: str):
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value):
        with self._lock:
            self._data[key] = value
            self._save()

    def delete(self, key: str):
        with self._lock:
            self._data.pop(key, None)
            self._save()

    def _load(self) -> dict:
        if os.path.exists(STORAGE_FILE):
            try:
                with open(STORAGE_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"Could not load storage file: {e}")
        return {}

    def _save(self):
        try:
            with open(STORAGE_FILE, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            log.error(f"Could not save storage file: {e}")
