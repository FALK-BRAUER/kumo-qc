"""Deflated Sharpe Ratio (#323 B.1) — Bailey & López de Prado (2014).

The observed Sharpe is INFLATED for two reasons:
  1. We tried MANY configs (multiple comparisons) — the max of N noisy Sharpes is > 0 even
     under a true-zero-edge null.
  2. Returns are non-normal (skew/kurtosis) — the naive Sharpe standard error is wrong.

DSR is the probability the TRUE Sharpe > 0 after BOTH corrections. It is the PRIMARY #323
selector because it directly answers "did this survive the number of bets we placed."

Pipeline (all per-period — de-annualise consistently; this module works in the units of the
supplied returns series, i.e. per-period Sharpe):

  SR_hat = mean(returns) / std(returns)              [per-period Sharpe estimate]
  SR_0   = sqrt(Var{SR_n}) · [ (1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)) ]   [expected max under null]
  PSR(SR_0) = Φ( (SR_hat - SR_0)·sqrt(T-1) / sqrt(1 - γ3·SR_hat + ((γ4-1)/4)·SR_hat²) )
  DSR    = PSR(SR_0)

where N = number of (effective) trials, Var{SR_n} = variance of the Sharpe estimates ACROSS
trials, γ = Euler-Mascheroni (≈0.5772), Φ⁻¹ = inverse standard normal CDF, e = Euler's number,
γ3 = skew of returns, γ4 = kurtosis (NON-excess; normal == 3), T = sample length.

NO numpy: the normal CDF/PPF are implemented via math.erf / a rational Beasley-Springer-Moro
approximation, so the objective layer pins no numeric stack and stays importable anywhere.

OQ-1 (design doc F): N is the EFFECTIVE number of INDEPENDENT trials, not the raw grid size
(correlated neighbours over-count N → over-deflate). This module takes `n_trials` as a caller
input so the selector can pass an effective-N estimate; it does not itself cluster trials.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

EULER_MASCHERONI = 0.5772156649015329
"""γ — used in the expected-max-of-N-Gaussians benchmark (Bailey & LdP 2014, eq. for SR_0)."""


def _norm_cdf(x: float) -> float:
    """Standard normal CDF Φ(x) via the error function (exact, no numpy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Standard normal inverse CDF Φ⁻¹(p) — Acklam's rational approximation (|err| < 1.15e-9).

    Defined on the open interval (0, 1). Raises on out-of-domain input (a degenerate trial
    count would otherwise silently produce ±inf and poison SR_0)."""
    if not (0.0 < p < 1.0):
        raise ValueError(f"norm_ppf domain is (0,1), got {p}")
    # Coefficients for Acklam's algorithm.
    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00)
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
           ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


def _moments(returns: Sequence[float]) -> tuple[float, float, float, float]:
    """(mean, std, skew, kurtosis) of a returns series. std/skew/kurt are population stats.

    Kurtosis is NON-excess (normal == 3.0), matching the PSR formula's (γ4-1)/4 term.
    """
    n = len(returns)
    if n < 2:
        raise ValueError("need >= 2 returns to estimate moments")
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n
    std = math.sqrt(var)
    if std == 0.0:
        return mean, 0.0, 0.0, 3.0
    m3 = sum((r - mean) ** 3 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n
    skew = m3 / std ** 3
    kurt = m4 / std ** 4
    return mean, std, skew, kurt


def sharpe_ratio(returns: Sequence[float]) -> float:
    """Per-period Sharpe = mean/std of the returns series (0.0 if no dispersion)."""
    mean, std, _, _ = _moments(returns)
    return 0.0 if std == 0.0 else mean / std


def expected_max_sharpe(n_trials: int, sharpe_variance_across_trials: float) -> float:
    """SR_0 — the expected MAX Sharpe under the null of zero true edge across N trials.

    The multiple-comparisons benchmark: with N trials each drawing a noisy Sharpe of variance
    `sharpe_variance_across_trials`, the best one is ~this large by luck alone. A real edge
    must clear THIS, not zero. Monotonic increasing in N (more trials → higher luck bar).
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if sharpe_variance_across_trials < 0.0:
        raise ValueError("variance must be >= 0")
    if n_trials == 1:
        return 0.0  # a single trial has no multiple-comparisons inflation
    sigma = math.sqrt(sharpe_variance_across_trials)
    g = EULER_MASCHERONI
    term = (1.0 - g) * _norm_ppf(1.0 - 1.0 / n_trials) + g * _norm_ppf(
        1.0 - 1.0 / (n_trials * math.e)
    )
    return sigma * term


def probabilistic_sharpe(returns: Sequence[float], sr_benchmark: float) -> float:
    """PSR(SR_0) — P(true Sharpe > sr_benchmark) given the sample's length + non-normality.

    Higher T (longer track) and lower skew/kurtosis distortion → tighter estimate → PSR moves
    decisively toward 0 or 1. The skew/kurtosis terms widen the standard error for fat-tailed
    series (you need a bigger observed Sharpe to be confident).
    """
    n = len(returns)
    if n < 2:
        raise ValueError("need >= 2 returns for PSR")
    sr_hat = sharpe_ratio(returns)
    _, std, skew, kurt = _moments(returns)
    if std == 0.0:
        # No dispersion → a positive mean is a (degenerate) certain edge, else no edge.
        return 1.0 if sr_hat > sr_benchmark else 0.0
    denom_var = 1.0 - skew * sr_hat + ((kurt - 1.0) / 4.0) * sr_hat**2
    if denom_var <= 0.0:
        # Extreme non-normality breaks the Gaussian SE approximation — refuse to fabricate.
        return 0.0
    z = (sr_hat - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom_var)
    return _norm_cdf(z)


def deflated_sharpe(
    returns: Sequence[float],
    *,
    n_trials: int,
    sharpe_variance_across_trials: float,
) -> float:
    """DSR = PSR(SR_0) — the probability the true Sharpe beats the multiple-trials benchmark.

    The #323 PRIMARY selector. `> 0.8` is the filter threshold. Properties (asserted in tests):
      - DECREASES as n_trials rises (the multiple-comparisons correction bites).
      - → high for a strong stable series at N=1 (no deflation).
      - → ~0.5 for a pure-noise series (no edge to find).
    """
    sr_0 = expected_max_sharpe(n_trials, sharpe_variance_across_trials)
    return probabilistic_sharpe(returns, sr_0)
