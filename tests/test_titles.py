"""The chat-title generator: the pure cleaning helper, plus the one-shot SDK call
exercised with a fake client. The real generation (Claude actually titling) needs
the CLI + auth and is verified locally."""

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from daemon import titles


def test_clean_title_strips_quotes_whitespace_and_takes_first_line():
    assert titles._clean_title('  "Fix the parser"  ') == "Fix the parser"
    assert titles._clean_title("Fix the parser\nignored second line") == "Fix the parser"
    assert titles._clean_title("'Single quoted'") == "Single quoted"


def test_clean_title_returns_none_on_empty():
    assert titles._clean_title("") is None
    assert titles._clean_title("   \n  ") is None


def test_clean_title_strips_a_stray_title_prefix():
    assert titles._clean_title("Title: Fix the parser") == "Fix the parser"
    assert titles._clean_title("title: fix the parser") == "fix the parser"
    assert titles._clean_title('Title: "Quoted thing"') == "Quoted thing"


def test_clean_title_keeps_a_legit_title_without_a_colon():
    # No colon → not the "Title:" preamble; the real title is left intact.
    assert titles._clean_title("Title bar refactor") == "Title bar refactor"


def test_clean_title_caps_length_on_a_word_boundary():
    out = titles._clean_title("word " * 30)  # 150 chars of words
    assert out is not None
    assert len(out) <= 60
    assert not out.endswith(" ")


class FakeTitleClient:
    """Stands in for ClaudeSDKClient in the title call: records the query and
    replies with a canned assistant message (or raises on connect)."""

    def __init__(self, options=None, *, reply="A Generated Title", raise_on_enter=False):
        self.options = options
        self.queried: list[str] = []
        self._reply = reply
        self._raise_on_enter = raise_on_enter

    async def __aenter__(self):
        if self._raise_on_enter:
            raise RuntimeError("connect failed")
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt):
        self.queried.append(prompt)

    async def receive_response(self):
        yield AssistantMessage(content=[TextBlock(text=self._reply)], model="test")
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="t",
        )


async def test_generate_returns_cleaned_assistant_text(monkeypatch):
    client = FakeTitleClient(reply='  "My Title"  ')
    monkeypatch.setattr(titles, "ClaudeSDKClient", lambda options=None: client)

    assert await titles.AgentTitleGenerator().generate("help me debug") == "My Title"
    assert client.queried == ["help me debug"]


async def test_generate_truncates_long_input(monkeypatch):
    client = FakeTitleClient()
    monkeypatch.setattr(titles, "ClaudeSDKClient", lambda options=None: client)

    await titles.AgentTitleGenerator().generate("x" * 5000)

    assert len(client.queried[0]) == titles.MAX_TITLE_INPUT_CHARS


async def test_generate_returns_none_when_the_client_raises(monkeypatch):
    monkeypatch.setattr(
        titles, "ClaudeSDKClient", lambda options=None: FakeTitleClient(raise_on_enter=True)
    )

    assert await titles.AgentTitleGenerator().generate("hi") is None
