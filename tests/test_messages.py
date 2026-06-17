import pytest

from daemon import messages
from daemon.db import apply_migrations_sync


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()


def test_append_and_list_in_insertion_order():
    messages.append_message("s", "user", "hello")
    messages.append_message("s", "text", "hi there")
    messages.append_message("other", "user", "elsewhere")  # a different surface

    rows = messages.list_messages("s")
    assert [(r["kind"], r["text"]) for r in rows] == [("user", "hello"), ("text", "hi there")]
    assert rows[0]["id"] < rows[1]["id"]  # ordered by insertion


def test_append_returns_rowid_and_carries_html():
    mid = messages.append_message("s", "artifact", "design", html="<p>hi</p>")
    row = messages.list_messages("s")[0]
    assert row["id"] == mid
    assert row["html"] == "<p>hi</p>"


def test_set_message_summary_updates_the_row():
    mid = messages.append_message("s", "user", "fix the parser please")
    assert messages.set_message_summary(mid, "fix the parser") is True
    assert messages.list_messages("s")[0]["summary"] == "fix the parser"
    # No such row → False.
    assert messages.set_message_summary(999_999, "nope") is False
