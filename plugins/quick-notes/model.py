"""Note storage for Quick Notes: one Markdown file per note in a folder.

No bar imports, so this module reads and tests without a running smabar.
The first non-empty line of a file is the note's title; the file's mtime is
its "updated" time, so notes edited with any other editor sort correctly.
"""

import json
import os
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MAX_TEXT = 20_000
TITLE_CHARS = 80
PREVIEW_CHARS = 80

# Heading marks, list bullets, numbering, quotes and task boxes in front of a line.
MARKERS = re.compile(r"^(?:#{1,6}\s+|[-*+]\s+|>\s+|\d+[.)]\s+|\[[ xX]\]\s+)+")


class NoteError(ValueError):
    """An expected failure. `key` names the locale string the UI shows."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key


@dataclass
class Note:
    id: str
    text: str
    updated: float
    pinned: bool = False

    @property
    def title(self) -> str:
        return title_of(self.text)

    @property
    def preview(self) -> str:
        return preview_of(self.text)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def title_of(text: str) -> str:
    """The first non-empty line without its Markdown markers; "" for an empty note."""
    lines = _lines(text)
    return _clip(MARKERS.sub("", lines[0]), TITLE_CHARS) if lines else ""


def preview_of(text: str) -> str:
    """The lines after the title, joined into one short line."""
    return _clip(" ".join(MARKERS.sub("", line) for line in _lines(text)[1:]), PREVIEW_CHARS)


def clean(text: str) -> str:
    """Normalised note text or a NoteError the UI can show."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise NoteError("empty", "text must not be empty")
    if len(text) > MAX_TEXT:
        raise NoteError("long", f"text must be at most {MAX_TEXT} characters")
    return text


def atomic_write(path: Path, text: str) -> None:
    """Write beside the final name, then swap: a reader never sees half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class NoteStore:
    """Notes as <data_dir>/notes/<id>.md; the pinned id in <data_dir>/pinned.json.

    The index is rebuilt from the folder by rescan(), so files added or edited
    by another program appear on the next scan. Every *.md file counts as a
    note; its stem is the id.
    """

    def __init__(self, data_dir: Path, now: Callable[[], float] = time.time) -> None:
        self.root = data_dir / "notes"
        self._pin_file = data_dir / "pinned.json"
        self._now = now
        self._notes: dict[str, Note] = {}
        self._seen: dict[str, tuple[int, int]] = {}
        self.pinned_id: str | None = None

    def load(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            pinned = json.loads(self._pin_file.read_text(encoding="utf-8")).get("pinned")
        except (OSError, ValueError, AttributeError):
            pinned = None
        self.pinned_id = pinned if isinstance(pinned, str) else None
        self.rescan()

    def rescan(self) -> bool:
        """Sync the index with the folder by name, mtime and size; True when anything changed."""
        seen: dict[str, tuple[int, int]] = {}
        with os.scandir(self.root) as entries:
            for entry in entries:
                if entry.name.endswith(".md") and not entry.name.startswith(".") and entry.is_file():
                    stat = entry.stat()
                    seen[entry.name[:-3]] = (stat.st_mtime_ns, stat.st_size)
        if seen == self._seen:
            return False
        for note_id in set(self._notes) - set(seen):
            del self._notes[note_id]
        for note_id, stamp in seen.items():
            if self._seen.get(note_id) == stamp:
                continue
            try:
                raw = (self.root / f"{note_id}.md").read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # ponytail: a half-written or binary file waits for its next change
            self._notes[note_id] = Note(note_id, raw.replace("\r\n", "\n").strip(), stamp[0] / 1e9)
        self._seen = seen
        if self.pinned_id not in self._notes:
            self.pinned_id = None
        return True

    def _with_pin(self, note: Note) -> Note:
        return Note(note.id, note.text, note.updated, note.id == self.pinned_id)

    def notes(self, query: str = "") -> list[Note]:
        """Pinned first, then newest first; `query` filters the full text, case-insensitively."""
        needle = query.strip().lower()
        found = [self._with_pin(note) for note in self._notes.values() if needle in note.text.lower()]
        found.sort(key=lambda note: (not note.pinned, -note.updated, note.id))
        return found

    def get(self, note_id: str) -> Note:
        note = self._notes.get(note_id)
        if note is None:
            raise NoteError("missing", "note not found; list notes for current ids")
        return self._with_pin(note)

    def add(self, text: str) -> Note:
        return self._write(self._new_id(), clean(text))

    def update(self, note_id: str, text: str) -> Note:
        return self._write(self.get(note_id).id, clean(text))

    def delete(self, note_id: str) -> Note:
        """Remove the file; the returned note (with its pin state) is what restore() takes."""
        note = self.get(note_id)
        (self.root / f"{note.id}.md").unlink()
        del self._notes[note.id]
        self._seen.pop(note.id, None)
        if note.pinned:
            self._set_pin(None)
        return note

    def restore(self, note: Note) -> Note:
        if note.pinned:
            self._set_pin(note.id)
        return self._write(note.id, note.text)

    def pin(self, note_id: str | None) -> None:
        """Pin one note, replacing the previous pin; None unpins."""
        self._set_pin(self.get(note_id).id if note_id is not None else None)

    def _set_pin(self, note_id: str | None) -> None:
        self.pinned_id = note_id
        atomic_write(self._pin_file, json.dumps({"pinned": note_id}))

    def _new_id(self) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self._now()))
        while True:
            note_id = f"{stamp}-{secrets.token_hex(2)}"
            if note_id not in self._notes and not (self.root / f"{note_id}.md").exists():
                return note_id

    def _write(self, note_id: str, text: str) -> Note:
        path = self.root / f"{note_id}.md"
        atomic_write(path, text + "\n")
        now = self._now()
        os.utime(path, (now, now))  # the injected clock stamps "updated", so tests are deterministic
        stat = path.stat()
        self._seen[note_id] = (stat.st_mtime_ns, stat.st_size)
        self._notes[note_id] = Note(note_id, text, stat.st_mtime)
        return self._with_pin(self._notes[note_id])
