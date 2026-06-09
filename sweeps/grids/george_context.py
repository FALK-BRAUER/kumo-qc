"""George-context FY2025 sweep protocol.

This grid is deliberately named and hand-curated instead of a blind cartesian explosion. It
supports the #416 protocol:

1. Run a six-pack to prove the architecture levers are live.
2. Then run a 30-pack in five waves of six variants to compare industry warm-up, watchlist carry,
   George attention, entry confirmation, and exit management.

Every variant is a real `SweepConfig`: phase choices remain pluggable, runtime knobs enter the
config identity, and the existing local/cloud adapters can build/run the configs.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sweeps.types import PhaseChoice, SweepConfig

BASE_MODULE = "strategies.champion_george_context"
SECURITY_PROFILE_SOURCE = "data/bluecloudtrading/runtime/security_profiles.csv"
GEORGE_ATTENTION_SOURCE = "data/bluecloudtrading/runtime/george_attention.csv"


@dataclass(frozen=True, slots=True)
class GeorgeSweepVariant:
    variant_id: str
    family: str
    hypothesis: str
    config: SweepConfig
    wave: int
    base_module: str = BASE_MODULE

    @property
    def config_hash(self) -> str:
        return self.config.config_hash


def _pairs(**kwargs: object) -> tuple[tuple[str, object], ...]:
    return tuple(sorted(kwargs.items()))


def _runtime(**kwargs: object) -> tuple[tuple[str, object], ...]:
    return _pairs(**kwargs)


def _phase(
    kind: str,
    impl_name: str,
    *,
    enabled: bool = True,
    free_params: int | None = None,
    params: Mapping[str, object] | None = None,
) -> PhaseChoice:
    phase_params = dict(params or {})
    return PhaseChoice(
        kind=kind,
        impl_name=impl_name,
        params=_pairs(**phase_params),
        free_params=len(phase_params) if free_params is None else free_params,
        enabled=enabled,
    )


def _rebalance(
    *, enabled: bool = True, free_params: int | None = None, **params: object
) -> PhaseChoice:
    return _phase(
        "rebalance",
        "industry_warmup",
        enabled=enabled,
        free_params=free_params,
        params=params,
    )


def _ranking(
    *, enabled: bool = True, free_params: int | None = None, **params: object
) -> PhaseChoice:
    return _phase(
        "ranking",
        "george_industry_attention",
        enabled=enabled,
        free_params=free_params,
        params=params,
    )


def _entry(**params: object) -> PhaseChoice:
    return _phase("entry_selection", "bct_intraday_gap_vol_confirm", params=params)


def _exit(impl_name: str, **params: object) -> PhaseChoice:
    free_params = len(params)
    if impl_name == "mfe_intraday_exit" and "diagnostic_log" not in params:
        params = {**params, "diagnostic_log": True}
        free_params = len(params) - 1
    return _phase("exit_hard", impl_name, free_params=free_params, params=params)


def _position_path(**params: object) -> PhaseChoice:
    return _phase("trail", "position_path_tracker", params=params)


def _config(
    *choices: PhaseChoice,
    runtime_overrides: tuple[tuple[str, object], ...] = (),
    continuous_weekly: bool = True,
    warmup_days: int = 320,
) -> SweepConfig:
    return SweepConfig(
        choices=tuple(choices),
        continuous_weekly=continuous_weekly,
        warmup_days=warmup_days,
        runtime_overrides=runtime_overrides,
    )


def _variant(
    variant_id: str,
    family: str,
    hypothesis: str,
    *choices: PhaseChoice,
    wave: int,
    runtime_overrides: tuple[tuple[str, object], ...] = (),
) -> GeorgeSweepVariant:
    return GeorgeSweepVariant(
        variant_id=variant_id,
        family=family,
        hypothesis=hypothesis,
        wave=wave,
        config=_config(*choices, runtime_overrides=runtime_overrides),
    )


_DISABLE_GEORGE = (
    _rebalance(enabled=False, free_params=0),
    _ranking(enabled=False, free_params=0),
)

_PROFILE_RUNTIME = _runtime(security_profile_source=SECURITY_PROFILE_SOURCE)
_ATTENTION_RUNTIME = _runtime(george_attention_source=GEORGE_ATTENTION_SOURCE)
_FULL_SOURCE_RUNTIME = _runtime(
    security_profile_source=SECURITY_PROFILE_SOURCE,
    george_attention_source=GEORGE_ATTENTION_SOURCE,
)
_INDUSTRY_CARRY_RUNTIME = _runtime(
    security_profile_source=SECURITY_PROFILE_SOURCE,
    watchlist_carry_max=10,
)
_FULL_CARRY_RUNTIME = _runtime(
    security_profile_source=SECURITY_PROFILE_SOURCE,
    george_attention_source=GEORGE_ATTENTION_SOURCE,
    watchlist_carry_max=10,
)


def _ctx_top3() -> tuple[PhaseChoice, ...]:
    return (
        _rebalance(top_n=3),
        _ranking(industry_weight=1.0, watchlist_weight=0.0, ticker_attention_weight=0.0),
    )


def _ctx_full_carry() -> tuple[PhaseChoice, ...]:
    return (
        _rebalance(top_n=5, attention_weight=1.0, etf_proxy_weight=1.0),
        _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
    )


def _ctx_industry_carry() -> tuple[PhaseChoice, ...]:
    return (
        _rebalance(top_n=5),
        _ranking(industry_weight=1.0, watchlist_weight=1.0, ticker_attention_weight=0.0),
    )


def _ctx_attention_heavy() -> tuple[PhaseChoice, ...]:
    return (
        _rebalance(top_n=5, attention_weight=1.0),
        _ranking(industry_weight=0.25, watchlist_weight=0.0, ticker_attention_weight=1.0),
    )


def six_pack() -> tuple[GeorgeSweepVariant, ...]:
    """First validation pack: isolate each George-context architecture lever."""
    return (
        _variant(
            "gctx_baseline_no_george",
            "six_pack",
            "Control: champion stack with George rebalance/ranking disabled.",
            *_DISABLE_GEORGE,
            wave=0,
        ),
        _variant(
            "gctx_industry_only",
            "six_pack",
            "Top-down industry heat affects ranking; no ticker attention or carry contribution.",
            _rebalance(top_n=5),
            _ranking(industry_weight=1.0, watchlist_weight=0.0, ticker_attention_weight=0.0),
            wave=0,
            runtime_overrides=_PROFILE_RUNTIME,
        ),
        _variant(
            "gctx_attention_only",
            "six_pack",
            "Transcript/scanner ticker priors affect ranking without industry or watchlist weights.",
            _rebalance(enabled=False, free_params=0),
            _ranking(industry_weight=0.0, watchlist_weight=0.0, ticker_attention_weight=1.0),
            wave=0,
            runtime_overrides=_ATTENTION_RUNTIME,
        ),
        _variant(
            "gctx_watchlist_carry_only",
            "six_pack",
            "Memory effect only: ranking seeds a persistent watchlist and selection carry subscribes it.",
            _rebalance(enabled=False, free_params=0),
            _ranking(
                industry_weight=0.0,
                watchlist_weight=1.0,
                ticker_attention_weight=0.0,
                watchlist_add_min_industry_score=0.0,
                watchlist_remove_min_industry_score=-1.0,
                watchlist_ttl_days=10,
            ),
            wave=0,
            runtime_overrides=_runtime(watchlist_carry_max=10),
        ),
        _variant(
            "gctx_industry_watchlist",
            "six_pack",
            "Industry heat creates the watchlist; selection carry tests whether persistence helps.",
            _rebalance(top_n=5),
            _ranking(industry_weight=1.0, watchlist_weight=1.0, ticker_attention_weight=0.0),
            wave=0,
            runtime_overrides=_runtime(
                security_profile_source=SECURITY_PROFILE_SOURCE,
                watchlist_carry_max=10,
            ),
        ),
        _variant(
            "gctx_full",
            "six_pack",
            "Full George stack: industry heat, ticker priors, watchlist memory, and carry.",
            _rebalance(top_n=5, attention_weight=1.0, etf_proxy_weight=1.0),
            _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
            wave=0,
            runtime_overrides=_runtime(
                security_profile_source=SECURITY_PROFILE_SOURCE,
                george_attention_source=GEORGE_ATTENTION_SOURCE,
                watchlist_carry_max=10,
            ),
        ),
    )


def thirty_pack() -> tuple[GeorgeSweepVariant, ...]:
    """Targeted 30-pack: five six-variant waves after the six-pack passes."""
    variants: list[GeorgeSweepVariant] = []

    variants.extend(
        [
            _variant(
                "industry_top3_focus",
                "industry_warmup",
                "Only the strongest three industries get ranking preference.",
                _rebalance(top_n=3),
                _ranking(industry_weight=1.0, watchlist_weight=0.0, ticker_attention_weight=0.0),
                wave=1,
                runtime_overrides=_PROFILE_RUNTIME,
            ),
            _variant(
                "industry_top8_broad",
                "industry_warmup",
                "Broader industry set tests whether George's weekly scan should stay inclusive.",
                _rebalance(top_n=8),
                _ranking(industry_weight=1.0, watchlist_weight=0.0, ticker_attention_weight=0.0),
                wave=1,
                runtime_overrides=_PROFILE_RUNTIME,
            ),
            _variant(
                "industry_bct_share_heavy",
                "industry_warmup",
                "Favor industries with more BCT-qualified constituents.",
                _rebalance(top_n=5, bct_share_weight=3.0),
                _ranking(industry_weight=1.0, watchlist_weight=0.0, ticker_attention_weight=0.0),
                wave=1,
                runtime_overrides=_PROFILE_RUNTIME,
            ),
            _variant(
                "industry_attention_boost",
                "industry_warmup",
                "Let George transcript attention move industry scores strongly.",
                _rebalance(top_n=5, attention_weight=2.0),
                _ranking(industry_weight=1.0, watchlist_weight=0.0, ticker_attention_weight=0.0),
                wave=1,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "industry_proxy_off",
                "industry_warmup",
                "Turn off proxy ETF contribution to test stock-only industry heat.",
                _rebalance(top_n=5, etf_proxy_weight=0.0),
                _ranking(industry_weight=1.0, watchlist_weight=0.0, ticker_attention_weight=0.0),
                wave=1,
                runtime_overrides=_PROFILE_RUNTIME,
            ),
            _variant(
                "industry_proxy_boost",
                "industry_warmup",
                "Double proxy ETF contribution for rotation-led industries.",
                _rebalance(top_n=5, etf_proxy_weight=2.0),
                _ranking(industry_weight=1.0, watchlist_weight=0.0, ticker_attention_weight=0.0),
                wave=1,
                runtime_overrides=_PROFILE_RUNTIME,
            ),
        ]
    )

    variants.extend(
        [
            _variant(
                "carry_3_ttl5",
                "watchlist_carry",
                "Tiny carry list, short memory.",
                _rebalance(enabled=False, free_params=0),
                _ranking(watchlist_weight=1.0, watchlist_add_min_industry_score=0.0, watchlist_ttl_days=5),
                wave=2,
                runtime_overrides=_runtime(watchlist_carry_max=3),
            ),
            _variant(
                "carry_5_ttl10",
                "watchlist_carry",
                "Moderate carry list with one-to-two week memory.",
                _rebalance(enabled=False, free_params=0),
                _ranking(watchlist_weight=1.0, watchlist_add_min_industry_score=0.0, watchlist_ttl_days=10),
                wave=2,
                runtime_overrides=_runtime(watchlist_carry_max=5),
            ),
            _variant(
                "carry_10_ttl10",
                "watchlist_carry",
                "Default full carry candidate: ten carried names, normal memory.",
                _rebalance(enabled=False, free_params=0),
                _ranking(watchlist_weight=1.0, watchlist_add_min_industry_score=0.0, watchlist_ttl_days=10),
                wave=2,
                runtime_overrides=_runtime(watchlist_carry_max=10),
            ),
            _variant(
                "carry_15_ttl20",
                "watchlist_carry",
                "Large and patient carry list tests whether George's older finds still matter.",
                _rebalance(enabled=False, free_params=0),
                _ranking(watchlist_weight=1.0, watchlist_add_min_industry_score=0.0, watchlist_ttl_days=20),
                wave=2,
                runtime_overrides=_runtime(watchlist_carry_max=15),
            ),
            _variant(
                "carry_liquid_strict",
                "watchlist_carry",
                "Carry only very liquid names to avoid stale small-cap subscription noise.",
                _rebalance(enabled=False, free_params=0),
                _ranking(watchlist_weight=1.0, watchlist_add_min_industry_score=0.0, watchlist_ttl_days=10),
                wave=2,
                runtime_overrides=_runtime(
                    watchlist_carry_max=10,
                    watchlist_carry_min_avg_dollar_volume=200_000_000.0,
                ),
            ),
            _variant(
                "carry_price_loose",
                "watchlist_carry",
                "Permit lower-priced carried names where George often hunts momentum.",
                _rebalance(enabled=False, free_params=0),
                _ranking(watchlist_weight=1.0, watchlist_add_min_industry_score=0.0, watchlist_ttl_days=10),
                wave=2,
                runtime_overrides=_runtime(watchlist_carry_max=10, watchlist_carry_min_price=5.0),
            ),
        ]
    )

    variants.extend(
        [
            _variant(
                "attention_ticker_light",
                "george_attention",
                "Light ticker-prior bump.",
                _rebalance(top_n=5, attention_weight=0.5),
                _ranking(industry_weight=0.5, watchlist_weight=0.0, ticker_attention_weight=0.25),
                wave=3,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "attention_ticker_base",
                "george_attention",
                "Balanced ticker-prior bump.",
                _rebalance(top_n=5, attention_weight=1.0),
                _ranking(industry_weight=0.5, watchlist_weight=0.0, ticker_attention_weight=0.5),
                wave=3,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "attention_ticker_heavy",
                "george_attention",
                "Strong ticker-prior bump tests whether source evidence should dominate rank.",
                _rebalance(top_n=5, attention_weight=1.0),
                _ranking(industry_weight=0.25, watchlist_weight=0.0, ticker_attention_weight=1.0),
                wave=3,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "attention_industry_heavy",
                "george_attention",
                "Strong industry transcript prior with moderate ticker prior.",
                _rebalance(top_n=5, attention_weight=2.0),
                _ranking(industry_weight=1.0, watchlist_weight=0.0, ticker_attention_weight=0.5),
                wave=3,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "attention_with_watchlist",
                "george_attention",
                "Ticker prior can seed watchlist memory, but industry contribution stays low.",
                _rebalance(top_n=5, attention_weight=1.0),
                _ranking(industry_weight=0.25, watchlist_weight=0.75, ticker_attention_weight=0.75),
                wave=3,
                runtime_overrides=_runtime(
                    security_profile_source=SECURITY_PROFILE_SOURCE,
                    george_attention_source=GEORGE_ATTENTION_SOURCE,
                    watchlist_carry_max=10,
                ),
            ),
            _variant(
                "attention_floor_05",
                "george_attention",
                "Drop weak industries even when ticker attention exists.",
                _rebalance(top_n=5, attention_weight=1.0),
                _ranking(
                    industry_weight=1.0,
                    watchlist_weight=0.0,
                    ticker_attention_weight=0.5,
                    min_industry_score=0.5,
                ),
                wave=3,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
        ]
    )

    variants.extend(
        [
            _variant(
                "entry_gapvol_base",
                "entry_confirmation",
                "Canonical intraday gap/loud-open confirmation under George ranking.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(gap_threshold=0.03, vol_mult=1.0, window_bars=6),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "entry_gapvol_gap04",
                "entry_confirmation",
                "Require a stronger +4% gap before intraday confirmation.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(gap_threshold=0.04, vol_mult=1.0, window_bars=6),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "entry_gapvol_gap05",
                "entry_confirmation",
                "Require the highly selective +5% gap cohort.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(gap_threshold=0.05, vol_mult=1.0, window_bars=6),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "entry_gapvol_window60",
                "entry_confirmation",
                "Allow the first 60 minutes for the gap/loud-open confirmation.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(gap_threshold=0.03, vol_mult=1.0, window_bars=12),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "entry_gapvol_vol125",
                "entry_confirmation",
                "Require 1.25x opening volume for a louder confirmation.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(gap_threshold=0.03, vol_mult=1.25, window_bars=6),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "entry_gapvol_vol150",
                "entry_confirmation",
                "Require 1.5x opening volume to test stricter selectivity.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(gap_threshold=0.03, vol_mult=1.5, window_bars=6),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
        ]
    )

    variants.extend(
        [
            _variant(
                "exit_kijun_phase3_base",
                "exit_management",
                "Kijun G3 structural exit control.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _exit("kijun_g3_exits", cloud_exit_enabled=False, weekly_kijun_exit_enabled=False),
                wave=5,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "exit_cloud_adherence",
                "exit_management",
                "Hold recoverable Kijun dips until cloud-bottom adherence breaks.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _exit("cloud_adherence_trail"),
                wave=5,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "exit_weekly_kijun",
                "exit_management",
                "Add weekly Kijun as a higher-timeframe structural stop.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _exit("kijun_g3_exits", weekly_kijun_exit_enabled=True),
                wave=5,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "exit_proactive_target_06",
                "exit_management",
                "Take strength at +6% if the structure remains bullish.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _position_path(),
                _exit("proactive_strength_exit", target_pct=0.06, min_peak_pct=0.05),
                wave=5,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "exit_proactive_giveback_tight",
                "exit_management",
                "Tighter MFE giveback capture for winners that stall.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _position_path(),
                _exit(
                    "proactive_strength_exit",
                    target_pct=0.08,
                    min_peak_pct=0.04,
                    giveback_from_peak_pct=0.015,
                ),
                wave=5,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "exit_scratch_flat_3d",
                "exit_management",
                "Scratch stalled trades near flat after three days without useful MFE.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _position_path(),
                _exit(
                    "scratch_flat_exit",
                    no_progress_days=3,
                    min_mfe_pct=0.02,
                    scratch_band_pct=0.005,
                    max_loss_after_mfe_pct=0.02,
                ),
                wave=5,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
        ]
    )

    return tuple(variants)


def combo_thirty_pack() -> tuple[GeorgeSweepVariant, ...]:
    """Second 30-pack (#427): recombine George contexts with intraday MFE exit management."""
    variants: list[GeorgeSweepVariant] = []

    variants.extend(
        [
            _variant(
                "combo_target_04_top3",
                "mfe_target",
                "Top-3 industry context with fast +4% intraday harvest.",
                *_ctx_top3(),
                _position_path(),
                _exit("mfe_intraday_exit", target_pct=0.04, min_hold_bars=2),
                wave=1,
                runtime_overrides=_PROFILE_RUNTIME,
            ),
            _variant(
                "combo_target_06_top3",
                "mfe_target",
                "Top-3 industry context with +6% intraday harvest.",
                *_ctx_top3(),
                _position_path(),
                _exit("mfe_intraday_exit", target_pct=0.06, min_hold_bars=2),
                wave=1,
                runtime_overrides=_PROFILE_RUNTIME,
            ),
            _variant(
                "combo_target_08_top3",
                "mfe_target",
                "Top-3 industry context with +8% intraday harvest.",
                *_ctx_top3(),
                _position_path(),
                _exit("mfe_intraday_exit", target_pct=0.08, min_hold_bars=3),
                wave=1,
                runtime_overrides=_PROFILE_RUNTIME,
            ),
            _variant(
                "combo_target_06_fullcarry",
                "mfe_target",
                "Full George context plus carry with +6% intraday harvest.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("mfe_intraday_exit", target_pct=0.06, min_hold_bars=2),
                wave=1,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_target_08_fullcarry",
                "mfe_target",
                "Full George context plus carry with +8% intraday harvest.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("mfe_intraday_exit", target_pct=0.08, min_hold_bars=3),
                wave=1,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_target_10_fullcarry",
                "mfe_target",
                "Full George context plus carry with patient +10% harvest.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("mfe_intraday_exit", target_pct=0.10, min_hold_bars=4),
                wave=1,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
        ]
    )

    variants.extend(
        [
            _variant(
                "combo_giveback_base",
                "mfe_giveback",
                "Exit after 40% giveback from at least +6% MFE.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=2,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_giveback_tight",
                "mfe_giveback",
                "Tighter giveback: at least +4% MFE and 35% retrace.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.04, giveback_fraction=0.35, min_giveback_pct=0.015),
                wave=2,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_giveback_loose",
                "mfe_giveback",
                "Looser giveback: require +8% MFE and 50% retrace.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.08, giveback_fraction=0.50, min_giveback_pct=0.03),
                wave=2,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_session_fade",
                "mfe_giveback",
                "Use same-session MFE to catch intraday fades before EOD.",
                *_ctx_full_carry(),
                _position_path(),
                _exit(
                    "mfe_intraday_exit",
                    min_mfe_pct=0.05,
                    giveback_fraction=0.50,
                    min_giveback_pct=0.02,
                    use_session_path=True,
                ),
                wave=2,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_giveback_profit_floor",
                "mfe_giveback",
                "Giveback exits only if at least +2% profit remains.",
                *_ctx_full_carry(),
                _position_path(),
                _exit(
                    "mfe_intraday_exit",
                    min_mfe_pct=0.06,
                    giveback_fraction=0.40,
                    min_giveback_pct=0.02,
                    min_exit_return_pct=0.02,
                ),
                wave=2,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_giveback_patient_bars",
                "mfe_giveback",
                "Patient giveback waits for four 5-minute bars after entry.",
                *_ctx_full_carry(),
                _position_path(),
                _exit(
                    "mfe_intraday_exit",
                    min_mfe_pct=0.06,
                    giveback_fraction=0.45,
                    min_giveback_pct=0.02,
                    min_hold_bars=4,
                ),
                wave=2,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
        ]
    )

    variants.extend(
        [
            _variant(
                "combo_scratch3_mfe6",
                "scratch_mfe_combo",
                "Scratch flat/no-progress first, then +6% MFE harvest.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("scratch_flat_exit", no_progress_days=3, min_mfe_pct=0.02, scratch_band_pct=0.005),
                _exit("mfe_intraday_exit", target_pct=0.06, min_hold_bars=2),
                wave=3,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_scratch2_mfe6_tight",
                "scratch_mfe_combo",
                "Faster scratch with tight MFE giveback harvest.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("scratch_flat_exit", no_progress_days=2, min_mfe_pct=0.015, scratch_band_pct=0.004),
                _exit("mfe_intraday_exit", min_mfe_pct=0.05, giveback_fraction=0.35, min_giveback_pct=0.015),
                wave=3,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_scratch5_mfe8_patient",
                "scratch_mfe_combo",
                "Patient scratch plus +8% harvest.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("scratch_flat_exit", no_progress_days=5, min_mfe_pct=0.025, scratch_band_pct=0.004),
                _exit("mfe_intraday_exit", target_pct=0.08, min_hold_bars=4),
                wave=3,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_scratch_losscap_mfe",
                "scratch_mfe_combo",
                "Tighter post-MFE loss cap plus base giveback harvest.",
                *_ctx_full_carry(),
                _position_path(),
                _exit(
                    "scratch_flat_exit",
                    no_progress_days=3,
                    min_mfe_pct=0.02,
                    scratch_band_pct=0.003,
                    max_loss_after_mfe_pct=0.01,
                ),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=3,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_scratch_session_fade",
                "scratch_mfe_combo",
                "Scratch weak trades and exit same-day fades from session MFE.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("scratch_flat_exit", no_progress_days=3, min_mfe_pct=0.02, scratch_band_pct=0.006),
                _exit(
                    "mfe_intraday_exit",
                    min_mfe_pct=0.05,
                    giveback_fraction=0.50,
                    min_giveback_pct=0.02,
                    use_session_path=True,
                ),
                wave=3,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_scratch_highmfe_target",
                "scratch_mfe_combo",
                "Require more useful MFE before scratch while harvesting +6%.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("scratch_flat_exit", no_progress_days=3, min_mfe_pct=0.04, scratch_band_pct=0.005),
                _exit("mfe_intraday_exit", target_pct=0.06, min_hold_bars=2),
                wave=3,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
        ]
    )

    variants.extend(
        [
            _variant(
                "combo_context_no_george_mfe",
                "context_exit_combo",
                "Control context disabled with MFE giveback exit.",
                *_DISABLE_GEORGE,
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=4,
            ),
            _variant(
                "combo_context_top3_mfe",
                "context_exit_combo",
                "Top-3 industry context with base MFE giveback.",
                *_ctx_top3(),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=4,
                runtime_overrides=_PROFILE_RUNTIME,
            ),
            _variant(
                "combo_context_industry_carry_mfe",
                "context_exit_combo",
                "Industry plus watchlist carry with base MFE giveback.",
                *_ctx_industry_carry(),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=4,
                runtime_overrides=_INDUSTRY_CARRY_RUNTIME,
            ),
            _variant(
                "combo_context_attention_heavy_mfe",
                "context_exit_combo",
                "Attention-heavy context with base MFE giveback.",
                *_ctx_attention_heavy(),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "combo_context_fullcarry_mfe",
                "context_exit_combo",
                "Full context and watchlist carry with MFE giveback that keeps at least +1%.",
                *_ctx_full_carry(),
                _position_path(),
                _exit(
                    "mfe_intraday_exit",
                    min_mfe_pct=0.06,
                    giveback_fraction=0.40,
                    min_giveback_pct=0.02,
                    min_exit_return_pct=0.01,
                ),
                wave=4,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_context_fullcarry_scratch_mfe",
                "context_exit_combo",
                "Full context plus scratch-flat and MFE giveback.",
                *_ctx_full_carry(),
                _position_path(),
                _exit("scratch_flat_exit", no_progress_days=3, min_mfe_pct=0.02, scratch_band_pct=0.005),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=4,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
        ]
    )

    variants.extend(
        [
            _variant(
                "combo_entry_gap03_mfe",
                "entry_exit_combo",
                "Base +3% gap/loud-open entry with MFE giveback.",
                *_ctx_full_carry(),
                _entry(gap_threshold=0.03, vol_mult=1.0, window_bars=6),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=5,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_entry_window60_mfe",
                "entry_exit_combo",
                "Longer first-hour entry window with MFE giveback.",
                *_ctx_full_carry(),
                _entry(gap_threshold=0.03, vol_mult=1.0, window_bars=12),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=5,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_entry_gap04_mfe",
                "entry_exit_combo",
                "Stronger +4% gap entry with MFE giveback.",
                *_ctx_full_carry(),
                _entry(gap_threshold=0.04, vol_mult=1.0, window_bars=6),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=5,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_entry_vol125_mfe",
                "entry_exit_combo",
                "Louder 1.25x opening-volume entry with MFE giveback.",
                *_ctx_full_carry(),
                _entry(gap_threshold=0.03, vol_mult=1.25, window_bars=6),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=5,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_entry_gap04_window60_mfe",
                "entry_exit_combo",
                "Stronger gap with longer confirmation window and MFE giveback.",
                *_ctx_full_carry(),
                _entry(gap_threshold=0.04, vol_mult=1.0, window_bars=12),
                _position_path(),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=5,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
            _variant(
                "combo_entry_vol150_scratch_mfe",
                "entry_exit_combo",
                "Strict 1.5x opening-volume entry with scratch plus MFE giveback.",
                *_ctx_full_carry(),
                _entry(gap_threshold=0.03, vol_mult=1.5, window_bars=6),
                _position_path(),
                _exit("scratch_flat_exit", no_progress_days=3, min_mfe_pct=0.02, scratch_band_pct=0.005),
                _exit("mfe_intraday_exit", min_mfe_pct=0.06, giveback_fraction=0.40, min_giveback_pct=0.02),
                wave=5,
                runtime_overrides=_FULL_CARRY_RUNTIME,
            ),
        ]
    )

    return tuple(variants)


def all_variants() -> tuple[GeorgeSweepVariant, ...]:
    return six_pack() + thirty_pack() + combo_thirty_pack()



__all__ = [
    "BASE_MODULE",
    "GEORGE_ATTENTION_SOURCE",
    "SECURITY_PROFILE_SOURCE",
    "GeorgeSweepVariant",
    "all_variants",
    "combo_thirty_pack",
    "six_pack",
    "thirty_pack",
]
