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


PACKS = {
    "first": first_pack,
    "top_x_expansion": top_x_expansion_pack,
    "real_strategy_scanner": real_strategy_scanner_pack,
}


def all_variants() -> list[ScannerRankerVariant]:
    return [variant for pack in PACKS.values() for variant in pack()]
