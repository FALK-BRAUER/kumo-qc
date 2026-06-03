"""#362 SPIKE inc3 — standalone indicator-replay PROOF harness (throwaway, not production).

Question: can we SKIP the 560d set_warmup by REPLAYING the captured warmup daily input stream into
the REAL LEAN C# indicators (Ichimoku/SMA/ADX/ROC/MACD), and get BYTE-IDENTICAL state — including
the recursive EWM indicators (ADX, MACD) that re-feeding-last-N can't reproduce?

Design: fixed ~25-symbol universe (deliberately removes the DV-universe-cold confound so this
isolates the INDICATOR-replay fidelity). Two runs via MODE:
  - MODE="capture": set_warmup(560d); a daily consolidator records each symbol's warmup daily bars
    (EXACT Decimal as strings — float would lose precision vs the C# Decimal auto-feed) into the
    ObjectStore at warmup-end; then logs per-symbol score scalars each Jan day.
  - MODE="restore": NO set_warmup; at init, replay each symbol's captured stream into FRESH
    indicators via the public update() path; then logs the same scalars.
Compare the SCALARS|... log lines RUN1 vs RUN2 → byte-identical = the decision-parity proxy
(score_symbol_native reads exactly these). Also compare wall-clock (gate-2) + RSS (gate-3, directional
on this small universe; the decisive RSS number needs the full universe).
"""
from __future__ import annotations

import json
from decimal import Decimal

from AlgorithmImports import (  # type: ignore
    DataNormalizationMode, Field, IchimokuKinkoHyo, MovingAverageType, QCAlgorithm,
    Resolution, RollingWindow, TradeBar, TradeBarConsolidator, timedelta,
)

FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
KEY = "warmup_snapshot_spike-" + FP + "-"  # per-symbol: KEY + sym

# ~25 liquid names (fixed universe). Mix of mega-caps + a few of the #358 cold-start names.
SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V",
    "WMT", "MA", "COST", "NFLX", "AMD", "CRM", "ADBE", "PEP", "KO", "DIS",
    "ARCC", "ENB", "STT", "WAT", "DFS",
]


class Spike362(QCAlgorithm):
    MODE = "capture"  # edited to "restore" for RUN2

    def initialize(self) -> None:
        self.set_start_date(2025, 1, 1)
        self.set_end_date(2025, 1, 31)
        self.set_cash(100000)
        self.set_time_zone("America/New_York")
        self.universe_settings.data_normalization_mode = DataNormalizationMode.RAW
        self.settings.automatic_indicator_warm_up = False

        self._ind: dict = {}
        self._cap: dict[str, list] = {}     # capture buffers (MODE=capture)
        self._logged: set = set()            # (date,sym) logged once

        if self.MODE == "capture":
            self.set_warmup(timedelta(days=560))

        for tk in SYMBOLS:
            eq = self.add_equity(tk, Resolution.DAILY)
            eq.set_data_normalization_mode(DataNormalizationMode.RAW)
            sym = eq.symbol
            self._register(sym)
            if self.MODE == "restore":
                self._replay(sym)
        if self.MODE == "restore":
            # PURE fidelity log: replay-end state (after captured bars, BEFORE any live bar) — the
            # same logical point CAPTURE logs at on_warmup_finished. Removes the live-bar phase confound.
            for sym, ind in self._ind.items():
                self._log_scalars("WARMEND", sym, ind, tag="STATE")

    # -- indicator suite (mirrors lean_entry._register_indicators params) -----------------------
    def _register(self, sym) -> None:
        d_ichi = self.ichimoku(sym, 9, 26, 26, 52, 26, 26)
        sma200 = self.sma(sym, 200)
        adx = self.adx(sym, 9)
        adx_window = RollingWindow[float](5)
        adx.updated += lambda _s, _pt, a=adx, w=adx_window: w.add(a.current.value)
        roc13 = self.roc(sym, 13)
        macd = self.macd(sym, 12, 26, 9, MovingAverageType.EXPONENTIAL, Resolution.DAILY)
        vol_sma20 = self.sma(sym, 20, Resolution.DAILY, Field.VOLUME)
        self._ind[sym] = {"d_ichi": d_ichi, "sma200": sma200, "adx": adx,
                          "adx_window": adx_window, "roc13": roc13, "macd": macd,
                          "vol_sma20": vol_sma20}

    # -- replay (MODE=restore): re-feed the captured stream into fresh indicators ---------------
    def _replay(self, sym) -> None:
        if not self.object_store.contains_key(KEY + sym.value):
            return  # cold (unwarmed) — matches a name absent from the snapshot
        rows = json.loads(self.object_store.read(KEY + sym.value))
        ind = self._ind[sym]
        for r in rows:
            iso, o, h, lo, c, v = r
            et = self._iso_to_close_dt(iso)
            bar = TradeBar(et, sym, Decimal(o), Decimal(h), Decimal(lo), Decimal(c), Decimal(v),
                           timedelta(days=1))
            ind["d_ichi"].update(bar)
            ind["adx"].update(bar)
            ind["sma200"].update(et, Decimal(c))
            ind["roc13"].update(et, Decimal(c))
            ind["macd"].update(et, Decimal(c))
            ind["vol_sma20"].update(et, Decimal(v))

    def _iso_to_close_dt(self, iso: str):
        from datetime import datetime, time
        d = datetime.fromisoformat(iso).date()
        return datetime.combine(d, time(0, 0))  # consolidator end_time is midnight-of-next or close; match capture

    def on_warmup_finished(self) -> None:
        if self.MODE == "capture":
            # Capture via history over the EXACT warmup window (timedelta(days=560)) = the canonical
            # daily bars set_warmup actually fed (~385 bars). NOT history(560 BARS) — that over-warms
            # (the _seed_daily discrepancy). EXACT Decimal as str (byte preservation). Exclude any bar
            # dated >= start (the live feed owns today).
            from datetime import date
            start = date(2025, 1, 1)
            n = 0
            for sym in self._ind:
                rows = []
                for bar in self.history[TradeBar](sym, timedelta(days=560), Resolution.DAILY):
                    if bar.end_time.date() >= start:
                        continue
                    rows.append((bar.end_time.date().isoformat(), str(bar.open), str(bar.high),
                                 str(bar.low), str(bar.close), str(bar.volume)))
                if rows:
                    self.object_store.save(KEY + sym.value, json.dumps(rows))
                    n += 1
            self.log(f"SPIKE_CAPTURE_WROTE|symbols={n}")
            # PURE fidelity log: warmup-end state (after the auto-fed warmup bars, BEFORE any live
            # bar). The exact logical point RESTORE logs after replay → byte-compare these two.
            for sym, ind in self._ind.items():
                self._log_scalars("WARMEND", sym, ind, tag="STATE")

    def on_data(self, data) -> None:
        if self.is_warming_up:
            return
        d = self.time.date().isoformat()
        for sym, ind in self._ind.items():
            if (d, sym.value) in self._logged:
                continue
            self._logged.add((d, sym.value))
            self._log_scalars(d, sym, ind)

    def _log_scalars(self, d: str, sym, ind, tag: str = "SCALARS") -> None:
        di = ind["d_ichi"]
        adx = ind["adx"]
        aw = ind["adx_window"]
        ready = (di.is_ready and ind["sma200"].is_ready and adx.is_ready
                 and ind["roc13"].is_ready and aw.count >= 4)
        if not ready:
            self.log(f"{tag}|{d}|{sym.value}|NOTREADY|"
                     f"ichi={di.is_ready}|sma={ind['sma200'].is_ready}|adx={adx.is_ready}|"
                     f"roc={ind['roc13'].is_ready}|awc={aw.count}")
            return
        # full-precision repr → exact byte-compare RUN1 vs RUN2
        self.log(
            f"{tag}|{d}|{sym.value}|READY|"
            f"tenkan={di.tenkan.current.value}|kijun={di.kijun.current.value}|"
            f"spanA={di.senkou_a.current.value}|spanB={di.senkou_b.current.value}|"
            f"sma200={ind['sma200'].current.value}|adx={adx.current.value}|"
            f"pdi={adx.positive_directional_index.current.value}|"
            f"mdi={adx.negative_directional_index.current.value}|"
            f"roc={ind['roc13'].current.value}|aw0={aw[0]}|aw3={aw[3]}"
        )
