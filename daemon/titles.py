"""Chat-title generation seam.

Turns a user's message into a short conversation title via a tool-free, one-shot
Claude Agent SDK call. This is *pure generation* — text in, a cleaned title (or
None) out. The orchestration that decides when to title, persists the result, and
broadcasts it lives in ``agent_session`` (where the per-surface state is), keeping
the dependency one-directional. Swap ``generator`` for a fake in tests.
"""

from __future__ import annotations

import logging
from typing import Protocol

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, TextBlock

log = logging.getLogger(__name__)

_TITLE_SYSTEM_PROMPT = (
    "You write a concise title for a conversation, given the user's first message. "
    "Reply with ONLY the title: 3 to 6 words, no surrounding quotes, no trailing "
    "punctuation, no preamble or explanation."
)

# The opening of a message carries its topic; cap the input so a huge first-message
# paste (a stack trace, a whole file) doesn't blow up the title call's token cost.
MAX_TITLE_INPUT_CHARS = 2000


def _clean_title(raw: str) -> str | None:
    """Normalize the model's reply into a usable title, or None if there's nothing
    usable. Takes the first non-empty line, strips whitespace and surrounding quotes,
    and caps the length on a word boundary."""
    for line in raw.splitlines():
        line = line.strip().strip("\"'").strip()
        if not line:
            continue
        if len(line) > 60:
            line = line[:60].rsplit(" ", 1)[0].rstrip()
        return line or None
    return None


class TitleGenerator(Protocol):
    async def generate(self, message: str) -> str | None: ...


class AgentTitleGenerator:
    async def generate(self, message: str) -> str | None:
        """Run a one-shot, tool-free Claude call to title ``message``. Best-effort:
        any failure logs a warning and returns None (the caller leaves the chat
        untitled and retries on the next message)."""
        try:
            options = ClaudeAgentOptions(system_prompt=_TITLE_SYSTEM_PROMPT)
            parts: list[str] = []
            async with ClaudeSDKClient(options=options) as client:
                await client.query(message[:MAX_TITLE_INPUT_CHARS])
                async for response in client.receive_response():
                    if isinstance(response, AssistantMessage):
                        parts.extend(
                            block.text for block in response.content if isinstance(block, TextBlock)
                        )
            return _clean_title("".join(parts))
        except Exception:
            log.warning("title generation failed", exc_info=True)
            return None


# The active generators. `generator` titles a whole chat session (from its first
# message); `summarizer` labels each prompt for the outline rail. Same shape, but
# separate seams so tests can stub them independently. Tests inject fakes via
# daemon.titles.generator / daemon.titles.summarizer.
generator: TitleGenerator = AgentTitleGenerator()
summarizer: TitleGenerator = AgentTitleGenerator()
