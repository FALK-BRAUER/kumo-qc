"""Intraday-selectivity grid (#323) — the declarative sweep space.

This is the GRID ENUMERATOR the #323 sweep runs. It produces a list of `SweepConfig`s
(the RunConfig Protocol's input) over REAL, EXISTING phase params.

GRID REFINEMENT (order-density mine + HQ, 2026-06-02 — supersedes the original gap-emphasis):
the mine REFUTED gap-SIZE as the separator (W1 loser median gap 4.27% ≈ W5 winner 4.22%); the
real lever is SIGNAL-SCORE STRICTNESS + entries-density. So the PRIMARY axis is now the
signal phase's `min_score`, gap is DE-EMPHASISED, and the regime axes stay minimal/off-biased.

Why a sweep-local grid (not just `enumerate_product` over `space()`)?
  - The phase `space()` is the drift-proof per-phase surface. This grid is a SWEEP-DESIGN
    artifact: it selects WHICH algorithm phase to wire and which #323 candidate points to
    enumerate, and folds in a CROSS-CUTTING knob (the entries-throttle) that is not yet a
    single phase's param. Each variant is captured in ONE deterministic `config_hash`.
  - It is DECLARATIVE + PRUNABLE: axes are module data; `coarse=True` trims each axis for a
    first pass; the full grid is the cartesian product. `enumerate_grid` emits configs + a
    count; `dry_run` lists them without running anything (coarse→fine, #320-E).

THE GRID (axes) — every value maps to a REAL phase Param (verified 2026-06-02):

PRIMARY — SIGNAL SCORE TIER (the new lever):
  - min_score ∈ {6, 7, 8}  → bct_score_full.Params.min_score
    6 = ++ looser control · 7 = champion · 8 = +++ strictest (8/8-only quality cut).

ALGORITHM (which entry-selection phase is wired):
  - gap_loud        → bct_intraday_gap_vol_confirm  (Rank-1, OOS-validated base)
  - hold_above_n    → bct_intraday_hold_confirm     (Rank-2)
  - gap_loud_wick   → bct_intraday_gap_vol_confirm + lower-wick booster (Rank-3)
  Reclaim-cross is RETIRED — never enumerated.

SELECTIVITY (de-emphasised gap, per the mine):
  - gap_pct     ∈ {0.03, 0.04}        → bct_intraday_gap_vol_confirm.Params.gap_threshold
  - vol_ratio   ∈ {1.0, 1.5, 2.0, 2.5}→ bct_intraday_gap_vol_confirm.Params.vol_mult
  - hold_n_bars ∈ {3, 6, 12}          → bct_intraday_hold_confirm window (hold algo only)
  - entries_cap ∈ {off, 10, 15, 20}   → ENTRIES-THROTTLE HOOK. No explicit max-positions cap
    param exists yet (the only cap is the implicit cash heat-cap in flat_pct_heatcap). HQ is
    building an explicit cap as a fast-follow; this axis is a CLEAN HOOK that maps to that
    param when it lands. For v1 it is carried as a sizing PhaseChoice knob (see _sizing_choice)
    so the variant + hash already capture the intended throttle; the adapter wires it to the
    explicit cap (or, until then, to flat_pct_heatcap.position_pct) without a grid change.

REGIME (minimal, off-biased):
  - vix_gate ∈ {off, 75, 50} → vix_percentile.Params.vix_percentile_enabled +
    vix_percentile_threshold (off ⇒ enabled=False; 75/50 ⇒ enabled=True at that pctile).
  - spy_200ma ∈ {off, on}    → biased OFF (analysis: harmful — drops a winner).

WINDOWS: handled by sweeps.windows (the 6 FY2025 bi-monthly panel + FY2024 OOS holdout).
EVERY config runs across ALL windows — the windows-AND-FY consistency IS the robustness gate.

Per-trade context (gap_pct / signal_score / vol_ratio at run time) for selectivity analysis
is a SEPARATE fast-follow HQ is coordinating (TradeRecord context fields + emit + parse); this
grid does not block on it. TradeRecord stays extensible (frozen dataclass, new fields additive).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sweeps.types import PhaseChoice, SweepConfig

# --------------------------------------------------------------------------- #
# Axis value catalogs (declarative — the refined #323 candidate sets).
# --------------------------------------------------------------------------- #
Algorithm = Literal["gap_loud", "hold_above_n", "gap_loud_wick"]

MIN_SCORE_AXIS: tuple[int, ...] = (6, 7, 8)
"""PRIMARY axis — bct_score_full.min_score. 6=++looser, 7=champion, 8=+++8/8-only."""

ALGORITHM_AXIS: tuple[Algorithm, ...] = ("gap_loud", "hold_above_n", "gap_loud_wick")
"""The three live algorithms. Reclaim-cross is RETIRED and never appears."""

ALGORITHM_IMPL: dict[Algorithm, str] = {
    "gap_loud": "bct_intraday_gap_vol_confirm",
    "hold_above_n": "bct_intraday_hold_confirm",
    "gap_loud_wick": "bct_intraday_gap_vol_confirm",  # + lower_wick booster toggle
}

GAP_PCT_AXIS: tuple[float, ...] = (0.03, 0.04)  # DE-EMPHASISED (mine: 3-6% behave alike)
VOL_RATIO_AXIS: tuple[float, ...] = (1.0, 1.5, 2.0, 2.5)
HOLD_N_BARS_AXIS: tuple[int, ...] = (3, 6, 12)
ENTRIES_CAP_AXIS: tuple[int | None, ...] = (None, 10, 15, 20)  # None == off (the hook axis)

# REGIME (secondary — minimal). vix_gate as a percentile ceiling (None == off).
VIX_GATE_AXIS: tuple[int | None, ...] = (None, 75, 50)  # None==off, enabled@75, enabled@50
SPY_200MA_AXIS: tuple[bool, ...] = (False, True)  # bias OFF (analysis: harmful)

# --------------------------------------------------------------------------- #
# Coarse subsets — a representative slice per axis for a first pass (#320-E coarse→fine).
# Keep the PRIMARY (min_score) wide; trim selectivity; collapse regime to off-bias.
# --------------------------------------------------------------------------- #
COARSE_MIN_SCORE: tuple[int, ...] = (7, 8)            # champion + the quality cut
COARSE_GAP_PCT: tuple[float, ...] = (0.03,)
COARSE_VOL_RATIO: tuple[float, ...] = (1.0, 2.0)
COARSE_HOLD_N_BARS: tuple[int, ...] = (3, 12)
COARSE_ENTRIES_CAP: tuple[int | None, ...] = (None, 15)
COARSE_VIX_GATE: tuple[int | None, ...] = (None, 75)
COARSE_SPY_200MA: tuple[bool, ...] = (False,)         # off only (bias)


@dataclass(frozen=True, slots=True)
class GridAxes:
    """The resolved per-axis candidate sets for one enumeration pass (coarse or full).

    Declarative + prunable: swap any tuple for a narrower set (e.g. the loop's round-N+1
    constraint) and `enumerate_grid` re-expands. `coarse()`/`full()` are the canonical passes.
    """

    min_score: tuple[int, ...]
    algorithms: tuple[Algorithm, ...]
    gap_pct: tuple[float, ...]
    vol_ratio: tuple[float, ...]
    hold_n_bars: tuple[int, ...]
    entries_cap: tuple[int | None, ...]
    vix_gate: tuple[int | None, ...]
    spy_200ma: tuple[bool, ...]

    @classmethod
    def full(cls) -> GridAxes:
        """The full #323 grid — every candidate on every axis."""
        return cls(
            min_score=MIN_SCORE_AXIS,
            algorithms=ALGORITHM_AXIS,
            gap_pct=GAP_PCT_AXIS,
            vol_ratio=VOL_RATIO_AXIS,
            hold_n_bars=HOLD_N_BARS_AXIS,
            entries_cap=ENTRIES_CAP_AXIS,
            vix_gate=VIX_GATE_AXIS,
            spy_200ma=SPY_200MA_AXIS,
        )

    @classmethod
    def coarse(cls) -> GridAxes:
        """The coarse first-pass subset — primary wide, selectivity trimmed, regime off-biased."""
        return cls(
            min_score=COARSE_MIN_SCORE,
            algorithms=ALGORITHM_AXIS,
            gap_pct=COARSE_GAP_PCT,
            vol_ratio=COARSE_VOL_RATIO,
            hold_n_bars=COARSE_HOLD_N_BARS,
            entries_cap=COARSE_ENTRIES_CAP,
            vix_gate=COARSE_VIX_GATE,
            spy_200ma=COARSE_SPY_200MA,
        )


# --------------------------------------------------------------------------- #
# Free-param accounting — what each axis costs the DoF budget (ADR D5.5).
# A swept axis with a single candidate is FIXED (costs 0); >1 candidate is a free param.
# --------------------------------------------------------------------------- #
def _is_swept(values: Sequence[object]) -> bool:
    return len(set(values)) > 1


def _signal_choice(min_score: int, *, swept: bool) -> PhaseChoice:
    """The PRIMARY axis — bct_score_full.min_score (the signal-score strictness tier)."""
    return PhaseChoice(
        kind="signal",
        impl_name="bct_score_full",
        params=(("min_score", min_score),),
        free_params=int(swept),
    )


def _algorithm_choice(
    algo: Algorithm,
    *,
    gap_pct: float,
    vol_ratio: float,
    hold_n_bars: int,
    swept_axes: dict[str, bool],
) -> PhaseChoice:
    """The entry-selection PhaseChoice for one algorithm at one selectivity point.

    Folds ONLY the params that algorithm consumes (gap algos take gap_threshold/vol_mult; the
    hold algo takes vol_mult/hold_n_bars), so a variant differing only on an irrelevant axis
    collapses to the SAME config. `lower_wick_booster` distinguishes gap_loud_wick (Rank-3).
    """
    impl = ALGORITHM_IMPL[algo]
    params: list[tuple[str, object]] = []
    free = 0
    if algo in ("gap_loud", "gap_loud_wick"):
        params.append(("gap_threshold", gap_pct))
        params.append(("vol_mult", vol_ratio))
        free += int(swept_axes["gap_pct"]) + int(swept_axes["vol_ratio"])
        if algo == "gap_loud_wick":
            params.append(("lower_wick_booster", True))  # the Rank-3 booster toggle
    else:  # hold_above_n
        params.append(("vol_mult", vol_ratio))
        params.append(("hold_n_bars", hold_n_bars))
        free += int(swept_axes["vol_ratio"]) + int(swept_axes["hold_n_bars"])
    params.sort()
    return PhaseChoice(kind="entry_selection", impl_name=impl, params=tuple(params), free_params=free)


def _sizing_choice(entries_cap: int | None, *, swept: bool) -> PhaseChoice:
    """The entries-throttle HOOK, carried on the sizing phase (flat_pct_heatcap).

    No explicit max-positions cap param exists yet — HQ is building one as a fast-follow. This
    axis is a clean hook: `entries_cap` (None == off, else a max-concurrent target) rides on
    the sizing phase so the variant + config_hash already capture the intended throttle. The
    adapter maps it to the explicit cap when it lands (or, until then, to position_pct). Naming
    the field `entries_cap` keeps the mapping a one-line adapter change, not a grid re-emit.
    """
    return PhaseChoice(
        kind="sizing",
        impl_name="flat_pct_heatcap",
        params=(("entries_cap", entries_cap),),  # None == off
        free_params=int(swept),
    )


def _regime_choice(
    vix_gate: int | None, spy_200ma: bool, *, swept_axes: dict[str, bool]
) -> PhaseChoice:
    """The (secondary, minimal) regime gate — vix_percentile + the spy_200ma toggle.

    Bias to OFF: the default point (vix off / spy off) is the no-regime variant the analysis
    prefers. `vix_gate` None ⇒ vix_percentile_enabled=False; 75/50 ⇒ enabled=True at that
    threshold (maps to vix_percentile.Params.vix_percentile_threshold).
    """
    free = int(swept_axes["vix_gate"]) + int(swept_axes["spy_200ma"])
    return PhaseChoice(
        kind="regime",
        impl_name="vix_percentile",
        params=(
            ("spy_200ma", spy_200ma),
            ("vix_percentile_enabled", vix_gate is not None),
            ("vix_percentile_threshold", float(vix_gate) if vix_gate is not None else None),
        ),
        free_params=free,
    )


@dataclass(frozen=True, slots=True)
class GridEnumeration:
    """The enumerated grid: the deduped SweepConfigs + the axis pass that produced them."""

    configs: tuple[SweepConfig, ...]
    axes: GridAxes
    coarse: bool

    @property
    def cardinality(self) -> int:
        return len(self.configs)


def enumerate_grid(axes: GridAxes | None = None, *, coarse: bool = False) -> GridEnumeration:
    """Expand the declarative axes into a deduped list of SweepConfigs.

    Determinism + dedup: irrelevant axes are NOT folded into a variant (a gap algo ignores
    hold_n_bars), so the naive cartesian product yields DUPLICATES that collapse on
    `config_hash`. We dedup on the hash, keeping insertion order — same axes always yield the
    SAME config set in the SAME order (the #182 determinism discipline).

    `coarse=True` uses the coarse subset when `axes` is None. Pass a custom `GridAxes` for the
    loop's round-N+1 constraint.
    """
    if axes is None:
        axes = GridAxes.coarse() if coarse else GridAxes.full()

    swept = {
        "min_score": _is_swept(axes.min_score),
        "gap_pct": _is_swept(axes.gap_pct),
        "vol_ratio": _is_swept(axes.vol_ratio),
        "hold_n_bars": _is_swept(axes.hold_n_bars),
        "entries_cap": _is_swept(axes.entries_cap),
        "vix_gate": _is_swept(axes.vix_gate),
        "spy_200ma": _is_swept(axes.spy_200ma),
    }

    seen: set[str] = set()
    configs: list[SweepConfig] = []
    for min_score in axes.min_score:
        for algo in axes.algorithms:
            is_gap = algo in ("gap_loud", "gap_loud_wick")
            gap_values = axes.gap_pct if is_gap else (axes.gap_pct[0],)
            hold_values = axes.hold_n_bars if not is_gap else (axes.hold_n_bars[0],)
            for gap_pct in gap_values:
                for vol_ratio in axes.vol_ratio:
                    for hold_n_bars in hold_values:
                        for entries_cap in axes.entries_cap:
                            for vix_gate in axes.vix_gate:
                                for spy_200ma in axes.spy_200ma:
                                    cfg = SweepConfig(
                                        choices=(
                                            _signal_choice(
                                                min_score, swept=swept["min_score"]
                                            ),
                                            _algorithm_choice(
                                                algo,
                                                gap_pct=gap_pct,
                                                vol_ratio=vol_ratio,
                                                hold_n_bars=hold_n_bars,
                                                swept_axes=swept,
                                            ),
                                            _sizing_choice(
                                                entries_cap, swept=swept["entries_cap"]
                                            ),
                                            _regime_choice(
                                                vix_gate, spy_200ma, swept_axes=swept
                                            ),
                                        )
                                    )
                                    h = cfg.config_hash
                                    if h in seen:
                                        continue
                                    seen.add(h)
                                    configs.append(cfg)
    return GridEnumeration(configs=tuple(configs), axes=axes, coarse=coarse)


def dry_run(enumeration: GridEnumeration) -> str:
    """A human-readable listing of the grid (count + one line per config). Runs NOTHING.

    Each line: config_hash · the resolved phase choices/params. The header states the pass
    (coarse/full) + the cardinality (the count #323 asks the enumerator to emit). For a large
    full grid this is the audit surface before any compute is spent.
    """
    lines: list[str] = []
    pass_name = "COARSE" if enumeration.coarse else "FULL"
    lines.append(f"# intraday-selectivity grid ({pass_name}) — {enumeration.cardinality} configs")
    for cfg in enumeration.configs:
        parts = []
        for c in sorted(cfg.choices, key=lambda x: x.kind):
            pstr = ",".join(f"{k}={v}" for k, v in c.params)
            parts.append(f"{c.kind}:{c.impl_name}({pstr})")
        lines.append(f"{cfg.config_hash}  {' | '.join(parts)}  dof={cfg.total_free_params}")
    return "\n".join(lines) + "\n"
