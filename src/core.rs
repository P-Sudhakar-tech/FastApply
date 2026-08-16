//! Pure, PyO3-independent compute cores. No Python types appear here on
//! purpose: the `#[pyfunction]` wrappers in lib.rs marshal to/from Python
//! and delegate the actual elementwise work to these functions, which can
//! then be called directly from `cargo bench` (benches/native_benches.rs)
//! without embedding a Python interpreter, and unit-tested with plain
//! `cargo test` — neither of which would be straightforward against the
//! PyO3-typed functions directly, since those need an active GIL token.

use rayon::prelude::*;
use regex::Regex;

/// Below this length, rayon's work-splitting/join overhead costs more than
/// a plain sequential loop saves — so we only parallelize past it.
pub const PARALLEL_THRESHOLD: usize = 50_000;

macro_rules! elementwise {
    ($slice:expr, $threshold:expr, $f:expr) => {
        if $slice.len() >= $threshold {
            $slice.par_iter().map($f).collect()
        } else {
            $slice.iter().map($f).collect()
        }
    };
}

pub fn affine_f64(slice: &[f64], a: f64, b: f64) -> Vec<f64> {
    elementwise!(slice, PARALLEL_THRESHOLD, |&x| a * x + b)
}

pub fn affine_i64(slice: &[i64], a: i64, b: i64) -> Vec<i64> {
    elementwise!(slice, PARALLEL_THRESHOLD, |&x| a.wrapping_mul(x).wrapping_add(b))
}

pub fn abs_f64(slice: &[f64]) -> Vec<f64> {
    elementwise!(slice, PARALLEL_THRESHOLD, |&x: &f64| x.abs())
}

pub fn abs_i64(slice: &[i64]) -> Vec<i64> {
    elementwise!(slice, PARALLEL_THRESHOLD, |&x: &i64| x.wrapping_abs())
}

pub fn str_upper(items: &[String]) -> Vec<String> {
    elementwise!(items, PARALLEL_THRESHOLD, |s: &String| s.to_uppercase())
}

pub fn str_lower(items: &[String]) -> Vec<String> {
    elementwise!(items, PARALLEL_THRESHOLD, |s: &String| s.to_lowercase())
}

pub fn str_strip(items: &[String]) -> Vec<String> {
    elementwise!(items, PARALLEL_THRESHOLD, |s: &String| s.trim().to_string())
}

pub fn str_contains(items: &[String], re: &Regex) -> Vec<bool> {
    elementwise!(items, PARALLEL_THRESHOLD, |s: &String| re.is_match(s))
}

pub fn str_replace(items: &[String], re: &Regex, repl: &str) -> Vec<String> {
    elementwise!(items, PARALLEL_THRESHOLD, |s: &String| re
        .replace_all(s, repl)
        .into_owned())
}

/// Row-wise `sum(coeffs[i] * columns[i][row]) + intercept`. `columns` is a
/// struct-of-arrays layout — one slice per DataFrame column rather than an
/// array-of-rows — so each column stays a contiguous view with no
/// transposition needed.
pub fn row_affine_f64(columns: &[&[f64]], coeffs: &[f64], intercept: f64) -> Vec<f64> {
    let n = columns.first().map(|s| s.len()).unwrap_or(0);
    let compute = |i: usize| -> f64 {
        columns
            .iter()
            .zip(coeffs.iter())
            .fold(intercept, |acc, (col, &c)| acc + c * col[i])
    };
    if n >= PARALLEL_THRESHOLD {
        (0..n).into_par_iter().map(compute).collect()
    } else {
        (0..n).map(compute).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn affine_f64_matches_expected() {
        assert_eq!(affine_f64(&[0.0, 1.0, 2.0], 2.0, 1.0), vec![1.0, 3.0, 5.0]);
    }

    #[test]
    fn affine_i64_wraps_on_overflow_rather_than_panicking() {
        let out = affine_i64(&[i64::MAX], 2, 0);
        assert_eq!(out.len(), 1); // must not panic
    }

    #[test]
    fn abs_f64_matches_expected() {
        assert_eq!(abs_f64(&[-1.5, 0.0, 2.5]), vec![1.5, 0.0, 2.5]);
    }

    #[test]
    fn str_upper_matches_expected() {
        assert_eq!(str_upper(&["ada".to_string(), "Grace".to_string()]), vec!["ADA", "GRACE"]);
    }

    #[test]
    fn row_affine_f64_matches_expected() {
        let a = vec![1.0, 2.0, 3.0];
        let b = vec![10.0, 20.0, 30.0];
        let out = row_affine_f64(&[&a, &b], &[1.0, 1.0], 0.0);
        assert_eq!(out, vec![11.0, 22.0, 33.0]);
    }

    #[test]
    fn parallel_and_sequential_paths_agree_past_threshold() {
        let n = PARALLEL_THRESHOLD + 10;
        let data: Vec<f64> = (0..n).map(|i| i as f64).collect();
        let out = affine_f64(&data, 2.0, 1.0);
        assert_eq!(out[0], 1.0);
        assert_eq!(out[n - 1], 2.0 * (n - 1) as f64 + 1.0);
        assert_eq!(out.len(), n);
    }
}
