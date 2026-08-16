from unittest import mock

import numpy as np
import pandas as pd
import pytest

import turboply  # noqa: F401  (registers the .turboply accessor)
from turboply import _turboply, decide_str

LARGE_N = 1000


def _large_str_series(fmt="Item_{}_Mixed"):
    return pd.Series([fmt.format(i) for i in range(LARGE_N)])


# --- whitelisted no-arg methods, reachable via .turboply(func) -------------


@pytest.mark.parametrize("func", [str.upper, str.lower, str.strip])
def test_whitelisted_method_matches_pandas(func):
    s = _large_str_series("  Item_{}_Mixed  ")
    expected = s.apply(func)
    result = s.turboply(func)
    pd.testing.assert_series_equal(result, expected)


def test_whitelisted_method_actually_calls_native(monkeypatch):
    s = _large_str_series()
    with mock.patch.object(_turboply, "str_upper", wraps=_turboply.str_upper) as spy:
        result = s.turboply(str.upper)
    assert result.equals(s.apply(str.upper))
    # verified_native() calls native_fn twice by design: once on the
    # sample to verify it agrees with Python, once on the full Series.
    assert spy.call_count == 2


def test_unwhitelisted_string_method_falls_back():
    s = _large_str_series()
    assert decide_str.decide(s, str.title).result is None
    pd.testing.assert_series_equal(s.turboply(str.title), s.apply(str.title))


def test_lambda_wrapping_whitelisted_method_is_not_matched():
    """Only exact identity (`func is str.upper`) is trusted — a lambda
    that happens to do the same thing isn't, since we can't safely tell
    two different callables compute the same thing without probing, and
    the whole point of the identity whitelist is to avoid needing to."""
    s = _large_str_series()
    wrapped = lambda x: x.upper()  # noqa: E731
    decision = decide_str.decide(s, wrapped)
    assert decision.result is None
    pd.testing.assert_series_equal(s.turboply(wrapped), s.apply(wrapped))


def test_small_string_series_never_engages():
    s = pd.Series(["a", "b", "c"])
    assert decide_str.decide(s, str.upper).result is None


def test_series_with_nulls_never_engages():
    """Plain pandas .apply(str.upper) itself raises TypeError on a null
    value (None has no .upper()), so there's no "matches pandas" output
    to compare against here — this only checks that decide_str declines
    up front rather than crashing partway through a native call."""
    s = pd.Series(["a", None, "c"] * 400)
    assert decide_str.decide(s, str.upper).result is None


def test_mixed_type_object_series_falls_back():
    s = pd.Series([f"item_{i}" if i % 2 == 0 else i for i in range(LARGE_N)])
    assert decide_str.decide(s, str.upper).result is None


def test_unicode_matches_pandas():
    s = pd.Series(["café", "MÜNCHEN", "  日本語  ", "İstanbul", "ﬃ ligature"] * 200)
    for func in (str.upper, str.lower, str.strip):
        expected = s.apply(func)
        result = s.turboply(func)
        pd.testing.assert_series_equal(result, expected)


def test_engine_native_succeeds_for_whitelisted_string_method():
    s = _large_str_series()
    result = s.turboply(str.upper, engine="native")
    pd.testing.assert_series_equal(result, s.apply(str.upper))


def test_engine_native_raises_for_non_whitelisted_string_method():
    s = _large_str_series()
    with pytest.raises(ValueError, match="not eligible"):
        s.turboply(str.title, engine="native")


def test_verbose_reports_native_string_engine(capsys):
    s = _large_str_series()
    s.turboply(str.upper, verbose=True)
    err = capsys.readouterr().err
    assert "engine=native-str-upper" in err


# --- .turboply.str.contains / .replace --------------------------------------


def test_str_contains_matches_pandas():
    s = _large_str_series()
    expected = s.str.contains("Item_1", regex=True)
    result = s.turboply.str.contains("Item_1")
    pd.testing.assert_series_equal(result, expected)


def test_str_contains_regex_matches_pandas():
    s = _large_str_series()
    expected = s.str.contains(r"Item_\d*1_", regex=True)
    result = s.turboply.str.contains(r"Item_\d*1_")
    pd.testing.assert_series_equal(result, expected)


def test_str_replace_matches_pandas():
    s = _large_str_series()
    expected = s.str.replace("Item", "Entry", regex=True)
    result = s.turboply.str.replace("Item", "Entry")
    pd.testing.assert_series_equal(result, expected)


def test_str_replace_regex_matches_pandas():
    s = _large_str_series()
    expected = s.str.replace(r"\d+", "#", regex=True)
    result = s.turboply.str.replace(r"\d+", "#")
    pd.testing.assert_series_equal(result, expected)


def test_str_contains_invalid_regex_falls_back_to_pandas():
    """Rust's regex crate has no backreference support (unlike Python's
    re), so a pattern relying on it can't compile there — must still
    produce the correct (pandas) result rather than erroring out."""
    s = _large_str_series()
    pattern = r"(Item)_\d+_\1"  # backreference: unsupported by Rust regex
    expected = s.str.contains(pattern, regex=True)
    result = s.turboply.str.contains(pattern)
    pd.testing.assert_series_equal(result, expected)


def test_str_contains_actually_calls_native_when_eligible():
    s = _large_str_series()
    with mock.patch.object(_turboply, "str_contains", wraps=_turboply.str_contains) as spy:
        result = s.turboply.str.contains("Item")
    assert result.equals(s.str.contains("Item", regex=True))
    assert spy.call_count == 2  # sample-verify, then full run — see above


def test_str_contains_verbose(capsys):
    s = _large_str_series()
    s.turboply.str.contains("Item", verbose=True)
    err = capsys.readouterr().err
    assert "engine=native-str-contains" in err


def test_str_replace_verbose(capsys):
    s = _large_str_series()
    s.turboply.str.replace("Item", "X", verbose=True)
    err = capsys.readouterr().err
    assert "engine=native-str-replace" in err
