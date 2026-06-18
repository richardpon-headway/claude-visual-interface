"""The per-call token-usage repository: appends one row per LLM call and rolls them
up by surface (the session total) and by prompt (the future per-prompt breakdown)."""

import pytest

from daemon import token_usage
from daemon.db import apply_migrations_sync


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("CVI_DB_PATH", str(tmp_path / "cvi.db"))
    apply_migrations_sync()


def test_session_totals_sum_across_kinds():
    token_usage.append_usage("s", "turn", output_tokens=100, input_tokens=2000, message_id=1)
    token_usage.append_usage("s", "title", output_tokens=5, input_tokens=40)  # session-level
    token_usage.append_usage("s", "summary", output_tokens=8, input_tokens=60, message_id=1)

    assert token_usage.session_totals("s") == (113, 2100)


def test_session_totals_zero_for_unknown_surface():
    assert token_usage.session_totals("nobody") == (0, 0)


def test_session_totals_scoped_per_surface():
    token_usage.append_usage("a", "turn", output_tokens=10, input_tokens=10)
    token_usage.append_usage("b", "turn", output_tokens=99, input_tokens=99)
    assert token_usage.session_totals("a") == (10, 10)


def test_tokens_for_message_filters_to_one_prompt():
    token_usage.append_usage("s", "turn", output_tokens=100, input_tokens=2000, message_id=1)
    token_usage.append_usage("s", "summary", output_tokens=8, input_tokens=60, message_id=1)
    token_usage.append_usage("s", "turn", output_tokens=50, input_tokens=900, message_id=2)

    assert token_usage.tokens_for_message(1) == (108, 2060)
    assert token_usage.tokens_for_message(2) == (50, 900)
    assert token_usage.tokens_for_message(999) == (0, 0)
