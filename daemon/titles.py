"""Chat-title generation seam.

Turns a user's message into a short conversation title via a tool-free, one-shot
Claude Agent SDK call. This is *pure generation* — text in, a cleaned title (or
None) out. The orchestration that decides when to title, persists the result, and
broadcasts it lives in ``agent_session`` (where the per-surface state is), keeping
the dependency one-directional. Swap ``generator`` for a fake in tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from daemon import token_usage

log = logging.getLogger(__name__)

_TITLE_SYSTEM_PROMPT = (
    "You write a concise title for a conversation, given the user's recent messages. "
    "Reply with the title text only — 3 to 6 words, no surrounding quotes, no trailing "
    "punctuation, no preamble or explanation. Do not prefix it with 'Title:' or any "
    "other label."
)

# The opening of a message carries its topic; cap the input so a huge first-message
# paste (a stack trace, a whole file) doesn't blow up the title call's token cost.
MAX_TITLE_INPUT_CHARS = 2000

# How often the session title is regenerated (every Nth text-bearing user prompt) and
# how many recent user messages feed that regeneration. Distinct concepts that happen
# to share a value. The title call is a separate conversation (no session prompt cache),
# so the window is what bounds its cost — see agent_session._title_input.
TITLE_REFRESH_EVERY = 5
TITLE_WINDOW_MESSAGES = 5


def _clean_title(raw: str) -> str | None:
    """Normalize the model's reply into a usable title, or None if there's nothing
    usable. Takes the first non-empty line, strips whitespace and surrounding quotes,
    drops a stray "Title:" label the model sometimes emits, and caps the length on a
    word boundary."""
    for line in raw.splitlines():
        line = line.strip().strip("\"'").strip()
        # Drop a "Title:" preamble (the model occasionally ignores the prompt). Only the
        # label-with-colon form — a real title that merely starts with the word "Title"
        # (no colon, e.g. "Title bar refactor") is left intact.
        if line[:6].lower() == "title:":
            line = line[6:].strip().strip("\"'").strip()
        if not line:
            continue
        if len(line) > 60:
            line = line[:60].rsplit(" ", 1)[0].rstrip()
        return line or None
    return None


@dataclass
class TitleResult:
    """A title call's outcome: the cleaned title (or None) plus the call's token
    usage, so the caller can record it toward the session total."""

    title: str | None
    output_tokens: int = 0
    input_tokens: int = 0


class TitleGenerator(Protocol):
    async def generate(self, message: str) -> TitleResult: ...


class AgentTitleGenerator:
    async def generate(self, message: str) -> TitleResult:
        """Run a one-shot, tool-free Claude call to title ``message``. Best-effort:
        any failure logs a warning and returns an empty TitleResult (the caller leaves
        the chat untitled and retries on the next message). Reports the call's token
        usage so it counts toward the session total."""
        try:
            options = ClaudeAgentOptions(system_prompt=_TITLE_SYSTEM_PROMPT)
            parts: list[str] = []
            output_tokens = 0
            input_tokens = 0
            async with ClaudeSDKClient(options=options) as client:
                await client.query(message[:MAX_TITLE_INPUT_CHARS])
                async for response in client.receive_response():
                    if isinstance(response, AssistantMessage):
                        parts.extend(
                            block.text for block in response.content if isinstance(block, TextBlock)
                        )
                    elif isinstance(response, ResultMessage):
                        out, inp = token_usage.usage_tokens(response.usage)
                        output_tokens += out
                        input_tokens += inp
            return TitleResult(_clean_title("".join(parts)), output_tokens, input_tokens)
        except Exception:
            log.warning("title generation failed", exc_info=True)
            return TitleResult(None)


# The active generators. `generator` titles a whole chat session (from its first
# message); `summarizer` labels each prompt for the outline rail. Same shape, but
# separate seams so tests can stub them independently. Tests inject fakes via
# daemon.titles.generator / daemon.titles.summarizer.
generator: TitleGenerator = AgentTitleGenerator()
summarizer: TitleGenerator = AgentTitleGenerator()
