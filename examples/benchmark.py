"""Benchmark: plain pandas .apply() vs .turboply.apply() on 1,000 rows.

    .venv/Scripts/python.exe examples/benchmark.py

As of Phase 2 (see claude.md), the numeric-transform case below is routed
through the native affine fast path (decide.py + Rust affine_f64/abs_f64)
whenever the callable can be verified as a linear/abs transform on a
numeric Series of at least decide.MIN_ROWS rows; the string and row-wise
DataFrame cases are still Phase 1's plain pandas fallback (Phases 4/5).

Reported numbers use the median of many repeats with a warmup, since these
calls run in well under a millisecond and a plain mean is dominated by OS
scheduling noise at that scale.
"""

import statistics
import time

import numpy as np
import pandas as pd

import turboply  # noqa: F401  (registers the .turboply accessor)

N_ROWS = 1000
N_REPEATS = 50
N_WARMUP = 5


def timed(fn, repeats=N_REPEATS, warmup=N_WARMUP):
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return times


def report(label, pandas_times, turboply_times):
    p_med = statistics.median(pandas_times) * 1000
    t_med = statistics.median(turboply_times) * 1000
    speedup = p_med / t_med if t_med else float("inf")

    print(label)
    print(f"  pandas .apply()    {p_med:8.4f} ms (median of {N_REPEATS})")
    print(f"  .turboply.apply()  {t_med:8.4f} ms (median of {N_REPEATS})")
    print(f"  speedup            {speedup:.2f}x")
    print()


def main():
    rng = np.random.default_rng(42)
    df = pd.DataFrame(
        {
            "a": rng.integers(0, 1000, size=N_ROWS),
            "b": rng.normal(size=N_ROWS),
            "name": [f"item_{i}" for i in range(N_ROWS)],
        }
    )

    print(f"Benchmarking on {N_ROWS} rows, {N_REPEATS} repeats per case (+{N_WARMUP} warmup)\n")

    numbers = df["a"]
    report(
        "Series numeric transform: x * 2 + 1  [native fast path]",
        timed(lambda: numbers.apply(lambda x: x * 2 + 1)),
        timed(lambda: numbers.turboply.apply(lambda x: x * 2 + 1)),
    )

    names = df["name"]
    report(
        "Series string transform: str.upper  [Phase 4, still fallback]",
        timed(lambda: names.apply(str.upper)),
        timed(lambda: names.turboply.apply(str.upper)),
    )

    report(
        "DataFrame row-wise apply, axis=1  [Phase 5, still fallback]",
        timed(lambda: df.apply(lambda row: row["a"] + row["b"], axis=1)),
        timed(lambda: df.turboply.apply(lambda row: row["a"] + row["b"], axis=1)),
    )

    print(
        "Only the numeric-transform case is accelerated today. String ops and\n"
        "row-wise DataFrame apply are unchanged pandas fallback until Phases 4/5."
    )


if __name__ == "__main__":
    main()
