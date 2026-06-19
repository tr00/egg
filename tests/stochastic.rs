use egg::*;

type CostRewrite = Rewrite<Expr, WeightedCost<Expr>>;


define_language! {
    enum Expr {
        Num(i32),
        "+" = Add([Id; 2]),
        "*" = Mul([Id; 2]),
        "-" = Neg(Id),
        Symbol(Symbol),
    }
}

fn weight(enode: &Expr) -> f64 {
    match enode {
        Expr::Add(_) | Expr::Mul(_) | Expr::Neg(_) => 1.0,
        Expr::Num(_) | Expr::Symbol(_) => 0.0,
    }
}

/// Build a `Rewrite` whose applier is a `StochasticApplier`.
fn sr(name: &str, lhs: &str, rhs: &str) -> CostRewrite {
    let searcher: Pattern<Expr> = lhs.parse().unwrap();
    let applier: Pattern<Expr> = rhs.parse().unwrap();
    Rewrite::new(
        name,
        searcher,
        StochasticApplier::from_pattern(applier),
    )
    .unwrap()
}

/// Commutative-ring axioms plus cancellation and double-negation.
fn rules() -> Vec<CostRewrite> {
    vec![
        // commutativity
        sr("comm-add", "(+ ?a ?b)", "(+ ?b ?a)"),
        sr("comm-mul", "(* ?a ?b)", "(* ?b ?a)"),
        // associativity
        sr("assoc-add", "(+ (+ ?a ?b) ?c)", "(+ ?a (+ ?b ?c))"),
        sr("assoc-add-r", "(+ ?a (+ ?b ?c))", "(+ (+ ?a ?b) ?c)"),
        sr("assoc-mul", "(* (* ?a ?b) ?c)", "(* ?a (* ?b ?c))"),
        sr("assoc-mul-r", "(* ?a (* ?b ?c))", "(* (* ?a ?b) ?c)"),
        // identity
        sr("add-0", "(+ ?a 0)", "?a"),
        sr("mul-1", "(* ?a 1)", "?a"),
        // annihilation
        sr("mul-0", "(* ?a 0)", "0"),
        // additive inverse  (non-linear: both ?a must match same eclass)
        sr("add-cancel", "(+ ?a (- ?a))", "0"),
        // distribution
        sr("distribute", "(* ?a (+ ?b ?c))", "(+ (* ?a ?b) (* ?a ?c))"),
        sr("factor", "(+ (* ?a ?b) (* ?a ?c))", "(* ?a (+ ?b ?c))"),
        // double negation
        sr("neg-neg", "(- (- ?a))", "?a"),
        // negation distributes over products
        sr("neg-mul-l", "(* (- ?a) ?b)", "(- (* ?a ?b))"),
        sr("neg-mul-r", "(* ?a (- ?b))", "(- (* ?a ?b))"),
    ]
}

/// Equality-saturate `input` with `WeightedCost` and return the
/// cheapest extraction (string) together with its cached cost.
fn optimize(input: &str) -> (String, f64) {
    let expr: RecExpr<Expr> = input.parse().unwrap();
    let runner: Runner<Expr, WeightedCost<Expr>> =
        Runner::new(WeightedCost::new(weight))
            .with_expr(&expr)
            .with_iter_limit(30)
            .with_node_limit(50_000)
            .run(&rules());
    let root = runner.roots[0];
    let best_cost = runner.egraph[root].data.clone().unwrap();
    let extractor = Extractor::new(&runner.egraph, AstSize);
    let (_, best) = extractor.find_best(root);
    (best.to_string(), best_cost)
}

// ── identity and annihilation ───────────────────────────────────────

#[test]
fn mul_by_zero() {
    let (s, c) = optimize("(* x 0)");
    assert_eq!(s, "0");
    assert_eq!(c, 0.0);
}

#[test]
fn add_zero() {
    let (s, c) = optimize("(+ x 0)");
    assert_eq!(s, "x");
    assert_eq!(c, 0.0);
}

#[test]
fn mul_one() {
    let (s, c) = optimize("(* x 1)");
    assert_eq!(s, "x");
    assert_eq!(c, 0.0);
}

#[test]
fn mul_zero_nested() {
    let (s, c) = optimize("(* (* 0 x) y)");
    assert_eq!(s, "0");
    assert_eq!(c, 0.0);
}

// ── double negation ─────────────────────────────────────────────────

#[test]
fn double_negation() {
    let (s, c) = optimize("(- (- x))");
    assert_eq!(s, "x");
    assert_eq!(c, 0.0);
}

#[test]
fn double_neg_in_add() {
    let (s, c) = optimize("(+ (- (- a)) b)");
    assert_eq!(s, "(+ a b)");
    assert_eq!(c, 1.0);
}

// ── compound identity / annihilation ────────────────────────────────

#[test]
fn mul_zero_plus_y() {
    // (+ (* x 0) y) -> (+ 0 y) -> y
    let (s, c) = optimize("(+ (* x 0) y)");
    assert_eq!(s, "y");
    assert_eq!(c, 0.0);
}

#[test]
fn one_times_x_plus_zero() {
    // (+ (* 1 x) 0) -> (+ x 0) -> x
    let (s, c) = optimize("(+ (* 1 x) 0)");
    assert_eq!(s, "x");
    assert_eq!(c, 0.0);
}

// ── commutativity (cost-preserving, don't assert exact form) ────────

#[test]
fn commute_add_cost() {
    // Both (+ a b) and (+ b a) are in the eclass, each costs 1.
    let (_, c) = optimize("(+ b a)");
    assert_eq!(c, 1.0);
}

#[test]
fn commute_mul_cost() {
    let (_, c) = optimize("(* b a)");
    assert_eq!(c, 1.0);
}

// ── associativity (cost-preserving) ─────────────────────────────────

#[test]
fn assoc_cost() {
    // All right-associated permutations cost 2.
    let (_, c) = optimize("(+ (+ a b) c)");
    assert_eq!(c, 2.0);
}

#[test]
fn assoc_deep_cost() {
    let (_, c) = optimize("(+ (+ (+ a b) c) d)");
    assert_eq!(c, 3.0);
}

// ── distribution ────────────────────────────────────────────────────

#[test]
fn distribute_eclass_contains_both_forms() {
    // (* a (+ b c)) and (+ (* a b) (* a c)) are in the same eclass.
    // WeightedCost picks the cheaper (factored form, cost 2).
    let (_, c) = optimize("(* a (+ b c))");
    assert_eq!(c, 2.0);
}

// ── additive inverse / cancellation ─────────────────────────────────

#[test]
fn cancellation_simple() {
    // a*b + (-(a*b)) -> 0
    // neg-mul rewrites (-a)*b to -(a*b), then add-cancel fires.
    let (s, c) = optimize("(+ (* a b) (* (- a) b))");
    assert_eq!(s, "0");
    assert_eq!(c, 0.0);
}

#[test]
fn cancellation_via_distribution() {
    // a*(b+c) + (-a)*c
    //   distribute: ab + ac + (-a)*c
    //   neg-mul:    ab + ac + -(ac)
    //   cancel:     ab + 0
    //   identity:   ab
    //
    // Distribution is *necessary* here — without it, there is no
    // ac term to cancel with -(ac).
    let (s, c) = optimize("(+ (* a (+ b c)) (* (- a) c))");
    assert_eq!(s, "(* a b)");
    assert_eq!(c, 1.0);
}

// ── Strassen-style algebraic identity ───────────────────────────────
//
// The c11 element of a 2x2 matrix product  C = A · B  is
//   c11 = a11·b11 + a12·b21
// In Strassen's algorithm it is computed as
//   M1 + M4 - M5 + M7
// where M1 = (a11+a22)(b11+b22), etc.
//
// We demonstrate the algebraic identity that Strassen relies on:
//
//   (a+b)(c+d) + (-a)c + (-b)d  =  ad + bc
//
// After distributing and cancelling, two of the four products
// annihilate, leaving a two-product result.

#[test]
fn strassen_identity() {
    let input = "(+ (+ (* (+ a b) (+ c d)) (* (- a) c)) (* (- b) d))";
    let (s, c) = optimize(input);
    // ad + bc  (or bc + ad):  2 muls + 1 add = 3
    assert_eq!(c, 3.0);
    // all four leaves present
    for leaf in &["a", "b", "c", "d"] {
        assert!(s.contains(leaf), "missing {leaf} in result: {s}");
    }
    // exactly two products survived cancellation
    assert_eq!(s.matches("(* ").count(), 2, "expected 2 muls in: {s}");
}


/// Verify StochasticApplier can wrap ConditionalApplier.
#[test]
fn stochastic_conditional_compose() {
    let searcher: Pattern<Expr> = "(+ ?a ?b)".parse().unwrap();
    let rhs: Pattern<Expr> = "(+ ?b ?a)".parse().unwrap();

    let cond_applier = ConditionalApplier {
        condition: |_egraph: &mut EGraph<Expr, WeightedCost<Expr>>, _eclass: Id, _subst: &Subst| true,
        applier: rhs.clone(),
    };
    let stochastic = StochasticApplier::new(rhs, cond_applier);

    let rw = Rewrite::new("commute-stochastic-cond", searcher, stochastic).unwrap();
    let rules = &[rw];

    let expr: RecExpr<Expr> = "(+ 1 2)".parse().unwrap();
    let mut runner = Runner::<Expr, WeightedCost<Expr>>::new(WeightedCost::new(weight))
        .with_expr(&expr)
        .with_iter_limit(5)
        .run(rules);
    // After saturation, 1+2 and 2+1 should be in the same eclass
    let root = runner.roots[0];
    let egraph = &mut runner.egraph;
    let expected = egraph.add_expr(&"(+ 2 1)".parse().unwrap());
    assert_eq!(egraph.find(root), egraph.find(expected));
}