from daemon.view_state import ViewStore


def test_open_code_records_file_and_range_per_pane():
    store = ViewStore()
    store.open_code("s", "a.py", {"start": 10, "end": 20}, pane=0)
    store.open_code("s", "b.py", None, pane=1)

    state = store.get_or_create("s")
    assert state.open[0].file == "a.py"
    assert (state.open[0].range.start, state.open[0].range.end) == (10, 20)
    assert state.open[1].file == "b.py"
    assert state.open[1].range is None


def test_split_pane_sets_count_and_trims_orphaned_panes():
    store = ViewStore()
    store.open_code("s", "a.py", None, pane=0)
    store.open_code("s", "b.py", None, pane=1)
    store.split_pane("s", 1)

    state = store.get_or_create("s")
    assert state.panes == 1
    assert set(state.open) == {0}  # pane 1 dropped when the split shrank


def test_highlight_range_accumulates_per_file():
    store = ViewStore()
    store.highlight_range("s", "a.py", {"start": 1, "end": 2})
    store.highlight_range("s", "a.py", {"start": 5, "end": 6})

    highlights = store.get_or_create("s").highlights["a.py"]
    assert [(r.start, r.end) for r in highlights] == [(1, 2), (5, 6)]


def test_show_diff_sets_the_current_diff():
    store = ViewStore()
    store.show_diff("s", "current", "patch-1")
    assert (store.get_or_create("s").diff.a, store.get_or_create("s").diff.b) == (
        "current",
        "patch-1",
    )


def test_set_selection_records_and_clears():
    store = ViewStore()
    store.set_selection("s", "a.py", {"start": 3, "end": 8})
    sel = store.get_or_create("s").selection
    assert sel is not None
    assert sel.file == "a.py"
    assert (sel.range.start, sel.range.end) == (3, 8)


def test_snapshot_is_json_shaped_and_starts_empty():
    store = ViewStore()
    snap = store.snapshot("fresh")
    assert snap == {
        "surface": "fresh",
        "panes": 1,
        "open": {},
        "highlights": {},
        "diff": None,
        "selection": None,
    }
