"""Evidence-reel timeline model (R-1, R-2).

A single ordered track of trimmed clips that export to one concatenated MP4.
See docs/editing/adr/ADR-0001-evidence-reel-single-track.md.

Pure domain — no Qt / FFmpeg / Rust imports.  ``ClipEntry`` is a frozen
dataclass (matches the player-domain convention in ``core/player/models.py``);
``EditTimeline`` is a mutable container whose list IS the single source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

# Sentinel for "trim end = end of source". A frozen dataclass cannot compute a
# default from another field, so out_point_s defaults to this and __post_init__
# resolves it to source_duration_s.
_END = -1.0


@dataclass(frozen=True)
class ClipEntry:
    """One trimmed clip on the reel.

    All times are seconds within the *source* file.  ``in_point_s`` /
    ``out_point_s`` are clamped into ``[0, source_duration_s]`` with
    ``in <= out`` on construction, so an entry is always internally consistent.
    """

    source_path: Path
    source_duration_s: float
    in_point_s: float = 0.0
    out_point_s: float = _END  # resolves to source_duration_s in __post_init__

    def __post_init__(self) -> None:
        dur = max(0.0, float(self.source_duration_s))
        in_ = min(max(0.0, float(self.in_point_s)), dur)
        out = dur if self.out_point_s == _END else float(self.out_point_s)
        out = min(max(0.0, out), dur)
        if out < in_:
            out = in_
        # Frozen dataclass: normalise via object.__setattr__.
        object.__setattr__(self, "source_path", Path(self.source_path))
        object.__setattr__(self, "source_duration_s", dur)
        object.__setattr__(self, "in_point_s", in_)
        object.__setattr__(self, "out_point_s", out)

    @property
    def trimmed_duration_s(self) -> float:
        """Duration this clip contributes to the reel (out − in)."""
        return self.out_point_s - self.in_point_s

    def with_trim(self, in_point_s: float, out_point_s: float) -> "ClipEntry":
        """Return a copy with new (clamped) trim points."""
        return ClipEntry(
            self.source_path, self.source_duration_s, in_point_s, out_point_s
        )


@dataclass
class EditTimeline:
    """Ordered, mutable list of :class:`ClipEntry` — the evidence reel.

    The ``clips`` list is the single source of truth; the QML bridge mirrors it.
    """

    clips: List[ClipEntry] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.clips is None:
            self.clips = []

    # ── Mutations ─────────────────────────────────────────────────────
    def add(self, clip: ClipEntry) -> int:
        """Append *clip*; return its new index."""
        self.clips.append(clip)
        return len(self.clips) - 1

    def remove(self, index: int) -> ClipEntry:
        """Remove and return the clip at *index*. Raises IndexError if invalid."""
        return self.clips.pop(index)

    def move(self, src: int, dst: int) -> None:
        """Move the clip at *src* to position *dst* (clamped). Reorders the reel.

        Raises IndexError if *src* is out of range.
        """
        n = len(self.clips)
        if not (0 <= src < n):
            raise IndexError(f"src index {src} out of range (0..{n - 1})")
        clip = self.clips.pop(src)
        dst = max(0, min(int(dst), len(self.clips)))
        self.clips.insert(dst, clip)

    def set_trim(self, index: int, in_point_s: float, out_point_s: float) -> None:
        """Replace the clip at *index* with a re-trimmed copy."""
        self.clips[index] = self.clips[index].with_trim(in_point_s, out_point_s)

    def clear(self) -> None:
        self.clips.clear()

    # ── Queries ───────────────────────────────────────────────────────
    @property
    def total_duration_s(self) -> float:
        """Total reel duration = sum of every clip's trimmed duration."""
        return sum(c.trimmed_duration_s for c in self.clips)

    def __len__(self) -> int:
        return len(self.clips)

    def __iter__(self):
        return iter(self.clips)

    def __getitem__(self, index: int) -> ClipEntry:
        return self.clips[index]

    def validate(self) -> List[str]:
        """Return a list of human-readable problems (empty = valid).

        Used by the export path to refuse impossible reels (e.g. zero-length).
        """
        errors: List[str] = []
        if not self.clips:
            errors.append("La línea de tiempo está vacía.")
        for i, c in enumerate(self.clips):
            if c.trimmed_duration_s <= 0:
                errors.append(f"El clip #{i + 1} tiene duración cero tras el recorte.")
        return errors
