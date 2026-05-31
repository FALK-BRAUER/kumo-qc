"""Entry-selection phase: the methodology §4 Gate 2 ENTRY CONFIRMATION (the P&L unlock).

Kind: entry_selection
Marker: bct_entry_confirm_v1
Tested params: macd 12/26/9 (frozen-canonical), volume_gate_mult=1.0, tenkan_pullback_tol=0.005,
  flat_eps=0.002, gap_up_threshold=0.01, min_confirm=2 (phase-1 reference defaults)
Sweep space (space()): tenkan_pullback_tol x flat_eps x volume_gate_mult x gap_up_threshold x
  min_confirm — the genuinely-sweepable axes (grid 3^5 = 243). macd_fast/macd_slow/macd_signal
  are ALL frozen-canonical 12/26/9 (§2 "NOT per-ticker optimized"; macd_signal's old sweep was
  also INERT — the indicator is built 12/26/9 and the phase never read it — so it was dropped).
Complexity (COMPLEXITY): 5 free params (the five swept axes).

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

The 4 components (canonical §2; C2 reads the latest DAILY OHLC bar — HQ #253-P1 ruling):
  C1 Regime    live price above daily cloud AND Tenkan > Kijun -> BULL.
  C2 T-Bounce  ALL of: (a) NOT below Tenkan >3 sessions (was-above / not a downtrend bounce);
               (b) PULLBACK = the daily LOW touched/penetrated Tenkan OR sits <= tenkan_pullback_tol
                   ABOVE it (a CEILING — a deeper touch is BETTER, never rejected);
               (c) BOUNCE = bullish close (close>open) OR lower-wick rejection (lower_wick >=
                   0.5*candle_range);
               (d) T > K; (e) NOT inside the cloud. Degraded -> DON'T count if: below Tenkan >3
               sessions / Tenkan flat (|T/K-1|<=flat_eps OR T<K) / gap-up (open vs prior close >
               gap_up_threshold, Rule #10).
  C3 MACD      12/26/9 daily (frozen-canonical): CONFIRM if hist >= 0 (positive OR FLAT both
               count) OR (hist < 0 AND turning up = divergence). FAIL ONLY if hist < 0 AND turning
               down/flat. (flat is a sizing nuance, NOT a gate fail — HQ FLAG 3.)
  C4 Volume    entry candle volume >= volume_gate_mult x 20-day avg (GATE = 1.0x; 1.5x is the
               full-SIZE tier, NOT the gate — GH#253 correction of the original 1.5x summary).

SCOPE GUARD (phase-1): this phase carries Gate-2 SCORING only. Gate-1 (rule compliance: rating
>= ++, falling-knife, scheduled-event, gap-up) and Gate-4 (resistance-proximity block) are
SEPARATE entry_selection VARIANTS for phase-2 (#148 ResistanceZone, #150 RiskReward, #64
DojiDelay). Gate-5 day-type order mechanics live in entry_timing (phase-2 BuyStop/LimitPullback).
Do NOT cram them here (GH#253 phase-1 scope guard).

HQ RULINGS APPLIED (the 5 flags, now RESOLVED — was FLAGGED for HQ, ruled #253-P1):
  - FLAG 1 (C2b pullback) = a CEILING (not a floor-band): daily LOW <= Tenkan OR within
    <= tenkan_pullback_tol ABOVE Tenkan. A closer/deeper touch always counts.
  - FLAG 5 (C2c bounce) = the literal daily candle: bullish close OR lower-wick rejection
    (lower_wick = min(open,close)-low >= 0.5*(high-low)), replacing the old close>=Tenkan proxy.
  - FLAG 2 (C2 Tenkan-flat degrade) = T≈K proximity: |T/K-1| <= flat_eps (default 0.2%) OR T<K.
  - FLAG 4 (C2 degrades) = sessions_below_tenkan > 3 (downtrend) + gap-up open-vs-prior-close >
    gap_up_threshold (default 1%, NOT 5%).
  - FLAG 3 (C3) = positive OR FLAT confirm; negative-turning-up confirms; only negative-turning-
    down/flat fails. (Positive-flat / zero-flat now CONFIRM — was incorrectly failing.)

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
    daily_open: float,
    daily_high: float,
    daily_low: float,
    daily_close: float,
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
    flat_eps: float,
    volume_gate_mult: float,
    gap_up_threshold: float,
) -> ComponentScore:
    """Pure §4 Gate-2 component scorer (the golden-mastered core — NO QC objects).

    C2 reads the latest DAILY OHLC BAR (HQ #253-P1 ruling — NOT the live close-snapshot): the
    pullback is a daily-LOW touch and the bounce is a daily-candle test. Every input is a plain
    float/int hand-computable in a fixture; the phase's evaluate() reads them from the maintained
    indicator suite (d_ichi + the TBounceTracker's last daily bar) and calls here. Pure = the
    methodology golden-master is a unit test (no QC mocks in the assertion path).

    `price` (the live price) drives C1's price-vs-cloud and C2(e) not-in-cloud; the DAILY bar
    drives C2(b)/C2(c). (C1's price-vs-cloud keeps the live price for consistency with the signal
    scorer's live-price conditions.)
    """
    # --- C1 Regime: price above the daily cloud AND Tenkan > Kijun (BULL). ---
    c1 = bool(price > d_cloud_top and d_tenkan > d_kijun)

    # --- C2 T-Bounce: read the DAILY OHLC bar; ALL sub-conditions + the degrade guards. ---
    # (a) was above Tenkan recently (not a downtrend bounce): NOT below Tenkan >3 sessions (FLAG 4).
    was_above = sessions_below_tenkan <= 3
    # (b) FLAG 1 — pullback is a CEILING (not a floor-band): the daily LOW touched/penetrated the
    #     Tenkan, OR sits within <= tenkan_pullback_tol ABOVE it. A closer/deeper touch is BETTER
    #     (never rejected). low <= tenkan OR (low - tenkan)/tenkan <= tol.
    pullback = d_tenkan > 0.0 and (
        daily_low <= d_tenkan or (daily_low - d_tenkan) / d_tenkan <= tenkan_pullback_tol
    )
    # (c) FLAG 5 — literal daily-candle bounce: bullish close (close>open) OR a lower-wick
    #     rejection (lower_wick >= 0.5 * candle_range). lower_wick = min(open,close) - low.
    candle_range = daily_high - daily_low
    lower_wick = min(daily_open, daily_close) - daily_low
    bounced = bool(
        daily_close > daily_open
        or (candle_range > 0.0 and lower_wick >= 0.5 * candle_range)
    )
    # (d) T > K.
    t_over_k = d_tenkan > d_kijun
    # (e) NOT inside the cloud (live price vs the daily cloud).
    not_in_cloud = not (d_cloud_bottom <= price <= d_cloud_top)
    # FLAG 2 — "Tenkan flattened" = T≈K proximity (or T<K): degrade (don't count C2) if
    #   |tenkan/kijun - 1| <= flat_eps OR tenkan < kijun.
    tenkan_flat = d_kijun > 0.0 and (abs(d_tenkan / d_kijun - 1.0) <= flat_eps or d_tenkan < d_kijun)
    # FLAG 4 — gap-up degrade: today's open vs PRIOR daily close > gap_up_threshold (HQ default 1%).
    large_gap_up = gap_up_frac > gap_up_threshold
    c2 = bool(
        was_above and pullback and bounced and t_over_k and not_in_cloud
        and not tenkan_flat and not large_gap_up
    )

    # --- C3 MACD 12/26/9 (FLAG 3): "flat" is a sizing nuance, NOT a gate fail. ---
    # CONFIRM if hist >= 0 (positive OR flat both count) OR (hist < 0 AND turning up = divergence).
    # FAIL ONLY if hist < 0 AND not turning up (negative turning down/flat).
    if macd_hist_now >= 0.0:
        c3 = True  # positive OR flat-at/above-zero -> confirm (flat is a size nuance, not a fail)
    elif macd_hist_now > macd_hist_prev:
        c3 = True  # negative but turning up = momentum divergence -> confirm
    else:
        c3 = False  # negative AND turning down/flat = the only failing MACD state

    # --- C4 Volume: entry candle >= volume_gate_mult x 20-day avg (GATE = 1.0x). ---
    c4 = bool(vol_avg20 > 0.0 and volume >= volume_gate_mult * vol_avg20)

    return ComponentScore(c1_regime=c1, c2_tbounce=c2, c3_macd=c3, c4_volume=c4)


class BctEntryConfirm(BasePhase):
    PHASE_KIND = "entry_selection"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]  # GATES the signal's stubs in place

    # ADR D5 overfitting-defense: 5 swept axes (== space() axes). macd_fast/macd_slow/macd_signal
    # are ALL frozen-canonical 12/26/9 (§2 "NOT per-ticker optimized") so they are NOT free params.
    # (#253-P1: macd_signal DROPPED from the sweep — it was inert anyway: the MACD indicator is
    # built with a literal 12/26/9 in lean_entry and the phase never read Params.macd_signal, so
    # sweeping it burned 3x budget for a no-op. Now frozen like macd_fast/macd_slow.)
    COMPLEXITY = ComplexityDecl(
        free_params=5,
        note="tenkan_pullback_tol + flat_eps + volume_gate_mult + gap_up_threshold + min_confirm.",
    )

    @dataclass(slots=True)
    class Params:
        macd_fast: int = 12          # canonical (NOT swept)
        macd_slow: int = 26          # canonical (NOT swept)
        macd_signal: int = 9         # canonical (NOT swept — #253-P1 dropped the inert axis)
        volume_gate_mult: float = 1.0
        tenkan_pullback_tol: float = 0.005   # C2(b) pullback CEILING above Tenkan (0.5%)
        flat_eps: float = 0.002              # C2 Tenkan-flat degrade: |T/K-1| <= flat_eps (0.2%)
        gap_up_threshold: float = 0.01       # C2 gap-up degrade: open vs prior close > 1% (Rule #10)
        min_confirm: int = 2                 # qualify >= 2/4 (regime+volume mandatory)
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            """Sweepable axes of the §4 Gate-2 trigger (ADR D2). 5 axes -> grid 3x3x3x3x3 = 243.

            tenkan_pullback_tol: the C2(b) pullback CEILING — how far ABOVE Tenkan the daily LOW
              may sit and still count as a touch (0.3%/0.5%/0.8%; a deeper touch always counts).
            flat_eps: the C2 Tenkan-flat degrade band — |T/K-1| <= flat_eps degrades C2 (0.1/0.2/0.5%).
            volume_gate_mult: the C4 gate multiple (1.0 canonical gate; 1.25/1.5 toward full-SIZE).
            gap_up_threshold: the C2 gap-up degrade — open vs prior close above this degrades C2
              (0.5%/1%/2%; HQ default 1%).
            min_confirm: the X/4 qualify floor (2 canonical; 3 = 75%-size-tier gate, 4 = full-only).
            macd_fast/macd_slow/macd_signal are NOT axes (frozen canonical 12/26/9 — §2 forbids
              per-ticker MACD opt; macd_signal's sweep was also inert, so it is dropped).
            """
            return ParamSpace(
                axes={
                    "tenkan_pullback_tol": (0.003, 0.005, 0.008),
                    "flat_eps": (0.001, 0.002, 0.005),
                    "volume_gate_mult": (1.0, 1.25, 1.5),
                    "gap_up_threshold": (0.005, 0.01, 0.02),
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
        tbounce = ind.get("tbounce")  # the maintained T-Bounce tracker (last daily OHLC + degrade)
        if d_ichi is None or macd is None or vol_sma20 is None or macd_hist_window is None:
            return None
        if not (d_ichi.is_ready and macd.is_ready and vol_sma20.is_ready):
            return None
        if macd_hist_window.count < 2:
            return None
        # C2 reads the latest DAILY OHLC bar from the tracker (HQ #253-P1). No bar yet -> decline.
        if tbounce is None or tbounce.last_close is None:
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

        return evaluate_gate2(
            price=price,
            daily_open=float(tbounce.last_open),
            daily_high=float(tbounce.last_high),
            daily_low=float(tbounce.last_low),
            daily_close=float(tbounce.last_close),
            d_tenkan=d_tenkan,
            d_kijun=d_kijun,
            d_cloud_top=d_cloud_top,
            d_cloud_bottom=d_cloud_bottom,
            macd_hist_now=macd_hist_now,
            macd_hist_prev=macd_hist_prev,
            volume=volume,
            vol_avg20=vol_avg20,
            sessions_below_tenkan=int(tbounce.sessions_below_tenkan),
            gap_up_frac=float(tbounce.gap_up_frac),
            tenkan_pullback_tol=self.p.tenkan_pullback_tol,
            flat_eps=self.p.flat_eps,
            volume_gate_mult=self.p.volume_gate_mult,
            gap_up_threshold=self.p.gap_up_threshold,
        )

    @property
    def version_marker(self) -> str:
        return "bct_entry_confirm_v1"
