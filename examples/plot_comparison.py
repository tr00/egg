#!/usr/bin/env python3
"""Compare baseline vs stochastic output_cost from two CSV files."""

import csv
import sys

import matplotlib.pyplot as plt


def read_costs(path):
    with open(path) as f:
        reader = csv.DictReader(f)
        return [float(row["output_cost"]) for row in reader]


def main():
    base_path = sys.argv[1] if len(sys.argv) > 1 else "baseline.csv"
    stoch_path = sys.argv[2] if len(sys.argv) > 2 else "stochastic.csv"

    base = read_costs(base_path)
    stoch = read_costs(stoch_path)
    n = min(len(base), len(stoch))
    base, stoch = base[:n], stoch[:n]

    wins_better = sum(
        1 for b, s in zip(base, stoch) if b < s
    )  # baseline lower = better
    wins_worse = sum(1 for b, s in zip(base, stoch) if b > s)
    draws = sum(1 for b, s in zip(base, stoch) if b == s)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # --- left: scatter plot with y=x agreement line ---
    ax = axes[0]
    lo = 0
    hi = max(max(base), max(stoch)) * 1.05
    # ax.plot([lo, hi], [lo, hi], "k--", alpha=0.4, label="equal cost")
    for i in range(n):
        color = (
            "green" if base[i] < stoch[i] else "red" if base[i] > stoch[i] else "gray"
        )
        ax.scatter(base[i], stoch[i], c=color, s=20, alpha=0.7, edgecolors="none")
    ax.set_xlabel("baseline output_cost")
    ax.set_ylabel("stochastic output_cost")
    ax.set_title(f"Baseline vs Stochastic  (n={n})")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    # custom legend
    ax.scatter([], [], c="green", s=30, label=f"baseline better ({wins_better})")
    ax.scatter([], [], c="red", s=30, label=f"stochastic better ({wins_worse})")
    ax.scatter([], [], c="gray", s=30, label=f"draw ({draws})")
    ax.legend(fontsize=8)

    # --- right: bar chart of win/draw/loss ---
    ax2 = axes[1]
    cats = ["baseline\nbetter", "draw", "stochastic\nbetter"]
    vals = [wins_better, draws, wins_worse]
    cols = ["green", "gray", "red"]
    bars = ax2.bar(cats, vals, color=cols, edgecolor="black", linewidth=0.5)
    for bar, v in zip(bars, vals):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            str(v),
            ha="center",
            va="bottom",
            fontweight="bold",
        )
    ax2.set_ylabel("count")
    ax2.set_title("Win / Draw / Loss")

    plt.tight_layout()
    out = "comparison.png"
    plt.savefig(out, dpi=150)
    print(f"Saved to {out}")
    print(
        f"Baseline better: {wins_better}  |  Draw: {draws}  |  Stochastic better: {wins_worse}"
    )


if __name__ == "__main__":
    main()
