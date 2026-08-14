"""Benchmark: plain pandas .apply() vs .turboply.apply() on 1,000 rows.

    .venv/Scripts/python.exe examples/benchmark.py

Phase 1 status (see claude.md): .turboply.apply() is currently a pure
fallback to pandas .apply() — no native dispatch is wired up yet. So the
timings below are expected to be roughly equal, give or take accessor
overhead. This script exists as the harness that Phase 2's numeric fast
path should show a real speedup against once it lands.
"""

import statistics
import time

import numpy as np
import pandas as pd

import turboply  # noqa: F401  (registers the .turboply accessor)

N_ROWS = 1000
N_REPEATS = 30


def timed(fn, repeats=N_REPEATS):
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return times


def report(label, pandas_times, turboply_times):
    p_mean = statistics.mean(pandas_times) * 1000
    p_stdev = statistics.stdev(pandas_times) * 1000
    t_mean = statistics.mean(turboply_times) * 1000
    t_stdev = statistics.stdev(turboply_times) * 1000
    speedup = p_mean / t_mean if t_mean else float("inf")

    print(label)
    print(f"  pandas .apply()    {p_mean:8.4f} ms  (stdev {p_stdev:.4f} ms)")
    print(f"  .turboply.apply()  {t_mean:8.4f} ms  (stdev {t_stdev:.4f} ms)")
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

    print(f"Benchmarking on {N_ROWS} rows, {N_REPEATS} repeats per case\n")

    numbers = df["a"]
    report(
        "Series numeric transform: x * 2 + 1",
        timed(lambda: numbers.apply(lambda x: x * 2 + 1)),
        timed(lambda: numbers.turboply.apply(lambda x: x * 2 + 1)),
    )

    names = df["name"]
    report(
        "Series string transform: str.upper",
        timed(lambda: names.apply(str.upper)),
        timed(lambda: names.turboply.apply(str.upper)),
    )

    report(
        "DataFrame row-wise apply (axis=1): row['a'] + row['b']",
        timed(lambda: df.apply(lambda row: row["a"] + row["b"], axis=1)),
        timed(lambda: df.turboply.apply(lambda row: row["a"] + row["b"], axis=1)),
    )

    print(
        "No speedup yet is expected: Phase 2 (native numeric fast path) hasn't\n"
        "landed. The numeric-transform case above is the one to watch once it does."
    )


if __name__ == "__main__":
    main()
