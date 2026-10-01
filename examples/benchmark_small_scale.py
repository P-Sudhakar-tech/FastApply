"""Benchmark: plain pandas .apply() vs .turbofastapply() in the small-data
range (50-5,000 rows) that the Post-P9 small-data optimization pass (see
claude.md) specifically targeted.

    .venv/Scripts/python.exe examples/benchmark_small_scale.py

`examples/benchmark_scale.py` covers 10,000-50,000 rows, where the fast
paths were never in question -- this script exists to make the 50-1,000
row regression-and-fix story in claude.md / README.md reproducible from
the repo itself, rather than only verifiable by installing
turbofastapply==0.1.0 from PyPI and diffing by hand. Re-run this after any
change to decide.py or decide_row.py to catch a regression in this range
before it ships.

Two cases, each eligible under the default engine="auto" once its own
MIN_ROWS is reached -- decide.py's is 50, decide_row.py's is 100 (lowered
from an interim 300 once decide_row.py's _RowView replaced real per-row
pandas Series construction with a lightweight dict stand-in, cutting the
fixed cost 3-4x):
  - numeric transform: x * 2 + 1        -> decide.py + Rust affine_i64
  - row-wise:          row['a']+row['b'] -> decide_row.py + Rust row_affine_f64
"""

import statistics
import time

import numpy as np
import pandas as pd

import turbofastapply  # noqa: F401  (registers the .turbofastapply accessor)

N_ROWS_LIST = [50, 100, 200, 300, 500, 1_000, 5_000]


def bench(f, repeats, warmup):
    for _ in range(warmup):
        f()
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        f()
        times.append(time.perf_counter() - t0)
    return statistics.median(times) * 1000


def main():
    print(f"Benchmarking the small-data range: {N_ROWS_LIST}\n")

    print("Case 1: Series numeric transform  x * 2 + 1  [native fast path, int64]")
    for n in N_ROWS_LIST:
        s = pd.Series(np.arange(n, dtype=np.int64))
        t_pandas = bench(lambda: s.apply(lambda x: x * 2 + 1), repeats=100, warmup=15)
        t_turbo = bench(lambda: s.turbofastapply(lambda x: x * 2 + 1), repeats=100, warmup=15)
        flag = "" if t_pandas / t_turbo >= 1.0 else "  <- regression"
        print(
            f"  n={n:5d}  pandas={t_pandas:8.4f} ms  turbofastapply={t_turbo:8.4f} ms  "
            f"speedup={t_pandas / t_turbo:6.2f}x{flag}"
        )

    print()
    print("Case 2: DataFrame row-wise apply, axis=1  row['a'] + row['b']  [native fast path]")
    for n in N_ROWS_LIST:
        df = pd.DataFrame({"a": np.arange(n, dtype=np.float64), "b": np.arange(n, dtype=np.float64)})
        t_pandas = bench(lambda: df.apply(lambda row: row["a"] + row["b"], axis=1), repeats=60, warmup=15)
        t_turbo = bench(
            lambda: df.turbofastapply(lambda row: row["a"] + row["b"], axis=1), repeats=60, warmup=15
        )
        flag = "" if t_pandas / t_turbo >= 0.85 else "  <- check: should be ~1.0x (declines) below MIN_ROWS=100, a win above it"
        print(
            f"  n={n:5d}  pandas={t_pandas:8.4f} ms  turbofastapply={t_turbo:8.4f} ms  "
            f"speedup={t_pandas / t_turbo:6.2f}x{flag}"
        )


if __name__ == "__main__":
    main()
