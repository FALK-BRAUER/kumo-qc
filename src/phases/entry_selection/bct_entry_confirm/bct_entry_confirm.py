"""Entry-selection phase: the methodology §4 Gate 2 ENTRY CONFIRMATION (the P&L unlock).

Kind: entry_selection
Marker: bct_entry_confirm_v1
Tested params: macd_fast=12, macd_slow=26, macd_signal=9, volume_gate_mult=1.0,
  tenkan_pullback_tol=0.005, min_confirm=2 (phase-1 reference defaults)
Sweep space (space()): tenkan_pullback_tol x volume_gate_mult x macd_signal x min_confirm —
  the genuinely-sweepable axes (grid 3x3x3x3 = 81). macd_fast/macd_slow are NOT swept (the
  canonical 12/26 are fixed by the methodology — sweeping them = per-ticker MACD optimization,
  which §2 Component 3 explicitly forbids: "12/26/9 daily, NOT per-ticker optimized").
Complexity (COMPLEXITY): 4 free params (the four swept axes).

METHODOLOGY (the bible — strategy/methodology.md §2 Components 1-4 + §4 Gate 2, fintrack repo;
authoritative spec pinned in GH#253 comment). This is the ENTRY TRIGGER the qualifier lacked:
#228 proved the SIGNAL scorer already matches methodology, so the -0.616 blind-entry Sharpe is
NOT a broken scorer — a qualified name was bought BLIND at next open with no entry trigger. This
phase GATES the qualified+ranked candidates (signal phase output) so a name FIRES only on a
CONFIRMED entry.

Gate 2 is SCORED X/4, NOT binary (GH#253 correction): count how many of the 4 components
confirm. Qualify rule = score >= min_confirm (default 2) AND regime(C1) pass AND volume(C4)
pass (the two MANDATORY gates). The X/4 score is emitted to qc._entry_confirm[ticker] +
PhaseResult.facts so a downstream methodology sizer (signal_quality x regime_size x volume_size)
can consume it; phase-1 baseline sizing (flat_pct_heatcap) ignores it — the GATE is the behavior.

The 4 components (canonical §2):
  C1 Regime    price above daily cloud AND Tenkan > Kijun -> BULL.
  C2 T-Bounce  ALL of: (a) price was above Tenkan (not a downtrend bounce); (b) pullback within
               tenkan_pullback_tol of Tenkan; (c) bounced (lower wick OR bullish close);
               (d) T > K; (e) NOT inside the cloud. Degraded -> DON'T count (below Tenkan >3
               sessions / Tenkan flattened / first test after a large gap-up — Rule #10).
  C3 MACD      12/26/9 daily (NOT per-ticker optimized): hist positive+turning-up = confirm;
               positive-flat = confirm (valid); negative-turning-up = confirm (half/divergence);
               negative-turning-down = NO (the one MACD state that fails the component).
  C4 Volume    entry candle volume >= volume_gate_mult x 20-day avg (GATE = 1.0x; 1.5x is the
               full-SIZE tier, NOT the gate — GH#253 correction of the original 1.5x summary).

SCOPE GUARD (phase-1): this phase carries Gate-2 SCORING only. Gate-1 (rule compliance: rating
>= ++, falling-knife, scheduled-event, gap-up) and Gate-4 (resistance-proximity block) are
SEPARATE entry_selection VARIANTS for phase-2 (#148 ResistanceZone, #150 RiskReward, #64
DojiDelay). Gate-5 day-type order mechanics live in entry_timing (phase-2 BuyStop/LimitPullback).
Do NOT cram them here (GH#253 phase-1 scope guard).

CANONICAL-SOURCE FLAGS (could not byte-confirm against the bible from this repo — implemented to
the GH#253 authoritative comment + standard defs; flagged for HQ's canonical §4 Gate 2):
  - C2 (b) the literal pullback tolerance: §2 states "0.3-0.5% of Tenkan". Implemented as a
    SINGLE symmetric band |price/tenkan - 1| <= tenkan_pullback_tol (default 0.005 = 0.5%, the
    band's upper edge). Whether the bible means a 0.3..0.5 RANGE (reject closer than 0.3%) vs a
    <=0.5% ceiling is the one C2 nuance to confirm — FLAGGED.
  - C2 degraded "Tenkan flattened (~Kijun or crossing below)": "~Kijun" needs a numeric epsilon;
    used tenkan within tenkan_pullback_tol of kijun as the flat proxy. FLAGGED.
  - C3 "turning-up / turning-down / flat" thresholds: used strict hist[0] vs hist[1] sign-of-
    delta (flat = exactly equal). The bible's flat tolerance (if any) is FLAGGED.
  - C2 "large gap-up (Rule #10)" magnitude + "below Tenkan >3 sessions" session count: used the
    methodology-stated >3 sessions and a gap_up_threshold (default 0.05) for the degrade. FLAGGED.

Charter: single code path (reads maintained qc._indicators O(1)/candidate, NO per-bar history),
no count caps / time exits / fixed slots, RAW. GOLDEN-MASTERED to the §4 Gate 2 + §2 component
spec on hand-spec fixtures (assert exact X/4 + each component pass/fail). Reconciliation artifact:
research/methodology/bct-entry-confirm-reconciliation.md.

Changelog:
  v1  methodology §4 Gate 2 entry-confirmation gate (C1-C4 X/4 scoring, >=min_confirm w/
      regime+volume mandatory), reading the maintained indicator suite (d_ichi/macd/vol_sma20 +
      the tbounce/macd-hist rolling windows).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.shared.param_space import ComplexityDecl, ParamSpace


@dataclass(slots=True)
class ComponentScore:
    """The per-candidate §4 Gate-2 evaluation: the 4 component booleans + the X/4 count + the
    two mandatory-gate flags (regime C1, volume C4) the qualify rule keys on."""

    c1_regime: bool
    c2_tbounce: bool
    c3_macd: bool
    c4_volume: bool

    @property
    def score(self) -> int:
        return int(self.c1_regime) + int(self.c2_tbounce) + int(self.c3_macd) + int(self.c4_volume)

    def qualifies(self, min_confirm: int) -> bool:
        """Qualify rule (§4 Gate 2): score >= min_confirm AND regime + volume both pass
        (the two MANDATORY components — a 2/4 that misses either is DO-NOT-ENTER)."""
        return self.score >= min_confirm and self.c1_regime and self.c4_volume


def evaluate_gate2(
    *,
    price: float,
    d_tenkan: float,
    d_kijun: float,
    d_cloud_top: float,
    d_cloud_bottom: float,
    macd_hist_now: float,
    macd_hist_prev: float,
    volume: float,
    vol_avg20: float,
    sessions_below_tenkan: int,
    gap_up_frac: float,
    tenkan_pullback_tol: float,
    volume_gate_mult: float,
    gap_up_threshold: float,
) -> ComponentScore:
    """Pure §4 Gate-2 component scorer (the golden-mastered core — NO QC objects).

    Every input is a plain float/int hand-computable in a fixture; the phase's evaluate() reads
    them from the maintained indicator suite and calls here. Keeping this pure is what makes the
    methodology golden-master a unit test (no QC mocks in the assertion path).
    """
    # --- C1 Regime: price above the daily cloud AND Tenkan > Kijun (BULL). ---
    c1 = bool(price > d_cloud_top and d_tenkan > d_kijun)

    # --- C2 T-Bounce: ALL sub-conditions, with the degraded-state guards. ---
    # (a) was above Tenkan recently (not a bounce off a downtrend): NOT below Tenkan >3 sessions.
    was_above = sessions_below_tenkan <= 3
    # (b) pullback within tolerance of Tenkan (touched the line).
    near_tenkan = d_tenkan > 0.0 and abs(price / d_tenkan - 1.0) <= tenkan_pullback_tol
    # (c) bounced: a bullish reclaim — price back at/above Tenkan (close held/reversed up).
    bounced = price >= d_tenkan
    # (d) T > K.
    t_over_k = d_tenkan > d_kijun
    # (e) NOT inside the cloud.
    not_in_cloud = not (d_cloud_bottom <= price <= d_cloud_top)
    # Degraded guards (don't count C2): Tenkan flattened (~Kijun) or a large gap-up first test.
    tenkan_flat = d_kijun > 0.0 and abs(d_tenkan / d_kijun - 1.0) <= tenkan_pullback_tol
    large_gap_up = gap_up_frac >= gap_up_threshold
    c2 = bool(
        was_above and near_tenkan and bounced and t_over_k and not_in_cloud
        and not tenkan_flat and not large_gap_up
    )

    # --- C3 MACD 12/26/9: only negative-AND-turning-down fails. ---
    hist_positive = macd_hist_now > 0.0
    turning_up = macd_hist_now > macd_hist_prev
    turning_down = macd_hist_now < macd_hist_prev
    # positive (turning-up OR flat) = confirm; negative-turning-up = confirm (divergence/half);
    # negative-turning-down = NO. Flat-at/below-zero with no positive momentum -> NO.
    if hist_positive:
        c3 = True
    elif turning_up:
        c3 = True  # negative but turning up = momentum divergence, half-confirm counts
    else:
        c3 = False  # negative-turning-down (or negative-flat) = the failing state
    _ = turning_down  # readability: the explicit failing branch is the else above

    # --- C4 Volume: entry candle >= volume_gate_mult x 20-day avg (GATE = 1.0x). ---
    c4 = bool(vol_avg20 > 0.0 and volume >= volume_gate_mult * vol_avg20)

    return ComponentScore(c1_regime=c1, c2_tbounce=c2, c3_macd=c3, c4_volume=c4)


class BctEntryConfirm(BasePhase):
    PHASE_KIND = "entry_selection"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]  # GATES the signal's stubs in place

    # ADR D5 overfitting-defense: 4 swept axes (== space() axes). macd_fast/macd_slow are NOT
    # swept (canonical 12/26, per §2 "NOT per-ticker optimized") so they are NOT free params.
    COMPLEXITY = ComplexityDecl(
        free_params=4,
        note="tenkan_pullback_tol + volume_gate_mult + macd_signal + min_confirm.",
    )

    @dataclass(slots=True)
    class Params:
        macd_fast: int = 12          # canonical (NOT swept)
        macd_slow: int = 26          # canonical (NOT swept)
        macd_signal: int = 9         # canonical default; swept (signal-line smoothing)
        volume_gate_mult: float = 1.0
        tenkan_pullback_tol: float = 0.005   # 0.5% = §2 pullback band upper edge
        gap_up_threshold: float = 0.05       # large-gap-up degrade (Rule #10)
        min_confirm: int = 2                 # qualify >= 2/4 (regime+volume mandatory)
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            """Sweepable axes of the §4 Gate-2 trigger (ADR D2). 4 axes -> grid 3x3x3x3 = 81.

            tenkan_pullback_tol: the C2 pullback band (0.3%/0.5%/0.8% — tighter = stricter touch).
            volume_gate_mult: the C4 gate multiple (1.0 canonical gate; 1.25/1.5 toward the
              full-SIZE tier — sweeps how strong the volume confirmation must be).
            macd_signal: the C3 signal-line smoothing (8/9/12 — 9 canonical; fast/slow stay fixed).
            min_confirm: the X/4 qualify floor (2 canonical; 3 = 75%-size-tier gate, 4 = full-only).
            macd_fast/macd_slow are NOT axes (canonical 12/26 — §2 forbids per-ticker MACD opt).
            """
            return ParamSpace(
                axes={
                    "tenkan_pullback_tol": (0.003, 0.005, 0.008),
                    "volume_gate_mult": (1.0, 1.25, 1.5),
                    "macd_signal": (8, 9, 12),
                    "min_confirm": (2, 3, 4),
                }
            )

    def __init__(self, params: "BctEntryConfirm.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        p = self.p
        date_str = ctx.time.strftime("%Y-%m-%d")

        active_by_value = {s.value: s for s in getattr(qc, "_active", set())}
        indicators = getattr(qc, "_indicators", {})

        # Per-symbol X/4 score for a downstream methodology sizer (phase-1 sizer ignores it).
        confirm_scores: dict[str, int] = {}
        qc._entry_confirm = confirm_scores  # publish the gate scores (single source)

        confirmed: list[OrderIntent] = []
        declined = 0

        for intent in ctx.bar_state.sized_orders:
            sym = active_by_value.get(intent.ticker)
            if sym is None:
                declined += 1
                continue
            ind = indicators.get(sym)
            cs = self._score_candidate(qc, sym, ind)
            if cs is None:
                # indicators not ready -> cannot CONFIRM an entry -> decline (gate is strict).
                declined += 1
                continue
            confirm_scores[intent.ticker] = cs.score
            if cs.qualifies(p.min_confirm):
                confirmed.append(intent)
            else:
                declined += 1

        ctx.bar_state.sized_orders = confirmed
        return PhaseResult(
            decision=confirmed,
            blocked=False,  # entry_selection GATES candidates; it does not block the bar
            reason=(
                f"{len(confirmed)} entry-confirmed (>={p.min_confirm}/4 w/ regime+volume), "
                f"{declined} declined [{date_str}]"
            ),
            facts={
                "confirmed": len(confirmed),
                "declined": declined,
                "scores": dict(confirm_scores),
            },
            metrics={},
        )

    def _score_candidate(self, qc: Any, sym: Any, ind: dict[str, Any] | None) -> ComponentScore | None:
        """Read the maintained indicator suite for `sym` and run the pure Gate-2 scorer.

        Returns None if the indicators needed are absent/not-ready (the phase then declines —
        an unconfirmable candidate is not entered). NO per-bar history (single code path)."""
        if ind is None:
            return None
        d_ichi = ind.get("d_ichi")
        macd = ind.get("macd")
        vol_sma20 = ind.get("vol_sma20")
        macd_hist_window = ind.get("macd_hist_window")
        tbounce = ind.get("tbounce")  # the maintained T-Bounce state tracker (sessions/gap)
        if d_ichi is None or macd is None or vol_sma20 is None or macd_hist_window is None:
            return None
        if not (d_ichi.is_ready and macd.is_ready and vol_sma20.is_ready):
            return None
        if macd_hist_window.count < 2:
            return None

        try:
            price = float(qc.securities[sym].price)
            volume = float(qc.securities[sym].volume)
        except Exception:
            return None
        if price <= 0.0:
            return None

        d_tenkan = d_ichi.tenkan.current.value
        d_kijun = d_ichi.kijun.current.value
        d_cloud_top = max(d_ichi.senkou_a.current.value, d_ichi.senkou_b.current.value)
        d_cloud_bottom = min(d_ichi.senkou_a.current.value, d_ichi.senkou_b.current.value)
        macd_hist_now = macd_hist_window[0]
        macd_hist_prev = macd_hist_window[1]
        vol_avg20 = vol_sma20.current.value

        # T-Bounce degrade inputs from the maintained tracker (sessions below Tenkan + gap-up).
        sessions_below_tenkan = int(getattr(tbounce, "sessions_below_tenkan", 0)) if tbounce else 0
        gap_up_frac = float(getattr(tbounce, "gap_up_frac", 0.0)) if tbounce else 0.0

        return evaluate_gate2(
            price=price,
            d_tenkan=d_tenkan,
            d_kijun=d_kijun,
            d_cloud_top=d_cloud_top,
            d_cloud_bottom=d_cloud_bottom,
            macd_hist_now=macd_hist_now,
            macd_hist_prev=macd_hist_prev,
            volume=volume,
            vol_avg20=vol_avg20,
            sessions_below_tenkan=sessions_below_tenkan,
            gap_up_frac=gap_up_frac,
            tenkan_pullback_tol=self.p.tenkan_pullback_tol,
            volume_gate_mult=self.p.volume_gate_mult,
            gap_up_threshold=self.p.gap_up_threshold,
        )

    @property
    def version_marker(self) -> str:
        return "bct_entry_confirm_v1"
