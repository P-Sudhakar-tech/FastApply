import threading
import time

import pandas as pd
import pytest

import turboply  # noqa: F401  (registers the .turboply accessor)
from turboply import parallel

N_ROWS = parallel.MIN_ROWS + 200


def _gil_releasing_func(thread_ids):
    """A callable that sleeps (releases the GIL) and records which thread
    ran it, so the test can directly verify real parallel engagement
    instead of asserting on flaky wall-clock timing. Returns a string —
    non-numeric output — so the native numeric fast path (which would
    otherwise legitimately catch a plain `x * 2`-style affine transform
    and short-circuit before ever reaching the parallel tier) correctly
    declines and this exercises tier 2 specifically."""

    def func(x):
        thread_ids.add(threading.get_ident())
        time.sleep(0.0005)
        return f"row-{x}"

    return func


def _cpu_bound_func(x):
    total = 0
    for _ in range(50):
        total += x
    return total


# --- correctness -----------------------------------------------------------


def test_parallel_fallback_matches_pandas_for_gil_releasing_func():
    s = pd.Series(range(N_ROWS))
    func = _gil_releasing_func(set())
    expected = s.apply(lambda x: f"row-{x}")  # same output, no sleep, for comparison
    result = s.turboply(func)
    pd.testing.assert_series_equal(result, expected)


def test_parallel_fallback_matches_pandas_for_dataframe_axis1():
    df = pd.DataFrame({"a": range(N_ROWS), "b": range(N_ROWS)})
    thread_ids = set()

    def func(row):
        thread_ids.add(threading.get_ident())
        time.sleep(0.0005)
        return f"{row['a']}-{row['b']}"

    expected = df.apply(lambda row: f"{row['a']}-{row['b']}", axis=1)
    result = df.turboply(func, axis=1)
    pd.testing.assert_series_equal(result, expected)
    assert len(thread_ids) > 1, "expected the row-wise func to run on multiple threads"


def test_cpu_bound_func_still_correct_even_if_not_parallelized():
    """Whether or not the race decides threading helps, the result must
    always match plain pandas — correctness never depends on the timing
    decision going one way or the other."""
    s = pd.Series(range(N_ROWS))
    expected = s.apply(_cpu_bound_func)
    result = s.turboply(_cpu_bound_func)
    pd.testing.assert_series_equal(result, expected)


# --- real multi-thread engagement (not timing-based, so not flaky) --------


def test_gil_releasing_func_actually_runs_on_multiple_threads():
    thread_ids = set()
    s = pd.Series(range(N_ROWS))
    s.turboply(_gil_releasing_func(thread_ids))
    assert len(thread_ids) > 1, "expected the sleep-based func to engage the thread pool"


def test_try_parallel_fallback_returns_none_below_min_rows():
    s = pd.Series(range(parallel.MIN_ROWS - 1))
    assert parallel.try_parallel_fallback(s, lambda x: f"row-{x}") is None


def test_try_parallel_fallback_returns_none_when_func_raises():
    s = pd.Series(range(N_ROWS))

    def bad(x):
        raise RuntimeError("boom")

    assert parallel.try_parallel_fallback(s, bad) is None


# --- verbose reporting -------------------------------------------------------


def test_verbose_reports_threaded_parallel_engine(capsys):
    s = pd.Series(range(N_ROWS))
    s.turboply(_gil_releasing_func(set()), verbose=True)
    err = capsys.readouterr().err
    assert "engine=threaded-parallel" in err


# --- engine="pandas" bypasses the parallel tier too -------------------------


def test_engine_pandas_never_engages_parallel_fallback(monkeypatch):
    s = pd.Series(range(N_ROWS))
    monkeypatch.setattr(
        parallel,
        "try_parallel_fallback",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    result = s.turboply(_gil_releasing_func(set()), engine="pandas")
    pd.testing.assert_series_equal(result, s.apply(lambda x: f"row-{x}"))
