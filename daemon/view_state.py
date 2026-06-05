"""Live, in-memory view state for each surface.

View-control primitives are transient (the plan keeps them out of SQLite): they
describe what the left pane is currently showing — which files are open in which
split panes, which line ranges are highlighted, and whether a diff is up. The
daemon holds one ViewState per surface so a late-joining browser can be handed a
snapshot, and the read-only pull primitives can report it (later phase).

A surface id is opaque here; a later phase maps it to a review session.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Range:
    start: int
    end: int


@dataclass
class OpenFile:
    file: str
    range: Range | None = None


@dataclass
class Diff:
    a: str
    b: str


@dataclass
class ViewState:
    surface: str
    panes: int = 1
    open: dict[int, OpenFile] = field(default_factory=dict)
    highlights: dict[str, list[Range]] = field(default_factory=dict)
    diff: Diff | None = None


def _to_range(raw: dict[str, int] | None) -> Range | None:
    if raw is None:
        return None
    return Range(start=raw["start"], end=raw["end"])


class ViewStore:
    """The set of live surfaces, keyed by surface id. Single-process, in-memory."""

    def __init__(self) -> None:
        self._surfaces: dict[str, ViewState] = {}

    def get_or_create(self, surface: str) -> ViewState:
        state = self._surfaces.get(surface)
        if state is None:
            state = ViewState(surface=surface)
            self._surfaces[surface] = state
        return state

    def open_code(
        self, surface: str, file: str, line_range: dict[str, int] | None, pane: int
    ) -> None:
        self.get_or_create(surface).open[pane] = OpenFile(file=file, range=_to_range(line_range))

    def split_pane(self, surface: str, n: int) -> None:
        state = self.get_or_create(surface)
        state.panes = n
        # Drop open files for panes that no longer exist after the split shrank.
        state.open = {pane: f for pane, f in state.open.items() if pane < n}

    def highlight_range(self, surface: str, file: str, line_range: dict[str, int]) -> None:
        state = self.get_or_create(surface)
        added = _to_range(line_range)
        if added is not None:
            state.highlights.setdefault(file, []).append(added)

    def show_diff(self, surface: str, a: str, b: str) -> None:
        self.get_or_create(surface).diff = Diff(a=a, b=b)

    def snapshot(self, surface: str) -> dict[str, Any]:
        return asdict(self.get_or_create(surface))


# The daemon owns a single live store for the whole process.
store = ViewStore()
