"""The tool-call summarizer feeding the activity feed, plus the relay wiring."""

from claude_agent_sdk import AssistantMessage, ToolUseBlock

from daemon.activity_relay import relay_message_activity, summarize_tool_use
from daemon.view_state import store


def _tool(name, inp):
    return ToolUseBlock(id="t", name=name, input=inp)


def test_grep_shows_the_pattern():
    assert summarize_tool_use(_tool("Grep", {"pattern": "WITS"})) == "Grep WITS"


def test_grep_shows_pattern_and_path():
    assert summarize_tool_use(_tool("Grep", {"pattern": "WITS", "path": "daemon"})) == (
        "Grep WITS in daemon"
    )


def test_bash_shows_the_command():
    assert summarize_tool_use(_tool("Bash", {"command": "ls -la"})) == "Bash ls -la"


def test_bash_truncates_a_long_command():
    out = summarize_tool_use(_tool("Bash", {"command": "find " + "x" * 200}))
    assert len(out) <= 120
    assert out.endswith("…")


def test_read_shows_the_path():
    assert summarize_tool_use(_tool("Read", {"file_path": "daemon/mcp_server.py"})) == (
        "Read daemon/mcp_server.py"
    )


def test_glob_shows_the_pattern():
    assert summarize_tool_use(_tool("Glob", {"pattern": "**/*.py"})) == "Glob **/*.py"


def test_render_html_shows_the_title_and_never_the_html():
    out = summarize_tool_use(
        _tool("mcp__cvi__render_html", {"title": "WITS Schema", "html": "<h1>" + "z" * 5000})
    )
    assert out == "render_html → WITS Schema"  # prefix stripped, title only
    assert "z" not in out  # the HTML body must never leak into the feed


def test_render_html_without_a_title_is_just_the_name():
    out = summarize_tool_use(_tool("mcp__cvi__render_html", {"html": "<p>hi</p>"}))
    assert out == "render_html"


def test_unknown_tool_falls_back_to_key_values():
    out = summarize_tool_use(_tool("WebFetch", {"url": "https://acme.example/x"}))
    assert out == "WebFetch url=https://acme.example/x"


def test_no_input_is_just_the_name():
    assert summarize_tool_use(_tool("Bash", {})) == "Bash"


async def test_relay_records_the_tool_summary_not_the_bare_name():
    message = AssistantMessage(content=[_tool("Grep", {"pattern": "WITS"})], model="test")
    await relay_message_activity("relay-tool", message)
    entries = [(e.kind, e.text) for e in store.get_or_create("relay-tool").activity]
    assert ("tool", "Grep WITS") in entries
