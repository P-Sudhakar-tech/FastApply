"""Standalone script to manually try out turboply.

Run it directly (no pytest needed) to see the package working end to end.
Requires the package to be built first (`maturin develop` or `./build.ps1`):

    .venv/Scripts/python.exe examples/quickstart.py

Every check prints PASS/FAIL and compares against plain pandas .apply() so
you can see for yourself that `s.turboply(func)` — the primary API, the
accessor is directly callable — is a correctness-safe drop-in replacement.
`.turboply.apply(func)` still works too, as an alias.
"""

import pandas as pd

import turboply


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

    # 1. Native extension loaded and callable.
    results.append(check("native extension loads", turboply.dummy_add(2, 3), 5))

    # 2. Series accessor: simple numeric transform.
    s = pd.Series([1, 2, 3, 4, 5])
    results.append(
        check(
            "series .turboply(func) matches pandas",
            s.turboply(lambda x: x * 2),
            s.apply(lambda x: x * 2),
        )
    )

    # 3. Series accessor: string transform.
    names = pd.Series(["ada", "grace", "margaret"])
    results.append(
        check(
            "series .turboply(func) (strings) matches pandas",
            names.turboply(str.title),
            names.apply(str.title),
        )
    )

    # 4. DataFrame accessor: column-wise apply (axis=0, the default).
    df = pd.DataFrame({"a": [1, 2, 3], "b": [10, 20, 30]})
    results.append(
        check(
            "dataframe .turboply(func) (axis=0) matches pandas",
            df.turboply(lambda col: col.sum()),
            df.apply(lambda col: col.sum()),
        )
    )

    # 5. DataFrame accessor: row-wise apply (axis=1).
    results.append(
        check(
            "dataframe .turboply(func) (axis=1) matches pandas",
            df.turboply(lambda row: row["a"] + row["b"], axis=1),
            df.apply(lambda row: row["a"] + row["b"], axis=1),
        )
    )

    # 6. Empty series edge case.
    empty = pd.Series([], dtype=float)
    results.append(
        check(
            "empty series fallback matches pandas",
            empty.turboply(lambda x: x),
            empty.apply(lambda x: x),
        )
    )

    # 7. .apply() still works as an alias for the direct-call form.
    results.append(
        check(
            ".turboply.apply(func) alias matches .turboply(func)",
            s.turboply.apply(lambda x: x * 2),
            s.turboply(lambda x: x * 2),
        )
    )

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
