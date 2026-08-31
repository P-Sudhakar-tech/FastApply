"""Benchmark: plain pandas GroupBy.apply() vs .turbofastapply() for the new
threaded parallel fallback (P9, groupby_parallel.py).

    .venv/Scripts/python.exe examples/benchmark_groupby.py

Three cases, to show the tier is genuinely measured rather than assumed:
  1. A GIL-releasing per-group callable (simulated I/O via time.sleep) —
     the case this tier is built for. Should show a real speedup.
  2. A CPU-bound pure-Python per-group callable — the GIL prevents any
     benefit from threading here, and the sample-timing race should
     correctly decline to parallelize, landing at ~1.0x (no regression).
  3. A more realistic mixed callable (does real pandas/numpy work
     internally, which releases the GIL for its C-level portions, plus
     some Python-level custom logic) — closer to a real-world per-group
     transform than either pure synthetic case above.

Reported numbers use the median of several repeats with a warmup, same
methodology as examples/benchmark.py and benchmark_scale.py.
"""

import statistics
import time

import numpy as np
import pandas as pd

import turbofastapply  # noqa: F401  (registers the .turbofastapply accessor)

N_GROUPS = 1000  # comfortably above groupby_parallel.MIN_GROUPS (800) --
# below that threshold the parallel tier declines immediately (by
# design, see groupby_parallel.py) so there's nothing to demonstrate.
ROWS_PER_GROUP = 5
N_REPEATS = 8
N_WARMUP = 2


def timed(fn, repeats=N_REPEATS, warmup=N_WARMUP):
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return times


def report(label, pandas_times, turbofastapply_times):
    p_med = statistics.median(pandas_times) * 1000
    t_med = statistics.median(turbofastapply_times) * 1000
    speedup = p_med / t_med if t_med else float("inf")

    print(label)
    print(f"  pandas GroupBy.apply()  {p_med:8.4f} ms (median of {N_REPEATS})")
    print(f"  .turbofastapply()             {t_med:8.4f} ms (median of {N_REPEATS})")
    print(f"  speedup                 {speedup:.2f}x")
    print()
    return speedup


def make_df():
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "key": np.repeat(np.arange(N_GROUPS), ROWS_PER_GROUP),
            "value": rng.integers(0, 1000, size=N_GROUPS * ROWS_PER_GROUP),
        }
    )


def main():
    print(f"Benchmarking on {N_GROUPS} groups x {ROWS_PER_GROUP} rows/group, "
          f"{N_REPEATS} repeats per case (+{N_WARMUP} warmup)\n")

    df = make_df()

    # Case 1: GIL-releasing (simulated I/O per group).
    def gil_releasing(g):
        time.sleep(0.0005)
        return g["value"].sum()

    grouped = df.groupby("key")
    report(
        "Case 1: GIL-releasing callable (simulated I/O, time.sleep per group)",
        timed(lambda: grouped.apply(gil_releasing)),
        timed(lambda: grouped.turbofastapply(gil_releasing)),
    )

    # Case 2: CPU-bound pure Python (GIL held the whole time).
    def cpu_bound(g):
        total = 0
        for v in g["value"]:
            total += v * v
        return total

    report(
        "Case 2: CPU-bound pure-Python callable (no threading benefit expected)",
        timed(lambda: grouped.apply(cpu_bound)),
        timed(lambda: grouped.turbofastapply(cpu_bound)),
    )

    # Case 3: Mixed — real pandas/numpy work (releases GIL in spots) plus
    # custom Python logic, closer to a real per-group transform.
    def mixed(g, multiplier=1.0):
        s = g["value"]
        stats = pd.Series(
            {
                "mean": s.mean(),
                "std": s.std(ddof=0),
                "median": s.median(),
                "range": s.max() - s.min(),
            }
        )
        return stats * multiplier

    report(
        "Case 3: mixed callable (pandas/numpy stats + custom logic, extra kwarg)",
        timed(lambda: grouped.apply(mixed, 1.5)),
        timed(lambda: grouped.turbofastapply(mixed, 1.5)),
    )

    print(
        "Case 1 shows the real win this tier targets: a per-group callable that\n"
        "releases the GIL (I/O, sleep, many numpy/pandas C internals) benefits\n"
        "from genuine multi-threaded execution. Case 2 shows the race correctly\n"
        "declining to parallelize a pure-Python CPU-bound callable, landing at\n"
        "~1.0x rather than regressing. Case 3 is the more realistic middle case."
    )


if __name__ == "__main__":
    main()
