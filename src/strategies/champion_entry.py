"""champion-entry (#253 Phase-1) — champion-asis + the methodology §4 Gate-2 ENTRY TRIGGER.

The Phase-1 P&L-unlock measurement config: the EXACT champion-asis phase stack with the two new
entry phases wired in between ranking and sizing (PHASE_ORDER: ... ranking -> entry_selection ->
entry_timing -> sizing ...):

    universe (dv_rank_cap) -> signal (bct_score_full)
    -> regime (spy_200ma, vix_percentile)
    -> entry_selection (bct_entry_confirm)   [NEW — §4 Gate-2 X/4 confirmation gate]
    -> entry_timing (market_on_open_entry)   [NEW — baseline MOO mechanics, explicit]
    -> sizing (flat_pct_heatcap)
    -> exit_hard (kijun_g3_exits) -> diagnostics (version_marker, chart_emit)

WHY a NEW config (not a champion-asis edit): champion-asis is the -0.616 BLIND-ENTRY baseline —
a qualified name is bought at next open with NO entry trigger (#228 proved the SCORER already
matches methodology, so the gap is the missing entry confirmation, not a broken scorer). This
config ADDS that trigger so a name FIRES only on a CONFIRMED entry. champion-asis stays UNCHANGED
(its own config_hash, the baseline to measure against); champion-entry is its OWN config with its
OWN config_hash, judged on its OWN MERITS (does the entry trigger improve risk-adjusted return /
cut bad entries) — NEVER vs the 0.778 adjusted-data champion.

Every phase except the two new ones is the champion-asis Slot VERBATIM (same impl, same params)
so the ONLY behavioral delta vs the baseline is the entry confirmation — a clean controlled
measurement of the trigger's effect.

Single code path (local == cloud); RAW; no count caps / time exits / fixed slots. Pins to
(git commit + this config hash + substrate fingerprint).
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.bct_entry_confirm.bct_entry_confirm import BctEntryConfirm
from phases.entry_timing.market_on_open_entry.market_on_open_entry import MarketOnOpenEntry
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

CONFIG = StrategyConfig(
    name="champion-entry",
    # 1.0.0: first cut of the Phase-1 entry-trigger config (#253). Champion-asis stack VERBATIM
    # + entry_selection(bct_entry_confirm) + entry_timing(market_on_open_entry).
    version="1.0.0",
    phases={
        # --- champion-asis stack, VERBATIM (the controlled-measurement invariant) ---
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(
            impl=BctScoreFull,
            params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25),
        ),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        # --- NEW: the §4 Gate-2 entry trigger (the only behavioral delta vs the baseline) ---
        # Methodology defaults: gate at >=2/4 with regime+volume mandatory, volume gate 1.0x,
        # pullback band 0.5%, canonical MACD 12/26/9.
        "entry_selection": Slot(
            impl=BctEntryConfirm,
            params=BctEntryConfirm.Params(),
        ),
        # --- NEW: baseline market-on-open mechanics (explicit; matches the engine's MOO fire) ---
        "entry_timing": Slot(
            impl=MarketOnOpenEntry,
            params=MarketOnOpenEntry.Params(),
        ),
        # --- champion-asis stack, VERBATIM (continued) ---
        "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=0.10)),
        "exit_hard": [
            Slot(impl=KijunG3Exits, params=KijunG3Exits.Params(
                cloud_exit_enabled=False, weekly_kijun_exit_enabled=False,
                phase3_days=56, phase3_pnl=0.15,
            )),
        ],
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)

# LEAN-deployable (#238): same live-coarse universe wiring as champion-asis. The entry phases are
# in PHASE_ORDER between ranking and sizing; the build seeds runtime.lean_entry + the new entry
# phase modules into dist/. Config-only fixtures omit this flag.
LEAN_ENTRY = True
