"""The clipboard history store: one JSON file, newest first, pinned entries protected.

No bar imports, so test_history.py exercises it against a temporary directory.
"""

import json
import os
import uuid
from pathlib import Path


class History:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[dict] = []  # newest first; each {id, text, at, pinned}

    def load(self) -> None:
        """Reads the file. Missing: FileNotFoundError; unreadable or malformed: OSError/ValueError."""
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        entries = raw.get("entries") if isinstance(raw, dict) else None
        if not isinstance(entries, list) or not all(_is_entry(item) for item in entries):
            raise ValueError("history.json has no valid entries list")
        self.entries = entries

    def save(self) -> None:
        """Write beside the final name, then swap: a reader never sees half a file."""
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"entries": self.entries}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, text: str, now: int, *, max_chars: int, max_entries: int) -> bool:
        """Records a copied text at the top; a repeat moves up instead of duplicating.

        Returns False when nothing changed: whitespace-only or oversized text,
        or the text that is already on top.
        """
        if not text.strip() or len(text) > max_chars:
            return False
        if self.entries and self.entries[0]["text"] == text:
            return False
        entry = next((item for item in self.entries if item["text"] == text), None)
        if entry is None:
            entry = {"id": uuid.uuid4().hex, "text": text, "at": now, "pinned": False}
        else:
            self.entries.remove(entry)
            entry["at"] = now
        self.entries.insert(0, entry)
        self.trim(max_entries)
        return True

    def trim(self, max_entries: int) -> bool:
        """Keeps at most max_entries unpinned entries, dropping the oldest ones.

        Pinned entries do not count and never fall off.
        """
        excess = self.unpinned() - max_entries
        if excess <= 0:
            return False
        for entry in self.entries[::-1]:
            if excess == 0:
                break
            if not entry["pinned"]:
                self.entries.remove(entry)
                excess -= 1
        return True

    def get(self, entry_id: str) -> dict | None:
        return next((item for item in self.entries if item["id"] == entry_id), None)

    def pin(self, entry_id: str, pinned: bool) -> bool:
        entry = self.get(entry_id)
        if entry is None or entry["pinned"] == pinned:
            return False
        entry["pinned"] = pinned
        return True

    def delete(self, entry_id: str) -> bool:
        entry = self.get(entry_id)
        if entry is None:
            return False
        self.entries.remove(entry)
        return True

    def clear(self) -> int:
        """Removes every unpinned entry and returns how many went."""
        kept = [item for item in self.entries if item["pinned"]]
        removed = len(self.entries) - len(kept)
        self.entries = kept
        return removed

    def unpinned(self) -> int:
        return sum(1 for item in self.entries if not item["pinned"])

    def ordered(self) -> list[dict]:
        """Pinned entries first, then the rest, each group newest first."""
        return [item for item in self.entries if item["pinned"]] + [
            item for item in self.entries if not item["pinned"]
        ]

    def search(self, query: str, limit: int) -> list[dict]:
        """Case-insensitive substring match in display order; an empty query lists everything."""
        needle = query.casefold()
        return [item for item in self.ordered() if needle in item["text"].casefold()][:limit]


def _is_entry(item: object) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("text"), str)
        and isinstance(item.get("at"), (int, float))
        and isinstance(item.get("pinned"), bool)
    )
