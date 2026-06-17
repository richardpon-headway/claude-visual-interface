import pytest

from daemon.db import apply_migrations_sync, open_db
from daemon.mcp_server import (
    ALLOWED_TOOLS,
    CVI_CHAT_SYSTEM_PROMPT,
    CVI_REVIEW_SYSTEM_PROMPT,
    SERVER_NAME,
    TOOLS,
    build_agent_options,
    cvi_server,
)


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    # Some primitives now persist to SQLite; isolate the DB and seed the session
    # that upsert_finding's VALID_ARGS reference (the finding FK requires it).
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()
    conn = open_db()
    try:
        conn.execute(
            "INSERT INTO session (id, type, status, created_at, updated_at) "
            "VALUES ('mcp-test', 'review', 'running', 't', 't')",
        )
        conn.commit()
    finally:
        conn.close()


EXPECTED_PRIMITIVES = {
    # view-control
    "open_code",
    "split_pane",
    "highlight_range",
    "show_diff",
    "render_html",
    "render_file",
    # state
    "upsert_finding",
    "set_disposition",
    "anchor_message",
    # pull
    "get_selection",
    "get_view_state",
}

# Valid arguments for each primitive, so every handler can be exercised.
VALID_ARGS = {
    "open_code": {"surface": "mcp-test", "file": "a.py"},
    "split_pane": {"surface": "mcp-test", "n": 2},
    "highlight_range": {"surface": "mcp-test", "file": "a.py", "range": {"start": 1, "end": 3}},
    "show_diff": {"surface": "mcp-test", "a": "current", "b": "patch-1"},
    "render_html": {"surface": "mcp-test", "html": "<p>hi</p>"},
    # The seeded session has no worktree, so render_file returns its (content-block)
    # error result — enough to exercise the handler.
    "render_file": {"surface": "mcp-test", "path": "a.py"},
    "upsert_finding": {"session_id": "mcp-test", "file": "a.py", "title": "t", "body": "b"},
    "set_disposition": {"finding_id": "f", "value": "dismiss"},
    "anchor_message": {"message_id": "m", "file": "a.py", "range": {"start": 1, "end": 2}},
    "get_selection": {"surface": "mcp-test"},
    "get_view_state": {"surface": "mcp-test"},
}

# anchor_message stays stubbed until the messages table (phase 4); its handler
# still echoes its name.
UNWIRED_PRIMITIVES = {
    "anchor_message",
}


def test_server_registers_the_full_primitive_vocabulary():
    assert {t.name for t in TOOLS} == EXPECTED_PRIMITIVES
    assert cvi_server["type"] == "sdk"
    assert cvi_server["name"] == SERVER_NAME


def test_chat_and_review_prompts_differ_and_both_drive_the_html_canvas():
    assert CVI_CHAT_SYSTEM_PROMPT != CVI_REVIEW_SYSTEM_PROMPT
    # The general chat prompt is not review-framed but still drives render_html.
    assert "code-review surface" not in CVI_CHAT_SYSTEM_PROMPT
    assert "render_html" in CVI_CHAT_SYSTEM_PROMPT
    assert "no JavaScript" in CVI_CHAT_SYSTEM_PROMPT
    # The review prompt keeps the code-review framing.
    assert "code-review surface" in CVI_REVIEW_SYSTEM_PROMPT


def test_pull_primitives_are_marked_read_only():
    read_only = {t.name for t in TOOLS if t.annotations and t.annotations.readOnlyHint}
    assert read_only == {"get_selection", "get_view_state"}


def test_allowed_tools_are_fully_qualified():
    assert ALLOWED_TOOLS == [f"mcp__{SERVER_NAME}__{t.name}" for t in TOOLS]


async def test_every_handler_returns_a_content_block():
    for t in TOOLS:
        result = await t.handler(VALID_ARGS[t.name])
        assert isinstance(result["content"], list)
        assert result["content"]
        assert result["content"][0]["type"] == "text"


async def test_unwired_primitives_still_echo_their_name():
    by_name = {t.name: t for t in TOOLS}
    for name in UNWIRED_PRIMITIVES:
        result = await by_name[name].handler(VALID_ARGS[name])
        assert name in result["content"][0]["text"]


def test_build_agent_options_attaches_server_and_approves_primitives():
    options = build_agent_options()
    assert options.mcp_servers == {SERVER_NAME: cvi_server}
    # cvi primitives plus the read-only review tools are auto-approved.
    assert set(ALLOWED_TOOLS).issubset(options.allowed_tools)
    assert {"Read", "Grep", "Glob", "Bash"}.issubset(options.allowed_tools)
    assert options.cwd is None


def test_build_agent_options_sets_the_review_worktree():
    options = build_agent_options(cwd="/tmp/worktree")
    assert options.cwd == "/tmp/worktree"


def test_build_agent_options_passes_resume_session_id():
    assert build_agent_options(resume="sdk-xyz").resume == "sdk-xyz"
    assert build_agent_options().resume is None


async def test_review_permission_gate_allows_read_only_tools_and_denies_writes():
    options = build_agent_options(cwd="/tmp/worktree")
    allow_read = await options.can_use_tool("Read", {}, None)
    allow_cvi = await options.can_use_tool(f"mcp__{SERVER_NAME}__upsert_finding", {}, None)
    deny_edit = await options.can_use_tool("Edit", {}, None)
    assert allow_read.behavior == "allow"
    assert allow_cvi.behavior == "allow"
    assert deny_edit.behavior == "deny"
