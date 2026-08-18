"""Benchmark: plain pandas .apply() vs .turboply() across row counts, to
see whether the native fast paths' speedup holds as data grows and where
the Rust-side sequential/parallel split (`core::PARALLEL_THRESHOLD =
50_000` elements) actually kicks in.

    .venv/Scripts/python.exe examples/benchmark_scale.py

Two cases, both native-fast-path-eligible under the default engine="auto":
  - numeric transform: x * 2 + 1        -> decide.py + Rust affine_i64
  - row-wise:          row['a']+row['b'] -> decide_row.py + Rust row_affine_f64

Row counts: 10_000 / 20_000 / 30_000 / 40_000 / 50_000. The Rust core
switches from a plain sequential loop to a rayon-parallel iterator at
exactly 50_000 elements, so the top of this range is the first point
where that switch can actually be observed rather than assumed.

Repeats scale down as N grows (row-wise axis=1 in particular is
notoriously slow in vanilla pandas — it builds a Series object per row —
so a fixed high repeat count would make the largest sizes take minutes).
"""

import statistics
import time

import numpy as np
import pandas as pd

import turboply  # noqa: F401  (registers the .turboply accessor)

N_ROWS_LIST = [10_000, 20_000, 30_000, 40_000, 50_000]
N_WARMUP = 2

# Mirrors core::PARALLEL_THRESHOLD in src/core.rs — not exposed to Python,
# so kept in sync here manually for reporting purposes only.
PARALLEL_THRESHOLD = 50_000


def repeats_for(n):
    # Keep total wall time bounded: fewer repeats for slower/larger cases.
    return max(5, min(30, 300_000 // n))


def timed(fn, repeats, warmup=N_WARMUP):
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return times


def report(label, n, pandas_times, turboply_times, repeats):
    p_med = statistics.median(pandas_times) * 1000
    t_med = statistics.median(turboply_times) * 1000
    speedup = p_med / t_med if t_med else float("inf")
    print(f"  n={n:>6}  pandas={p_med:9.3f} ms  turboply={t_med:9.3f} ms  "
          f"speedup={speedup:5.2f}x  (median of {repeats})")
    return speedup


def main():
    rng = np.random.default_rng(42)

    print(f"Rust PARALLEL_THRESHOLD = {PARALLEL_THRESHOLD} elements\n")

    print("Case 1: Series numeric transform  x * 2 + 1  [native fast path, int64]")
    for n in N_ROWS_LIST:
        s = pd.Series(rng.integers(0, 1000, size=n))
        repeats = repeats_for(n)
        crosses = " <- crosses PARALLEL_THRESHOLD" if n >= PARALLEL_THRESHOLD else ""
        speedup = report(
            "",
            n,
            timed(lambda: s.apply(lambda x: x * 2 + 1), repeats),
            timed(lambda: s.turboply(lambda x: x * 2 + 1), repeats),
            repeats,
        )
        if crosses:
            print(f"    {n} elements >= threshold, Rust core uses rayon parallel iterator{crosses}")
    print()

    print("Case 2: DataFrame row-wise apply, axis=1  row['a'] + row['b']  [native fast path]")
    for n in N_ROWS_LIST:
        df = pd.DataFrame(
            {
                "a": rng.integers(0, 1000, size=n),
                "b": rng.integers(0, 1000, size=n),
            }
        )
        repeats = repeats_for(n)
        report(
            "",
            n,
            timed(lambda: df.apply(lambda row: row["a"] + row["b"], axis=1), repeats),
            timed(lambda: df.turboply(lambda row: row["a"] + row["b"], axis=1), repeats),
            repeats,
        )
    print()


if __name__ == "__main__":
    main()
