"""Build a run's funnel.json from /backtests/read.runtimeStatistics (#303 substrate).

The per-run signal->order funnel rides QC runtimeStatistics (set_runtime_statistic at run-time,
keys `funnel.*`). It is NOT in result.json's stats — this is the separate decomposition channel
the #303 mine reads for per-regime attrition. QC purges backtests within hours, so this MUST run
soon after the BT completes. Writes results/archive/<config_hash>/<backtest_id>/funnel.json in the
exact format the other regimes use (funnel + funnel_semantics legend + name + note).

Usage: python3 scripts/build_funnel_json.py <config_hash> <backtest_id> <name>
  e.g. python3 scripts/build_funnel_json.py fd8248b34265 5fe8ea69... substrate-fy2020

Fail-loud: if no funnel.* keys are retrieved (purged / not emitted) it RAISES — never writes an
empty/faked funnel (a missing funnel is reported, never silently zeroed).
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))
import qc_v2_cloud as q  # noqa: E402

ARCHIVE = _ROOT / "results" / "archive"

# the distinct-vs-candidate_days semantics legend — stable across runs (matches the committed
# regimes' funnel.json). Counter base-name -> unit.
FUNNEL_SEMANTICS = {
    "signal_winners": "daily",
    "regime_pass": "daily",
    "regime_blocked_days": "daily",
    "injection_survives": "distinct",
    "preflight_pass": "distinct",
    "gap_eligible": "candidate_days",
    "confirm_fire": "candidate_days",
    "cash_ok": "candidate_days",
    "sized": "candidate_days",
    "orders": "fire",
}


def build(config_hash, backtest_id, name):
    run_dir = ARCHIVE / config_hash / backtest_id
    if not run_dir.is_dir():
        raise SystemExit(f"no run dir: {run_dir}")
    pid = q.ensure_project()  # resolve PID (idempotent) — never pass a None projectId
    bt = q.post("/backtests/read", {"projectId": pid, "backtestId": backtest_id}).get("backtest", {})
    rt = bt.get("runtimeStatistics", {}) or {}
    # funnel.* counters ONLY — exclude the funnel._sem.* legend keys (those are the unit legend,
    # carried separately in funnel_semantics; leaving them in `funnel` pollutes the counter set).
    funnel = {k: v for k, v in rt.items() if k.startswith("funnel.") and not k.startswith("funnel._sem.")}
    if not funnel:
        raise SystemExit(
            f"NO funnel.* keys in runtimeStatistics for {backtest_id} "
            f"(purged or not emitted) — refusing to write an empty funnel.json"
        )
    doc = {
        "backtest_id": backtest_id,
        "funnel": dict(sorted(funnel.items())),
        "funnel_semantics": FUNNEL_SEMANTICS,
        "name": name,
        "note": ("per-run funnel decomposition from /backtests/read.runtimeStatistics "
                 "(captured post-run before purge); distinct vs candidate_days per funnel_semantics"),
    }
    out = run_dir / "funnel.json"
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}: {len(funnel)} funnel counters")
    for k, v in sorted(funnel.items()):
        print(f"  {k} = {v}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: build_funnel_json.py <config_hash> <backtest_id> <name>")
    build(sys.argv[1], sys.argv[2], sys.argv[3])
