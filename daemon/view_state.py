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
class Artifact:
    # A self-contained HTML page the session rendered onto the left pane (e.g. a
    # design, diagram, report, or text-driven review). Transient, like the rest of
    # the view state; rendered in a sandboxed iframe by the browser.
    html: str
    title: str | None = None


@dataclass
class Selection:
    file: str
    range: Range


@dataclass
class ActivityEntry:
    # One segment of the conversation: the user's prompt, Claude's text, a tool
    # call, a run result, or an inline artifact (kind="artifact": `html` carries a
    # model-authored HTML page, `text` its title).
    kind: str  # "user" | "text" | "tool" | "result" | "artifact" | "file"
    text: str
    html: str | None = None
    # For a user prompt: a generated one-line summary used as its outline-rail label
    # (set asynchronously after the prompt is recorded; None until/unless generated).
    summary: str | None = None
    # For a file segment (kind="file", `text` is the path): the unified diff vs the
    # review base. The full file is fetched on demand via GET /sessions/{id}/file.
    diff: str | None = None


# Cap the per-surface activity buffer so a long review can't grow it without
# bound; oldest entries are dropped when it overflows.
MAX_ACTIVITY = 200


@dataclass
class ViewState:
    surface: str
    panes: int = 1
    open: dict[int, OpenFile] = field(default_factory=dict)
    highlights: dict[str, list[Range]] = field(default_factory=dict)
    diff: Diff | None = None
    # An HTML page rendered onto the left pane instead of the code views. When set
    # the browser shows the artifact; opening code (open_code / split_pane) clears
    # it to return the pane to the code view.
    artifact: Artifact | None = None
    # What the user has selected on the left pane (emitted by the browser, read
    # back by the pull primitives). The pane emits selections only — no input.
    selection: Selection | None = None
    # Recent review narration, buffered so a browser connecting mid-review sees
    # what's happened so far (rides the connect snapshot).
    activity: list[ActivityEntry] = field(default_factory=list)
    # Whether an agent turn is currently in flight on this surface. Transient and
    # snapshot-carried (no DB home) so a browser connecting mid-turn sees the
    # thinking indicator.
    thinking: bool = False


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
        state = self.get_or_create(surface)
        state.open[pane] = OpenFile(file=file, range=_to_range(line_range))
        state.artifact = None  # showing code returns the left pane to the code view

    def split_pane(self, surface: str, n: int) -> None:
        state = self.get_or_create(surface)
        state.panes = n
        # Drop open files for panes that no longer exist after the split shrank.
        state.open = {pane: f for pane, f in state.open.items() if pane < n}
        state.artifact = None  # establishing a code layout clears any artifact

    def highlight_range(self, surface: str, file: str, line_range: dict[str, int]) -> None:
        state = self.get_or_create(surface)
        added = _to_range(line_range)
        if added is not None:
            state.highlights.setdefault(file, []).append(added)

    def show_diff(self, surface: str, a: str, b: str) -> None:
        self.get_or_create(surface).diff = Diff(a=a, b=b)

    def render_html(self, surface: str, html: str, title: str | None) -> None:
        self.get_or_create(surface).artifact = Artifact(html=html, title=title)

    def set_selection(self, surface: str, file: str, line_range: dict[str, int]) -> None:
        selected = _to_range(line_range)
        self.get_or_create(surface).selection = (
            Selection(file=file, range=selected) if selected is not None else None
        )

    def set_thinking(self, surface: str, active: bool) -> None:
        self.get_or_create(surface).thinking = active

    def append_activity(
        self, surface: str, kind: str, text: str, html: str | None = None, diff: str | None = None
    ) -> ActivityEntry:
        activity = self.get_or_create(surface).activity
        entry = ActivityEntry(kind=kind, text=text, html=html, diff=diff)
        activity.append(entry)
        if len(activity) > MAX_ACTIVITY:
            del activity[: len(activity) - MAX_ACTIVITY]
        return entry

    def snapshot(self, surface: str) -> dict[str, Any]:
        return asdict(self.get_or_create(surface))


# The daemon owns a single live store for the whole process.
store = ViewStore()
