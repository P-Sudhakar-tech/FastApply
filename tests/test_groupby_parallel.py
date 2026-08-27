import threading
import time

import numpy as np
import pandas as pd
import pytest

import turboply  # noqa: F401  (registers the .turboply accessor)
from turboply import groupby_parallel

N_GROUPS = groupby_parallel.MIN_GROUPS + 10
ROWS_PER_GROUP = 3

# groupby_parallel.py's dispatch is a genuine timing race (sample serial vs.
# threaded, use whichever measured faster), same as parallel.py's — a single
# run can occasionally lose the race to scheduling noise. Retrying keeps
# these tests meaningful (still exercising real behavior, not mocked)
# without being flaky. Mirrors tests/test_parallel.py's _eventually.
_ATTEMPTS = 5


def _eventually(attempt, attempts=_ATTEMPTS):
    last_error = None
    for _ in range(attempts):
        try:
            if attempt():
                return
        except AssertionError as exc:
            last_error = exc
    raise AssertionError(f"condition never true in {attempts} attempts") from last_error


def _df():
    return pd.DataFrame(
        {
            "key": np.repeat(np.arange(N_GROUPS), ROWS_PER_GROUP),
            "value": np.arange(N_GROUPS * ROWS_PER_GROUP),
        }
    )


def _gil_releasing_sum(thread_ids):
    """Sleeps (releases the GIL) and records which thread ran it, so tests
    can directly verify real parallel engagement instead of asserting on
    flaky wall-clock timing."""

    def func(g):
        thread_ids.add(threading.get_ident())
        time.sleep(0.001)
        return g["value"].sum()

    return func


def _cpu_bound_sum(g):
    total = 0
    for v in g["value"]:
        total += v
    return total


# --- correctness -----------------------------------------------------------


def test_parallel_fallback_matches_pandas_for_gil_releasing_func():
    df = _df()
    grouped = df.groupby("key")
    func = _gil_releasing_sum(set())
    expected = grouped.apply(lambda g: g["value"].sum(), include_groups=False)
    result = grouped.turboply(func, include_groups=False)
    pd.testing.assert_series_equal(result, expected)


def test_cpu_bound_func_still_correct_even_if_not_parallelized():
    df = _df()
    grouped = df.groupby("key")
    expected = grouped.apply(_cpu_bound_sum, include_groups=False)
    result = grouped.turboply(_cpu_bound_sum, include_groups=False)
    pd.testing.assert_series_equal(result, expected)


def test_cpu_bound_large_groups_never_falsely_engages_parallel_tier():
    """Regression test for a real bug found via examples/benchmark_groupby.py:
    with large-ish groups (many rows each), the sample-timing race for a
    CPU-bound (GIL-held) callable occasionally read a false "speedup" from
    pure measurement noise, and committing the full run on that one bad
    reading caused an actual ~3x wall-clock regression vs plain pandas (the
    threaded pre-pass never benefits under the GIL, but still pays full
    serial-equivalent cost plus threading/replay overhead on top). A single
    timing pair, and even a median across repeats, both let this through in
    a 40-trial empirical sweep; a unanimous requirement (every sample
    repeat must individually clear MIN_SPEEDUP) measured 0/40 false
    positives on the same adversarial shape reproduced here. Run this
    shape's eligibility check many times directly (cheap — declining is
    fast) to catch any regression in that guarantee."""
    n_groups = groupby_parallel.MIN_GROUPS
    rows_per_group = 1000
    df = pd.DataFrame(
        {
            "key": np.repeat(np.arange(n_groups), rows_per_group),
            "value": np.arange(n_groups * rows_per_group),
        }
    )
    grouped = df.groupby("key")

    for _ in range(20):
        result = groupby_parallel.try_parallel_fallback(grouped, _cpu_bound_sum, (), {})
        assert result is None, "CPU-bound callable on large groups must never falsely engage the parallel tier"


def test_parallel_fallback_matches_pandas_for_seriesgroupby():
    df = _df()
    grouped = df["value"].groupby(df["key"])

    def func(s):
        time.sleep(0.001)
        return s.sum()

    expected = grouped.apply(lambda s: s.sum())
    result = grouped.turboply(func)
    pd.testing.assert_series_equal(result, expected)


def test_parallel_fallback_matches_pandas_dataframe_shaped_result():
    df = _df()
    grouped = df.groupby("key")

    def func(g):
        time.sleep(0.001)
        return g.assign(value_x2=g["value"] * 2)

    expected = grouped.apply(func, include_groups=False)
    result = grouped.turboply(func, include_groups=False)
    pd.testing.assert_frame_equal(result, expected)


def test_parallel_fallback_matches_pandas_multikey_dropna_false():
    df = _df()
    df["key2"] = np.where(df["key"] % 5 == 0, None, "x")
    grouped_expected = df.groupby(["key", "key2"], dropna=False)
    grouped_result = df.groupby(["key", "key2"], dropna=False)

    def func(g):
        time.sleep(0.001)
        return g["value"].sum()

    expected = grouped_expected.apply(func, include_groups=False).reset_index(drop=True)
    result = grouped_result.turboply(func, include_groups=False).reset_index(drop=True)
    pd.testing.assert_series_equal(result, expected)


def test_parallel_fallback_passes_extra_args_and_kwargs():
    df = _df()
    grouped = df.groupby("key")

    def func(g, multiplier, offset=0):
        time.sleep(0.001)
        return g["value"].sum() * multiplier + offset

    expected = grouped.apply(func, 2, offset=5, include_groups=False)
    result = grouped.turboply(func, 2, offset=5, include_groups=False)
    pd.testing.assert_series_equal(result, expected)


# --- real multi-thread engagement (not mocked, so retried against timing noise) --


def test_gil_releasing_func_actually_runs_on_multiple_threads():
    # No include_groups here on purpose: that kwarg makes the parallel tier
    # decline outright by design (see the dedicated decline test below), so
    # proving real thread engagement needs a plain call without it. func
    # still works fine on the ungrouped-column-included group either way.
    def attempt():
        thread_ids = set()
        df = _df()
        df.groupby("key").turboply(_gil_releasing_sum(thread_ids))
        return len(thread_ids) > 1

    _eventually(attempt)


# --- direct try_parallel_fallback eligibility checks ------------------------


def test_try_parallel_fallback_returns_none_below_min_groups():
    df = pd.DataFrame({"key": np.repeat(np.arange(groupby_parallel.MIN_GROUPS - 1), 2), "value": range((groupby_parallel.MIN_GROUPS - 1) * 2)})
    grouped = df.groupby("key")
    assert groupby_parallel.try_parallel_fallback(grouped, lambda g: g["value"].sum(), (), {}) is None


def test_try_parallel_fallback_returns_none_when_func_raises():
    df = _df()
    grouped = df.groupby("key")

    def bad(g):
        raise RuntimeError("boom")

    assert groupby_parallel.try_parallel_fallback(grouped, bad, (), {}) is None


def test_try_parallel_fallback_declines_when_include_groups_passed():
    """include_groups strips grouping columns from each group inside real
    GroupBy.apply() -- plain iteration (which the threaded pre-pass relies
    on) doesn't do that stripping, so this tier must not engage at all
    rather than risk calling func on the wrong shape of group."""
    df = _df()
    grouped = df.groupby("key")
    assert (
        groupby_parallel.try_parallel_fallback(
            grouped, _gil_releasing_sum(set()), (), {"include_groups": False}
        )
        is None
    )


def test_engine_auto_falls_back_correctly_when_include_groups_passed():
    df = _df()
    grouped = df.groupby("key")
    func = _gil_releasing_sum(set())
    expected = grouped.apply(func, include_groups=False)
    result = grouped.turboply(func, include_groups=False)
    pd.testing.assert_series_equal(result, expected)


# --- verbose reporting -------------------------------------------------------


def test_verbose_reports_threaded_parallel_engine(capsys):
    def attempt():
        df = _df()
        df.groupby("key").turboply(_gil_releasing_sum(set()), verbose=True)
        return "engine=threaded-parallel" in capsys.readouterr().err

    _eventually(attempt)


# --- engine="pandas" bypasses the parallel tier too -------------------------


def test_engine_pandas_never_engages_parallel_fallback(monkeypatch):
    df = _df()
    monkeypatch.setattr(
        groupby_parallel,
        "try_parallel_fallback",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    result = df.groupby("key").turboply(_gil_releasing_sum(set()), engine="pandas", include_groups=False)
    pd.testing.assert_series_equal(
        result, df.groupby("key").apply(lambda g: g["value"].sum(), include_groups=False)
    )


def test_engine_native_never_engages_parallel_fallback(monkeypatch):
    df = _df()
    monkeypatch.setattr(
        groupby_parallel,
        "try_parallel_fallback",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    with pytest.raises(ValueError, match="no native GroupBy fast path"):
        df.groupby("key").turboply(_gil_releasing_sum(set()), engine="native", include_groups=False)
