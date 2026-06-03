"""Sweep SCORING (#276b) — raw per-(config,window) BT results → ranked champion leaderboard.

This is the LOCAL post-processing step that turns the FIRE loop's checkpoint (one JSONL row
per (config, window) backtest) into a ranked leaderboard via the #323 objective layer
(sweeps/objective/{selector,dsr,pbo,gates}). It runs LOCALLY (not on QC), so numpy is fine —
the objective layer itself stays numpy-free, this driver does the linear algebra (eigenvalues)
that the effective-trials control needs.

The OQ-1 control (HQ flagged): DSR's `n_trials` MUST be the EFFECTIVE de-correlated trial
count, NEVER the raw grid cardinality. Raw cardinality over-deflates DSR and kills the robust
champion (correlated neighbours over-count N). We estimate the effective count via the
participation ratio of the config-return correlation-matrix eigenvalues (López de Prado's
de-correlated trials): N_eff = (Σλᵢ)² / Σλᵢ². Correlated configs collapse N_eff toward ~1;
orthogonal configs keep N_eff ≈ cardinality.

Two effective-N quantities (HQ's refinement):
  - PER-ROUND N_eff — for the coarse PRUNE within a single round.
  - CUMULATIVE N_eff — over the UNION of ALL configs tried across ALL rounds (round-1 +
    round-2 + refine). The FINAL champion's DSR deflates by the CUMULATIVE count, because the
    multiple-comparisons bar is set by every bet placed across the whole search, not one round.
The caller logs both for audit (`diagnostics`).

CHARTER: fail loud. A degraded RunResult is NEVER scored. A failed BT row (error != null) is
dropped at load and NEVER imputed. No fabricated coverage — every scored number traces to a
real checkpoint row.
"""
from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping, Sequence
from typing import Any
from pathlib import Path

import numpy as np

from sweeps.objective import dsr as dsr_mod
from sweeps.objective.gates import WindowReturns
from sweeps.objective.pbo import cscv_pbo
from sweeps.objective.selector import ConfigEvidence, ObjectiveScore, select
from sweeps.types import RunResult, Window

logger = logging.getLogger("sweeps.score_sweep")

# Conservative fallback multiplier when the correlation matrix is degenerate (< 2 valid
# configs or rank-deficient). N_eff falls back to n_distinct_primary_axis_levels * this
# factor, clamped to [1, n_configs]. Small (<= 3) so the fallback NEVER under-deflates by
# pretending the search was wider than the primary axis can justify.
FALLBACK_AXIS_FACTOR = 3.0

# When N_eff lands within this fraction of the raw cardinality we WARN: the configs look
# statistically independent, which is suspicious for a neighbour-dense grid (they usually
# should de-correlate). Not an error — a flag for the orchestrator to eyeball.
NEAR_CARDINALITY_WARN_FRAC = 0.90


# --------------------------------------------------------------------------- #
# Checkpoint loading.
# --------------------------------------------------------------------------- #
def load_checkpoint(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Load the FIRE-loop JSONL checkpoint → {config_hash: [window-result row, ...]}.

    One line per (config, window). Schema per row:
        {"config_hash": str, "window_name": str, "is_oos": bool, "sharpe": float,
         "net_pct": float, "dd_pct": float, "orders": int,
         "daily_returns": [float, ...], "error": str | null}

    Rows with `error != null` are DROPPED — a failed BT is NOT scored and NEVER imputed
    (CLAUDE.md data-integrity: never fabricate / fill expected values). The drop count is
    logged so the orchestrator can reconcile coverage. Malformed JSON or a row missing a
    required key fails loud (we never silently skip a structurally-broken checkpoint).
    """
    path = Path(path)
    required = {"config_hash", "window_name", "is_oos", "sharpe", "net_pct", "dd_pct", "orders"}
    by_config: dict[str, list[dict[str, Any]]] = {}
    n_total = 0
    n_dropped = 0
    with path.open() as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            n_total += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: malformed JSON checkpoint row: {exc}") from exc
            missing = required - row.keys()
            if missing:
                raise ValueError(
                    f"{path}:{lineno}: checkpoint row missing required keys {sorted(missing)}"
                )
            if row.get("error") is not None:
                n_dropped += 1
                continue
            by_config.setdefault(row["config_hash"], []).append(row)
    logger.info(
        "checkpoint loaded path=%s rows_total=%d rows_dropped_error=%d configs=%d",
        path,
        n_total,
        n_dropped,
        len(by_config),
    )
    return by_config


# --------------------------------------------------------------------------- #
# Effective number of (de-correlated) trials — the OQ-1 control.
# --------------------------------------------------------------------------- #
def _aligned_return_matrix(
    returns_by_config: Mapping[str, Sequence[float]],
) -> tuple[list[str], np.ndarray]:
    """Stack per-config daily-return series into a [n_configs × T] matrix, aligned by index.

    Configs with fewer than 2 returns are dropped (no dispersion → no correlation signal).
    Series are aligned positionally and truncated to the shortest common length T (the
    checkpoint daily_returns are per-config stitched series on the same time axis; we align by
    index because the FIRE checkpoint carries no per-day dates). Returns (kept_hashes, matrix).
    """
    valid = {h: list(r) for h, r in returns_by_config.items() if len(r) >= 2}
    if len(valid) < 2:
        return list(valid.keys()), np.empty((len(valid), 0))
    t = min(len(r) for r in valid.values())
    hashes = sorted(valid.keys())
    matrix = np.array([valid[h][:t] for h in hashes], dtype=float)
    return hashes, matrix


def _participation_ratio(matrix: np.ndarray) -> float | None:
    """Participation ratio of the correlation-matrix eigenvalues: N_eff = (Σλ)² / Σλ².

    `matrix` is [n_configs × T] (configs are rows). Builds the n_configs×n_configs correlation
    matrix across configs, takes its eigenvalues (real, symmetric → eigvalsh), and returns the
    participation ratio. Returns None if the matrix is degenerate (a zero-variance row → no
    finite correlation; fewer than 2 rows; non-finite eigenvalues) so the caller can fall back.
    """
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 2:
        return None
    # A zero-variance row makes np.corrcoef emit NaNs — that config has no return signal to
    # de-correlate against; refuse and let the caller use the conservative fallback.
    stds = matrix.std(axis=1)
    if np.any(stds == 0.0):
        return None
    with np.errstate(all="raise"):
        try:
            corr = np.corrcoef(matrix)
        except FloatingPointError:
            return None
    if not np.all(np.isfinite(corr)):
        return None
    eig = np.linalg.eigvalsh(corr)
    eig = eig[eig > 0.0]  # numerical noise can produce tiny negatives; drop non-positive
    denom = float(np.sum(eig**2))
    if denom <= 0.0 or not math.isfinite(denom):
        return None
    n_eff = float(np.sum(eig)) ** 2 / denom
    if not math.isfinite(n_eff):
        return None
    return n_eff


def effective_n(
    returns_matrix: Mapping[str, Sequence[float]],
    *,
    primary_levels: int,
) -> float:
    """Effective de-correlated trial count for DSR's `n_trials` (the OQ-1 control).

    Method: participation ratio of the config-return correlation-matrix eigenvalues,
    N_eff = (Σλᵢ)² / Σλᵢ². 3 identical configs → N_eff ≈ 1; 3 orthogonal → N_eff ≈ 3.

    `returns_matrix` maps config_hash → that config's daily-return series (aligned by index).
    `primary_levels` = number of distinct levels on the sweep's primary axis — drives the
    CONSERVATIVE fallback when the correlation matrix is degenerate (< 2 configs with valid
    returns, or rank-deficient): N_eff = clamp(primary_levels * FALLBACK_AXIS_FACTOR, 1,
    n_configs). The fallback never claims more independence than the primary axis warrants.

    GUARDS (mandatory):
      - 1 <= N_eff <= n_configs (asserted).
      - structured log of the N_eff used + the method + the raw cardinality.
      - WARN if N_eff ≈ cardinality (independent-looking — usually should de-correlate).

    Returns a float (never the raw cardinality unless the configs genuinely de-correlate to it).
    """
    n_configs = len(returns_matrix)
    cardinality = n_configs
    if n_configs == 0:
        raise ValueError("effective_n needs at least one config (got empty returns_matrix)")
    if n_configs == 1:
        # A single config has no multiple-comparisons inflation.
        logger.info(
            "effective_n method=single_config n_eff=1.0 cardinality=%d", cardinality
        )
        return 1.0

    hashes, matrix = _aligned_return_matrix(returns_matrix)
    pr = _participation_ratio(matrix)

    if pr is None:
        method = "fallback_primary_axis"
        n_eff = float(primary_levels) * FALLBACK_AXIS_FACTOR
        n_eff = min(max(n_eff, 1.0), float(n_configs))
        logger.warning(
            "effective_n method=%s n_eff=%.4f cardinality=%d primary_levels=%d "
            "reason=degenerate_correlation_matrix",
            method,
            n_eff,
            cardinality,
            primary_levels,
        )
    else:
        method = "participation_ratio"
        # The PR is computed over the configs that had valid returns; clamp to the FULL
        # cardinality (configs dropped for no-dispersion still count as trials placed).
        n_eff = min(max(pr, 1.0), float(n_configs))
        near_card = n_eff >= NEAR_CARDINALITY_WARN_FRAC * cardinality and cardinality >= 2
        log = logger.warning if near_card else logger.info
        log(
            "effective_n method=%s n_eff=%.4f cardinality=%d valid_configs=%d%s",
            method,
            n_eff,
            cardinality,
            len(hashes),
            " NEAR_CARDINALITY_independent_looking" if near_card else "",
        )

    assert 1.0 <= n_eff <= float(n_configs), (
        f"effective_n guard violated: {n_eff} not in [1, {n_configs}]"
    )
    return n_eff


def cumulative_effective_n(
    rounds: Sequence[Mapping[str, Sequence[float]]],
    *,
    primary_levels: int,
) -> float:
    """Effective de-correlated trial count over the UNION of ALL configs across ALL rounds.

    HQ's refinement: per-round N_eff is for the coarse PRUNE; the FINAL champion's DSR deflates
    by the CUMULATIVE effective-N over every config tried across round-1 + round-2 + refine.
    We UNION the per-round return-maps (later rounds override an earlier duplicate config_hash —
    a re-run of the same config is the same trial, not a new one) and run the SAME participation
    ratio over the union. Computed independently of the per-round values so the caller can log
    both and confirm cumulative >= any single round (the union is at least as wide).
    """
    if not rounds:
        raise ValueError("cumulative_effective_n needs at least one round")
    union: dict[str, Sequence[float]] = {}
    for rnd in rounds:
        union.update(rnd)  # later round wins on a duplicate hash (same trial, re-run)
    logger.info(
        "cumulative_effective_n n_rounds=%d union_configs=%d", len(rounds), len(union)
    )
    return effective_n(union, primary_levels=primary_levels)


# --------------------------------------------------------------------------- #
# Evidence assembly (per-config ConfigEvidence for the selector).
# --------------------------------------------------------------------------- #
def _stitch_daily_returns(rows: Sequence[dict[str, Any]]) -> list[float]:
    """Concatenate a config's per-window daily_returns into one stitched series (window order).

    Rows are ordered by window_name for determinism. A row may omit daily_returns (the FIRE
    checkpoint allows it) — that window contributes nothing to the DSR series (but its net_pct
    still feeds the window-level gates). The stitched series is the config's pooled daily P&L.
    """
    stitched: list[float] = []
    for row in sorted(rows, key=lambda r: r["window_name"]):
        dr = row.get("daily_returns") or []
        stitched.extend(float(x) for x in dr)
    return stitched


def _combined_curve_metrics(rows: Sequence[dict[str, Any]]) -> tuple[float, float, int]:
    """(ann_return, max_dd, n_trades) from a config's stitched daily-return curve + orders.

    ann_return: compounded total return of the stitched daily series (geometric), reported as a
    fraction (not annualised across calendar — the panel IS the sample; "ann" here is the
    Calmar numerator the selector expects, return-over-DD). max_dd: peak-to-trough magnitude
    (>= 0) of the cumulative equity curve. n_trades: total orders across windows.
    """
    daily = _stitch_daily_returns(rows)
    n_trades = sum(int(r["orders"]) for r in rows)
    if not daily:
        # No daily curve → fall back to summing window net_pct (a coarse total return); DD
        # unknown from a curve we don't have, so 0.0 (Calmar guards a zero DD → 0.0).
        total_ret = sum(float(r["net_pct"]) for r in rows) / 100.0
        return total_ret, 0.0, n_trades
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in daily:
        equity *= 1.0 + r
        peak = max(peak, equity)
        if peak > 0.0:
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)
    total_ret = equity - 1.0
    return total_ret, max_dd, n_trades


def _config_windows(rows: Sequence[dict[str, Any]]) -> tuple[WindowReturns, ...]:
    """Per-window WindowReturns for the gates: ret = window net_pct (fraction), is_oos flag.

    `n_trades` per window = that window's order count. `ret` is net_pct / 100 (the gates and
    concentration guard work in return fractions; net_pct is a percentage). Window order is by
    window_name for determinism. The window's [start,end] is unknown from the checkpoint, so we
    use the window_name for all three Window fields (the gates only read `.name`).
    """
    out: list[WindowReturns] = []
    for row in sorted(rows, key=lambda r: r["window_name"]):
        name = row["window_name"]
        out.append(
            WindowReturns(
                window=Window(name=name, start=name, end=name),
                n_trades=int(row["orders"]),
                ret=float(row["net_pct"]) / 100.0,
                is_oos=bool(row["is_oos"]),
            )
        )
    return tuple(out)


def assemble_evidence(
    results: Mapping[str, Sequence[dict[str, Any]]],
    *,
    n_trials: float,
) -> tuple[list[ConfigEvidence], dict[str, list[float]]]:
    """Build one ConfigEvidence per config from the per-(config,window) checkpoint rows.

    Per config:
      - dsr: PSR of the config's stitched daily-return Sharpe vs expected_max_sharpe(n_trials,
        variance_of_per-config-Sharpes-across-configs). DSR is the #323 PRIMARY selector input.
      - ann_return / max_dd: from the config's combined (stitched) equity curve.
      - n_trades: total orders across windows.
      - windows: tuple[WindowReturns] (ret = window net%, is_oos from the row).

    `n_trials` is the EFFECTIVE (de-correlated) trial count — pass the CUMULATIVE N_eff for the
    final champion's deflation (the multiple-comparisons bar is the whole search). Returns the
    evidence list AND the stitched-returns map (config_hash → daily series) so the caller can
    build the PBO matrix from the SAME series without re-stitching.

    Raises if a config has zero windows (a structurally-empty result — never silently scored).
    """
    if not results:
        raise ValueError("assemble_evidence: no configs to score")

    stitched_by_config: dict[str, list[float]] = {}
    sharpes: dict[str, float] = {}
    for h, rows in results.items():
        if not rows:
            raise ValueError(f"config {h} has no window rows — cannot score an empty config")
        daily = _stitch_daily_returns(rows)
        stitched_by_config[h] = daily
        sharpes[h] = dsr_mod.sharpe_ratio(daily) if len(daily) >= 2 else 0.0

    # Variance of the per-config Sharpe estimates ACROSS configs — the DSR multiple-trials term.
    sharpe_values = list(sharpes.values())
    if len(sharpe_values) >= 2:
        mean_s = sum(sharpe_values) / len(sharpe_values)
        var_across = sum((s - mean_s) ** 2 for s in sharpe_values) / len(sharpe_values)
    else:
        var_across = 0.0

    n_trials_int = max(1, int(round(n_trials)))
    evidence: list[ConfigEvidence] = []
    for h, rows in results.items():
        daily = stitched_by_config[h]
        if len(daily) >= 2:
            config_dsr = dsr_mod.deflated_sharpe(
                daily,
                n_trials=n_trials_int,
                sharpe_variance_across_trials=var_across,
            )
        else:
            # No daily curve to estimate a Sharpe → DSR is undefined; 0.0 (will fail the DSR
            # filter, kept on the leaderboard as a reject — never imputed to a passing value).
            config_dsr = 0.0
        ann_return, max_dd, n_trades = _combined_curve_metrics(rows)
        evidence.append(
            ConfigEvidence(
                config_hash=h,
                dsr=config_dsr,
                pbo=0.0,  # per-config slot; the sweep-global PBO is broadcast in select()
                ann_return=ann_return,
                max_dd=max_dd,
                n_trades=n_trades,
                windows=_config_windows(rows),
            )
        )
    return evidence, stitched_by_config


# --------------------------------------------------------------------------- #
# Sweep-global PBO over the config × per-period (daily-return) matrix.
# --------------------------------------------------------------------------- #
# WIRING ASSUMPTION (for the orchestrator to reconcile): the prompt phrases the PBO input as a
# "config × window-returns matrix". CSCV (pbo.py) partitions the T OBSERVATIONS into n_splits
# contiguous blocks and computes a per-SLICE Sharpe — it is a PER-PERIOD estimator that needs
# many observations to be informative (with only 6 calendar windows the IS/OS Sharpe over 3
# observations is pure noise → PBO pins near 0.5 regardless of edge). The statistically sound
# per-period axis the sweep already produces is the STITCHED DAILY-RETURN series (~240 obs).
# So `_sweep_pbo` builds the config × stitched-daily-return matrix (the pbo module's documented
# "per-period returns"), aligned by index to the common min length. The window dimension still
# governs the GATES (trade-count + concentration) per-config; PBO is the per-period overfitting
# measure across the whole sweep.
def _pbo_return_matrix(
    stitched_by_config: Mapping[str, Sequence[float]],
) -> dict[str, list[float]]:
    """config_hash → stitched daily-return series, aligned by index to the common min length.

    Configs with < 2 returns are dropped (no per-period signal for CSCV). All kept series are
    truncated to the shortest common length T so every config shares one time axis (pbo.py
    requires equal-length series). Returns an empty mapping if < 2 configs survive.
    """
    valid = {h: list(r) for h, r in stitched_by_config.items() if len(r) >= 2}
    if len(valid) < 2:
        return {}
    t = min(len(r) for r in valid.values())
    return {h: r[:t] for h, r in valid.items()}


def _sweep_pbo(stitched_by_config: Mapping[str, Sequence[float]]) -> float | None:
    """Sweep-global CSCV PBO over the config × stitched-daily-return matrix. None if not computable.

    PBO needs >= 2 configs and n_obs >= n_splits (n_splits even). We adapt n_splits down to the
    largest even number <= n_obs (>= 2). With too few observations (< 2) PBO is undefined → None
    (the caller surfaces it; the PBO filter is then UNKNOWN, never fabricated to a passing 0).
    """
    matrix = _pbo_return_matrix(stitched_by_config)
    if len(matrix) < 2:
        return None
    n_obs = len(next(iter(matrix.values())))
    if n_obs < 2:
        return None
    n_splits = min(16, n_obs)
    if n_splits % 2 != 0:
        n_splits -= 1
    if n_splits < 2:
        return None
    return cscv_pbo(matrix, n_splits=n_splits).pbo


# --------------------------------------------------------------------------- #
# Top-level scoring.
# --------------------------------------------------------------------------- #
def score_sweep(
    results: Mapping[str, Sequence[dict[str, Any]]],
    *,
    champion_score: float | None,
    primary_levels: int,
    prior_round_returns: Sequence[Mapping[str, Sequence[float]]] = (),
    degraded: Mapping[str, RunResult] | None = None,
) -> tuple[list[ObjectiveScore], dict[str, Any]]:
    """Score a whole sweep → (ranked leaderboard, diagnostics).

    Pipeline:
      1. Assemble per-config stitched returns; compute PER-ROUND N_eff (this round's configs)
         and CUMULATIVE N_eff (union of this round + `prior_round_returns`). The champion DSR
         deflates by the CUMULATIVE count (the whole-search multiple-comparisons bar).
      2. assemble_evidence(results, n_trials=cumulative_n_eff).
      3. Sweep-global CSCV PBO over the config × window-return matrix.
      4. selector.select(evidence, pbo, champion_score) → ranked ObjectiveScores.

    `champion_score` — the #321 cost-aware champion_intraday score under THIS objective (None →
    must_beat_champion stays UNKNOWN, never fabricated). `primary_levels` drives the N_eff
    fallback. `prior_round_returns` — earlier rounds' {config_hash: daily series} for the
    cumulative union. `degraded` — any config_hash → degraded RunResult: FAILS LOUD (a degraded
    run is NEVER scored, G-DATA gate #261/#270).

    Returns the ranked leaderboard (passing configs first, then rejects) + a diagnostics dict:
    {n_eff_per_round, n_eff_cumulative, pbo, champion_score, n_configs, n_passing, n_rejected,
     objective_n_trials}.
    """
    if degraded:
        bad = sorted(h for h, rr in degraded.items() if rr.is_degraded)
        if bad:
            raise ValueError(
                f"refusing to score: degraded RunResult(s) present for configs {bad} "
                "(a degraded run is NEVER scored — G-DATA gate, #261/#270). Re-run those "
                "backtests; do not impute."
            )

    if not results:
        raise ValueError("score_sweep: no results to score")

    # 1. Effective-N (per-round + cumulative).
    this_round_returns = {
        h: _stitch_daily_returns(rows) for h, rows in results.items()
    }
    n_eff_round = effective_n(this_round_returns, primary_levels=primary_levels)
    n_eff_cumulative = cumulative_effective_n(
        [*prior_round_returns, this_round_returns],
        primary_levels=primary_levels,
    )

    # 2. Evidence — the champion's DSR deflates by the CUMULATIVE count.
    evidence, stitched_by_config = assemble_evidence(results, n_trials=n_eff_cumulative)

    # 3. Sweep-global PBO over the config × stitched-daily-return matrix.
    pbo = _sweep_pbo(stitched_by_config)
    if pbo is None:
        # Undefined PBO (too few configs with a per-period series). The selector's filter
        # requires a numeric PBO; surface this loud rather than fabricate a passing 0.0.
        raise ValueError(
            "sweep PBO is not computable (need >= 2 configs each with >= 2 daily returns). "
            "Cannot run the #323 PBO filter — checkpoint coverage is too thin to score."
        )

    # 4. Select + rank.
    leaderboard = select(evidence, pbo=pbo, champion_score=champion_score)

    n_passing = sum(1 for s in leaderboard if s.filter_verdict.passed)
    diagnostics = {
        "n_eff_per_round": n_eff_round,
        "n_eff_cumulative": n_eff_cumulative,
        "objective_n_trials": max(1, int(round(n_eff_cumulative))),
        "pbo": pbo,
        "champion_score": champion_score,
        "n_configs": len(results),
        "n_passing": n_passing,
        "n_rejected": len(leaderboard) - n_passing,
    }
    logger.info(
        "score_sweep done configs=%d passing=%d rejected=%d n_eff_round=%.3f "
        "n_eff_cumulative=%.3f pbo=%.4f champion_score=%s",
        diagnostics["n_configs"],
        n_passing,
        diagnostics["n_rejected"],
        n_eff_round,
        n_eff_cumulative,
        pbo,
        champion_score,
    )
    return leaderboard, diagnostics
