#!/usr/bin/env python3
"""Generate all terms of a given size over a signature, using at most k variables.

A *term* is a tree built from the operators of a signature.  Its *size* is the
number of nodes in that tree: every operator application, constant and variable
counts as one.  So `(& A B)` has size 3 and `(~ (& A B))` has size 4.

By default terms are emitted up to renaming of variables: leaves are labelled
with a canonical "restricted growth" assignment so that the first distinct
variable encountered (left to right) is always the 0th, the next new one the
1st, and so on.  This yields exactly one representative per renaming class while
still respecting the "at most k distinct variables" bound.  Pass
--all-labelings to instead emit every assignment drawn from the k-variable pool.

Plug in your own signature with --signature path/to/sig.json (see SIGNATURE
below for the format) or pick one of the built-ins with --builtin.

Examples:
    python termgen.py -n 3 -k 2
    python termgen.py -n 4 -k 2 --notation infix --symbols names
    python termgen.py -n 4 -k 2 --signature mysig.json

    python scripts/termgen/termgen.py -n 5 -k 3 --builtin bool --notation prefix --sample 10 --seed 42

    python scripts/termgen/termgen.py -n 500 -k 3 --builtin bool --notation prefix --sample 1000 --seed 42 > scripts/termgen/bool_500_3.txt
    python scripts/termgen/termgen.py -n 50 -k 3 --builtin bool --notation prefix --sample 1000 --seed 42 > scripts/termgen/bool_50_3.txt
    # 1000 term, 50 size, 3 vars
    # 1000 term, 500 size, 3 vars
"""

import argparse
import itertools
import json
import random
import sys

# --------------------------------------------------------------------------- #
# Signature                                                                   #
# --------------------------------------------------------------------------- #
#
# A signature is a list of operators; each operator has a `name` (a word form
# such as "plus"), a `symbol` (a glyph form such as "+") and an `arity`.
# Operators of arity 0 are constants (e.g. true, 0, nil).  Variables are not
# part of the signature -- their count is bounded by k and their names come
# from --var-names.

# Built-in signatures, keyed by the name used with --builtin.
BUILTINS = {
    "bv": [
        {"name": "not", "symbol": "~", "arity": 1},
        {"name": "neg", "symbol": "-", "arity": 1},
        {"name": "plus", "symbol": "+", "arity": 2},
        {"name": "minus", "symbol": "-", "arity": 2},
        {"name": "times", "symbol": "*", "arity": 2},
        {"name": "and", "symbol": "&", "arity": 2},
        {"name": "or", "symbol": "|", "arity": 2},
        {"name": "shl", "symbol": "<<", "arity": 2},
        {"name": "shr", "symbol": ">>", "arity": 2},
    ],
    "bool": [
        {"name": "and", "symbol": "&", "arity": 2},
        {"name": "or", "symbol": "|", "arity": 2},
        {"name": "xor", "symbol": "^", "arity": 2},
        {"name": "not", "symbol": "~", "arity": 1},
        # {"name": "true",  "symbol": "T", "arity": 0},
        # {"name": "false", "symbol": "F", "arity": 0},
    ],
    "int": [
        {"name": "plus", "symbol": "+", "arity": 2},
        {"name": "minus", "symbol": "-", "arity": 2},
        {"name": "times", "symbol": "*", "arity": 2},
        {"name": "neg", "symbol": "-", "arity": 1},
        # {"name": "zero",  "symbol": "0", "arity": 0},
        # {"name": "one",   "symbol": "1", "arity": 0},
    ],
}


class Operator:
    __slots__ = ("name", "symbol", "arity")

    def __init__(self, name, symbol, arity):
        self.name = name
        self.symbol = symbol
        self.arity = int(arity)


class Signature:
    def __init__(self, operators):
        self.operators = [Operator(**o) for o in operators]
        self.constants = [o for o in self.operators if o.arity == 0]
        self.functions = [o for o in self.operators if o.arity > 0]
        if not self.operators:
            raise ValueError("signature is empty")

    @classmethod
    def load(cls, path):
        with open(path) as f:
            data = json.load(f)
        # Accept either a bare list or {"operators": [...]}.
        ops = data["operators"] if isinstance(data, dict) else data
        return cls(ops)


# --------------------------------------------------------------------------- #
# Term representation                                                          #
# --------------------------------------------------------------------------- #
#
# A term is one of:
#   ("op",  Operator, (child, ...))   an operator application
#   ("var", index)                    a variable, identified by an int index


def op(operator, children):
    return ("op", operator, tuple(children))


def var(index):
    return ("var", index)


# --------------------------------------------------------------------------- #
# Generation                                                                   #
# --------------------------------------------------------------------------- #


def compositions(total, parts):
    """Yield every tuple of `parts` positive ints summing to `total`."""
    if parts == 1:
        if total >= 1:
            yield (total,)
        return
    for first in range(1, total - parts + 2):
        for rest in compositions(total - first, parts - 1):
            yield (first,) + rest


def gen_shapes(size, sig, _cache):
    """Yield all term *shapes* of the given size.

    A shape is a term whose variable leaves are placeholders -- every variable
    is emitted as ("var", None).  Constants are concrete.  Variables are
    labelled in a later pass so we can enforce the canonical / at-most-k rule.
    """
    if size in _cache:
        return _cache[size]

    shapes = []
    if size == 1:
        shapes.append(("var", None))  # a variable placeholder
        for c in sig.constants:  # or a constant
            shapes.append(op(c, ()))
    else:
        for f in sig.functions:
            if f.arity == 0:
                continue
            # The f node uses 1; its children share the remaining size-1.
            for parts in compositions(size - 1, f.arity):
                child_choices = [gen_shapes(p, sig, _cache) for p in parts]
                for combo in itertools.product(*child_choices):
                    shapes.append(op(f, combo))

    _cache[size] = shapes
    return shapes


def count_var_slots(shape):
    kind = shape[0]
    if kind == "var":
        return 1
    if kind == "op":
        return sum(count_var_slots(c) for c in shape[2])
    return 0


def fill_vars(shape, labels, pos):
    """Return a copy of `shape` with the i-th var placeholder set to labels[i]."""
    kind = shape[0]
    if kind == "var":
        i = pos[0]
        pos[0] += 1
        return var(labels[i])
    if kind == "op":
        return op(shape[1], [fill_vars(c, labels, pos) for c in shape[2]])
    return shape


def canonical_labelings(num_slots, k):
    """Restricted-growth strings of length num_slots with values < k.

    Each value is at most 1 + the max so far, so we get one representative per
    way of partitioning the leaves into <= k variable classes.
    """
    if num_slots == 0:
        yield ()
        return

    def rec(prefix, used):
        if len(prefix) == num_slots:
            yield tuple(prefix)
            return
        for v in range(min(used + 1, k)):
            prefix.append(v)
            yield from rec(prefix, max(used + 1, v + 1) if v == used else used)
            prefix.pop()

    yield from rec([], 0)


def all_labelings(num_slots, k):
    """Every assignment of num_slots leaves to one of k variables."""
    return itertools.product(range(k), repeat=num_slots)


def generate(size, k, sig, canonical=True):
    """Yield every term of exactly `size` using at most `k` distinct variables."""
    cache = {}
    label_fn = canonical_labelings if canonical else all_labelings
    for shape in gen_shapes(size, sig, cache):
        slots = count_var_slots(shape)
        if slots == 0:
            yield shape
            continue
        for labels in label_fn(slots, k):
            yield fill_vars(shape, list(labels), [0])


def reservoir_sample(it, n, rng):
    """Return n items chosen uniformly at random from iterable `it`.

    Uses reservoir sampling so the full (possibly enormous) term set is never
    materialised.  If `it` has fewer than n items, all of them are returned in
    a random order.
    """
    reservoir = []
    for i, item in enumerate(it):
        if i < n:
            reservoir.append(item)
        else:
            j = rng.randint(0, i)
            if j < n:
                reservoir[j] = item
    rng.shuffle(reservoir)
    return reservoir


# --------------------------------------------------------------------------- #
# Direct random generation                                                     #
# --------------------------------------------------------------------------- #
#
# Enumerating every shape of size n only to keep a few is hopeless once n is
# large (the number of shapes grows ~exponentially).  To draw a sample we
# instead generate random terms directly.  We first count, by dynamic
# programming, how many shapes of each size exist; those exact (big-int) counts
# let us recurse down the tree choosing each branch with the right probability,
# so every shape of size n is equally likely -- without ever building them all.


def count_shapes(n, sig):
    """Return (count, cpow) for shapes up to size n.

    count[s]    = number of shapes of size s.
    cpow[j][t]  = number of ordered j-tuples of shapes whose sizes sum to t
                  (the j-fold convolution of count).  cpow[arity][t] is exactly
                  the number of ways to fill an arity-ary operator's children
                  with total size t, which is what both counting and sampling
                  need.
    """
    num_const = len(sig.constants)
    max_arity = max((f.arity for f in sig.functions), default=0)

    count = [0] * (n + 1)
    cpow = [[0] * (n + 1) for _ in range(max_arity + 1)]
    cpow[0][0] = 1  # one way to fill zero children with total size 0

    for m in range(1, n + 1):
        leaf = (1 + num_const) if m == 1 else 0
        funcs = sum(cpow[f.arity][m - 1] for f in sig.functions)
        count[m] = leaf + funcs
        # Extend every convolution row to index m using the now-final count[m].
        for j in range(1, max_arity + 1):
            total = 0
            row_below = cpow[j - 1]
            for u in range(1, m + 1):
                below = row_below[m - u]
                if below:
                    total += count[u] * below
            cpow[j][m] = total

    return count, cpow


def _weighted_index(weights, total, rng):
    """Pick an index into `weights` with probability weights[i]/total."""
    r = rng.randrange(total)
    acc = 0
    for i, w in enumerate(weights):
        acc += w
        if r < acc:
            return i
    return len(weights) - 1  # unreachable unless total mismatches


def sample_shape(size, sig, count, cpow, rng):
    """Return one shape of exactly `size`, drawn uniformly at random.

    Recurses to a depth of at most `size`; callers raise the recursion limit
    accordingly for large sizes.
    """
    if size == 1:
        # A leaf: the variable placeholder, or one of the constants.
        r = rng.randrange(1 + len(sig.constants))
        return ("var", None) if r == 0 else op(sig.constants[r - 1], ())

    # Choose the root operator, weighted by how many shapes it yields.
    weights = [cpow[f.arity][size - 1] for f in sig.functions]
    f = sig.functions[_weighted_index(weights, count[size], rng)]

    # Choose child sizes summing to size-1, weighted by product of subcounts.
    children = []
    rem_total, rem_children = size - 1, f.arity
    for _ in range(f.arity):
        below = rem_children - 1
        denom = cpow[rem_children][rem_total]
        # Each remaining child needs >= 1, so this child is <= rem_total-below.
        sizes = range(1, rem_total - below + 1)
        weights = [count[u] * cpow[below][rem_total - u] for u in sizes]
        u = sizes[_weighted_index(weights, denom, rng)]
        children.append(sample_shape(u, sig, count, cpow, rng))
        rem_total -= u
        rem_children -= 1

    return op(f, children)


def label_randomly(shape, k, rng, canonical=True):
    """Fill variable placeholders with random variables in [0, k).

    With canonical=True the chosen labels are renumbered by first appearance,
    so output uses the same canonical variable names as the enumerator.
    """
    slots = count_var_slots(shape)
    if slots and k < 1:
        raise ValueError("term needs variables but k < 1")
    labels = [rng.randrange(k) for _ in range(slots)]
    if canonical:
        remap, nxt = {}, 0
        for i, v in enumerate(labels):
            if v not in remap:
                remap[v] = nxt
                nxt += 1
            labels[i] = remap[v]
    return fill_vars(shape, labels, [0])


def sample_terms(size, k, n, sig, rng, canonical=True):
    """Yield `n` random terms of exactly `size` using at most `k` variables.

    Samples with replacement, so duplicates are possible (likely only when the
    space of terms is itself small).
    """
    count, cpow = count_shapes(size, sig)
    if count[size] == 0:
        raise ValueError(f"no terms of size {size} exist over this signature")
    for _ in range(n):
        shape = sample_shape(size, sig, count, cpow, rng)
        yield label_randomly(shape, k, rng, canonical)


# --------------------------------------------------------------------------- #
# Rendering                                                                    #
# --------------------------------------------------------------------------- #


def render(term, notation, use_symbols, var_names):
    def sym(operator):
        return operator.symbol if use_symbols else operator.name

    def name_of_var(index):
        if index < len(var_names):
            return var_names[index]
        return f"v{index}"  # fall back gracefully past the pool

    def go(t):
        if t[0] == "var":
            return name_of_var(t[1])
        operator, children = t[1], t[2]
        rendered = [go(c) for c in children]

        if not children:  # constant
            return sym(operator)

        if notation == "sexpr":
            return "(" + " ".join([sym(operator), *rendered]) + ")"

        if notation == "prefix":
            return sym(operator) + "(" + ", ".join(rendered) + ")"

        # infix
        if len(children) == 2:
            return f"({rendered[0]} {sym(operator)} {rendered[1]})"
        if len(children) == 1:
            return f"{sym(operator)}({rendered[0]})"
        # arity >= 3 has no natural infix form: fall back to functional.
        return sym(operator) + "(" + ", ".join(rendered) + ")"

    return go(term)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #


def build_arg_parser():
    p = argparse.ArgumentParser(
        description="Generate terms of size n with at most k distinct variables.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "-n",
        "--size",
        type=int,
        required=True,
        help="exact term size (number of nodes)",
    )
    p.add_argument(
        "-k",
        "--vars",
        type=int,
        default=2,
        help="maximum number of distinct variables (default: 2)",
    )
    p.add_argument(
        "--notation",
        choices=["sexpr", "infix", "prefix"],
        default="sexpr",
        help="output notation (default: sexpr)",
    )
    p.add_argument(
        "--symbols",
        choices=["symbols", "names"],
        default="symbols",
        help="render operators as symbols (+) or names (plus)",
    )
    p.add_argument(
        "--var-names",
        default="x,y,z,u,v,w,a,b,c,d,e,f",
        help="comma-separated variable name pool",
    )

    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--builtin",
        choices=sorted(BUILTINS),
        help="use a built-in signature (default: bool)",
    )
    src.add_argument("--signature", help="path to a JSON signature file")

    p.add_argument(
        "--all-labelings",
        action="store_true",
        help="emit every variable assignment from the pool, not just "
        "canonical representatives up to renaming",
    )
    p.add_argument(
        "--count",
        action="store_true",
        help="print only the number of terms, not the terms",
    )

    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="seed for --sample/--shuffle, for reproducible output",
    )
    p.add_argument(
        "--sample",
        type=int,
        default=None,
        metavar="N",
        help="emit N random terms generated directly (uniform over "
        "shapes; with replacement). Scales to large sizes, "
        "unlike full enumeration.",
    )
    p.add_argument(
        "--shuffle",
        action="store_true",
        help="enumerate all terms and emit them in a random order",
    )
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    if args.size < 1:
        sys.exit("error: size must be >= 1")
    if args.vars < 0:
        sys.exit("error: number of variables must be >= 0")

    if args.signature:
        sig = Signature.load(args.signature)
    else:
        sig = Signature(BUILTINS[args.builtin or "bool"])

    if args.sample is not None and args.sample < 0:
        sys.exit("error: --sample must be >= 0")

    var_names = [v.strip() for v in args.var_names.split(",") if v.strip()]
    use_symbols = args.symbols == "symbols"
    canonical = not args.all_labelings

    # A fresh RNG seeded once: same --seed (with the same other flags) always
    # reproduces the same terms in the same order.
    rng = random.Random(args.seed)

    if args.sample is not None:
        # Direct random generation -- never enumerates the full space, so it
        # scales to large sizes.  Recursion can go as deep as the term size.
        sys.setrecursionlimit(max(sys.getrecursionlimit(), args.size + 1000))
        try:
            terms = sample_terms(args.size, args.vars, args.sample, sig, rng, canonical)
        except ValueError as e:
            sys.exit(f"error: {e}")
    else:
        terms = generate(args.size, args.vars, sig, canonical=canonical)

    if args.count:
        print(sum(1 for _ in terms))
        return

    if args.shuffle and args.sample is None:
        terms = list(terms)
        rng.shuffle(terms)

    out = sys.stdout.write
    for term in terms:
        out(render(term, args.notation, use_symbols, var_names))
        out("\n")


if __name__ == "__main__":
    main()
