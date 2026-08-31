"""Benchmark: plain pandas .apply() vs .turbofastapply() on 1,000 rows.

    .venv/Scripts/python.exe examples/benchmark.py

Two cases below are routed through a genuine native fast path under the
default engine="auto":
  - numeric transform -> decide.py + Rust affine_i64/f64, abs_i64/f64 (P2)
  - row['a'] + row['b'] -> decide_row.py + Rust row_affine_f64, the
    multivariate generalization of the same affine trick (P5)

A third case, str.upper (P4, decide_str.py + Rust str_upper — an
identity-whitelist match verified against a sample), is included too,
run two ways: under the default engine="auto" (falls back to plain
pandas — matches it, no speedup expected) and forced via engine="native"
(shows the actual native-path numbers). This isn't an oversight: string
data has to be copied into owned Rust Strings on the way in and new
Python str objects on the way out, unlike the numeric/row-wise paths'
genuine zero-copy numpy views, and that round-trip was benchmarked
(500 to 1,000,000 rows, this repo's git history) to consistently cost
more than it saves. So "auto" deliberately never picks it — see
accessor.py's module docstring and claude.md for the full writeup. The
numbers below demonstrate exactly that, rather than asserting it.

Arbitrary callables that don't match a native pattern get a
sampling-based threaded fallback (P3) instead of a straight serial loop,
when a sample measurement shows it's actually faster.

`s.turbofastapply(func)` is the primary API (the accessor is directly callable);
`.apply()` still works as an alias.

Reported numbers use the median of many repeats with a warmup, since these
calls run in well under a millisecond and a plain mean is dominated by OS
scheduling noise at that scale.
"""

import statistics
import time

import numpy as np
import pandas as pd

import turbofastapply  # noqa: F401  (registers the .turbofastapply accessor)

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


def report(label, pandas_times, turbofastapply_times):
    p_med = statistics.median(pandas_times) * 1000
    t_med = statistics.median(turbofastapply_times) * 1000
    speedup = p_med / t_med if t_med else float("inf")

    print(label)
    print(f"  pandas .apply()  {p_med:8.4f} ms (median of {N_REPEATS})")
    print(f"  .turbofastapply()      {t_med:8.4f} ms (median of {N_REPEATS})")
    print(f"  speedup          {speedup:.2f}x")
    print()


def main():
    rng = np.random.default_rng(42)
    df = pd.DataFrame(
        {
            "a": rng.integers(0, 1000, size=N_ROWS),
            "b": rng.integers(0, 1000, size=N_ROWS),
            "name": [f"item_{i}" for i in range(N_ROWS)],
        }
    )

    print(f"Benchmarking on {N_ROWS} rows, {N_REPEATS} repeats per case (+{N_WARMUP} warmup)\n")

    numbers = df["a"]
    report(
        "Series numeric transform: x * 2 + 1  [native fast path, int64]",
        timed(lambda: numbers.apply(lambda x: x * 2 + 1)),
        timed(lambda: numbers.turbofastapply(lambda x: x * 2 + 1)),
    )

    report(
        "DataFrame row-wise apply, axis=1: row['a'] + row['b']  [native fast path, Phase 5]",
        timed(lambda: df.apply(lambda row: row["a"] + row["b"], axis=1)),
        timed(lambda: df.turbofastapply(lambda row: row["a"] + row["b"], axis=1)),
    )

    names = df["name"]
    report(
        "Series string transform: str.upper, engine='auto'  [never native, by design]",
        timed(lambda: names.apply(str.upper)),
        timed(lambda: names.turbofastapply(str.upper)),
    )
    report(
        "Series string transform: str.upper, engine='native'  [forced, see caveat above]",
        timed(lambda: names.apply(str.upper)),
        timed(lambda: names.turbofastapply(str.upper, engine="native")),
    )

    print(
        "Numeric and row-wise cases get a genuine native speedup under the\n"
        "default engine='auto'. The string case is included specifically to\n"
        "show why it doesn't: 'auto' matches plain pandas exactly (correct\n"
        "fallback, no regression), while forcing engine='native' shows the\n"
        "measured slowdown that 'auto' avoids picking automatically."
    )


if __name__ == "__main__":
    main()
