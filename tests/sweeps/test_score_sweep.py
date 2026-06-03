"""Sweep-scoring tests (#276b) — effective-N control, cumulative-N, evidence, full scoring.

FIXTURES ONLY — ZERO cloud, ZERO LEAN. Every input is a hand-built checkpoint row dict or a
synthetic return matrix so the participation-ratio + DSR/PBO wiring is asserted exactly.
"""
from __future__ import annotations

import hashlib
import json
import logging

import numpy as np
import pytest

from sweeps.objective.selector import FILTER
from sweeps.score_sweep import (
    FALLBACK_AXIS_FACTOR,
    assemble_evidence,
    cumulative_effective_n,
    effective_n,
    load_checkpoint,
    score_sweep,
)
from sweeps.types import ResultMetrics, RunResult


# --------------------------------------------------------------------------- #
# Fixtures: synthetic correlated / orthogonal return matrices.
# --------------------------------------------------------------------------- #
def _identical_matrix(n_configs: int = 3, t: int = 200) -> dict[str, list[float]]:
    """n_configs configs sharing the SAME return series → maximally correlated (N_eff ≈ 1)."""
    rng = np.random.default_rng(0)
    base = rng.normal(0.001, 0.01, size=t).tolist()
    return {f"c{i}": list(base) for i in range(n_configs)}


def _orthogonal_matrix(n_configs: int = 3, t: int = 400) -> dict[str, list[float]]:
    """n_configs INDEPENDENT return series → near-orthogonal (N_eff ≈ n_configs)."""
    rng = np.random.default_rng(42)
    return {f"c{i}": rng.normal(0.0, 0.01, size=t).tolist() for i in range(n_configs)}


# --------------------------------------------------------------------------- #
# effective_n — participation ratio on known matrices.
# --------------------------------------------------------------------------- #
def test_effective_n_identical_configs_collapse_to_one() -> None:
    """3 identical configs de-correlate to N_eff ≈ 1 (one effective trial)."""
    n_eff = effective_n(_identical_matrix(3), primary_levels=3)
    assert n_eff == pytest.approx(1.0, abs=0.05)


def test_effective_n_orthogonal_configs_recover_cardinality() -> None:
    """3 orthogonal configs keep N_eff ≈ 3 (each is its own independent trial)."""
    n_eff = effective_n(_orthogonal_matrix(3), primary_levels=3)
    assert n_eff == pytest.approx(3.0, abs=0.4)


def test_effective_n_never_exceeds_cardinality_or_falls_below_one() -> None:
    """The hard guard: 1 <= N_eff <= n_configs across both regimes."""
    for mat in (_identical_matrix(4), _orthogonal_matrix(4)):
        n_eff = effective_n(mat, primary_levels=2)
        assert 1.0 <= n_eff <= 4.0


def test_effective_n_single_config_is_one() -> None:
    n_eff = effective_n({"only": [0.01, -0.01, 0.02, 0.0]}, primary_levels=1)
    assert n_eff == 1.0


# --- fallback path (degenerate matrix) --- #
def test_effective_n_fallback_when_fewer_than_two_valid_configs() -> None:
    """Only one config has >= 2 returns → degenerate → conservative primary-axis fallback.

    fallback = clamp(primary_levels * FALLBACK_AXIS_FACTOR, 1, n_configs).
    """
    mat = {"a": [0.01, -0.01, 0.02], "b": [0.0]}  # b has < 2 returns
    n_eff = effective_n(mat, primary_levels=1)
    expected = min(max(1 * FALLBACK_AXIS_FACTOR, 1.0), 2.0)  # clamp to n_configs=2
    assert n_eff == pytest.approx(expected)


def test_effective_n_fallback_on_zero_variance_row() -> None:
    """A flat (zero-variance) config makes corrcoef degenerate → fallback path, not a crash."""
    mat = {"a": [0.01, -0.01, 0.02, 0.0], "b": [0.005, 0.005, 0.005, 0.005]}
    n_eff = effective_n(mat, primary_levels=2)
    # fallback = clamp(2 * 3, 1, 2) = 2
    assert n_eff == pytest.approx(2.0)


# --- guards: assert + structured log --- #
def test_effective_n_logs_method_and_cardinality(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="sweeps.score_sweep"):
        effective_n(_identical_matrix(3), primary_levels=3)
    rec = [r for r in caplog.records if "method=participation_ratio" in r.getMessage()]
    assert rec, "effective_n must structured-log the method + cardinality"
    assert "cardinality=3" in rec[0].getMessage()


def test_effective_n_warns_near_cardinality(caplog) -> None:
    """Orthogonal configs (N_eff ≈ cardinality) trip the suspicious-independence WARNING."""
    with caplog.at_level(logging.WARNING, logger="sweeps.score_sweep"):
        effective_n(_orthogonal_matrix(3), primary_levels=3)
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("NEAR_CARDINALITY" in r.getMessage() for r in warns)


def test_effective_n_empty_raises() -> None:
    with pytest.raises(ValueError):
        effective_n({}, primary_levels=1)


# --------------------------------------------------------------------------- #
# cumulative_effective_n — union >= per-round.
# --------------------------------------------------------------------------- #
def test_cumulative_exceeds_per_round_on_disjoint_union() -> None:
    """Two rounds of distinct orthogonal configs → cumulative N_eff > either round alone."""
    rng = np.random.default_rng(7)
    round1 = {f"r1_{i}": rng.normal(0, 0.01, 300).tolist() for i in range(3)}
    round2 = {f"r2_{i}": rng.normal(0, 0.01, 300).tolist() for i in range(3)}
    per_round = effective_n(round1, primary_levels=3)
    cumulative = cumulative_effective_n([round1, round2], primary_levels=3)
    assert cumulative > per_round
    assert cumulative == pytest.approx(6.0, abs=1.0)  # 6 independent trials


def test_cumulative_dedupes_rerun_configs() -> None:
    """A config re-run in a later round is the SAME trial — union dedupes by hash."""
    rng = np.random.default_rng(11)
    shared = {f"c{i}": rng.normal(0, 0.01, 300).tolist() for i in range(3)}
    cumulative = cumulative_effective_n([shared, dict(shared)], primary_levels=3)
    single = effective_n(shared, primary_levels=3)
    assert cumulative == pytest.approx(single, abs=0.01)


def test_cumulative_empty_raises() -> None:
    with pytest.raises(ValueError):
        cumulative_effective_n([], primary_levels=1)


# --------------------------------------------------------------------------- #
# load_checkpoint — drops error rows, fails loud on malformed.
# --------------------------------------------------------------------------- #
def _row(h: str, w: str, *, is_oos=False, sharpe=1.0, net=5.0, dd=3.0, orders=20,
         daily=None, error=None) -> dict:
    return {
        "config_hash": h, "window_name": w, "is_oos": is_oos, "sharpe": sharpe,
        "net_pct": net, "dd_pct": dd, "orders": orders,
        "daily_returns": daily if daily is not None else [], "error": error,
    }


def test_load_checkpoint_drops_error_rows(tmp_path) -> None:
    p = tmp_path / "ckpt.jsonl"
    p.write_text(
        json.dumps(_row("a", "w1")) + "\n"
        + json.dumps(_row("a", "w2", error="LEAN crashed")) + "\n"
        + json.dumps(_row("b", "w1")) + "\n"
    )
    loaded = load_checkpoint(p)
    assert set(loaded.keys()) == {"a", "b"}
    assert len(loaded["a"]) == 1  # the error row dropped, never imputed
    assert len(loaded["b"]) == 1


def test_load_checkpoint_malformed_json_fails_loud(tmp_path) -> None:
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps(_row("a", "w1")) + "\n{not json}\n")
    with pytest.raises(ValueError, match="malformed JSON"):
        load_checkpoint(p)


def test_load_checkpoint_missing_key_fails_loud(tmp_path) -> None:
    p = tmp_path / "incomplete.jsonl"
    p.write_text(json.dumps({"config_hash": "a", "window_name": "w1"}) + "\n")
    with pytest.raises(ValueError, match="missing required keys"):
        load_checkpoint(p)


# --------------------------------------------------------------------------- #
# assemble_evidence — shape + content.
# --------------------------------------------------------------------------- #
def _seed(h: str) -> int:
    """Deterministic per-config seed (Python's str hash is per-process salted — never use it)."""
    return int(hashlib.sha256(h.encode()).hexdigest()[:8], 16)


def _robust_config_rows(h: str, *, win_net=5.0, orders=20) -> list[dict]:
    """5 FY2025 bimonthly windows + 1 FY2024 OOS — passes the gates by construction.

    A genuine positive daily edge (mean 0.001, low noise) shared across configs so the
    sweep-global PBO of a robust sweep sits LOW (the in-sample winner stays good out-of-sample).
    Seeded deterministically so PBO/DSR are reproducible run-to-run.
    """
    rng = np.random.default_rng(_seed(h))
    rows = []
    for i in range(5):
        rows.append(_row(h, f"w{i}", net=win_net, orders=orders,
                         daily=rng.normal(0.0012, 0.006, 40).tolist()))
    rows.append(_row(h, "oos_fy2024", is_oos=True, net=win_net * 0.8, orders=orders,
                     daily=rng.normal(0.0012, 0.006, 40).tolist()))
    return rows


def _edge_config_rows(h: str, *, mu: float, sigma: float, win_net: float,
                      orders: int = 20) -> list[dict]:
    """5 panel + 1 OOS windows with a parameterised daily edge (mu/sigma).

    A high-mu / low-sigma config DOMINATES (wins IS and OS → low sweep PBO + high DSR); a
    low-mu / high-sigma config is weak (loses the DSR filter). This lets a fixture build a sweep
    with a clear champion + weak field — the structure that yields a LOW sweep-global PBO and a
    real survivor (uniform / indistinguishable configs give PBO ~0.9 by construction: the IS
    winner is noise).
    """
    rng = np.random.default_rng(_seed(h))
    rows = [
        _row(h, f"w{i}", net=win_net, orders=orders, daily=rng.normal(mu, sigma, 40).tolist())
        for i in range(5)
    ]
    rows.append(_row(h, "oos_fy2024", is_oos=True, net=win_net * 0.8, orders=orders,
                     daily=rng.normal(mu, sigma, 40).tolist()))
    return rows


def _dominant_field(n_weak: int = 5) -> dict[str, list[dict]]:
    """A sweep with ONE dominant config ('champ') + n_weak weak-but-positive configs.

    The champ wins IS and OS → sweep PBO ≈ 0 and champ clears the full #323 filter; the weak
    field fails the DSR gate (kept on the leaderboard as rejects). Deterministically seeded.
    """
    field = {"champ": _edge_config_rows("champ", mu=0.0025, sigma=0.004, win_net=8.0)}
    for i in range(n_weak):
        field[f"weak{i:02d}"] = _edge_config_rows(f"weak{i:02d}", mu=0.0004, sigma=0.006,
                                                  win_net=4.0)
    return field


def test_assemble_evidence_shape() -> None:
    results = {"a": _robust_config_rows("a"), "b": _robust_config_rows("b")}
    evidence, stitched = assemble_evidence(results, n_trials=2.0)
    assert {e.config_hash for e in evidence} == {"a", "b"}
    for e in evidence:
        assert len(e.windows) == 6  # 5 panel + 1 OOS
        assert any(w.is_oos for w in e.windows)
        assert e.n_trades == 20 * 6
        assert 0.0 <= e.dsr <= 1.0
        assert len(stitched[e.config_hash]) == 40 * 6


def test_assemble_evidence_empty_config_fails_loud() -> None:
    with pytest.raises(ValueError, match="no window rows"):
        assemble_evidence({"a": []}, n_trials=1.0)


def test_assemble_evidence_dsr_deflates_with_more_trials() -> None:
    """Same returns, larger n_trials → lower DSR (the multiple-comparisons correction bites)."""
    results = {"a": _robust_config_rows("a"), "b": _robust_config_rows("b")}
    ev_few, _ = assemble_evidence(results, n_trials=1.0)
    ev_many, _ = assemble_evidence(results, n_trials=500.0)
    dsr_few = {e.config_hash: e.dsr for e in ev_few}["a"]
    dsr_many = {e.config_hash: e.dsr for e in ev_many}["a"]
    assert dsr_many <= dsr_few


# --------------------------------------------------------------------------- #
# score_sweep — degraded fails loud; sane leaderboard; concentration bites.
# --------------------------------------------------------------------------- #
def test_score_sweep_degraded_result_fails_loud() -> None:
    results = {"a": _robust_config_rows("a"), "b": _robust_config_rows("b")}
    degraded = {
        "a": RunResult(metrics=ResultMetrics(0.0, 0.0, 0.0, 0), is_degraded=True),
    }
    with pytest.raises(ValueError, match="degraded"):
        score_sweep(results, champion_score=None, primary_levels=2, degraded=degraded)


def test_score_sweep_returns_ranked_leaderboard_and_diagnostics() -> None:
    results = _dominant_field(n_weak=5)  # 1 champ + 5 weak = 6 configs
    leaderboard, diag = score_sweep(results, champion_score=None, primary_levels=6)
    assert len(leaderboard) == 6
    assert {s.config_hash for s in leaderboard} == set(results.keys())
    # diagnostics shape
    for k in ("n_eff_per_round", "n_eff_cumulative", "pbo", "champion_score",
              "n_configs", "n_passing", "n_rejected", "objective_n_trials"):
        assert k in diag
    assert diag["n_configs"] == 6
    assert 1.0 <= diag["n_eff_per_round"] <= 6.0
    assert diag["n_eff_cumulative"] >= diag["n_eff_per_round"] - 1e-9
    assert 0.0 <= diag["pbo"] <= 1.0
    # The dominant config survives the full filter and tops the leaderboard.
    assert diag["n_passing"] >= 1
    assert leaderboard[0].config_hash == "champ"
    assert leaderboard[0].filter_verdict.passed
    # passing configs sort before rejects, and by descending score.
    passing = [s for s in leaderboard if s.filter_verdict.passed]
    scores = [s.score for s in passing]
    assert scores == sorted(scores, reverse=True)
    # rejects all sit AFTER the last passing config.
    last_pass = max(i for i, s in enumerate(leaderboard) if s.filter_verdict.passed)
    assert all(not s.filter_verdict.passed for s in leaderboard[last_pass + 1:])


def test_score_sweep_concentration_reject_bites_single_window_carried() -> None:
    """A config whose return is carried by ONE window is REJECTED-concentration; a robust one
    passes the concentration gate. Both share the sweep so PBO/N_eff are computable."""
    rng = np.random.default_rng(3)

    def _carried_rows(h: str) -> list[dict]:
        rows = []
        # five near-flat panel windows + one huge window = single-window-carried.
        nets = [0.1, 0.1, 0.1, 0.1, 0.1]
        for i, net in enumerate(nets):
            rows.append(_row(h, f"w{i}", net=net, orders=20,
                             daily=rng.normal(0.0, 0.005, 40).tolist()))
        rows.append(_row(h, "w5_big", net=30.0, orders=20,
                         daily=rng.normal(0.01, 0.005, 40).tolist()))
        # OOS positive so the OOS leg of the guard isn't what trips it.
        rows.append(_row(h, "oos_fy2024", is_oos=True, net=2.0, orders=20,
                         daily=rng.normal(0.001, 0.005, 40).tolist()))
        return rows

    results = {
        "robust0": _robust_config_rows("robust0", win_net=5.0),
        "robust1": _robust_config_rows("robust1", win_net=6.0),
        "robust2": _robust_config_rows("robust2", win_net=7.0),
        "carried": _carried_rows("carried"),
    }
    leaderboard, _ = score_sweep(results, champion_score=None, primary_levels=4)
    by_hash = {s.config_hash: s for s in leaderboard}
    # The single-window-carried config is rejected, and the FIRST failing gate (lexicographic:
    # concentration precedes PBO) is the W5-concentration guard — exactly the #323 robustness
    # rejection. Its score is zeroed but it stays on the leaderboard with its reason.
    assert not by_hash["carried"].filter_verdict.passed
    assert "concentration" in by_hash["carried"].filter_verdict.reason
    assert by_hash["carried"].score == 0.0
    # Every config is retained (rejects kept for transparency).
    assert set(by_hash) == {"robust0", "robust1", "robust2", "carried"}


def test_score_sweep_champion_beat_wired_through() -> None:
    """champion_score flows to must_beat_champion on passing configs (the #321 hook)."""
    results = _dominant_field(n_weak=5)
    lb_unknown, _ = score_sweep(results, champion_score=None, primary_levels=6)
    assert all(s.must_beat_champion is None for s in lb_unknown)
    lb_low_bar, _ = score_sweep(results, champion_score=-99.0, primary_levels=6)
    passing = [s for s in lb_low_bar if s.filter_verdict.passed]
    assert passing and all(s.must_beat_champion is True for s in passing)


def test_score_sweep_empty_raises() -> None:
    with pytest.raises(ValueError, match="no results"):
        score_sweep({}, champion_score=None, primary_levels=1)
