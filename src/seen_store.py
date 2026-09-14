"""Tracks which article links have already been emailed, so hourly runs only
send what's genuinely new since the last digest instead of repeating items.
"""

import json
import os
import time
from typing import Dict, List

from src.config import SEEN_STORE_PATH, SEEN_TTL_DAYS


class SeenStore:
    def __init__(self, path: str = SEEN_STORE_PATH):
        self.path = path
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._data: Dict[str, float] = self._load()

    def _load(self) -> Dict[str, float]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f)

    def has(self, url: str) -> bool:
        return url in self._data

    def mark_seen(self, urls: List[str]) -> None:
        now = time.time()
        for url in urls:
            if url:
                self._data[url] = now
        self._prune()
        self._save()

    def _prune(self) -> None:
        cutoff = time.time() - (SEEN_TTL_DAYS * 86400)
        self._data = {u: t for u, t in self._data.items() if t >= cutoff}