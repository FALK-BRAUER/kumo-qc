"""#352 regime-conditional interpretable multivariate composite — fit/score + OOS evaluation.

Single features don't discriminate (#349); the signal is multivariate + regime-conditional. This builds
an INTERPRETABLE composite (NOT a black box): per regime, a correlation-weighted z-score —
  fit  = {per-feature (mean, std, sign)} on the FIT window only, sign = sign(spearman(feature, label))
  score(point) = Σ_f sign_f · (x_f − mean_f) / std_f      (readable: each feature's weight = its sign)

OVERFIT GUARD (the whole game, #352): fit on ONE window, score OUT-OF-SAMPLE on the other. The fit
NEVER sees the test rows; each test point is scored independently (pure function of fit + its own
features — no label, no other test points). fail-loud on degenerate fit (constant feature / too few rows).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from feature_panel import quartile_auc, spearman

MIN_FIT_ROWS = 20


@dataclass(frozen=True)
class CompositeFit:
    """Frozen per-feature stats from the FIT window: feature → (mean, std, sign). Immutable so a fit
    can't be mutated by later test scoring (leakage guard)."""
    stats: dict[str, tuple[float, float, float]]
    n_fit: int

    @property
    def features(self) -> tuple[str, ...]:
        return tuple(self.stats)


def fit_composite(rows: Sequence[dict], features: Sequence[str], min_rows: int = MIN_FIT_ROWS) -> CompositeFit:
    """Fit on rows = [{"feats": {f: val|None}, "label": float}]. Per feature: mean/std over non-None
    values + sign = sign(spearman(value, label)). FAIL-LOUD: a feature with < min_rows usable points
    or zero variance (constant → can't z-score) raises — never silently drop or impute."""
    stats: dict[str, tuple[float, float, float]] = {}
    for f in features:
        pairs = [(r["feats"][f], r["label"]) for r in rows
                 if r["feats"].get(f) is not None and r.get("label") is not None]
        if len(pairs) < min_rows:
            raise ValueError(f"fit_composite: feature {f!r} has {len(pairs)} usable rows < min {min_rows}")
        xs = [p[0] for p in pairs]
        ls = [p[1] for p in pairs]
        n = len(xs)
        mean = sum(xs) / n
        var = sum((x - mean) ** 2 for x in xs) / n
        if var <= 0.0:
            raise ValueError(f"fit_composite: feature {f!r} is constant (zero variance) — cannot z-score")
        std = math.sqrt(var)
        sp = spearman(xs, ls)
        sign = 0.0 if sp is None else (1.0 if sp >= 0 else -1.0)
        stats[f] = (mean, std, sign)
    if not stats:
        raise ValueError("fit_composite: no features fit")
    return CompositeFit(stats=stats, n_fit=len(rows))


def score(fit: CompositeFit, feats: dict[str, float | None]) -> float | None:
    """Composite z-score for ONE candidate. Pure function of (fit, this point's features) — NO label,
    NO other points (the leakage guard). None if the point has none of the fit features."""
    total = 0.0
    used = 0
    for f, (mean, std, sign) in fit.stats.items():
        x = feats.get(f)
        if x is None:
            continue
        total += sign * (x - mean) / std
        used += 1
    return total / used if used else None


def oos_evaluate(fit_rows: Sequence[dict], test_rows: Sequence[dict], features: Sequence[str],
                 min_rows: int = MIN_FIT_ROWS) -> dict:
    """Fit on fit_rows ONLY, score test_rows with the frozen fit, grade on the HELD-OUT test labels
    (Spearman + quartile AUC of composite-score vs forward-return). Returns the fit + OOS grades."""
    fit = fit_composite(fit_rows, features, min_rows)
    scored = [(score(fit, r["feats"]), r["label"]) for r in test_rows]
    pairs = [(s, l) for s, l in scored if s is not None and l is not None]
    if len(pairs) < 8:
        return {"fit": fit, "spearman": None, "auc": None, "n_test": len(pairs)}
    ss = [p[0] for p in pairs]
    ls = [p[1] for p in pairs]
    return {"fit": fit, "spearman": spearman(ss, ls), "auc": quartile_auc(ss, ls), "n_test": len(pairs)}
