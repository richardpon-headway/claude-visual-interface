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
        result = await t.handler({"surface": "s-1"})
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"
        assert t.name in result["content"][0]["text"]


def test_build_agent_options_attaches_server_and_approves_primitives():
    options = build_agent_options()
    assert options.mcp_servers == {SERVER_NAME: cvi_server}
    assert options.allowed_tools == ALLOWED_TOOLS
