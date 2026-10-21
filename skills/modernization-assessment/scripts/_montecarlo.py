"""Monte Carlo roll-up of the coding estimate (estimation.json "rollup"): P10 / P50 / P80 / P90 instead of sum-of-lows to sum-of-highs.

Adding every item's low and every item's high assumes all items land at the same extreme together, so the range widens with every
item and the AI factors stack on top. Standard practice (PERT, AACE RP 41R-08 estimate ranging) sums the expectations and combines
the spreads: each item is a three-point estimate (low, mode, high), items are partially correlated (one shared driver, rho), and the
AI-assistance factors are systemic (one draw per iteration for every item). The fixed seed keeps the result reproducible.

Item: {"pkg": id, "lo": h, "hi": h, "kind": "code" | "red" | "db" | "fixed", "pos": 0.4, "n": 1}
  kind  selects the AI factor (code_factor, redesign_factor, db_factor; fixed = not accelerated)
  pos   where the mode sits between lo and hi (estimation.json likely_position)
  n     identical independent items priced together (database objects of one kind and size): normal approximation of their sum
"""
import math
import random

SQRT2 = math.sqrt(2.0)


def tri_inv(u, a, b, c):
    """Inverse CDF of the triangular distribution (low a, high b, mode c)."""
    if b <= a:
        return a
    fc = (c - a) / (b - a)
    if u < fc:
        return a + math.sqrt(u * (b - a) * (c - a))
    return b - math.sqrt((1 - u) * (b - a) * (b - c))


def tri_mean_sd(a, b, c):
    return (a + b + c) / 3.0, math.sqrt(max(a * a + b * b + c * c - a * b - a * c - b * c, 0.0) / 18.0)


def pct(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, max(0, int(round(p * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def simulate(items, factors, cfg):
    """Returns {pkg: [hours per iteration]} for AI-assisted (factors) delivery.
    factors: {"code": [lo, hi], "red": [lo, hi], "db": [lo, hi]}; cfg: estimation.json "rollup" (iterations, seed, correlation, factor_position)."""
    iters, rho = int(cfg.get("iterations", 4000)), float(cfg.get("correlation", 0.3))
    fpos = float(cfg.get("factor_position", 0.5))
    rng = random.Random(cfg.get("seed", 1))
    a, b = math.sqrt(rho), math.sqrt(1 - rho)
    prepared = []
    for it in items:
        lo, hi = float(it["lo"]), float(it["hi"])
        if hi <= 0 and lo <= 0:
            continue
        c = lo + it.get("pos", 0.4) * (hi - lo)
        n = max(int(it.get("n", 1)), 1)
        mean_sd = tri_mean_sd(lo, hi, c) if n > 1 else None
        prepared.append((it["pkg"], it["kind"], lo, hi, c, n, mean_sd))
    pkgs = sorted({p[0] for p in prepared})
    out = {p: [0.0] * iters for p in pkgs}
    for k in range(iters):
        uf = rng.random()  # systemic: one AI-productivity draw for the whole team and every item
        f = {kind: tri_inv(uf, lo, hi, lo + fpos * (hi - lo)) for kind, (lo, hi) in factors.items()}
        f["fixed"] = 1.0
        zc = rng.gauss(0.0, 1.0)  # shared driver of the item draws (same team, same code base, same rates)
        for pkg, kind, lo, hi, c, n, ms in prepared:
            z = a * zc + b * rng.gauss(0.0, 1.0)
            if ms:
                v = max(n * ms[0] + math.sqrt(n) * ms[1] * z, n * lo)
            else:
                v = tri_inv(0.5 * (1.0 + math.erf(z / SQRT2)), lo, hi, c)
            out[pkg][k] += v * f[kind]
    return out


def summary(samples):
    s = sorted(samples)
    return {"p10": pct(s, 0.10), "p50": pct(s, 0.50), "p80": pct(s, 0.80), "p90": pct(s, 0.90), "mean": sum(s) / len(s) if s else 0.0}


def total(sim, pkgs):
    pkgs = [p for p in pkgs if p in sim]
    if not pkgs:
        return []
    n = len(sim[pkgs[0]])
    return [sum(sim[p][k] for p in pkgs) for k in range(n)]
