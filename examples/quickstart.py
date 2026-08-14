"""Standalone script to manually try out turboply.

Run it directly (no pytest needed) to see the package working end to end:

    $env:PYTHONPATH = "python"          # PowerShell, from the repo root
    .venv/Scripts/python.exe examples/quickstart.py

Every check prints PASS/FAIL and compares against plain pandas .apply() so
you can see for yourself that the .turboply accessor is a correctness-safe
drop-in replacement.
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
            "series .turboply.apply matches pandas",
            s.turboply.apply(lambda x: x * 2),
            s.apply(lambda x: x * 2),
        )
    )

    # 3. Series accessor: string transform.
    names = pd.Series(["ada", "grace", "margaret"])
    results.append(
        check(
            "series .turboply.apply (strings) matches pandas",
            names.turboply.apply(str.title),
            names.apply(str.title),
        )
    )

    # 4. DataFrame accessor: column-wise apply (axis=0, the default).
    df = pd.DataFrame({"a": [1, 2, 3], "b": [10, 20, 30]})
    results.append(
        check(
            "dataframe .turboply.apply (axis=0) matches pandas",
            df.turboply.apply(lambda col: col.sum()),
            df.apply(lambda col: col.sum()),
        )
    )

    # 5. DataFrame accessor: row-wise apply (axis=1).
    results.append(
        check(
            "dataframe .turboply.apply (axis=1) matches pandas",
            df.turboply.apply(lambda row: row["a"] + row["b"], axis=1),
            df.apply(lambda row: row["a"] + row["b"], axis=1),
        )
    )

    # 6. Empty series edge case.
    empty = pd.Series([], dtype=float)
    results.append(
        check(
            "empty series fallback matches pandas",
            empty.turboply.apply(lambda x: x),
            empty.apply(lambda x: x),
        )
    )

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
