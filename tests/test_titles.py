"""The label helper: turning a prompt's text into a short display label (session
title / outline-rail row) by truncating it. No model calls — the old title/summary
generation agents were removed."""

from daemon import titles


def test_truncate_label_returns_short_text_unchanged():
    assert titles.truncate_label("fix the parser") == "fix the parser"


def test_truncate_label_strips_surrounding_whitespace():
    assert titles.truncate_label("  fix the parser  ") == "fix the parser"


def test_truncate_label_takes_the_first_non_empty_line():
    assert titles.truncate_label("fix the parser\nignored second line") == "fix the parser"
    assert titles.truncate_label("\n\n  real first line\nsecond") == "real first line"


def test_truncate_label_cuts_to_the_first_n_characters():
    out = titles.truncate_label("x" * 200, 80)
    assert out == "x" * 80


def test_truncate_label_uses_the_default_cap():
    out = titles.truncate_label("y" * 500)
    assert out is not None
    assert len(out) == titles.TITLE_MAX_CHARS


def test_truncate_label_returns_none_when_nothing_usable():
    assert titles.truncate_label("") is None
    assert titles.truncate_label("   \n  ") is None
