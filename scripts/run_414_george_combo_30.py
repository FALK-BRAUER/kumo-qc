"""#414 George combo FY2025 local BT sweep: 30 recombined variants, 6 workers.

This is the second sweep after `run_408_george_range_30.py`. The first 30-pack tested mostly
one-axis families. This runner recombines the best observed pieces:

- proactive winner exits around target 6-8%, min-peak 3-5%, giveback 1.5-2.5%
- buy-stop entry offsets around 0.5-1.0%
- optional min-hold protection before proactive exits
- 3-4.5% flat sizing, selected ATR/risk controls, and a few non-binding gate checks

Usage:
  python3 scripts/run_414_george_combo_30.py --workers 6
  python3 scripts/run_414_george_combo_30.py --data-folder /Users/falk/projects/kumo-qc/data --full-warmup --workers 6
  python3 scripts/run_414_george_combo_30.py --window jan --limit 1 --workers 1 --sweep-id george_combo_30_smoke
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

import scripts.run_408_george_range_30 as base


def _scratch(
    no_progress_days: int,
    min_mfe_pct: float,
    scratch_band_pct: float,
    max_loss_after_mfe_pct: float,
) -> dict[str, Any]:
    return base._scratch(no_progress_days, min_mfe_pct, scratch_band_pct, max_loss_after_mfe_pct)


def _combo(
    variant_id: str,
    hypothesis: str,
    *,
    target_pct: float = 0.06,
    min_peak_pct: float = 0.04,
    giveback_from_peak_pct: float = 0.015,
    require_still_bullish: bool = False,
    proactive_min_hold_days: int = 0,
    breakout_pct: float = 0.005,
    position_pct: float = 0.04,
    scratch: dict[str, Any] | None = None,
    atr_mult: float = 0.50,
    resistance_buffer_pct: float = 0.02,
    breadth_threshold: float = 0.40,
) -> base.VariantSpec:
    return base._v(
        variant_id,
        "combo",
        hypothesis,
        target_pct=target_pct,
        min_peak_pct=min_peak_pct,
        giveback_from_peak_pct=giveback_from_peak_pct,
        require_still_bullish=require_still_bullish,
        proactive_min_hold_days=proactive_min_hold_days,
        scratch=scratch,
        entry_trigger="buy_stop",
        entry_trigger_params={"breakout_pct": breakout_pct},
        sizer="flat",
        sizer_params={"position_pct": position_pct, "max_gross_pct": 1.0},
        atr_mult=atr_mult,
        resistance_buffer_pct=resistance_buffer_pct,
        breadth_threshold=breadth_threshold,
    )


def _vol_combo(
    variant_id: str,
    hypothesis: str,
    *,
    risk_pct: float,
    max_position_pct: float,
    fallback_stop_pct: float,
    breakout_pct: float = 0.005,
    target_pct: float = 0.06,
    min_peak_pct: float = 0.04,
    giveback_from_peak_pct: float = 0.015,
) -> base.VariantSpec:
    return base._v(
        variant_id,
        "combo",
        hypothesis,
        target_pct=target_pct,
        min_peak_pct=min_peak_pct,
        giveback_from_peak_pct=giveback_from_peak_pct,
        require_still_bullish=False,
        scratch=None,
        entry_trigger="buy_stop",
        entry_trigger_params={"breakout_pct": breakout_pct},
        sizer="vol_risk",
        sizer_params={
            "risk_pct": risk_pct,
            "max_position_pct": max_position_pct,
            "fallback_stop_pct": fallback_stop_pct,
            "min_scale": 0.4,
            "vix_baseline": 20.0,
            "vix_slope": 0.02,
        },
    )


COMBO_VARIANTS: tuple[base.VariantSpec, ...] = (
    _combo("combo_gb_buy005", "Best exit plus 0.5% buy-stop offset."),
    _combo("combo_gb_buy010", "Best exit plus 1.0% buy-stop offset.", breakout_pct=0.010),
    _combo("combo_gb_buy005_min7", "Best exit, 0.5% buy-stop, defer proactive exits for 7 days.", proactive_min_hold_days=7),
    _combo("combo_gb_buy005_min14", "Best exit, 0.5% buy-stop, defer proactive exits for 14 days.", proactive_min_hold_days=14),
    _combo("combo_t08_buy005", "8% target runner plus 0.5% buy-stop.", target_pct=0.08, min_peak_pct=0.05, giveback_from_peak_pct=0.025, require_still_bullish=True),
    _combo("combo_t08_buy010", "8% target runner plus 1.0% buy-stop.", target_pct=0.08, min_peak_pct=0.05, giveback_from_peak_pct=0.025, require_still_bullish=True, breakout_pct=0.010),
    _combo("combo_minp03_buy005", "Low min-peak giveback plus 0.5% buy-stop.", min_peak_pct=0.03, giveback_from_peak_pct=0.025, require_still_bullish=True),
    _combo("combo_minp03_buy010", "Low min-peak giveback plus 1.0% buy-stop.", min_peak_pct=0.03, giveback_from_peak_pct=0.025, require_still_bullish=True, breakout_pct=0.010),
    _combo("combo_gb_buy005_pos03", "Best exit/buy-stop with 3% flat sizing.", position_pct=0.03),
    _combo("combo_gb_buy005_pos035", "Best exit/buy-stop with 3.5% flat sizing.", position_pct=0.035),
    _combo("combo_gb_buy005_pos045", "Best exit/buy-stop with 4.5% flat sizing.", position_pct=0.045),
    _combo("combo_t08_buy005_pos03", "8% target/buy-stop with 3% sizing.", target_pct=0.08, min_peak_pct=0.05, giveback_from_peak_pct=0.025, require_still_bullish=True, position_pct=0.03),
    _combo("combo_minp03_buy005_pos03", "Low min-peak/buy-stop with 3% sizing.", min_peak_pct=0.03, giveback_from_peak_pct=0.025, require_still_bullish=True, position_pct=0.03),
    _combo("combo_gb_buy010_pos03", "Best exit, 1% buy-stop, 3% sizing.", breakout_pct=0.010, position_pct=0.03),
    _combo("combo_gb_buy005_scratch_tight", "Best exit/buy-stop with tight scratch rescue.", scratch=_scratch(3, 0.02, 0.003, 0.01)),
    _combo("combo_gb_buy005_scratch_1d", "Best exit/buy-stop with aggressive 1d low-MFE scratch.", scratch=_scratch(1, 0.01, 0.003, 0.01)),
    _combo("combo_gb_buy005_scratch_pat", "Best exit/buy-stop with patient scratch.", scratch=_scratch(5, 0.03, 0.0075, 0.025)),
    _combo("combo_t08_buy005_scratch_tight", "8% target/buy-stop with tight scratch.", target_pct=0.08, min_peak_pct=0.05, giveback_from_peak_pct=0.025, require_still_bullish=True, scratch=_scratch(3, 0.02, 0.003, 0.01)),
    _combo("combo_minp03_buy005_scratch_tight", "Low min-peak/buy-stop with tight scratch.", min_peak_pct=0.03, giveback_from_peak_pct=0.025, require_still_bullish=True, scratch=_scratch(3, 0.02, 0.003, 0.01)),
    _combo("combo_gb_buy005_min7_pos03", "Best exit/buy-stop, min-hold 7d, 3% sizing.", proactive_min_hold_days=7, position_pct=0.03),
    _combo("combo_gb_buy010_min7_pos03", "Best exit, 1% buy-stop, min-hold 7d, 3% sizing.", proactive_min_hold_days=7, breakout_pct=0.010, position_pct=0.03),
    _combo("combo_t08_buy005_min7", "8% target/buy-stop with 7d proactive min-hold.", target_pct=0.08, min_peak_pct=0.05, giveback_from_peak_pct=0.025, require_still_bullish=True, proactive_min_hold_days=7),
    _combo("combo_minp03_buy005_min7", "Low min-peak/buy-stop with 7d proactive min-hold.", min_peak_pct=0.03, giveback_from_peak_pct=0.025, require_still_bullish=True, proactive_min_hold_days=7),
    _combo("combo_gb_buy005_atr075_pos03", "Best exit/buy-stop with 3% sizing and 0.75 ATR cushion.", position_pct=0.03, atr_mult=0.75),
    _vol_combo("combo_gb_buy005_vol050_cap04", "Conservative vol-risk cap with best exit/buy-stop.", risk_pct=0.005, max_position_pct=0.04, fallback_stop_pct=0.06),
    _vol_combo("combo_gb_buy005_vol075_cap04", "0.75% vol-risk capped at 4% with best exit/buy-stop.", risk_pct=0.0075, max_position_pct=0.04, fallback_stop_pct=0.06),
    _vol_combo("combo_t08_buy005_vol075_cap04", "8% target with capped vol-risk and buy-stop.", risk_pct=0.0075, max_position_pct=0.04, fallback_stop_pct=0.06, target_pct=0.08, min_peak_pct=0.05, giveback_from_peak_pct=0.025),
    _combo("combo_gb_buy005_res010", "Best exit/buy-stop with looser 1% resistance buffer.", resistance_buffer_pct=0.01),
    _combo("combo_gb_buy005_breadth050", "Best exit/buy-stop with stricter 50% breadth gate.", breadth_threshold=0.50),
    _combo("combo_gb_buy005_pos03_breadth050", "Best exit/buy-stop with 3% sizing and stricter breadth.", position_pct=0.03, breadth_threshold=0.50),
)

if len(COMBO_VARIANTS) != 30:
    raise RuntimeError(f"expected exactly 30 combo variants, got {len(COMBO_VARIANTS)}")
if len({variant.variant_id for variant in COMBO_VARIANTS}) != len(COMBO_VARIANTS):
    raise RuntimeError("duplicate combo variant_id in COMBO_VARIANTS")


def main() -> None:
    base.VARIANTS = COMBO_VARIANTS
    if not any(arg == "--sweep-id" or arg.startswith("--sweep-id=") for arg in sys.argv[1:]):
        sys.argv.extend(["--sweep-id", "george_combo_30"])
    base.main()


if __name__ == "__main__":
    main()
