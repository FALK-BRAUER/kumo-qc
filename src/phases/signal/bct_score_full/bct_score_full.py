"""Signal phase: BCT 8-condition score + pre-filter + parabolic block + dollar-vol tiebreak.

Kind: signal
Marker: bct_score_full_v1
Tested params: min_score=7, parabolic_threshold=0.25 (champion-asis-v1)
Sweep space (space()): min_score in (6,7,8) x parabolic_threshold in (0.20,0.25,0.30,0.35) — grid 12.
Complexity (COMPLEXITY): 2 free params (min_score, parabolic_threshold).
Charter: single code path, no count caps, no time exits. Faithful carve of oracle
_rebalance L527-590 (baseline-oracle-v0). Reads ranked_candidates from universe phase,
writes sized_orders (qty=0 stubs for the sizing phase).

Methodology (the in-project canonical BCT Signal Stack — CLAUDE.md): this phase = the
SIGNAL/QUALIFY phase ("does the name qualify"). The 8-condition Blue Flag checklist is
scored by score_symbol_native (phases.shared.oracle_helpers); FIRE = score>=min_score AND
not parabolic AND not invested/pre-filtered; DECLINE otherwise. The component<->condition
mapping + golden-master fixtures live in research/methodology/bct-signal-reconciliation.md.
Entry TIMING (T-Bounce / MACD / volume) is a SEPARATE downstream phase, NOT this one.

DO NOT modify evaluate() logic — breaks champion-asis-v1 parity (ARCH-C ±0.01 gate).

Changelog:
  v1  carve of oracle _rebalance L527-590 (8-condition score, pre-filter, parabolic, DV tiebreak).
  #228  + space()/COMPLEXITY template patterns + methodology golden-master (NO scoring change).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.symbol_key import canonical_symbol_key
from engine.context import OrderIntent, PhaseContext
from phases.shared.oracle_helpers import score_symbol_cached, score_symbol_native
from phases.shared.param_space import ComplexityDecl, ParamSpace


class BctScoreFull(BasePhase):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM = ["universe"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    # ADR D5 overfitting-defense: this phase exposes 2 free params to a sweep (== space() axes).
    # The runner sums COMPLEXITY.free_params across the active stack into a complexity penalty.
    COMPLEXITY = ComplexityDecl(
        free_params=2,
        note="min_score (qualify threshold) + parabolic_threshold (overextension block).",
    )

    @dataclass(slots=True)
    class Params:
        min_score: int = 7
        parabolic_threshold: float = 0.25
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            """Sweepable axes of this phase's params (ADR D2 — THE template `space()`).

            Returns a typed ParamSpace: a mapping of swept `.Params` field name -> the explicit,
            finite Sequence of candidate values. `enabled` is NOT swept (it is a wiring toggle,
            not a strategy axis). Grid cardinality = 3 x 4 = 12. Keep this in lockstep with
            COMPLEXITY.free_params (ComplexityDecl.validate enforces it).

            min_score: 6 (=++, looser), 7 (champion), 8 (=+++, strictest 8/8 only).
            parabolic_threshold: the maintained 13-day ROC ceiling above which an
              over-extended name is blocked (0.20..0.35 spans the plausible band).
            """
            return ParamSpace(
                axes={
                    "min_score": (6, 7, 8),
                    "parabolic_threshold": (0.20, 0.25, 0.30, 0.35),
                }
            )

    def __init__(self, params: "BctScoreFull.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        min_score = self.p.min_score
        parabolic_threshold = self.p.parabolic_threshold

        # Resolve candidates from universe phase (list of ticker strings)
        candidates_raw = ctx.bar_state.ranked_candidates  # list of str symbol values

        # Build symbol lookup from qc._active
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}  # #276b-1 FIX3

        # #238: dollar-volume tiebreak from the LIVE per-ticker trailing-mean DV
        # (qc._trailing_dv, computed once-daily by lean_entry._coarse_selection), NOT the
        # retired qc._eligible artifact and NOT a per-bar qc.history(20) — keeps on_data
        # history-free. Keys are lowercase (zip stems / coarse value lowered); candidate
        # tickers are canonical (upper).
        trailing_dv = getattr(qc, "_trailing_dv", {})

        candidates: list[tuple[Any, int, float]] = []  # (symbol, score, dollar_volume)
        blocked_log: list[str] = []
        # #348 feature-capture fix: stamp each winner's score + 8 conditions HERE, at signal-PASS,
        # keyed by symbol. The daily→intraday snapshot reads these instead of RE-scoring (which threw
        # for ~5/36 entries incl the biggest winners HOOD/GLW → context_status=CORE_MISSING, blind
        # winners). These ARE the values the signal selected on (native or cached path) → authoritative
        # by construction, no drift. Learn-substrate metadata only — NOT a trade gate (the snapshot
        # score gates nothing; H1 checks existence+date, preflight uses price/kijun) → trade-identical.
        signal_feats: dict[Any, dict[str, Any]] = {}

        # #332 warmup-cache CONSUMPTION (flag-ON): when lean_entry has loaded qc._warmup_cache (and
        # skipped SetWarmUp), score from the cached scalars for (symbol, today) instead of the live
        # qc._indicators. Decision-NEUTRAL by construction — same pre-filter / score_symbol_cached
        # (== native, proven by the 1000-tuple drift gate) / parabolic logic on the same scalar values
        # (== live indicators, proven by the golden ports + the end-to-end gate). flag-OFF (no cache
        # attr) leaves the live path below BYTE-UNTOUCHED.
        cache = getattr(qc, "_warmup_cache", None)
        cur_date = ctx.time.date() if cache is not None else None

        # #348 DECISION TRACE (flag-gated; default OFF → live path byte-untouched). When the
        # BCTAlgorithm.DECISION_TRACE class-attr is set (SWEEP_CLASS_ATTRS for an instrumentation run),
        # emit one DECISIONTRACE log line per SCORED candidate (post pre-filter) recording its signal
        # fate (passed / sub_min_score / parabolic) + score → the NON-TRADES substrate (which scored
        # names did/didn't survive the signal gate, parsed post-hoc from the local bt log.txt).
        _trace_on = bool(getattr(qc, "DECISION_TRACE", False))
        _trace_date = ctx.time.date()
        _trace_log = getattr(qc, "log", None)

        def _trace(tk: str, fate: str, score: Any = None) -> None:
            if _trace_on and callable(_trace_log):
                _trace_log(f"DECISIONTRACE|{_trace_date}|{tk}|{fate}|{'' if score is None else int(score)}")

        for ticker in candidates_raw:
            symbol = active_by_key.get(canonical_symbol_key(ticker))
            if symbol is None:
                continue
            if qc.portfolio[symbol].invested:
                continue
            if qc.transactions.get_open_orders(symbol):
                continue

            if cache is not None:
                scalars = cache.get(symbol.value, {}).get(cur_date)
                if scalars is None:
                    continue  # no cached row for (symbol, today) == live "indicator not ready" → skip
                price = scalars["d_price"]
                if price <= 0 or price < scalars["ma200"] or price < scalars["d_cloud_top"]:
                    continue  # pre-filter: cond8/cond5 can't reach min_score → skip (mirrors live)
                result = score_symbol_cached(scalars)
                if result["score"] < min_score:
                    _trace(ticker, "sub_min_score", result["score"])
                    continue
                if scalars["roc13"] > parabolic_threshold:  # E51 parabolic block (cached roc13)
                    blocked_log.append(ticker)
                    _trace(ticker, "parabolic", result["score"])
                    continue
                _trace(ticker, "passed", result["score"])
                signal_feats[symbol] = {"score": int(result["score"]),
                                        "conditions": [bool(c) for c in result.get("conditions", [])]}
                candidates.append((symbol, result["score"], float(trailing_dv.get(ticker.lower(), 0.0))))
                continue

            ind = getattr(qc, "_indicators", {}).get(symbol)
            if ind is None:
                continue

            # PRE-FILTER: skip symbols that cannot reach MIN_SCORE=7
            # Mirrors oracle L538-551 exactly
            sma200_ind = ind.get("sma200")
            d_ichi_ind = ind.get("d_ichi")
            if sma200_ind and sma200_ind.is_ready and d_ichi_ind and d_ichi_ind.is_ready:
                price = float(qc.securities[symbol].price)
                if price <= 0:
                    continue
                if price < sma200_ind.current.value:
                    continue  # condition 8 fails → max score 6 → skip
                cloud_top = max(d_ichi_ind.senkou_a.current.value, d_ichi_ind.senkou_b.current.value)
                if price < cloud_top:
                    continue  # condition 5 fails → max score 6 → skip

            # BCT score
            result = score_symbol_native(qc, symbol, ind)
            if result is None or result["score"] < min_score:
                _trace(ticker, "sub_min_score", result["score"] if result else None)
                continue

            # E51: Parabolic entry block — skip if the maintained 13-day ROC exceeds the
            # threshold. #213f: roc13 (maintained) replaces the per-bar qc.history(14).
            # roc(13) = (price - price[13-back])/price[13-back] == legacy parabolic, by
            # construction (a decimal fraction, comparable to parabolic_threshold).
            roc13 = ind.get("roc13")
            if roc13 is not None and roc13.is_ready and roc13.current.value > parabolic_threshold:
                blocked_log.append(ticker)
                _trace(ticker, "parabolic", result["score"])
                continue

            _trace(ticker, "passed", result["score"])
            # Dollar-volume tiebreak from the live trailing DV (no per-bar history). 0.0 if absent.
            dollar_volume = float(trailing_dv.get(ticker.lower(), 0.0))

            signal_feats[symbol] = {"score": int(result["score"]),
                                    "conditions": [bool(c) for c in result.get("conditions", [])]}
            candidates.append((symbol, result["score"], dollar_volume))

        # #348: publish the pass-time features for the snapshot to read (fresh each daily decision).
        qc._signal_features = signal_feats

        # Sort: score DESC, dollar_vol DESC — matches oracle L589-590
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)

        # Write as OrderIntent stubs (qty=0, sizing phase sets qty)
        ctx.bar_state.sized_orders = [
            OrderIntent(
                ticker=sym.value,
                qty=0,
                price=float(qc.securities[sym].price),
                stop=0.0,
                module="signal.bct_score_full",
                risk_dollars=0.0,
            )
            for sym, score, _dv in candidates
        ]

        return PhaseResult(
            decision=candidates,
            blocked=False,
            reason=f"{len(candidates)} candidates scored ≥{min_score}, {len(blocked_log)} parabolic blocks",
            facts={"candidate_count": len(candidates), "parabolic_blocked": len(blocked_log)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "bct_score_full_v1"
