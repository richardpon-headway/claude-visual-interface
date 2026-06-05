from daemon.mcp_server import ALLOWED_TOOLS, SERVER_NAME, TOOLS, build_agent_options, cvi_server

EXPECTED_PRIMITIVES = {
    # view-control
    "open_code",
    "split_pane",
    "highlight_range",
    "show_diff",
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
    "upsert_finding": {"session_id": "sess", "file": "a.py", "title": "t", "body": "b"},
    "set_disposition": {"finding_id": "f", "value": "dismiss"},
    "anchor_message": {"message_id": "m", "file": "a.py", "range": {"start": 1, "end": 2}},
    "get_selection": {"surface": "mcp-test"},
    "get_view_state": {"surface": "mcp-test"},
}

# Primitives still stubbed in this phase (state + pull); their handlers echo their name.
UNWIRED_PRIMITIVES = {
    "upsert_finding",
    "set_disposition",
    "anchor_message",
    "get_selection",
    "get_view_state",
}


def test_server_registers_the_full_primitive_vocabulary():
    assert {t.name for t in TOOLS} == EXPECTED_PRIMITIVES
    assert cvi_server["type"] == "sdk"
    assert cvi_server["name"] == SERVER_NAME


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
    assert options.allowed_tools == ALLOWED_TOOLS
