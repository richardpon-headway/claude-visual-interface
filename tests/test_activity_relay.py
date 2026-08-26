"""The tool-call summarizer feeding the activity feed, the render-tag sniffer, plus
the relay wiring."""

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

from daemon.activity_relay import (
    relay_message_activity,
    split_render_segments,
    summarize_tool_use,
)
from daemon.db import apply_migrations_sync
from daemon.view_state import store


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()


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


def test_split_plain_text_is_a_single_text_segment():
    segs = split_render_segments("just a normal reply")
    assert [(s.kind, s.text) for s in segs] == [("text", "just a normal reply")]


def test_split_blank_text_yields_no_segments():
    assert split_render_segments("   \n  ") == []


def test_split_extracts_an_artifact_with_its_title():
    segs = split_render_segments('<cvi-artifact title="Design"><p>hi</p></cvi-artifact>')
    assert len(segs) == 1
    assert segs[0].kind == "artifact"
    assert segs[0].title == "Design"
    assert segs[0].html == "<p>hi</p>"


def test_split_artifact_without_a_title_defaults_to_empty():
    segs = split_render_segments("<cvi-artifact><p>hi</p></cvi-artifact>")
    assert [(s.kind, s.title, s.html) for s in segs] == [("artifact", "", "<p>hi</p>")]


def test_split_preserves_surrounding_prose_in_order():
    segs = split_render_segments(
        "Here's the summary:\n"
        '<cvi-artifact title="X"><p>page</p></cvi-artifact>\n'
        "Let me know."
    )
    assert [(s.kind, s.text or s.html) for s in segs] == [
        ("text", "Here's the summary:"),
        ("artifact", "<p>page</p>"),
        ("text", "Let me know."),
    ]


def test_split_handles_multiple_artifacts():
    segs = split_render_segments(
        "<cvi-artifact><p>one</p></cvi-artifact><cvi-artifact><p>two</p></cvi-artifact>"
    )
    assert [(s.kind, s.html) for s in segs] == [
        ("artifact", "<p>one</p>"),
        ("artifact", "<p>two</p>"),
    ]


def test_split_ignores_a_tag_inside_a_fenced_code_block():
    # Showing the tag as an example must NOT render it.
    text = "How it works:\n```\n<cvi-artifact><p>x</p></cvi-artifact>\n```"
    segs = split_render_segments(text)
    assert [s.kind for s in segs] == ["text"]
    assert "<cvi-artifact>" in segs[0].text


def test_split_ignores_a_tag_inside_inline_code():
    segs = split_render_segments("use the `<cvi-artifact>` tag")
    assert [s.kind for s in segs] == ["text"]
    assert "<cvi-artifact>" in segs[0].text


def test_split_keeps_a_code_fence_that_lives_inside_the_artifact_html():
    # The load-bearing robustness property: a ```fence``` WITHIN the rendered HTML must
    # not prematurely terminate the artifact or leak into a separate text segment.
    html = "<pre>```html\n<b>x</b>\n```</pre>"
    segs = split_render_segments(f"<cvi-artifact>{html}</cvi-artifact>")
    assert [(s.kind, s.html) for s in segs] == [("artifact", html)]


def test_split_accepts_a_single_quoted_title():
    segs = split_render_segments("<cvi-artifact title='Design'><p>hi</p></cvi-artifact>")
    assert [(s.kind, s.title) for s in segs] == [("artifact", "Design")]


def test_split_ignores_an_unclosed_tag():
    # A truncated page must never render.
    segs = split_render_segments("<cvi-artifact><p>never closed")
    assert [s.kind for s in segs] == ["text"]


async def test_relay_renders_an_artifact_tag_and_never_persists_raw_html_as_text():
    html = "<h1>" + "z" * 5000 + "</h1>"
    block = TextBlock(text=f'Summary:\n<cvi-artifact title="Big">{html}</cvi-artifact>')
    await relay_message_activity(
        "relay-artifact", AssistantMessage(content=[block], model="test")
    )
    entries = [(e.kind, e.text, e.html) for e in store.get_or_create("relay-artifact").activity]
    assert ("text", "Summary:", None) in entries
    assert ("artifact", "Big", html) in entries
    # The raw HTML body is never recorded as a text segment.
    assert not any(kind == "text" and "z" in (text or "") for kind, text, _ in entries)


async def test_relay_marks_a_background_turn_artifact_as_background():
    block = TextBlock(text="<cvi-artifact><p>done</p></cvi-artifact>")
    await relay_message_activity(
        "relay-bg-artifact", AssistantMessage(content=[block], model="test"), background=True
    )
    entry = store.get_or_create("relay-bg-artifact").activity[-1]
    assert (entry.kind, entry.html, entry.background) == ("artifact", "<p>done</p>", True)


async def test_relay_records_ask_user_question_as_a_structured_ask_entry():
    questions = [
        {
            "question": "Which approach?",
            "header": "Approach",
            "multiSelect": False,
            "options": [{"label": "A", "description": "first"}, {"label": "B"}],
        }
    ]
    block = ToolUseBlock(id="ask-1", name="AskUserQuestion", input={"questions": questions})
    await relay_message_activity("relay-ask", AssistantMessage(content=[block], model="test"))

    entry = store.get_or_create("relay-ask").activity[-1]
    assert entry.kind == "ask"
    assert entry.ask_id == "ask-1"
    assert entry.questions == questions
    # And it rides the snapshot with the structured payload (no picker → just text).
    snap_entry = store.snapshot("relay-ask")["activity"][-1]
    assert snap_entry["ask_id"] == "ask-1"
    assert snap_entry["questions"] == questions
