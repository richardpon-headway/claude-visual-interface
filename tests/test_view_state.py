from daemon.view_state import ActivityEntry, ViewStore


def test_snapshot_is_json_shaped_and_starts_empty():
    store = ViewStore()
    assert store.snapshot("fresh") == {
        "surface": "fresh",
        "activity": [],
        "thinking": False,
    }


def test_set_thinking_flips_the_flag_and_rides_the_snapshot():
    store = ViewStore()
    assert store.snapshot("s")["thinking"] is False
    store.set_thinking("s", True)
    assert store.snapshot("s")["thinking"] is True
    store.set_thinking("s", False)
    assert store.get_or_create("s").thinking is False


def test_append_activity_accumulates_and_rides_the_snapshot():
    store = ViewStore()
    store.append_activity("s", "text", "reviewing the diff")
    store.append_activity("s", "tool", "Bash")

    snap = store.snapshot("s")
    assert snap["activity"] == [
        {"kind": "text", "text": "reviewing the diff", "html": None, "summary": None},
        {"kind": "tool", "text": "Bash", "html": None, "summary": None},
    ]


def test_append_activity_returns_the_stored_entry():
    store = ViewStore()
    entry = store.append_activity("s", "user", "hello")
    assert (entry.kind, entry.text) == ("user", "hello")
    # The returned object is the one in the buffer (callers enrich it in place).
    entry.summary = "greeting"
    assert store.get_or_create("s").activity[-1].summary == "greeting"


def test_append_activity_carries_an_artifact_payload():
    store = ViewStore()
    store.append_activity("s", "artifact", "design", html="<p>hi</p>")
    activity = store.get_or_create("s").activity
    assert activity[0].html == "<p>hi</p>"


def test_append_activity_keeps_full_history_uncapped():
    store = ViewStore()
    for i in range(500):
        store.append_activity("s", "text", f"line {i}")

    activity = store.get_or_create("s").activity
    assert len(activity) == 500
    assert activity[0].text == "line 0"
    assert activity[-1].text == "line 499"


def test_load_activity_replaces_the_transcript_and_rides_the_snapshot():
    store = ViewStore()
    store.load_activity(
        "s",
        [ActivityEntry(kind="user", text="hello", summary="greeting", message_id=7)],
    )
    snap = store.snapshot("s")
    # The loaded entry rides the snapshot; message_id stays server-only.
    assert snap["activity"] == [
        {"kind": "user", "text": "hello", "html": None, "summary": "greeting"}
    ]


def test_hydration_flag_tracks_per_surface():
    store = ViewStore()
    assert store.is_hydrated("s") is False
    store.mark_hydrated("s")
    assert store.is_hydrated("s") is True
    assert store.is_hydrated("other") is False
