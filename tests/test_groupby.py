import numpy as np
import pandas as pd
import pytest

import turboply  # noqa: F401  (registers the .turboply accessor)


def _df():
    return pd.DataFrame(
        {
            "key1": ["a", "a", "a", "b", "b", None],
            "key2": [1, 1, 2, 1, 1, 1],
            "value": [10, 20, 30, 40, 50, 60],
        }
    )


# --- correctness: DataFrameGroupBy --------------------------------------


def test_dataframegroupby_turboply_matches_apply_scalar_result():
    df = _df()
    func = lambda g: g["value"].sum()  # noqa: E731
    expected = df.groupby("key1").apply(func, include_groups=False)
    result = df.groupby("key1").turboply(func, include_groups=False)
    pd.testing.assert_series_equal(result, expected)


def test_dataframegroupby_turboply_matches_apply_multikey_dropna_false():
    # Mirrors the real-world call site that surfaced this feature request:
    # multi-column groupby with dropna=False (a None key forms its own
    # group instead of being dropped).
    df = _df()
    func = lambda g: g["value"].sum()  # noqa: E731
    grouped_expected = df.groupby(["key1", "key2"], dropna=False)
    grouped_result = df.groupby(["key1", "key2"], dropna=False)
    expected = grouped_expected.apply(func, include_groups=False).reset_index(drop=True)
    result = grouped_result.turboply(func, include_groups=False).reset_index(drop=True)
    pd.testing.assert_series_equal(result, expected)


def test_dataframegroupby_turboply_matches_apply_dataframe_result():
    df = _df()
    func = lambda g: g.assign(value_x2=g["value"] * 2)  # noqa: E731
    expected = df.groupby("key1").apply(func, include_groups=False)
    result = df.groupby("key1").turboply(func, include_groups=False)
    pd.testing.assert_frame_equal(result, expected)


def test_dataframegroupby_turboply_passes_extra_args_and_kwargs():
    df = _df()

    def func(g, multiplier, offset=0):
        return g["value"].sum() * multiplier + offset

    expected = df.groupby("key1").apply(func, 2, offset=5, include_groups=False)
    result = df.groupby("key1").turboply(func, 2, offset=5, include_groups=False)
    pd.testing.assert_series_equal(result, expected)


# --- correctness: SeriesGroupBy ------------------------------------------


def test_seriesgroupby_turboply_matches_apply():
    df = _df()
    func = lambda s: s.max() - s.min()  # noqa: E731
    expected = df["value"].groupby(df["key1"]).apply(func)
    result = df["value"].groupby(df["key1"]).turboply(func)
    pd.testing.assert_series_equal(result, expected)


# --- .apply() alias --------------------------------------------------------


def test_groupby_apply_alias_matches_direct_call():
    df = _df()
    func = lambda g: g["value"].sum()  # noqa: E731
    direct = df.groupby("key1").turboply(func, include_groups=False)
    aliased = df.groupby("key1").turboply.apply(func, include_groups=False)
    pd.testing.assert_series_equal(direct, aliased)


# --- engine="pandas" ---------------------------------------------------


def test_groupby_engine_pandas_matches_plain_apply():
    df = _df()
    func = lambda g: g["value"].sum()  # noqa: E731
    expected = df.groupby("key1").apply(func, include_groups=False)
    result = df.groupby("key1").turboply(func, engine="pandas", include_groups=False)
    pd.testing.assert_series_equal(result, expected)


# --- engine="native" -----------------------------------------------------


def test_groupby_engine_native_raises_no_fast_path():
    df = _df()
    func = lambda g: g["value"].sum()  # noqa: E731
    with pytest.raises(ValueError, match="no native GroupBy fast path"):
        df.groupby("key1").turboply(func, engine="native", include_groups=False)


def test_groupby_invalid_engine_raises():
    df = _df()
    with pytest.raises(ValueError, match="engine must be one of"):
        df.groupby("key1").turboply(lambda g: g["value"].sum(), engine="bogus")


# --- verbose ---------------------------------------------------------------


def test_groupby_verbose_reports_pandas_reason(capsys):
    df = _df()
    df.groupby("key1").turboply(lambda g: g["value"].sum(), verbose=True, include_groups=False)
    captured = capsys.readouterr()
    assert "engine=pandas" in captured.err
    assert "no native GroupBy fast path" in captured.err


def test_groupby_verbose_reports_forced_pandas_reason(capsys):
    df = _df()
    df.groupby("key1").turboply(lambda g: g["value"].sum(), engine="pandas", verbose=True, include_groups=False)
    captured = capsys.readouterr()
    assert "engine='pandas' forced" in captured.err


def test_groupby_verbose_silent_by_default(capsys):
    df = _df()
    df.groupby("key1").turboply(lambda g: g["value"].sum(), include_groups=False)
    captured = capsys.readouterr()
    assert captured.err == ""


# --- progress_bar ------------------------------------------------------


def test_groupby_progress_bar_reports_progress(capsys):
    df = pd.DataFrame({"key": np.repeat(np.arange(20), 3), "value": np.arange(60)})
    df.groupby("key").turboply(lambda g: g["value"].sum(), progress_bar=True, include_groups=False)
    captured = capsys.readouterr()
    assert "turboply [" in captured.err
    assert "20/20" in captured.err


def test_groupby_progress_bar_silent_by_default(capsys):
    df = _df()
    df.groupby("key1").turboply(lambda g: g["value"].sum(), include_groups=False)
    captured = capsys.readouterr()
    assert captured.err == ""


# --- accessor identity / caching -----------------------------------------


def test_groupby_accessor_is_cached_on_the_groupby_object():
    df = _df()
    grouped = df.groupby("key1")
    assert grouped.turboply is grouped.turboply
