"""Live, in-memory conversation state for each surface.

A surface's state is its conversation transcript (``activity``) plus a transient
``thinking`` flag. The daemon holds one ViewState per surface so a late-joining
browser can be handed a snapshot. Transient by design (the plan keeps it out of
SQLite); a surface id is opaque here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ActivityEntry:
    # One segment of the conversation: the user's prompt, Claude's text, a tool
    # call, a run result, or an inline artifact (kind="artifact": `html` is the page,
    # `text` its title). `summary` is a user prompt's generated outline-rail label.
    kind: str  # "user" | "text" | "tool" | "result" | "artifact"
    text: str
    html: str | None = None
    summary: str | None = None


# Cap the per-surface activity buffer so a long conversation can't grow it without
# bound; oldest entries are dropped when it overflows.
MAX_ACTIVITY = 200


@dataclass
class ViewState:
    surface: str
    # The conversation transcript, buffered so a browser connecting mid-conversation
    # sees what's happened so far (rides the connect snapshot).
    activity: list[ActivityEntry] = field(default_factory=list)
    # Whether an agent turn is currently in flight (drives the thinking indicator);
    # snapshot-carried so a browser connecting mid-turn sees it.
    thinking: bool = False


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

    def set_thinking(self, surface: str, active: bool) -> None:
        self.get_or_create(surface).thinking = active

    def append_activity(
        self, surface: str, kind: str, text: str, html: str | None = None
    ) -> ActivityEntry:
        activity = self.get_or_create(surface).activity
        entry = ActivityEntry(kind=kind, text=text, html=html)
        activity.append(entry)
        if len(activity) > MAX_ACTIVITY:
            del activity[: len(activity) - MAX_ACTIVITY]
        return entry

    def snapshot(self, surface: str) -> dict[str, Any]:
        return asdict(self.get_or_create(surface))


# The daemon owns a single live store for the whole process.
store = ViewStore()
