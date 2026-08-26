"""Benchmark: pandas .apply() vs .turboply() vs swifter's .apply() on 1,000 rows.

Optional — requires swifter, which is NOT a package dependency (it pulls
in dask, tqdm, etc. that turboply itself has no use for):

    .venv/Scripts/python.exe -m pip install swifter
    .venv/Scripts/python.exe examples/benchmark_vs_competitor.py

Same methodology as examples/benchmark.py: warmup + median of many
repeats, since these calls run in well under a millisecond. See that
script for the plain pandas-vs-turboply comparison and for why only the
numeric-transform case is accelerated today.
"""

import statistics
import sys
import time

import numpy as np
import pandas as pd

import turboply  # noqa: F401  (registers the .turboply accessor)

try:
    import swifter  # noqa: F401  (registers the .swifter accessor)
except ImportError:
    print("swifter isn't installed - run: pip install swifter", file=sys.stderr)
    raise SystemExit(1)

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


def main():
    rng = np.random.default_rng(42)
    numbers = pd.Series(rng.integers(0, 1000, size=N_ROWS))
    func = lambda x: x * 2 + 1  # noqa: E731

    pandas_times = timed(lambda: numbers.apply(func))
    turboply_times = timed(lambda: numbers.turboply(func))
    try:
        swifter_times = timed(lambda: numbers.swifter.progress_bar(False).apply(func))
    except Exception as exc:
        print(
            f"swifter {getattr(swifter, '__version__', '?')} failed to run against "
            f"pandas {pd.__version__} / Python {sys.version.split()[0]}: {exc!r}\n\n"
            "This is a real compatibility gap in the swifter/dask dependency stack, "
            "not a turboply bug: swifter 1.4.0 calls a Series.apply() kwarg that "
            "pandas 3.x removed, and pinning pandas<2.0 to work around that just "
            "surfaces a separate dask-vs-Python-3.11 incompatibility instead. "
            "Getting a clean swifter install may require an older Python "
            "(e.g. 3.9/3.10) in a dedicated environment; that's outside what this "
            "repo's toolchain targets, so this comparison is left as opt-in rather "
            "than something CI runs.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    p_med = statistics.median(pandas_times) * 1000
    t_med = statistics.median(turboply_times) * 1000
    s_med = statistics.median(swifter_times) * 1000

    print(f"Series numeric transform: x * 2 + 1  ({N_ROWS} rows, median of {N_REPEATS})\n")
    print(f"  pandas .apply()  {p_med:8.4f} ms")
    print(f"  .turboply()      {t_med:8.4f} ms  ({p_med / t_med:.2f}x vs pandas)")
    print(f"  .swifter.apply() {s_med:8.4f} ms  ({p_med / s_med:.2f}x vs pandas)")
    print()
    print(
        "Architectural difference worth noting alongside the numbers above:\n"
        "swifter's dispatch goes through a dask-based sampling/vectorization\n"
        "layer built with much larger data in mind, while turboply's fast path\n"
        "is a single native vectorized call with no such framework overhead."
    )


if __name__ == "__main__":
    main()
