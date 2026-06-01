"""Intraday-selectivity grid (#323) — the declarative sweep space, biased to SELECTIVITY.

This is the GRID ENUMERATOR the #323 sweep runs. It produces a list of `SweepConfig`s
(the RunConfig Protocol's input) over the axes Falk + HQ biased toward SELECTIVITY: the
analysis found ORDER-DENSITY / over-firing — not macro-regime — separates losing windows
from winning ones, so the param/selectivity axes are EMPHASISED and the regime axes are
kept MINIMAL (and biased toward OFF).

Why a sweep-local grid (not just `enumerate_product` over `space()`)?
  - The phase `space()` is the drift-proof per-phase surface (3 canonical points/axis). This
    grid is a SWEEP-DESIGN artifact: it selects WHICH algorithm phase to wire, sets the
    selectivity knobs to the #323 candidate sets (which are RICHER than a phase's coarse 3
    points — e.g. gap_pct ∈ {3,4,5,6%}), and folds in CROSS-CUTTING sweep knobs that are NOT
    a single phase's param (entries-per-window CAP, scanner/quality rank cut, the regime
    gate selection). Those cross-cutting knobs are modelled as extra PhaseChoices so the
    whole variant is captured in ONE deterministic `config_hash`.
  - It is DECLARATIVE: the axes are module data (`ALGORITHM_AXIS`, `SELECTIVITY_AXIS`, ...).
    `coarse=True` prunes each axis to a representative subset for a first-pass; the full grid
    is the cartesian product. `enumerate_grid` emits the configs + a count; `dry_run` lists
    them without running anything.

Contract with the run-a-config Protocol (#214): every emitted `SweepConfig` is consumed by
`RunConfig.__call__(config, window) -> ResultMetrics`. The adapter (local_lean/cloud_lean)
reads each `PhaseChoice.kind` / `.impl_name` / `.params` to fold the chosen impls+params into
the dist closure. This enumerator NEVER runs a backtest — it only builds the inputs.

THE GRID (axes):

ALGORITHM (which entry-selection phase is wired):
  - gap_loud        → bct_intraday_gap_vol_confirm  (Rank-1, OOS-validated base)
  - hold_above_n    → bct_intraday_hold_confirm     (Rank-2)
  - gap_loud_wick   → bct_intraday_gap_vol_confirm + lower-wick booster (Rank-3)
  Reclaim-cross is RETIRED — never enumerated.

SELECTIVITY / PARAM (EMPHASISED — the lever):
  - gap_pct          ∈ {0.03, 0.04, 0.05, 0.06}    (gap+loud algos only)
  - vol_ratio        ∈ {1.0, 1.5, 2.0, 2.5}
  - entries_cap      ∈ {off, 10, 15, 20}           (entries-per-window cap)
  - hold_n_bars      ∈ {3, 6, 12}                  (hold algo only)
  - rank_cut         ∈ {off, top-K}                (scanner/quality rank cut)

REGIME (SECONDARY — minimal, biased to OFF):
  - vix_gate         ∈ {off, pctile<75, pctile<50}
  - spy_200ma        ∈ {off, on}                   (bias OFF — analysis: harmful)
  - adx_tier         ∈ {off, STRONG-only}

WINDOWS: handled by sweeps.windows (the FY2025 bi-monthly panel + FY2024 OOS holdout). EVERY
config runs across ALL windows — that is the robustness gate, not part of THIS grid.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sweeps.types import PhaseChoice, SweepConfig

# --------------------------------------------------------------------------- #
# Axis value catalogs (declarative — the #323 candidate sets).
# --------------------------------------------------------------------------- #
Algorithm = Literal["gap_loud", "hold_above_n", "gap_loud_wick"]

ALGORITHM_AXIS: tuple[Algorithm, ...] = ("gap_loud", "hold_above_n", "gap_loud_wick")
"""The three live algorithms. Reclaim-cross is RETIRED and never appears."""

# The entry-selection phase impl each algorithm wires (impl_name -> dist builder lookup key).
ALGORITHM_IMPL: dict[Algorithm, str] = {
    "gap_loud": "bct_intraday_gap_vol_confirm",
    "hold_above_n": "bct_intraday_hold_confirm",
    "gap_loud_wick": "bct_intraday_gap_vol_confirm",  # + lower_wick booster toggle (see below)
}

GAP_PCT_AXIS: tuple[float, ...] = (0.03, 0.04, 0.05, 0.06)
VOL_RATIO_AXIS: tuple[float, ...] = (1.0, 1.5, 2.0, 2.5)
ENTRIES_CAP_AXIS: tuple[int | None, ...] = (None, 10, 15, 20)  # None == off
HOLD_N_BARS_AXIS: tuple[int, ...] = (3, 6, 12)
RANK_CUT_AXIS: tuple[int | None, ...] = (None, 10)  # None == off; top-K (K=10)

# REGIME (secondary — minimal). vix_gate as a percentile ceiling (None == off).
VIX_GATE_AXIS: tuple[int | None, ...] = (None, 75, 50)  # None==off, pctile<75, pctile<50
SPY_200MA_AXIS: tuple[bool, ...] = (False, True)  # bias OFF (analysis: harmful)
ADX_TIER_AXIS: tuple[Literal["off", "strong"], ...] = ("off", "strong")

# --------------------------------------------------------------------------- #
# Coarse subsets — a representative slice per axis for a first-pass (#320-E coarse→fine).
# The coarse subset keeps the EMPHASISED selectivity axes wide-ish and collapses the
# secondary regime axes to {off} (bias-to-off) + one alternative, so the first pass spends
# compute on the lever, not the secondary dimensions.
# --------------------------------------------------------------------------- #
COARSE_GAP_PCT: tuple[float, ...] = (0.03, 0.05)
COARSE_VOL_RATIO: tuple[float, ...] = (1.0, 2.0)
COARSE_ENTRIES_CAP: tuple[int | None, ...] = (None, 15)
COARSE_HOLD_N_BARS: tuple[int, ...] = (3, 12)
COARSE_RANK_CUT: tuple[int | None, ...] = (None,)        # off only in coarse
COARSE_VIX_GATE: tuple[int | None, ...] = (None, 75)
COARSE_SPY_200MA: tuple[bool, ...] = (False,)            # off only (bias)
COARSE_ADX_TIER: tuple[Literal["off", "strong"], ...] = ("off",)  # off only


@dataclass(frozen=True, slots=True)
class GridAxes:
    """The resolved per-axis candidate sets for one enumeration pass (coarse or full).

    Declarative + prunable: swap any tuple for a narrower set (e.g. the loop's round-N+1
    constraint) and `enumerate_grid` re-expands. `coarse()`/`full()` are the canonical passes.
    """

    algorithms: tuple[Algorithm, ...]
    gap_pct: tuple[float, ...]
    vol_ratio: tuple[float, ...]
    entries_cap: tuple[int | None, ...]
    hold_n_bars: tuple[int, ...]
    rank_cut: tuple[int | None, ...]
    vix_gate: tuple[int | None, ...]
    spy_200ma: tuple[bool, ...]
    adx_tier: tuple[Literal["off", "strong"], ...]

    @classmethod
    def full(cls) -> GridAxes:
        """The full #323 grid — every candidate on every axis."""
        return cls(
            algorithms=ALGORITHM_AXIS,
            gap_pct=GAP_PCT_AXIS,
            vol_ratio=VOL_RATIO_AXIS,
            entries_cap=ENTRIES_CAP_AXIS,
            hold_n_bars=HOLD_N_BARS_AXIS,
            rank_cut=RANK_CUT_AXIS,
            vix_gate=VIX_GATE_AXIS,
            spy_200ma=SPY_200MA_AXIS,
            adx_tier=ADX_TIER_AXIS,
        )

    @classmethod
    def coarse(cls) -> GridAxes:
        """The coarse first-pass subset — emphasised axes wide, secondary axes biased off."""
        return cls(
            algorithms=ALGORITHM_AXIS,
            gap_pct=COARSE_GAP_PCT,
            vol_ratio=COARSE_VOL_RATIO,
            entries_cap=COARSE_ENTRIES_CAP,
            hold_n_bars=COARSE_HOLD_N_BARS,
            rank_cut=COARSE_RANK_CUT,
            vix_gate=COARSE_VIX_GATE,
            spy_200ma=COARSE_SPY_200MA,
            adx_tier=COARSE_ADX_TIER,
        )


# --------------------------------------------------------------------------- #
# Free-param accounting — what each axis costs the DoF budget (ADR D5.5).
# A swept axis with a single candidate is NOT free (it is fixed), so it costs 0.
# --------------------------------------------------------------------------- #
def _is_swept(values: Sequence[object]) -> bool:
    """An axis is a FREE parameter iff it has >1 distinct candidate in this pass."""
    return len(set(values)) > 1


def _algorithm_choice(
    algo: Algorithm,
    *,
    gap_pct: float,
    vol_ratio: float,
    hold_n_bars: int,
    swept_axes: dict[str, bool],
) -> PhaseChoice:
    """The entry-selection PhaseChoice for one algorithm at one selectivity point.

    Folds ONLY the params that algorithm actually consumes (gap algos don't take hold_n_bars;
    the hold algo doesn't take gap_pct), so two variants that differ only on an irrelevant
    axis collapse to the SAME config (no phantom grid points). `lower_wick` is the booster
    toggle that distinguishes gap_loud_wick (Rank-3) from gap_loud (Rank-1).
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
    return PhaseChoice(
        kind="entry_selection",
        impl_name=impl,
        params=tuple(params),
        free_params=free,
    )


def _portfolio_choice(entries_cap: int | None, *, swept: bool) -> PhaseChoice:
    """The entries-per-window CAP, modelled as a portfolio_risk PhaseChoice.

    `off` (None) vs a finite cap is the selectivity throttle the #323 analysis cares about
    most (over-firing is what separates losing windows). Modelled as its own phase so it is
    part of the config hash + the dist-builder wires it.
    """
    return PhaseChoice(
        kind="portfolio_risk",
        impl_name="entries_per_window_cap",
        params=(("entries_cap", entries_cap),),  # None == off
        free_params=int(swept),
    )


def _universe_choice(rank_cut: int | None, *, swept: bool) -> PhaseChoice:
    """The scanner/quality rank cut (top-K), modelled as a universe PhaseChoice.

    `off` (None) keeps the full candidate set; top-K keeps only the K best-ranked candidates
    (a selectivity lever on WHICH names, complementing the entries cap on HOW MANY fire).
    """
    return PhaseChoice(
        kind="universe",
        impl_name="scanner_rank_cut",
        params=(("rank_cut", rank_cut),),  # None == off
        free_params=int(swept),
    )


def _regime_choice(
    vix_gate: int | None,
    spy_200ma: bool,
    adx_tier: Literal["off", "strong"],
    *,
    swept_axes: dict[str, bool],
) -> PhaseChoice:
    """The (secondary, minimal) regime gate. One PhaseChoice folds all three regime knobs.

    Bias to OFF: the default point (vix off / spy off / adx off) is the no-regime variant the
    analysis prefers; the alternatives are kept for falsification, not emphasis.
    """
    free = (
        int(swept_axes["vix_gate"])
        + int(swept_axes["spy_200ma"])
        + int(swept_axes["adx_tier"])
    )
    return PhaseChoice(
        kind="regime",
        impl_name="intraday_regime_gate",
        params=(
            ("adx_tier", adx_tier),
            ("spy_200ma", spy_200ma),
            ("vix_gate_pctile", vix_gate),  # None == off
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
    hold_n_bars), so the naive cartesian product yields DUPLICATE configs that collapse on
    `config_hash`. We dedup on the hash and keep insertion order — same axes always yield the
    SAME config set in the SAME order (the #182 determinism discipline).

    `coarse=True` uses the coarse subset (overrides an explicitly-passed `axes` only if `axes`
    is None). Pass a custom `GridAxes` for the loop's round-N+1 constraint.
    """
    if axes is None:
        axes = GridAxes.coarse() if coarse else GridAxes.full()

    swept = {
        "gap_pct": _is_swept(axes.gap_pct),
        "vol_ratio": _is_swept(axes.vol_ratio),
        "entries_cap": _is_swept(axes.entries_cap),
        "hold_n_bars": _is_swept(axes.hold_n_bars),
        "rank_cut": _is_swept(axes.rank_cut),
        "vix_gate": _is_swept(axes.vix_gate),
        "spy_200ma": _is_swept(axes.spy_200ma),
        "adx_tier": _is_swept(axes.adx_tier),
    }

    seen: set[str] = set()
    configs: list[SweepConfig] = []
    for algo in axes.algorithms:
        is_gap = algo in ("gap_loud", "gap_loud_wick")
        # Collapse the axis a given algorithm ignores to a single sentinel so we don't emit
        # phantom variants (a gap algo iterating hold_n_bars would dedup anyway, but skipping
        # it keeps the loop cheap and the count honest).
        gap_values = axes.gap_pct if is_gap else (axes.gap_pct[0],)
        hold_values = axes.hold_n_bars if not is_gap else (axes.hold_n_bars[0],)
        for gap_pct in gap_values:
            for vol_ratio in axes.vol_ratio:
                for hold_n_bars in hold_values:
                    for entries_cap in axes.entries_cap:
                        for rank_cut in axes.rank_cut:
                            for vix_gate in axes.vix_gate:
                                for spy_200ma in axes.spy_200ma:
                                    for adx_tier in axes.adx_tier:
                                        cfg = SweepConfig(
                                            choices=(
                                                _algorithm_choice(
                                                    algo,
                                                    gap_pct=gap_pct,
                                                    vol_ratio=vol_ratio,
                                                    hold_n_bars=hold_n_bars,
                                                    swept_axes=swept,
                                                ),
                                                _portfolio_choice(
                                                    entries_cap, swept=swept["entries_cap"]
                                                ),
                                                _universe_choice(
                                                    rank_cut, swept=swept["rank_cut"]
                                                ),
                                                _regime_choice(
                                                    vix_gate,
                                                    spy_200ma,
                                                    adx_tier,
                                                    swept_axes=swept,
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

    Each line: config_hash · algorithm · the resolved selectivity/regime params. The header
    states the pass (coarse/full) + the cardinality (the count #323 asks the enumerator to
    emit). For a large full grid this is the audit surface before any compute is spent.
    """
    lines: list[str] = []
    pass_name = "COARSE" if enumeration.coarse else "FULL"
    lines.append(
        f"# intraday-selectivity grid ({pass_name}) — {enumeration.cardinality} configs"
    )
    for cfg in enumeration.configs:
        parts = []
        for c in sorted(cfg.choices, key=lambda x: x.kind):
            pstr = ",".join(f"{k}={v}" for k, v in c.params)
            parts.append(f"{c.kind}:{c.impl_name}({pstr})")
        lines.append(f"{cfg.config_hash}  {' | '.join(parts)}  dof={cfg.total_free_params}")
    return "\n".join(lines) + "\n"
