use egg::*;
use std::process::Command;
use std::time::Instant;

type BoolRewrite = Rewrite<BoolExpr, WeightedCost<BoolExpr>>;

define_language! {
    enum BoolExpr {
        "&" = And([Id; 2]),
        "|" = Or([Id; 2]),
        "^" = Xor([Id; 2]),
        "~" = Not(Id),
        Symbol(Symbol),
    }
}

fn weight(enode: &BoolExpr) -> f64 {
    match enode {
        BoolExpr::And(_) | BoolExpr::Or(_) | BoolExpr::Xor(_) => 1.0,
        BoolExpr::Not(_) => 0.5,
        BoolExpr::Symbol(_) => 0.1,
    }
}

fn sr(name: &str, lhs: &str, rhs: &str, rules: &mut Vec<BoolRewrite>) {
    let lhs_pat: Pattern<BoolExpr> = lhs.parse().unwrap();
    let rhs_pat: Pattern<BoolExpr> = rhs.parse().unwrap();

    let x: Var = "?zzzz".parse().unwrap();

    rules.push(
        // (1) Cost-gated stochastic: search LHS, add RHS probabilistically
        Rewrite::new(
            name,
            lhs_pat.clone(),
            StochasticApplier::new(rhs_pat.clone(), rhs_pat.clone()),
        )
        .unwrap(),
    );
    // (2) Directional: search LHS & RHS in same eclass, remove LHS stochastically
    rules.push(
        Rewrite::new(
            format!("{}-remove", name),
            MultiPattern::new(vec![(x, lhs_pat.clone().ast), (x, rhs_pat.clone().ast)]),
            StochasticApplier::new_remove(lhs_pat.clone(), RemoveApplier::new(lhs_pat)),
        )
        .unwrap(),
    );
}

fn rules() -> Vec<BoolRewrite> {
    let mut rules = Vec::new();

    // commutativity
    sr("comm-and", "(& ?a ?b)", "(& ?b ?a)", &mut rules);
    sr("comm-or", "(| ?a ?b)", "(| ?b ?a)", &mut rules);
    // associativity
    sr(
        "assoc-and",
        "(& (& ?a ?b) ?c)",
        "(& ?a (& ?b ?c))",
        &mut rules,
    );
    sr(
        "assoc-and-r",
        "(& ?a (& ?b ?c))",
        "(& (& ?a ?b) ?c)",
        &mut rules,
    );
    sr(
        "assoc-or",
        "(| (| ?a ?b) ?c)",
        "(| ?a (| ?b ?c))",
        &mut rules,
    );
    sr(
        "assoc-or-r",
        "(| ?a (| ?b ?c))",
        "(| (| ?a ?b) ?c)",
        &mut rules,
    );
    // idempotence
    sr("idem-and", "(& ?a ?a)", "?a", &mut rules);
    sr("idem-or", "(| ?a ?a)", "?a", &mut rules);
    // double negation
    sr("not-not", "(~ (~ ?a))", "?a", &mut rules);
    // de morgan
    sr(
        "demorgan-and",
        "(~ (& ?a ?b))",
        "(| (~ ?a) (~ ?b))",
        &mut rules,
    );
    sr(
        "demorgan-and-r",
        "(| (~ ?a) (~ ?b))",
        "(~ (& ?a ?b))",
        &mut rules,
    );
    sr(
        "demorgan-or",
        "(~ (| ?a ?b))",
        "(& (~ ?a) (~ ?b))",
        &mut rules,
    );
    sr(
        "demorgan-or-r",
        "(& (~ ?a) (~ ?b))",
        "(~ (| ?a ?b))",
        &mut rules,
    );
    // absorption
    sr("absorb-and-or", "(& ?a (| ?a ?b))", "?a", &mut rules);
    sr("absorb-or-and", "(| ?a (& ?a ?b))", "?a", &mut rules);
    // distribution
    sr(
        "dist-and",
        "(& ?a (| ?b ?c))",
        "(| (& ?a ?b) (& ?a ?c))",
        &mut rules,
    );
    sr(
        "dist-or",
        "(| ?a (& ?b ?c))",
        "(& (| ?a ?b) (| ?a ?c))",
        &mut rules,
    );
    // factoring
    sr(
        "factor-and",
        "(| (& ?a ?b) (& ?a ?c))",
        "(& ?a (| ?b ?c))",
        &mut rules,
    );
    sr(
        "factor-or",
        "(& (| ?a ?b) (| ?a ?c))",
        "(| ?a (& ?b ?c))",
        &mut rules,
    );

    rules
}

fn generate_terms(size: usize, vars: usize, sample: usize, seed: Option<u64>) -> Vec<String> {
    let mut cmd = Command::new("python3");
    cmd.args([
        "./scripts/termgen.py",
        "--size",
        &size.to_string(),
        "--vars",
        &vars.to_string(),
        "--sample",
        &sample.to_string(),
    ]);

    if let Some(s) = seed {
        cmd.args(["--seed", &s.to_string()]);
    }

    let output = cmd
        .output()
        .expect("failed to run termgen.py — is python3 on PATH?");
    assert!(
        output.status.success(),
        "termgen.py failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

fn main() {
    let term_size: usize = std::env::var("TERM_SIZE")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(500);
    let vars: usize = std::env::var("VARS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(3);
    let sample: usize = std::env::var("SAMPLE")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(1);
    let seed: Option<u64> = std::env::var("SEED")
        .ok()
        .and_then(|v| v.parse().ok())
        .or(Some(42));
    let iter_limit: usize = std::env::var("ITER_LIMIT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(30);
    let node_limit: usize = std::env::var("NODE_LIMIT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(100_000);
    let cooling_rate: f64 = std::env::var("COOLING_RATE")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(0.89);

    eprintln!("Generating {sample} term(s) of size {term_size} with {vars} variables...");
    if let Some(s) = seed {
        eprintln!("Using seed: {s}");
    }
    let terms = generate_terms(term_size, vars, sample, seed);
    eprintln!("Generated {} term(s)", terms.len());
    eprintln!("Cooling rate: {cooling_rate}");
    eprintln!("Limits: {iter_limit} iterations, {node_limit} nodes");
    eprintln!();

    let rules = rules();

    println!("term_idx,input_size,eqsat_ms,eclasses,nodes,initial_cost,output_cost,stop_reason");

    for (i, input) in terms.iter().enumerate() {
        let expr: RecExpr<BoolExpr> = match input.parse() {
            Ok(e) => e,
            Err(e) => {
                eprintln!("  [term {i}] parse error: {e}");
                continue;
            }
        };
        let input_size = expr.len();

        // Calculate the initial cost before running e-graph
        let initial_cost: f64 = expr.as_ref().iter().map(weight).sum();

        let start = Instant::now();
        let cr = cooling_rate;
        let runner: Runner<BoolExpr, WeightedCost<BoolExpr>> =
            Runner::new(WeightedCost::new(weight))
                .with_expr(&expr)
                .with_iter_limit(iter_limit)
                .with_node_limit(node_limit)
                .with_convergence()
                .with_hook(move |runner| {
                    runner.egraph.analysis.temperature *= cr;
                    runner
                        .egraph
                        .analysis
                        .log_progress(&runner.egraph, runner.roots[0]);
                    Ok(())
                })
                .run(&rules);
        let elapsed = start.elapsed();

        let root = runner.roots[0];
        let best_cost = runner.egraph[root].data.clone().unwrap();
        let n_eclasses = runner.egraph.number_of_classes();
        let n_nodes = runner.egraph.total_number_of_nodes();
        let stop_reason = match runner.stop_reason.as_ref().unwrap() {
            StopReason::Saturated => "saturated".to_string(),
            StopReason::IterationLimit(n) => format!("iteration_limit({n})"),
            StopReason::NodeLimit(n) => format!("node_limit({n})"),
            StopReason::TimeLimit(t) => format!("time_limit({t:.1}s)"),
            StopReason::Other(s) => format!("other({s})"),
            StopReason::Convergence(n) => format!("convergence({n})"),
        };

        println!(
            "{i},{input_size},{:.1},{n_eclasses},{n_nodes},{initial_cost:.1},{best_cost:.1},{stop_reason}",
            elapsed.as_secs_f64() * 1000.0,
        );
        // eprintln!(
        //     "  [term {i}] input={input_size} nodes, initial_cost={initial_cost:.1} -> cost={best_cost:.1}, \
        //      {n_eclasses} eclasses, {n_nodes} enodes, {:.1} ms",
        //     elapsed.as_secs_f64() * 1000.0,
        // );
    }
}
