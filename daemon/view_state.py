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
    # call, a run result, an inline artifact (kind="artifact": `html` is the page,
    # `text` its title), or an AskUserQuestion picker (kind="ask"). `summary` is a user
    # prompt's generated outline-rail label.
    kind: str  # "user" | "text" | "tool" | "result" | "artifact" | "ask"
    text: str
    html: str | None = None
    summary: str | None = None
    # True when this segment belongs to an agent-initiated (background) turn — one the
    # model ran on its own after a background task finished, not a reply to a user
    # prompt. The browser marks these so they don't read as answers to something typed.
    background: bool = False
    # For an "ask" entry: the tool-use id (a stable handle the browser echoes back when
    # answering) and the structured AskUserQuestion `questions` payload to render as a
    # picker. `answer` is the user's chosen value, set once they pick.
    ask_id: str | None = None
    questions: list | None = None
    answer: str | None = None
    # The persisted `message` row id, so a prompt's summary can be written back to
    # the right row. Server-only — stripped from the snapshot (see ViewStore.snapshot).
    message_id: int | None = None


@dataclass
class ViewState:
    surface: str
    # The conversation transcript, buffered so a browser connecting mid-conversation
    # sees what's happened so far (rides the connect snapshot).
    activity: list[ActivityEntry] = field(default_factory=list)
    # Whether an agent turn is currently in flight (drives the thinking indicator);
    # snapshot-carried so a browser connecting mid-turn sees it.
    thinking: bool = False
    # Background tasks currently running for this surface (a launched `run_in_background`
    # shell that hasn't reported completion yet). Each entry is {"task_id", "description"}.
    # Drives the dedicated, non-blocking background-task indicator; snapshot-carried so a
    # browser connecting while a task runs still sees it.
    background_tasks: list[dict[str, str]] = field(default_factory=list)
    # Running session token totals across every LLM call (turn + title + summary).
    # Seeded from the persisted token_usage rows on hydration (so they survive a daemon
    # restart) and accumulated live; snapshot-carried so a refresh keeps the count.
    session_output_tokens: int = 0
    session_input_tokens: int = 0


class ViewStore:
    """The set of live surfaces, keyed by surface id. Single-process, in-memory."""

    def __init__(self) -> None:
        self._surfaces: dict[str, ViewState] = {}
        # Surfaces whose persisted history has been loaded this process run, so a
        # reconnect doesn't re-query the DB or clobber live entries.
        self._hydrated: set[str] = set()

    def get_or_create(self, surface: str) -> ViewState:
        state = self._surfaces.get(surface)
        if state is None:
            state = ViewState(surface=surface)
            self._surfaces[surface] = state
        return state

    def set_thinking(self, surface: str, active: bool) -> None:
        self.get_or_create(surface).thinking = active

    def set_background_tasks(self, surface: str, tasks: list[dict[str, str]]) -> None:
        """Replace the surface's running-background-task list (the source of truth is the
        AgentSession's live set; this copy rides the connect snapshot)."""
        self.get_or_create(surface).background_tasks = tasks

    def add_tokens(self, surface: str, output_tokens: int, input_tokens: int) -> tuple[int, int]:
        """Add one call's tokens to the running session totals; return the new totals."""
        state = self.get_or_create(surface)
        state.session_output_tokens += output_tokens
        state.session_input_tokens += input_tokens
        return state.session_output_tokens, state.session_input_tokens

    def seed_tokens(self, surface: str, output_tokens: int, input_tokens: int) -> None:
        """Set the session totals to a known baseline (the persisted sum), so a restart
        rebuilds the count before live accumulation resumes."""
        state = self.get_or_create(surface)
        state.session_output_tokens = output_tokens
        state.session_input_tokens = input_tokens

    def set_answer(self, surface: str, ask_id: str, answer: str) -> bool:
        """Record the chosen value on the matching `ask` entry so it rides the connect
        snapshot (the picker re-renders answered after a reload). False if not found."""
        for entry in self.get_or_create(surface).activity:
            if entry.ask_id == ask_id:
                entry.answer = answer
                return True
        return False

    def append_activity(
        self,
        surface: str,
        kind: str,
        text: str,
        html: str | None = None,
        ask_id: str | None = None,
        questions: list | None = None,
        background: bool = False,
    ) -> ActivityEntry:
        activity = self.get_or_create(surface).activity
        entry = ActivityEntry(
            kind=kind,
            text=text,
            html=html,
            ask_id=ask_id,
            questions=questions,
            background=background,
        )
        activity.append(entry)
        return entry

    def is_hydrated(self, surface: str) -> bool:
        return surface in self._hydrated

    def mark_hydrated(self, surface: str) -> None:
        self._hydrated.add(surface)

    def load_activity(self, surface: str, entries: list[ActivityEntry]) -> None:
        """Replace a surface's transcript with its persisted history. Used only by
        hydration on first connect, before any live entries are recorded."""
        self.get_or_create(surface).activity = entries

    def snapshot(self, surface: str) -> dict[str, Any]:
        snap = asdict(self.get_or_create(surface))
        # message_id is a server-only handle for persisting a prompt's summary; it
        # never goes to the browser.
        for entry in snap["activity"]:
            entry.pop("message_id", None)
        return snap


# The daemon owns a single live store for the whole process.
store = ViewStore()
