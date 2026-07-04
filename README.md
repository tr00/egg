# egg (stochastic fork)

This is a research fork of [egg](https://github.com/egraphs-good/egg), a Rust library for **e-graphs** and **equality saturation** originally created by [Max Willsey](https://mwillsey.com/) et al. ([POPL 2021 paper](https://doi.org/10.1145/3434304)). The fork extends egg with **stochastic rewriting** and **destructive deletion**, presented at the [EGRAPHS workshop at PLDI 2025](https://pldi25.sigplan.org/details/egraphs-2025-papers/7/Destructive-E-Graph-Rewrites).

## What is different from upstream egg

Standard equality saturation applies every matching rewrite unconditionally, which can cause the e-graph to grow explosively with low-quality terms. This fork adds two mechanisms to control that:

**Stochastic rewriting.** A `StochasticApplier` wraps any inner applier and gates it through a Metropolis-Hastings accept/reject step backed by a `WeightedCost` analysis. Cost-improving rewrites are always accepted; cost-worsening rewrites are accepted with probability exp(-delta_cost / temperature). The temperature is a single `f64` shared across all rules, which you can decay per iteration via `Runner::with_hook` to implement simulated annealing.

**Destructive deletion.** A `RemoveApplier` removes the matched top e-node from its e-class (instead of adding a new one), provided the e-class would still have at least one ground term afterward. When combined with `StochasticApplier::new_remove`, worse representatives are pruned probabilistically. This keeps the e-graph compact without losing the best expressions.

Together, these let equality saturation explore a much larger rewrite budget without blowing up.

## Using egg

Add `egg` to your `Cargo.toml`:

```toml
[dependencies]
egg = "0.11.0"
```

Make sure to compile with `--release` if you are measuring performance.

## Quick example: stochastic rewriting

Define a language, a cost function, and wrap your rewrites with `StochasticApplier`:

```rust
use egg::*;

define_language! {
    enum Arith {
        Num(i32),
        "+" = Add([Id; 2]),
        "*" = Mul([Id; 2]),
        Symbol(Symbol),
    }
}

// Cost function: prefer multiplications over additions.
fn weight(enode: &Arith) -> f64 {
    match enode {
        Arith::Add(_) => 3.0,
        Arith::Mul(_) => 1.0,
        _ => 1.0,
    }
}

// Helper: build a stochastic rewrite from pattern strings.
fn sr(name: &str, lhs: &str, rhs: &str) -> Rewrite<Arith, WeightedCost<Arith>> {
    let searcher: Pattern<Arith> = lhs.parse().unwrap();
    let applier: Pattern<Arith> = rhs.parse().unwrap();
    Rewrite::new(name, searcher, StochasticApplier::from_pattern(applier)).unwrap()
}

let rules = vec![
    sr("commute-add", "(+ ?a ?b)", "(+ ?b ?a)"),
    sr("commute-mul", "(* ?a ?b)", "(* ?b ?a)"),
    sr("add-0",       "(+ ?a 0)",  "?a"),
    sr("mul-0",       "(* ?a 0)",  "0"),
    sr("mul-1",       "(* ?a 1)",  "?a"),
];

let cost_fn = WeightedCost::new(weight);
let runner = Runner::<Arith, WeightedCost<Arith>>::new(cost_fn)
    .with_expr(&"(* (+ 0 a) 1)".parse().unwrap())
    .with_iter_limit(30)
    .with_node_limit(100_000)
    .run(&rules);

let extractor = Extractor::new(&runner.egraph, AstSize);
let (cost, best) = extractor.find_best(runner.roots[0]);
println!("Cost {cost}: {best}");
```

## Destructive deletion

Use `RemoveApplier` to remove a matched e-node from the e-graph. Use `StochasticApplier::new_remove` to combine removal with the stochastic cost gate:

```rust
use egg::*;

// Remove the matched e-node if the e-class still has a ground term.
let searcher: Pattern<Arith> = "(+ ?a ?b)".parse().unwrap();
let applier = RemoveApplier::new("(+ ?a ?b)".parse().unwrap());
let rw = Rewrite::new("remove-add", searcher, applier).unwrap();
```

For stochastic removal (only remove probabilistically, based on cost):

```rust
// MultiPattern: find e-classes that contain both LHS and RHS.
let x: Var = "?x".parse().unwrap();
let lhs: Pattern<Arith> = "(+ ?a ?b)".parse().unwrap();
let rhs: Pattern<Arith> = "(+ ?b ?a)".parse().unwrap();
let searcher = MultiPattern::new(vec![(x, lhs.ast.clone()), (x, rhs.ast.clone())]);
let applier = StochasticApplier::new_remove(lhs.clone(), RemoveApplier::new(lhs));
let rw = Rewrite::new("commute-add-remove", searcher, applier).unwrap();
```

## Stochastic parameters

The stochastic rewriting system has a small set of tunable parameters:

### `WeightedCost` analysis parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `weight` | `Box<dyn Fn(&L) -> f64>` | *(required)* | Per-operator cost function. The analysis computes total cost bottom-up as `weight(enode) + sum(child costs)`. Higher-weight operators are more expensive; the e-graph always tracks the cheapest representative per e-class. |
| `temperature` | `f64` | `1.0` | Global temperature for the Metropolis-Hastings acceptance gate. Shared across all stochastic rules. Set initially via `WeightedCost::new(...).with_temperature(T)`, or mutate directly on `runner.egraph.analysis.temperature` for annealing schedules. |

### `StochasticApplier` parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `pattern` | `Pattern<L>` | *(required)* | The pattern used for cost-checking. Instantiated against the e-graph to compute the candidate cost (`pat_cost`) before deciding whether to apply. |
| `inner` | `A: Applier` | *(required)* | The inner applier that performs the actual application (union, removal, etc.) when the cost gate passes. Defaults to a `Pattern<L>` when constructed with `from_pattern`. Can be any `Applier`, including `ConditionalApplier` or `RemoveApplier`. |
| `direction` | `StochasticDirection` | `Add` | Controls the acceptance formula. See below. |

### `StochasticDirection`

The direction controls how the cost delta is interpreted:

- **`Add`** (standard Metropolis-Hastings): Accept cost-neutral or cost-improving moves always (probability 1.0). Accept cost-worsening moves with probability `exp(-delta_cost / temperature)` where `delta_cost = pat_cost - eclass_cost`.
- **`Remove`** (complement): Keep the best expression in the e-class (probability 0 when `delta_cost <= 0`). Remove worse expressions with probability `1 - exp(-delta_cost / temperature)` where `delta_cost = pat_cost - eclass_cost >= 0`.

### Cooling schedule

The temperature does not decay automatically. You control it via `Runner::with_hook`, which runs at the start of every iteration before rewrites. A geometric decay `T *= alpha` (with `alpha` in `(0, 1)`, e.g. `0.95`) is the simplest effective schedule. At high temperature the search is exploratory (accepts cost-worsening moves freely); as it cools, only improving moves survive.

```rust
let cost_fn = WeightedCost::new(weight).with_temperature(10.0);
let runner = Runner::<Arith, WeightedCost<Arith>>::new(cost_fn)
    .with_expr(&start_expr)
    .with_hook(|runner| {
        runner.egraph.analysis.temperature *= 0.95;
        // Optionally log progress each iteration:
        runner.egraph.analysis.log_progress(&runner.egraph, runner.roots[0]);
        Ok(())
    })
    .run(&rules);
```

### `RemoveApplier` parameters

| Parameter | Type | Description |
|---|---|---|
| `pat` | `Pattern<L>` | The pattern whose top e-node will be removed from the e-graph. Must match the searcher pattern for correct substitution. |

`RemoveApplier` only removes the e-node if the e-class would still have at least one ground term afterward, so the e-graph always remains well-formed.

## Resources

- [egg website](https://egraphs-good.github.io/)
- [egg tutorial](https://docs.rs/egg/latest/egg/tutorials/)
- [API docs](https://docs.rs/egg/)
- [egg POPL 2021 paper](https://doi.org/10.1145/3434304) (Max Willsey et al.)
- [Destructive E-Graph Rewrites, EGRAPHS 2025](https://pldi25.sigplan.org/details/egraphs-2025-papers/7/Destructive-E-Graph-Rewrites)
- [egglog](https://github.com/egraphs-good/egglog) -- a Datalog-based successor with [paper](https://mwillsey.com/papers/egglog) and [web demo](https://egraphs-good.github.io/egglog)

## Developing

It's written in [Rust](https://www.rust-lang.org/).
Install Rust using [`rustup`](https://www.rust-lang.org/tools/install).

Run `cargo doc --open` to build and open the documentation in a browser.

Before committing/pushing, make sure to run `make`,
which runs all the tests and lints that CI will (including those under feature flags).
This requires the [`cbc`](https://projects.coin-or.org/Cbc) solver
due to the `lp` feature.

### Tests

Running `cargo test` will run the tests.
Some tests may time out; try `cargo test --release` if that happens.

Interesting tests in the `tests` directory:

- `stochastic.rs` -- stochastic rewriting and simulated annealing tests.
- `prop.rs` -- propositional logic proofs.
- `math.rs` -- real arithmetic with symbolic differentiation.
- `lambda.rs` -- lambda calculus partial evaluation.

### Benchmarking

Set `EGG_BENCH_CSV` to append a CSV row per test:

```bash
EGG_BENCH_CSV=math.csv cargo test --test math --release -- --nocapture --test --test-threads=1
```

### Feature flags

| Flag | Effect |
|---|---|
| `lp` | ILP-based extraction via `good_lp` (needs system `cbc` solver) |
| `serde-1` | Serialize/Deserialize for core types |
| `reports` | JSON report output (implies `serde-1`) |
| `deterministic` | Forces `IndexMap` over `HashMap` for reproducible iteration |
| `wasm-bindgen` | WASM compatibility shim |

## Future Work

- Currently, when a destructive rewrite is applied, we only support removing the
  corresponding e-node from the e-graph. This means that unrelated terms may be
  affected. Ideally a destructive rewrite would only remove terms that are
  directly involved. This would probably require more information in the
  e-graph, e.g. tracking the origin of each term. `egg` contains a second
  e-graph for explanations which apparently has this information.
- [`egglog`](https://github.com/egraphs-good/egglog) has a `delete` function.
- Destructive rewrites could take cost information into account to prioritize
  rewrites.
- Prof. Pavel Panchekha (from a discussion at PLDI 2025):
  - Try removing nodes older than a certain number of iterations.
  - Extracting is `(egraph -> term)`, while destructive rewrites are
    `(egraph -> egraph)`. Can be thought of as garbage collection.
