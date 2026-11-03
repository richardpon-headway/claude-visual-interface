"""Label helpers: turn a user's prompt into a short display label.

There is no model call here anymore. CVI used to run background Claude Agent SDK
calls to generate a conversation title and a per-prompt outline-rail summary; those
seams were removed because an unrestricted helper agent could execute the prompt
instead of just labeling it. Labels are now derived directly from the prompt's own
text — its first N characters — and a manual rename (``user_title``) always wins.
"""

from __future__ import annotations

# Session titles are the first prompt's text, cut to at most this many characters.
# A manual rename (user_title) overrides it; see sessions.effective_title.
TITLE_MAX_CHARS = 100


def truncate_label(text: str, limit: int = TITLE_MAX_CHARS) -> str | None:
    """The first non-empty line of ``text``, stripped and cut to at most ``limit``
    characters. Returns ``None`` when there's nothing usable, so the caller can leave
    the existing default in place."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:limit].rstrip() or None
    return None
