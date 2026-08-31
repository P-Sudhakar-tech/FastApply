//! `cargo bench` — Rust-level microbenchmarks for the pure compute cores
//! in src/core.rs, independent of the PyO3/Python marshaling overhead that
//! examples/benchmark.py measures end to end. Useful for catching a
//! regression in the Rust layer itself (e.g. an accidental loss of
//! parallelism, or a slower algorithm swapped in) without the Python
//! round-trip cost obscuring it.
//!
//! Run with: cargo bench
//! HTML reports land in target/criterion/report/index.html

use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion};
use regex::Regex;
// [lib].name in Cargo.toml is "_turbofastapply" (the Python extension module
// name), which is also the crate name benches import under — not the
// [package] name "turbofastapply".
use _turbofastapply::core;

fn bench_affine_f64(c: &mut Criterion) {
    let mut group = c.benchmark_group("affine_f64");
    for &n in &[1_000usize, 50_000, 200_000] {
        let data: Vec<f64> = (0..n).map(|i| i as f64).collect();
        group.bench_with_input(BenchmarkId::from_parameter(n), &data, |b, data| {
            b.iter(|| core::affine_f64(black_box(data), black_box(2.0), black_box(1.0)));
        });
    }
    group.finish();
}

fn bench_row_affine_f64(c: &mut Criterion) {
    let mut group = c.benchmark_group("row_affine_f64");
    for &n in &[1_000usize, 50_000, 200_000] {
        let a: Vec<f64> = (0..n).map(|i| i as f64).collect();
        let b: Vec<f64> = (0..n).map(|i| (n - i) as f64).collect();
        let columns = [a.as_slice(), b.as_slice()];
        group.bench_with_input(BenchmarkId::from_parameter(n), &columns, |bch, columns| {
            bch.iter(|| core::row_affine_f64(black_box(columns), black_box(&[1.0, 1.0]), black_box(0.0)));
        });
    }
    group.finish();
}

fn bench_str_upper(c: &mut Criterion) {
    let mut group = c.benchmark_group("str_upper");
    for &n in &[1_000usize, 50_000, 200_000] {
        let items: Vec<String> = (0..n).map(|i| format!("item_{i}_mixed_case")).collect();
        group.bench_with_input(BenchmarkId::from_parameter(n), &items, |b, items| {
            b.iter(|| core::str_upper(black_box(items)));
        });
    }
    group.finish();
}

fn bench_str_contains(c: &mut Criterion) {
    let mut group = c.benchmark_group("str_contains");
    let re = Regex::new(r"item_\d*5_").unwrap();
    for &n in &[1_000usize, 50_000, 200_000] {
        let items: Vec<String> = (0..n).map(|i| format!("item_{i}_mixed_case")).collect();
        group.bench_with_input(BenchmarkId::from_parameter(n), &items, |b, items| {
            b.iter(|| core::str_contains(black_box(items), black_box(&re)));
        });
    }
    group.finish();
}

criterion_group!(benches, bench_affine_f64, bench_row_affine_f64, bench_str_upper, bench_str_contains);
criterion_main!(benches);
