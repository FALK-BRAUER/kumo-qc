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
    return _phase("entry_selection", "bct_entry_confirm", params=params)


def _exit(impl_name: str, **params: object) -> PhaseChoice:
    return _phase("exit_hard", impl_name, params=params)


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
                "entry_confirm_2_default",
                "entry_confirmation",
                "Canonical 2-of-4 confirmation baseline under George ranking.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(min_confirm=2),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "entry_confirm_3_strict",
                "entry_confirmation",
                "Require 3-of-4 confirmation to reduce marginal entries.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(min_confirm=3),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "entry_gap_strict",
                "entry_confirmation",
                "Treat smaller gap-ups as degraded entries.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(gap_up_threshold=0.005),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "entry_gap_loose",
                "entry_confirmation",
                "Allow wider gap-ups when George context is strong.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(gap_up_threshold=0.02),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "entry_tenkan_tight",
                "entry_confirmation",
                "Tighter pullback tolerance tests stricter chart-quality discipline.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(tenkan_pullback_tol=0.003),
                wave=4,
                runtime_overrides=_FULL_SOURCE_RUNTIME,
            ),
            _variant(
                "entry_volume_125",
                "entry_confirmation",
                "Require stronger volume confirmation before entry.",
                _rebalance(top_n=5),
                _ranking(industry_weight=1.0, watchlist_weight=0.5, ticker_attention_weight=0.5),
                _entry(volume_gate_mult=1.25),
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


def all_variants() -> tuple[GeorgeSweepVariant, ...]:
    return six_pack() + thirty_pack()


__all__ = [
    "BASE_MODULE",
    "GEORGE_ATTENTION_SOURCE",
    "SECURITY_PROFILE_SOURCE",
    "GeorgeSweepVariant",
    "all_variants",
    "six_pack",
    "thirty_pack",
]
