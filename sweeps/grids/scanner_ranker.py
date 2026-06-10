"""#446 scanner-ranker deployment sweep pack.

The pack compares the current champion against an opt-in BCT/George-style LambdaMART scanner gate.
Top-X is deliberately explicit because George/BCT does not appear to use one fixed daily cutoff.
"""
from __future__ import annotations

from dataclasses import dataclass

from sweeps.types import PhaseChoice, SweepConfig

BASE_MODULE = "strategies.champion_intraday_gapvol"
DEFAULT_MODEL_KEY = "objectstore://bct_lambdamart_qc_safe_v1.json"
REAL_STRATEGY_BASES = (
    (
        "giveback_no_bull",
        "strategies.realized_giveback_no_bull",
        "Best return/DD realized candidate from #408: tight giveback without bullish-structure veto.",
    ),
    (
        "target04_fast_take",
        "strategies.realized_target_04_fast_take",
        "Highest closed win rate/profit-factor realized candidate from #408.",
    ),
    (
        "target08_let_run",
        "strategies.realized_target_08_let_run",
        "Patient realized candidate from #408: fewer trades and higher average closed return.",
    ),
)


@dataclass(frozen=True, slots=True)
class ScannerRankerVariant:
    variant_id: str
    family: str
    hypothesis: str
    config: SweepConfig
    wave: int = 0
    base_module: str = BASE_MODULE

    @property
    def config_hash(self) -> str:
        return self.config.config_hash


def _pairs(**kwargs: object) -> tuple[tuple[str, object], ...]:
    return tuple(sorted(kwargs.items()))


def _ranking(*, enabled: bool = True, free_params: int = 0) -> PhaseChoice:
    return PhaseChoice(
        kind="ranking",
        impl_name="lambdamart_scanner_ranker",
        params=(),
        free_params=free_params,
        enabled=enabled,
    )


def _entry(impl_name: str, *, free_params: int | None = None, **params: object) -> PhaseChoice:
    return PhaseChoice(
        kind="entry_selection",
        impl_name=impl_name,
        params=_pairs(**params),
        free_params=len(params) if free_params is None else free_params,
    )


def _sizing(impl_name: str, *, free_params: int | None = None, **params: object) -> PhaseChoice:
    return PhaseChoice(
        kind="sizing",
        impl_name=impl_name,
        params=_pairs(**params),
        free_params=len(params) if free_params is None else free_params,
    )


def _exit(impl_name: str, *, free_params: int | None = None, **params: object) -> PhaseChoice:
    phase_params = dict(params)
    counted_params = len(phase_params) if free_params is None else free_params
    if impl_name == "mfe_intraday_exit" and "diagnostic_log" not in phase_params:
        phase_params["diagnostic_log"] = True
        counted_params = len(phase_params) - 1 if free_params is None else free_params
    return PhaseChoice(
        kind="exit_hard",
        impl_name=impl_name,
        params=_pairs(**phase_params),
        free_params=counted_params,
    )


def _base_proactive_exit() -> PhaseChoice:
    return _exit("proactive_strength_exit", free_params=0)


def _config(
    *choices: PhaseChoice,
    runtime_overrides: tuple[tuple[str, object], ...] = (),
) -> SweepConfig:
    return SweepConfig(
        choices=tuple(choices),
        continuous_weekly=True,
        warmup_days=320,
        runtime_overrides=runtime_overrides,
    )


def _ranker_runtime(
    *,
    top_x: int,
    model_path: str = DEFAULT_MODEL_KEY,
    fallback: str = "raise",
    min_score: float | None = None,
) -> tuple[tuple[str, object], ...]:
    fields: dict[str, object] = {
        "scanner_ranker_enabled": True,
        "scanner_ranker_model_path": model_path,
        "scanner_ranker_top_x": top_x,
        "scanner_ranker_fallback": fallback,
    }
    if min_score is not None:
        fields["scanner_ranker_min_score"] = min_score
    return _pairs(**fields)


def first_pack() -> list[ScannerRankerVariant]:
    """Six deployable comparison cells for local Docker, QC cloud, or cached offline smoke runs."""
    return [
        ScannerRankerVariant(
            variant_id="scanner_champion_baseline",
            family="baseline",
            hypothesis="Current production champion, no learned scanner gate.",
            config=_config(),
        ),
        ScannerRankerVariant(
            variant_id="scanner_ranker_phase_off",
            family="fallback",
            hypothesis="Phase present but explicitly disabled; should match baseline wiring.",
            config=_config(
                _ranking(enabled=False),
                runtime_overrides=_pairs(scanner_ranker_enabled=False),
            ),
        ),
        ScannerRankerVariant(
            variant_id="scanner_ranker_fallback_bct_order",
            family="fallback",
            hypothesis="Missing model falls back to BCT signal order; proves fail-open control behavior.",
            config=_config(
                _ranking(),
                runtime_overrides=_ranker_runtime(
                    top_x=20,
                    model_path="objectstore://missing_bct_lambdamart_qc_safe_v1.json",
                    fallback="bct_order",
                ),
            ),
        ),
        ScannerRankerVariant(
            variant_id="scanner_lambdamart_top10",
            family="top_x",
            hypothesis="Strict George-style daily Top-10 scanner gate.",
            config=_config(_ranking(free_params=1), runtime_overrides=_ranker_runtime(top_x=10)),
        ),
        ScannerRankerVariant(
            variant_id="scanner_lambdamart_top20",
            family="top_x",
            hypothesis="Balanced daily Top-20 scanner gate.",
            config=_config(_ranking(free_params=1), runtime_overrides=_ranker_runtime(top_x=20)),
        ),
        ScannerRankerVariant(
            variant_id="scanner_lambdamart_top50",
            family="top_x",
            hypothesis="Wide daily Top-50 scanner gate; tests whether ranking helps without starving entries.",
            config=_config(_ranking(free_params=1), runtime_overrides=_ranker_runtime(top_x=50)),
        ),
    ]


def _top_x_variant(top_x: int, *, hypothesis: str, wave: int) -> ScannerRankerVariant:
    return ScannerRankerVariant(
        variant_id=f"scanner_lambdamart_top{top_x}",
        family="top_x",
        wave=wave,
        hypothesis=hypothesis,
        config=_config(_ranking(free_params=1), runtime_overrides=_ranker_runtime(top_x=top_x)),
    )


def top_x_expansion_pack() -> list[ScannerRankerVariant]:
    """Second-pack Top-X curve around the initial top10/top20/top50 result."""
    return [
        _top_x_variant(
            5,
            wave=1,
            hypothesis="Very strict daily Top-5 scanner gate; tests whether Q1 drawdown control improves further.",
        ),
        _top_x_variant(
            15,
            wave=1,
            hypothesis="Tight daily Top-15 scanner gate; bridges the initial top10/top20 split.",
        ),
        _top_x_variant(
            25,
            wave=1,
            hypothesis="Slightly wider than the initial Top-20 winner; tests whether extra candidates add return.",
        ),
        _top_x_variant(
            30,
            wave=1,
            hypothesis="Medium daily Top-30 scanner gate; tests whether top20 benefit persists with more breadth.",
        ),
        _top_x_variant(
            40,
            wave=1,
            hypothesis="Wide-but-not-top50 gate; tests where rank dilution starts hurting.",
        ),
        _top_x_variant(
            75,
            wave=1,
            hypothesis="Very wide daily Top-75 gate; checks whether the learned ranker becomes equivalent to baseline.",
        ),
    ]


def _real_strategy_variant(
    *,
    strategy_id: str,
    base_module: str,
    base_hypothesis: str,
    top_x: int | None,
) -> ScannerRankerVariant:
    if top_x is None:
        return ScannerRankerVariant(
            variant_id=f"{strategy_id}_scanner_off",
            family="real_strategy_control",
            wave=2,
            base_module=base_module,
            hypothesis=f"{base_hypothesis} Scanner disabled control.",
            config=_config(runtime_overrides=_pairs(scanner_ranker_enabled=False)),
        )
    return ScannerRankerVariant(
        variant_id=f"{strategy_id}_scanner_top{top_x}",
        family="real_strategy_scanner",
        wave=2,
        base_module=base_module,
        hypothesis=f"{base_hypothesis} LambdaMART scanner gate keeps daily Top-{top_x}.",
        config=_config(_ranking(free_params=1), runtime_overrides=_ranker_runtime(top_x=top_x)),
    )


def real_strategy_scanner_pack() -> list[ScannerRankerVariant]:
    """Promising #451 realized-strategy cells crossed with scanner-off/top15/top20/top25 gates."""
    variants: list[ScannerRankerVariant] = []
    for strategy_id, base_module, base_hypothesis in REAL_STRATEGY_BASES:
        variants.append(
            _real_strategy_variant(
                strategy_id=strategy_id,
                base_module=base_module,
                base_hypothesis=base_hypothesis,
                top_x=None,
            )
        )
        for top_x in (15, 20, 25):
            variants.append(
                _real_strategy_variant(
                    strategy_id=strategy_id,
                    base_module=base_module,
                    base_hypothesis=base_hypothesis,
                    top_x=top_x,
                )
            )
    return variants


def _top20_realization_config(*exits: PhaseChoice) -> SweepConfig:
    return _config(
        _ranking(free_params=1),
        *exits,
        runtime_overrides=_ranker_runtime(top_x=20),
    )


def top20_realized_exit_pack() -> list[ScannerRankerVariant]:
    """#455 top20-only realization sweep across the three real strategy bases.

    Exit variants include the base proactive exit explicitly because the sweep bridge treats
    `exit_hard` choices as the complete composed exit list.
    """
    base_exit = _base_proactive_exit()
    specs: tuple[tuple[str, str, str, tuple[PhaseChoice, ...]], ...] = (
        (
            "top20_base",
            "realization_baseline",
            "LambdaMART Top-20 gate with the selected real strategy's current exit unchanged.",
            (),
        ),
        (
            "top20_stale20",
            "stale_mfe",
            "Add stale-MFE exit after 20 trading sessions without a fresh peak, once MFE reached 4%.",
            (
                base_exit,
                _exit(
                    "stale_mfe_exit",
                    stale_sessions=20,
                    min_hold_sessions=20,
                    min_mfe_pct=0.04,
                    min_giveback_pct=0.015,
                    max_exit_return_pct=0.12,
                ),
            ),
        ),
        (
            "top20_stale30",
            "stale_mfe",
            "Add slower stale-MFE exit after 30 trading sessions without a fresh peak.",
            (
                base_exit,
                _exit(
                    "stale_mfe_exit",
                    stale_sessions=30,
                    min_hold_sessions=30,
                    min_mfe_pct=0.04,
                    min_giveback_pct=0.02,
                    max_exit_return_pct=0.15,
                ),
            ),
        ),
        (
            "top20_mfe_gb04",
            "mfe_giveback",
            "Add tighter intraday giveback realization once MFE reaches 4%.",
            (
                base_exit,
                _exit(
                    "mfe_intraday_exit",
                    min_mfe_pct=0.04,
                    giveback_fraction=0.35,
                    min_giveback_pct=0.015,
                    min_exit_return_pct=0.005,
                    min_hold_bars=2,
                ),
            ),
        ),
        (
            "top20_mfe_gb06",
            "mfe_giveback",
            "Add tighter intraday giveback realization once MFE reaches 6%.",
            (
                base_exit,
                _exit(
                    "mfe_intraday_exit",
                    min_mfe_pct=0.06,
                    giveback_fraction=0.40,
                    min_giveback_pct=0.02,
                    min_exit_return_pct=0.005,
                    min_hold_bars=2,
                ),
            ),
        ),
        (
            "top20_age60",
            "age_cap",
            "Add a 60-trading-session age cap for positions that are not strong runners.",
            (
                base_exit,
                _exit(
                    "stale_mfe_exit",
                    stale_sessions=0,
                    max_hold_sessions=60,
                    max_hold_return_pct=0.12,
                ),
            ),
        ),
    )
    variants: list[ScannerRankerVariant] = []
    for strategy_id, base_module, base_hypothesis in REAL_STRATEGY_BASES:
        for suffix, family, hypothesis, exits in specs:
            variants.append(
                ScannerRankerVariant(
                    variant_id=f"{strategy_id}_{suffix}",
                    family=family,
                    wave=3,
                    base_module=base_module,
                    hypothesis=f"{base_hypothesis} {hypothesis}",
                    config=_top20_realization_config(*exits),
                )
            )
    return variants


def _rank_aware_config(top_x: int, *choices: PhaseChoice) -> SweepConfig:
    return _config(
        _ranking(free_params=1),
        *choices,
        runtime_overrides=_ranker_runtime(top_x=top_x),
    )


def _rank_aware_entry(**params: object) -> PhaseChoice:
    return _entry(
        "rank_aware_gap_confirm",
        free_params=3,
        **params,
    )


def rank_aware_intraday_pack() -> list[ScannerRankerVariant]:
    """#469 first rank-aware scanner pack.

    Controls keep the current `bct_intraday_gap_vol_confirm` entry phase and use LambdaMART only
    as a Top-X gate. Rank-aware variants swap only the entry-selection algorithm; PreFlightStaleness
    remains preserved by the sweep bridge.
    """
    return [
        ScannerRankerVariant(
            variant_id="rankaware_top20_gate_control",
            family="rank_aware_control",
            wave=4,
            hypothesis="Control: LambdaMART Top-20 gate with current gap/loud-open intraday confirm.",
            config=_rank_aware_config(20),
        ),
        ScannerRankerVariant(
            variant_id="rankaware_top20_bucket_default",
            family="rank_aware_entry",
            wave=4,
            hypothesis="Top20: ranks 1-10 can pass looser gap/open-volume; ranks 11-20 use canonical confirmation.",
            config=_rank_aware_config(20, _rank_aware_entry()),
        ),
        ScannerRankerVariant(
            variant_id="rankaware_top20_bucket_strict_mid",
            family="rank_aware_entry",
            wave=4,
            hypothesis="Top20: top ranks are only slightly looser; ranks 11-20 require stronger gap and volume.",
            config=_rank_aware_config(
                20,
                _rank_aware_entry(
                    top_gap_threshold=0.030,
                    top_vol_mult=0.90,
                    mid_gap_threshold=0.040,
                    mid_vol_mult=1.15,
                ),
            ),
        ),
        ScannerRankerVariant(
            variant_id="rankaware_top20_top5_only_loose",
            family="rank_aware_entry",
            wave=4,
            hypothesis="Top20: only ranks 1-5 get easier confirmation; ranks 6-20 must prove stronger intraday demand.",
            config=_rank_aware_config(
                20,
                _rank_aware_entry(
                    top_rank_max=5,
                    mid_rank_max=20,
                    top_gap_threshold=0.025,
                    top_vol_mult=0.80,
                    mid_gap_threshold=0.040,
                    mid_vol_mult=1.15,
                ),
            ),
        ),
        ScannerRankerVariant(
            variant_id="rankaware_top50_gate_control",
            family="rank_aware_control",
            wave=4,
            hypothesis="Control: LambdaMART Top-50 gate with current gap/loud-open intraday confirm.",
            config=_rank_aware_config(50),
        ),
        ScannerRankerVariant(
            variant_id="rankaware_top50_bucket_default",
            family="rank_aware_entry",
            wave=4,
            hypothesis="Top50: keep breadth, but ranks beyond 20 need strong gap and volume confirmation.",
            config=_rank_aware_config(50, _rank_aware_entry()),
        ),
        ScannerRankerVariant(
            variant_id="rankaware_top50_tail_strict",
            family="rank_aware_entry",
            wave=4,
            hypothesis="Top50: lower-ranked names require a very strong gap and louder opening volume.",
            config=_rank_aware_config(
                50,
                _rank_aware_entry(
                    tail_gap_threshold=0.060,
                    tail_vol_mult=1.50,
                ),
            ),
        ),
        ScannerRankerVariant(
            variant_id="rankaware_top50_mid30_tail",
            family="rank_aware_entry",
            wave=4,
            hypothesis="Top50: ranks 11-30 use canonical confirmation; only ranks 31-50 get the strict tail gate.",
            config=_rank_aware_config(
                50,
                _rank_aware_entry(
                    mid_rank_max=30,
                    tail_gap_threshold=0.045,
                    tail_vol_mult=1.15,
                ),
            ),
        ),
    ]


def _rank_aware_sizing(**params: object) -> PhaseChoice:
    return _sizing(
        "rank_aware_heatcap",
        free_params=3,
        **params,
    )


def rank_aware_sizing_pack() -> list[ScannerRankerVariant]:
    """#469 second rank-aware scanner pack.

    Controls keep the current flat 5% intraday sizer and use LambdaMART only as a Top-X gate.
    Rank-aware variants preserve the existing entry confirm and scale capital by scanner rank.
    """
    return [
        ScannerRankerVariant(
            variant_id="ranksize_top20_flat_control",
            family="rank_aware_sizing_control",
            wave=5,
            hypothesis="Control: LambdaMART Top-20 gate with current flat 5% heat-cap sizing.",
            config=_rank_aware_config(20),
        ),
        ScannerRankerVariant(
            variant_id="ranksize_top20_balanced",
            family="rank_aware_sizing",
            wave=5,
            hypothesis="Top20: modestly overweight ranks 1-10 and underweight ranks 11-20.",
            config=_rank_aware_config(
                20,
                _rank_aware_sizing(
                    top_multiplier=1.15,
                    mid_multiplier=0.85,
                    tail_multiplier=0.50,
                ),
            ),
        ),
        ScannerRankerVariant(
            variant_id="ranksize_top20_concentrated",
            family="rank_aware_sizing",
            wave=5,
            hypothesis="Top20: concentrate capital into ranks 1-10; ranks 11-20 become small starters.",
            config=_rank_aware_config(
                20,
                _rank_aware_sizing(
                    top_multiplier=1.35,
                    mid_multiplier=0.65,
                    tail_multiplier=0.25,
                ),
            ),
        ),
        ScannerRankerVariant(
            variant_id="ranksize_top20_de_risked",
            family="rank_aware_sizing",
            wave=5,
            hypothesis="Top20: keep top ranks at base size and reduce ranks 11-20 to cut loser exposure.",
            config=_rank_aware_config(
                20,
                _rank_aware_sizing(
                    top_multiplier=1.00,
                    mid_multiplier=0.70,
                    tail_multiplier=0.25,
                ),
            ),
        ),
        ScannerRankerVariant(
            variant_id="ranksize_top50_flat_control",
            family="rank_aware_sizing_control",
            wave=5,
            hypothesis="Control: LambdaMART Top-50 gate with current flat 5% heat-cap sizing.",
            config=_rank_aware_config(50),
        ),
        ScannerRankerVariant(
            variant_id="ranksize_top50_balanced",
            family="rank_aware_sizing",
            wave=5,
            hypothesis="Top50: overweight top ranks, keep ranks 11-20 near base, make ranks 21-50 small.",
            config=_rank_aware_config(
                50,
                _rank_aware_sizing(
                    top_multiplier=1.25,
                    mid_multiplier=0.85,
                    tail_multiplier=0.45,
                ),
            ),
        ),
        ScannerRankerVariant(
            variant_id="ranksize_top50_tail_tiny",
            family="rank_aware_sizing",
            wave=5,
            hypothesis="Top50: let tail candidates through only as tiny probes, preserving breadth with less drag.",
            config=_rank_aware_config(
                50,
                _rank_aware_sizing(
                    top_multiplier=1.20,
                    mid_multiplier=0.80,
                    tail_multiplier=0.20,
                ),
            ),
        ),
        ScannerRankerVariant(
            variant_id="ranksize_top50_top_heavy",
            family="rank_aware_sizing",
            wave=5,
            hypothesis="Top50: aggressively concentrate into top ranks while retaining small tail optionality.",
            config=_rank_aware_config(
                50,
                _rank_aware_sizing(
                    top_multiplier=1.50,
                    mid_multiplier=0.70,
                    tail_multiplier=0.25,
                ),
            ),
        ),
    ]


PACKS = {
    "first": first_pack,
    "top_x_expansion": top_x_expansion_pack,
    "real_strategy_scanner": real_strategy_scanner_pack,
    "top20_realized_exit": top20_realized_exit_pack,
    "rank_aware_intraday": rank_aware_intraday_pack,
    "rank_aware_sizing": rank_aware_sizing_pack,
}


def all_variants() -> list[ScannerRankerVariant]:
    return [variant for pack in PACKS.values() for variant in pack()]
