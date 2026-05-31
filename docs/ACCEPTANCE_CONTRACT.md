# Acceptance Contract — machine-enforced gate criteria

Single source of truth for the gate criteria the PR / CI process enforces automatically.
Each criterion below maps to an **enforcer** (a CI check or an assertion). If it is not
enforced by code, it is not a gate — it is a wish.

This file is the deliverable of issue **#203** (the consolidated acceptance contract) and is
referenced from [ARCHITECTURE.md](ARCHITECTURE.md) §7. The full intended tier structure
(Tier 1 per-result, Tier 2 per-phase PR / #194, Tier 3 harness fidelity / #183, Tier 4
champion gates G1–G5, Tier 5 process) lives in #203; sections are codified here as their
enforcers land. The **SDLC liveness gate (#244-D)** is codified below.

---

## Liveness gate (#244-D) — anti-0-trades / anti-turnover-collapse

The liveness gate catches a **silent stop-trading regression**: a change that makes the
strategy fire zero (or near-zero) orders without any test failing. It has two arms — a fast
per-PR arm and a periodic full-FY arm.

### Per-PR arm (fast, pytest-collected — CI workflow PENDING, #194 follow-up)

These tests are READY and run in the standard `pytest` collection, but no `.github/workflows/`
exists yet (see the flag below), so nothing runs `pytest` on a PR today — a failing liveness
test cannot turn a PR red until the CI workflow lands. The gate is real + ready; it is just not
AUTOMATED yet.

| Criterion | Enforcer | Fail action |
|---|---|---|
| The real `champion_asis` CONFIG fires `orders > 0` on a triggering bar | `tests/acceptance/test_liveness.py::test_champion_config_fires_orders` (drives the real CONFIG through `StrategyEngine` on the #247 FakeQC harness) | pytest fails → PR-red ONCE the CI workflow lands |
| A deliberately-dead config (impossible `min_score=99`) fires ZERO orders | `::test_dead_config_fires_zero_orders` | pytest fails → PR-red ONCE the CI workflow lands |
| The SAME gate function (`assert_liveness`) that passes the champion FAILS on the dead config | `::test_liveness_gate_catches_dead_config` | pytest fails → PR-red ONCE the CI workflow lands |

The shared `assert_liveness(order_count)` gate (raises `LivenessError` on `order_count <= 0`)
is exercised by BOTH the champion (passes) and the dead config (fails). The 0-trades guard is
the load-bearing bit: it proves the gate would actually catch a regression to 0, rather than
an `orders > 0` assertion that could pass for the wrong reason. This is fast (no docker, no
backtest) and runs in the standard `pytest` collection — see CI wiring below.

### Periodic arm (full-FY, nightly / manual — NOT per-PR)

A full-FY2025 backtest is minutes + docker, so the trade-count band is checked **periodically**,
not on every PR.

- **Recorded baseline** (mainV2 `25b79d6`, full-FY2025 local): **75 orders / 32 round-trips**
  (Sharpe −0.616 / +3.899% / 3.4% DD) — the verified current behavior.
- **Band:** FAIL if `Total Orders < 50%` of baseline (**< 37**) OR round-trips collapse
  (**< 16**). This is a floor+band, **NOT a hard `== 75` pin** (that would break on every
  legitimate #228 signal change). Intent = catch a silent regression to 0 / turnover collapse,
  without freezing the strategy.
- **Enforcer:** `scripts/check_liveness_band.py <summary.json>` (exit 1 on a band breach). Its
  `check_band` logic is unit-tested in `tests/acceptance/test_liveness.py` (baseline passes;
  0 / sub-floor orders fail).

#### Periodic runbook

```bash
# 1. Produce a full-FY2025 LEAN summary JSON (serialized local runner).
kumo bt run algorithm/performance_bct --parameter <full-FY2025 params>
#    -> writes algorithm/performance_bct/backtests/<ts>/<id>-summary.json

# 2. Assert the trade-count band on that summary.
python scripts/check_liveness_band.py \
  algorithm/performance_bct/backtests/<ts>/<id>-summary.json
#    exit 0 = within band ; exit 1 = collapse (anti-0 / anti-turnover-collapse)
```

Run nightly or manually (e.g. before promoting a champion / after a signal change). A
scheduled CI workflow to run this automatically is a **follow-up** (see below) — it is not
wired here because no `.github/workflows/` exists in the repo yet and a full-FY BT needs the
docker LEAN runner + the local data substrate, which the per-PR CI does not provision.

---

## CI wiring (#194)

The per-PR liveness arm lives under `tests/acceptance/` and is collected by the standard
`pytest` run (`pytest.ini`: `testpaths = tests`). Any CI invocation of `pytest` over `tests/`
runs the liveness + 0-trades guard automatically — no separate check-list entry is needed.

> **Flag (#244-D STEP 0 finding):** there is currently **no `.github/workflows/` file in the
> repo** — #194 ("7-check merge gate") is CLOSED but the GitHub Actions workflow that would run
> these checks is not committed. The per-PR liveness test is collected by `pytest` and is ready
> to run the moment a CI workflow runs `pytest tests/`. **Standing up the actual CI workflow
> (and a scheduled job for the periodic band check) is a follow-up, tracked separately.**
