"""Standalone script to manually try out turbofastapply.

Run it directly (no pytest needed) to see the package working end to end.
Requires the package to be built first (`maturin develop` or `./build.ps1`):

    .venv/Scripts/python.exe examples/quickstart.py

Every check prints PASS/FAIL and compares against plain pandas .apply() so
you can see for yourself that `s.turbofastapply(func)` — the primary API, the
accessor is directly callable — is a correctness-safe drop-in replacement.
`.turbofastapply.apply(func)` still works too, as an alias.

Also demonstrates the engine/verbose/progress_bar options: engine="pandas"
forces the fallback, engine="native" requires the fast path and raises
with a specific reason if the callable isn't eligible, verbose=True prints
the routing decision, and progress_bar=True reports progress for the
pandas fallback path (the native path is a single vectorized call, so
there's nothing to report progress on there).
"""

import pandas as pd

import turbofastapply


def check(label, got, expected):
    ok = got == expected if not hasattr(got, "equals") else got.equals(expected)
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}")
    if not ok:
        print(f"    got:      {got!r}")
        print(f"    expected: {expected!r}")
    return ok


def main():
    results = []

    # 1. Series accessor: simple numeric transform.
    s = pd.Series([1, 2, 3, 4, 5])
    results.append(
        check(
            "series .turbofastapply(func) matches pandas",
            s.turbofastapply(lambda x: x * 2),
            s.apply(lambda x: x * 2),
        )
    )

    # 2. Series accessor: string transform (small series, plain fallback).
    names = pd.Series(["ada", "grace", "margaret"])
    results.append(
        check(
            "series .turbofastapply(func) (strings) matches pandas",
            names.turbofastapply(str.title),
            names.apply(str.title),
        )
    )

    # 2b. Whitelisted string method, explicitly forced to the native path
    #     (engine="native"). Note this is NOT what engine="auto"/the
    #     default does for strings: benchmarking found the native string
    #     path is consistently ~0.6-0.8x plain pandas at every scale
    #     tested (500 to 1,000,000 rows) due to owned-String FFI
    #     round-trip costs, so "auto" never picks it — see accessor.py's
    #     module docstring and claude.md for the numbers. engine="native"
    #     still verifies correctness against pandas on a sample the same
    #     way; it just doesn't imply a performance win the way the
    #     numeric/row-wise fast paths do.
    many_names = pd.Series(["  Ada  ", "GRACE", "margaret"] * 50)
    results.append(
        check(
            "series .turbofastapply(str.upper, engine='native') matches pandas",
            many_names.turbofastapply(str.upper, engine="native"),
            many_names.apply(str.upper),
        )
    )

    # 2c. .turbofastapply.str mirrors pandas' own .str accessor for the two
    #     regex ops that need arguments (contains/replace). Same
    #     performance caveat as 3b applies here too.
    results.append(
        check(
            ".turbofastapply.str.contains matches pandas",
            many_names.turbofastapply.str.contains("GRACE"),
            many_names.str.contains("GRACE", regex=True),
        )
    )
    results.append(
        check(
            ".turbofastapply.str.replace matches pandas",
            many_names.turbofastapply.str.replace(r"\s+", "_"),
            many_names.str.replace(r"\s+", "_", regex=True),
        )
    )

    # 3. DataFrame accessor: column-wise apply (axis=0, the default).
    df = pd.DataFrame({"a": [1, 2, 3], "b": [10, 20, 30]})
    results.append(
        check(
            "dataframe .turbofastapply(func) (axis=0) matches pandas",
            df.turbofastapply(lambda col: col.sum()),
            df.apply(lambda col: col.sum()),
        )
    )

    # 4. DataFrame accessor: row-wise apply (axis=1).
    results.append(
        check(
            "dataframe .turbofastapply(func) (axis=1) matches pandas",
            df.turbofastapply(lambda row: row["a"] + row["b"], axis=1),
            df.apply(lambda row: row["a"] + row["b"], axis=1),
        )
    )

    # 5. Empty series edge case.
    empty = pd.Series([], dtype=float)
    results.append(
        check(
            "empty series fallback matches pandas",
            empty.turbofastapply(lambda x: x),
            empty.apply(lambda x: x),
        )
    )

    # 6. .apply() still works as an alias for the direct-call form.
    results.append(
        check(
            ".turbofastapply.apply(func) alias matches .turbofastapply(func)",
            s.turbofastapply.apply(lambda x: x * 2),
            s.turbofastapply(lambda x: x * 2),
        )
    )

    # 7. engine="pandas" forces the fallback path even when eligible.
    large = pd.Series(range(100))
    results.append(
        check(
            "engine='pandas' matches plain pandas",
            large.turbofastapply(lambda x: x * 2, engine="pandas"),
            large.apply(lambda x: x * 2),
        )
    )

    # 8. engine="native" raises with a clear reason instead of silently
    #    falling back, when the callable isn't fast-path eligible.
    try:
        large.turbofastapply(lambda x: x**2, engine="native")
        results.append(check("engine='native' raises on ineligible func", False, True))
    except ValueError as exc:
        results.append(check(f"engine='native' raises: {exc}", True, True))

    # 9. verbose=True explains the routing decision (see stderr).
    print("\n[verbose demo - routing explanation printed to stderr below]")
    large.turbofastapply(lambda x: x * 2 + 1, verbose=True)

    # 10. progress_bar=True reports progress for the pandas fallback path.
    print("\n[progress_bar demo - bar printed to stderr below]")
    large.turbofastapply(lambda x: x**2, progress_bar=True)
    print()

    # 11. .groupby(...).turbofastapply(func) — correctness-only passthrough to
    #     GroupBy.apply() (no native fast path for GroupBy yet).
    grouped = df.groupby("a")
    results.append(
        check(
            "groupby .turbofastapply(func) matches GroupBy.apply(func)",
            grouped.turbofastapply(lambda g: g["b"].sum(), include_groups=False),
            grouped.apply(lambda g: g["b"].sum(), include_groups=False),
        )
    )

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
